"""Conservative ESE resource resolution for the integrated catalog."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import re

from .ourtaiko_catalog import chart_levels, chart_titles, title_key
from .tja_roll_parser import read_tja_text


def safe_resource(root: Path, relative):
    if not isinstance(relative, str) or not relative.strip():
        return None
    path = (root / relative).resolve()
    return path if path.is_relative_to(root.resolve()) and path.is_file() else None


def single_levels(text):
    """Inspect course headers only; note/timing analysis stays in the parser."""
    from .ourtaiko_catalog import COURSES, positive_id
    course, level, style = 4, None, "single"
    levels = {}
    for raw in text.splitlines():
        line = raw.split("//", 1)[0].strip()
        key, sep, value = line.partition(":")
        if sep:
            key, value = key.strip().lower(), value.strip().lower()
            if key == "course":
                course = int(value) + 1 if value.isdigit() else COURSES.get(value)
            elif key == "level":
                level = positive_id(value)
            elif key == "style":
                style = value
        if line.upper() == "#START" and style in ("single", "1") and course and level:
            levels[course] = level
    return levels


def enrich_resources(songs, charts, assignments, root, mapping):
    by_id = {int(s["id"]): s for s in songs}
    filenames = defaultdict(list)
    for path in sorted(root.rglob("*.tja")):
        filenames[title_key(path.name)].append(path)
    report = {"matched": 0, "missing": 0, "audio": 0, "issues": [], "unresolved": []}
    seen = set()
    for chart in charts:
        sid = assignments.get(chart["id"])
        if sid is None or sid in seen:
            continue
        song = by_id[sid]
        try:
            path = safe_resource(root, mapping.get(str(sid)) or mapping.get(sid))
            if path is None:
                matches = []
                for candidate in filenames.get(title_key(chart.get("tjaName")), []):
                    text = read_tja_text(str(candidate))
                    titles = {title_key(v) for v in re.findall(r"^TITLE\w*\s*:(.*)$", text, re.M | re.I)}
                    levels = single_levels(text)
                    expected = chart_levels(chart)
                    if titles & chart_titles(chart) and all(levels.get(i) == level for i, level in expected.items()):
                        matches.append(candidate)
                if len(matches) == 1:
                    path = matches[0]
            if path is None:
                song.setdefault("tja_path", "")
                song.setdefault("audio_path", "")
                report["missing"] += 1
                report["unresolved"].append({"id": sid, "source": chart["id"], "tjaName": chart.get("tjaName"), "reason": "no_verified_local_tja"})
                continue
            text = read_tja_text(str(path))
            relative = path.relative_to(root).as_posix()
            if not song.get("tja_path"):
                song["tja_path"] = relative
            if not (mapping.get(str(sid)) or mapping.get(sid)):
                mapping[str(sid)] = relative
            wave = re.search(r"^\s*WAVE\s*:(.*)$", text, re.M | re.I)
            audio = safe_resource(root, str(path.parent.relative_to(root) / wave.group(1).strip())) if wave else None
            if not song.get("audio_path"):
                song["audio_path"] = audio.relative_to(root).as_posix() if audio else ""
            report["matched"] += 1
            report["audio"] += bool(audio)
            seen.add(sid)
        except Exception as exc:
            report["issues"].append({"id": sid, "reason": type(exc).__name__})
    return report
