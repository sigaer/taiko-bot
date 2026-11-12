"""Retarget public catalog references without rewriting player publications."""
from __future__ import annotations

from copy import deepcopy
import csv
import io
import json
import os
from pathlib import Path
import tempfile

from taiko_bot.catalog_identity import identity_map, canonical_song_id
from .ourtaiko_catalog import atomic_json


def canonical_rows(rows, aliases, *, field="id", keyed=True):
    result, positions = [], {}
    # Current canonical records win; old records fill absent chart pairs only.
    ordered = sorted(enumerate(rows), key=lambda item: canonical_song_id(item[1].get(field), aliases) != item[1].get(field))
    for _, row in ordered:
        sid = canonical_song_id(row.get(field), aliases)
        if not isinstance(sid, int) or sid < 1:
            result.append(deepcopy(row))
            continue
        next_row = {**row, field: sid} if sid != row.get(field) else deepcopy(row)
        key = (sid, str(row.get("level", row.get("difficulty", ""))))
        if not keyed or key not in positions:
            positions[key] = len(result)
            result.append(next_row)
    return result


def remap_id_dict(values, aliases):
    result = {}
    for key, value in sorted(values.items(), key=lambda pair: canonical_song_id(pair[0], aliases) != int(pair[0]) if str(pair[0]).isdigit() else False):
        next_key = str(canonical_song_id(key, aliases))
        if next_key not in result:
            result[next_key] = deepcopy(value)
        elif isinstance(result[next_key], dict) and isinstance(value, dict):
            for subkey, item in value.items():
                result[next_key].setdefault(subkey, deepcopy(item))
    return result


