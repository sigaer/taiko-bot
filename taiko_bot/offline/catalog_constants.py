"""Fill missing V2 constants using the Viewer's pinned OurTaiko calculator.

No recalibration or star-to-constant approximation. Each single-player chart
must match catalog difficulty and, where known, its existing note count.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import importlib.util
import io
import json
import math
from pathlib import Path
import shutil

from .catalog_resources import safe_resource, single_levels
from .ourtaiko_catalog import atomic_json, positive_id
from .paths import root

FIELDS = ("id", "title", "difficulty", "totalNotes", "sub_constant_1", "main_constant", "sub_constant_2", "stamina", "handspeed", "burst", "complex", "rhythm")
DIFFICULTIES = {"hard": 3, "oni": 4, "edit": 5}


def fill_constants(catalog, *, output, csv_path, calculator, tja_root, limit=0):
    spec = importlib.util.spec_from_file_location("catalog_pinned_calculator", calculator)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    payload = json.loads(output.read_text()) if output.exists() else {"constants": {}, "provenance": {}, "attempts": {}}
    constants, provenance = payload["constants"], payload["provenance"]
    attempts = payload.setdefault("attempts", {})
    existing_rows = list(csv.DictReader(csv_path.open(encoding="utf-8-sig", newline=""))) if csv_path.exists() else []
    existing = {(int(r["id"]), r["difficulty"]) for r in existing_rows}
    calibration = hashlib.sha256((calculator.parent / "Constants/cached_computing_parameters.json").read_bytes()).hexdigest()
    processed = generated = 0
    processed_ids = set()
    issues = []
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node is required for the pinned TJA analyzer")
    for song in catalog:
        if any(str(song.get(field, "")).startswith("【双打】") for field in ("song_name", "song_name_jp")):
            continue
        sid = str(song["id"])
        wanted = {d: i for d, i in DIFFICULTIES.items() if positive_id(song.get(f"level_{i}")) and (int(sid), d) not in existing}
        path = safe_resource(tja_root, song.get("tja_path"))
        if not wanted or path is None:
            continue
        data = path.read_bytes()
        signature = hashlib.sha256(data + calibration.encode() + json.dumps({d: [song.get(f"level_{i}"), (song.get("max_combo") or [None]*5)[i-1]] for d,i in wanted.items()}, sort_keys=True).encode()).hexdigest()
        if attempts.get(sid) == signature:
            continue
        if limit and processed >= limit:
            break
        processed += 1
        processed_ids.add(int(sid))
        try:
            from .tja_roll_parser import read_tja_text
            levels = single_levels(read_tja_text(str(path)))
            result = module.calculate(data, node)
            charts = result.get("charts", [])
            source = provenance.setdefault(sid, {"tjaPath": song["tja_path"], "tjaSha256": hashlib.sha256(data).hexdigest(), "charts": {}})
            for difficulty, index in wanted.items():
                candidates = [c for c in charts if c.get("course") in (difficulty, difficulty + "_single") and c.get("branch") in ("master", "unbranched") and "constants" in c]
                candidates.sort(key=lambda c: c["branch"] != "master")
                if not candidates or levels.get(index) != positive_id(song.get(f"level_{index}")):
                    issues.append({"id": int(sid), "difficulty": difficulty, "reason": "missing_or_mismatched_single_course"})
                    continue
                chart = candidates[0]
                values = {"totalNotes": chart["totalNotes"], **chart["constants"]}
                combo = positive_id((song.get("max_combo") or [None]*5)[index - 1])
                if combo and combo != values["totalNotes"]:
                    issues.append({"id": int(sid), "difficulty": difficulty, "reason": "note_count_mismatch"})
                    continue
                if any(not isinstance(values.get(k), (int, float)) or not math.isfinite(values[k]) for k in FIELDS[3:]):
                    raise ValueError("invalid_constants")
                constants.setdefault(sid, {})[difficulty] = values
                source["charts"][difficulty] = {"course": chart["course"], "branch": chart["branch"], "catalogNotes": values["totalNotes"], "catalogLevel": levels[index]}
                existing_rows.append({"id": sid, "title": song.get("song_name_jp") or song["song_name"], "difficulty": difficulty, **values})
                existing.add((int(sid), difficulty))
                generated += 1
            # Only fill empty note counts. Existing catalog values stay intact.
            combos = list(song.get("max_combo") or ["-"] * 5)
            for chart in charts:
                course = chart.get("course")
                index = {"easy": 1, "normal": 2, **DIFFICULTIES}.get(course.removesuffix("_single") if isinstance(course, str) else "")
                if index and chart.get("branch") in ("master", "unbranched") and levels.get(index) == positive_id(song.get(f"level_{index}")) and not positive_id(combos[index-1]):
                    combos[index-1] = chart["totalNotes"]
            if song.get("catalog_source") == "ourtaiko":
                song["max_combo"] = combos
            attempts[sid] = signature
        except Exception as exc:
            issues.append({"id": int(sid), "reason": str(exc)[:120] or type(exc).__name__})
            attempts[sid] = signature
        if processed % 25 == 0:
            print(f"Calculated {processed} songs, added {generated} charts", flush=True)
    issues = [issue for issue in payload.get("issues", []) if issue["id"] not in processed_ids] + issues
    payload.update({"schemaVersion": 1, "generatedAt": datetime.now(timezone.utc).isoformat(), "calibrationSha256": calibration, "issues": issues})
    atomic_json(output, payload)
    # CSV consumers and Viewer supplements carry the same constants. Keep the
    # original rows (including hand-maintained values) in their original order.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(existing_rows)
    import os, tempfile
    fd, temporary = tempfile.mkstemp(prefix=".catalog-constants-", dir=csv_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(buffer.getvalue())
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), 0o644)
        os.replace(temporary, csv_path)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"processedSongs": processed, "addedCharts": generated, "issues": len(issues)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=root())
    parser.add_argument("--calculator", type=Path, default=Path("/home/sigaer/taiko/taiko-forum/taiko_viewer/.tja-runtime/calculate.py"))
    parser.add_argument("--tja-root", type=Path, default=Path("/home/sigaer/git/ESE_autosync"))
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()
    path = args.root / "songs/song_data.json"
    catalog = json.loads(path.read_text())
    result = fill_constants(catalog, output=args.root / "songs/catalog_constants.json", csv_path=args.root / "songs/constants_id_v2.csv", calculator=args.calculator, tja_root=args.tja_root, limit=args.limit)
    atomic_json(path, catalog)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