def migrate_references(root: Path, catalog, *, persist=True):
    aliases = identity_map(catalog)
    if not aliases:
        return {"updated": []}
    updated, staged = [], {}
    songs_dir = root / "songs"
    def read(name):
        path = songs_dir / name
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    def stage(name, old, value):
        if old != value:
            staged[name] = value
            updated.append(name)
    for name in ("song_alias.json", "song_alias_new.json"):
        old = read(name)
        if not isinstance(old, list):
            continue
        result = {}
        for row in old:
            sid = canonical_song_id(row["id"], aliases)
            target = result.setdefault(sid, {**row, "id": sid, "aliases": []})
            target["aliases"] = list(dict.fromkeys([*target["aliases"], *row.get("aliases", [])]))
        for song in catalog:
            if not song.get("legacy_ids"):
                continue
            target = result.setdefault(song["id"], {"id": song["id"], "song_name_jp": song.get("song_name_jp"), "aliases": []})
            target["aliases"] = list(dict.fromkeys([*target["aliases"], *(str(i) for i in song["legacy_ids"]), *(f"id{i}" for i in song["legacy_ids"])]))
        stage(name, old, list(result.values()))
    for name in ("song_data_raw.json", "song_score.json", "taiko_goku_onis.json"):
        old = read(name)
        if not isinstance(old, list):
            continue
        value = canonical_rows(old, aliases)
        if name == "song_data_raw.json":
            by_id = {song["id"]: song for song in catalog}
            for row in value:
                if row["id"] in by_id:
                    row["shelf_status"] = by_id[row["id"]]["shelf_status"]
        stage(name, old, value)
    old = read("rating_structured_with_ids.json")
    if isinstance(old, dict) and isinstance(old.get("songs"), dict):
        value = deepcopy(old)
        entries, seen = {}, set()
        for key, row in sorted(old["songs"].items(), key=lambda pair: int(pair[1].get("id") or 0) in aliases):
            sid = canonical_song_id(row.get("id"), aliases)
            pair = (sid, str(row.get("level"))) if isinstance(sid, int) and sid > 0 else (None, key)
            if pair not in seen:
                entries[key] = {**row, "id": sid}
                seen.add(pair)
        value["songs"] = entries
        stage("rating_structured_with_ids.json", old, value)
    for name in ("catalog_constants.json", "branch_audio_manifest.json"):
        old = read(name)
        if not isinstance(old, dict):
            continue
        value = deepcopy(old)
        for key in ("constants", "provenance", "attempts") if name == "catalog_constants.json" else ("songs",):
            if isinstance(value.get(key), dict):
                value[key] = remap_id_dict(value[key], aliases)
        if isinstance(value.get("issues"), list):
            value["issues"] = [{**row, "id": canonical_song_id(row["id"], aliases)} if "id" in row else row for row in value["issues"]]
        stage(name, old, value)
    old = read("song_difficulty.json")
    if isinstance(old, dict):
        value = {key: list(dict.fromkeys(canonical_song_id(i, aliases) for i in ids)) if isinstance(ids, list) else ids for key, ids in old.items()}
        stage("song_difficulty.json", old, value)
    old = read("analyze_result_filtered.json")
    if isinstance(old, dict) and isinstance(old.get("song_meta"), dict):
        value = deepcopy(old)
        metadata, keys, by_id = {}, {}, {}
        for key, row in sorted(old["song_meta"].items(), key=lambda pair: int(pair[1]["id"]) in aliases):
            sid = canonical_song_id(row["id"], aliases)
            target = by_id.get(sid)
            if target is None:
                target = key.rsplit("@@", 1)[0] + "@@" + str(sid) if "@@" in key else key
                metadata[target] = {**row, "id": sid}
                by_id[sid] = target
            keys[key] = target
        value["song_meta"] = metadata
        for section in ("by_bpm", "by_level", "by_tag"):
            value[section] = {key: list(dict.fromkeys(
                keys[item.rsplit("||", 1)[0]] + "||" + item.rsplit("||", 1)[1] for item in entries
            )) for key, entries in old[section].items()}
        stage("analyze_result_filtered.json", old, value)
    # Position records have nested, explicitly named song_id fields. Do not
    # rewrite category IDs, positions, dojo numbers, timestamps or filenames.
    def positions(value):
        if isinstance(value, dict):
            return {key: canonical_song_id(item, aliases) if key in ("song_id", "songId") else positions(item) for key, item in value.items()}
        return [positions(item) for item in value] if isinstance(value, list) else value
    old = read("cn_song_positions.json")
    if old is not None:
        value = positions(old)
        for category in value.get("categories", {}).values():
            seen = set()
            for field in ("ordered", "pending"):
                rows = []
                for sid in category[field]:
                    sid = canonical_song_id(sid, aliases)
                    if sid not in seen:
                        rows.append(sid); seen.add(sid)
                category[field] = rows
        stage("cn_song_positions.json", old, value)
    path = songs_dir / "constants_id_v2.csv"
    csv_body = None
    if path.is_file():
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, old_rows = reader.fieldnames, list(reader)
        # IDs in CSV are text; sort with numeric identity before grouping.
        rows = []
        seen = set()
        for row in sorted(old_rows, key=lambda row: int(row["id"]) in aliases):
            next_row = {**row, "id": str(canonical_song_id(row["id"], aliases))}
            key = (next_row["id"], next_row["difficulty"])
            if key not in seen:
                rows.append(next_row); seen.add(key)
        if rows != old_rows:
            output = io.StringIO(newline="")
            writer = csv.DictWriter(output, fieldnames=fields)
            writer.writeheader(); writer.writerows(rows)
            csv_body = output.getvalue()
            updated.append(path.name)
    if persist:
        for name, value in staged.items():
            atomic_json(songs_dir / name, value)
        if csv_body is not None:
            fd, temporary = tempfile.mkstemp(prefix=".catalog-reference-", dir=songs_dir)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
                    handle.write(csv_body); handle.flush(); os.fsync(handle.fileno()); os.fchmod(handle.fileno(), 0o644)
                os.replace(temporary, path)
            finally:
                Path(temporary).unlink(missing_ok=True)
    return {"updated": updated}
