"""Audit and optionally synchronize roll metadata from local TJA files.

The audit is intentionally conservative: matching and parser warnings are
recorded per song/course, existing values are preserved for blocked courses,
and writing requires an explicit ``--write`` flag.
"""

from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

import argparse
import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, MutableMapping, Sequence

from .chart_roll_metadata import apply_chart_roll_metadata_overrides
from .ese_audio_sync import (
    _build_tja_record,
    _iter_tja_files,
)
from .merge_index import (
    build_candidate_indexes,
    build_candidate_summary,
    choose_candidate_pool,
    collect_song_course_levels,
    select_candidate,
)
from .song_tja_mapping import (
    DEFAULT_MAPPING_PATH,
    load_song_tja_mapping,
    normalize_song_tja_mapping,
)
from .tja_roll_parser import parse_tja_roll_metadata, read_tja_text

DEFAULT_SONG_DATA = Path(str(_runtime_root() / 'songs/song_data.json'))
DEFAULT_TJA_ROOT = Path("/home/sigaer/git/ESE_autosync")
DEFAULT_REPORT = Path(str(_runtime_root() / 'logs/tja_roll_sync_audit.json'))
COURSES = ("easy", "normal", "hard", "oni", "ura")
COURSE_INDEX = {course: index for index, course in enumerate(COURSES, start=1)}
LOW_CONFIDENCE_SCORE = 800


def _json_copy(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _course_fields(song: Mapping[str, Any], level: int) -> tuple[Any, Any, Any, Any]:
    index = level - 1
    fields = []
    for name in ("roll_times", "roll_time", "balloons", "balloon_num"):
        value = song.get(name)
        fields.append(value[index] if isinstance(value, list) and index < len(value) else None)
    return tuple(fields)  # type: ignore[return-value]


def _parsed_course_fields(course: Mapping[str, Any]) -> Dict[str, Any]:
    roll_times = [float(value) for value in course.get("roll_times", [])]
    balloons = [int(value) for value in course.get("balloons", [])]
    return {
        "roll_times": roll_times,
        "roll_time": round(sum(roll_times), 6),
        "balloons": balloons,
        "balloon_num": sum(balloons),
    }


def _ensure_five(values: Any) -> List[Any]:
    result = list(values) if isinstance(values, list) else []
    return result[:5] + [None] * max(0, 5 - len(result))


def _replace_song_roll_fields(song: MutableMapping[str, Any], updates: Mapping[int, Mapping[str, Any]]) -> None:
    fields = {name: _ensure_five(song.get(name)) for name in ("roll_times", "roll_time", "balloons", "balloon_num")}
    for level, values in updates.items():
        index = level - 1
        for name in fields:
            fields[name][index] = _json_copy(values[name])
    song.update(fields)


def _differs(current: Sequence[Any], proposed: Sequence[Any]) -> bool:
    return _json_copy(list(current)) != _json_copy(list(proposed))


def _iter_tja_summaries(tja_root: Path) -> List[Any]:
    summaries = []
    for path in _iter_tja_files(tja_root):
        record = _build_tja_record(path)
        if record is None:
            continue
        summaries.append(build_candidate_summary(str(path), tja_root))
    return summaries


def audit_song_data(
    song_data: List[Dict[str, Any]],
    *,
    tja_root: Path = DEFAULT_TJA_ROOT,
    include_shelf_down: bool = True,
    song_tja_mapping: Mapping[int, str] | None = None,
    mapping_source: str | None = None,
) -> Dict[str, Any]:
    if song_tja_mapping is None:
        song_tja_mapping = (
            load_song_tja_mapping(DEFAULT_MAPPING_PATH)
            if DEFAULT_MAPPING_PATH.is_file()
            else {}
        )
    else:
        song_tja_mapping = normalize_song_tja_mapping(song_tja_mapping)
    candidates = _iter_tja_summaries(tja_root)
    indexes = build_candidate_indexes(candidates)
    songs_report: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {}
    proposed_songs: List[Dict[str, Any]] = []

    for song in song_data:
        if not isinstance(song, dict) or (not include_shelf_down and song.get("shelf_status") != 0):
            continue
        song_id = int(song.get("id") or 0)
        row: Dict[str, Any] = {
            "songId": song_id,
            "songName": song.get("song_name") or song.get("song_name_jp") or "",
            "shelfStatus": song.get("shelf_status"),
            "match": None,
            "courses": {},
            "blocked": [],
        }
        mapped_path = song_tja_mapping.get(song_id)
        mapping_has_song = song_id in song_tja_mapping
        candidate = None
        candidate_path: Path | None = None
        decision: Dict[str, Any]
        pool_size = 0

        if mapping_has_song:
            if not mapped_path:
                decision = {"reason": "song_id_mapping_empty"}
                row["blocked"].append("empty_mapping_path")
            else:
                candidate_path = tja_root / mapped_path
                decision = {"reason": "song_id_mapping", "path": mapped_path}
                if not candidate_path.is_file():
                    row["blocked"].append("mapped_tja_missing")
                    candidate_path = None
        else:
            candidate, decision = select_candidate(
                song, candidates, *indexes, tja_root
            )
            if candidate is not None:
                candidate_path = Path(candidate.path)
                pool_size = len(
                    choose_candidate_pool(song, candidates, *indexes)
                )

        if candidate_path is None:
            row["match"] = (
                {
                    "path": mapped_path,
                    "strategy": decision.get("reason"),
                    "score": None,
                    "candidatePoolSize": 0,
                }
                if mapping_has_song
                else None
            )
            if row["blocked"]:
                counts["songs_with_invalid_mapping"] = (
                    counts.get("songs_with_invalid_mapping", 0) + 1
                )
            else:
                row["blocked"].append("no_tja_match")
                counts["songs_without_match"] = counts.get("songs_without_match", 0) + 1
            row["ready"] = False
            row["writableCourses"] = []
            counts["songs_blocked"] = counts.get("songs_blocked", 0) + 1
            songs_report.append(row)
            proposed_songs.append(_json_copy(song))
            continue

        score = decision.get("score")
        row["match"] = {
            "path": mapped_path if mapping_has_song else candidate.rel_path,
            "strategy": decision.get("reason"),
            "score": score,
            "candidatePoolSize": pool_size,
        }
        if isinstance(score, (int, float)) and score < LOW_CONFIDENCE_SCORE and decision.get("reason") != "manual_override":
            row["blocked"].append("low_confidence_match")
        if pool_size > 1 and decision.get("reason") != "manual_override":
            row["blocked"].append("multiple_candidates")

        try:
            parsed = parse_tja_roll_metadata(read_tja_text(str(candidate_path)))
        except Exception as exc:
            row["blocked"].append("parser_error")
            row["parserError"] = str(exc)
            parsed = {}

        updates: Dict[int, Dict[str, Any]] = {}
        for course, level_text in collect_song_course_levels(song).items():
            chart_level = int(level_text)
            level = COURSE_INDEX.get("ura" if course == "Edit" else course.lower(), 0)
            parser_course = "ura" if course == "Edit" else course.lower()
            parsed_course = parsed.get(parser_course)
            course_row: Dict[str, Any] = {"level": chart_level, "fieldIndex": level, "status": "blocked", "diff": {}}
            if level < 1 or level > 5:
                course_row["status"] = "invalid_level"
                row["blocked"].append(f"invalid_level_{parser_course}")
            elif not isinstance(parsed_course, dict):
                course_row["status"] = "missing_course"
                row["blocked"].append(f"missing_{parser_course}")
            else:
                warnings = list(parsed_course.get("warnings") or [])
                if parsed_course.get("balloon_warning"):
                    warnings.append(str(parsed_course["balloon_warning"]))
                proposed = _parsed_course_fields(parsed_course)
                current = _course_fields(song, level)
                course_row["diff"] = {
                    "rollTimes": {"before": current[0], "after": proposed["roll_times"]},
                    "rollTime": {"before": current[1], "after": proposed["roll_time"]},
                    "balloons": {"before": current[2], "after": proposed["balloons"]},
                    "balloonNum": {"before": current[3], "after": proposed["balloon_num"]},
                }
                course_row["changed"] = any(
                    _differs(current[index] if isinstance(current[index], list) else [current[index]],
                             proposed[name] if isinstance(proposed[name], list) else [proposed[name]])
                    for index, name in enumerate(("roll_times", "roll_time", "balloons", "balloon_num"))
                )
                course_row["warnings"] = warnings
                if warnings:
                    row["blocked"].append(f"warnings_{parser_course}")
                else:
                    course_row["status"] = "ready"
                    updates[level] = proposed
            row["courses"][parser_course] = course_row

        updated_song = _json_copy(song)
        fatal_blocks = {
            "no_tja_match",
            "empty_mapping_path",
            "mapped_tja_missing",
            "low_confidence_match",
            "multiple_candidates",
            "parser_error",
        }
        if updates and not any(block in fatal_blocks for block in row["blocked"]):
            _replace_song_roll_fields(updated_song, updates)
            apply_chart_roll_metadata_overrides(updated_song)
        row["ready"] = not any(block in fatal_blocks for block in row["blocked"])
        row["writableCourses"] = sorted(
            course for course, value in row["courses"].items() if value.get("status") == "ready"
        ) if updates else []
        if row["ready"]:
            counts["songs_ready"] = counts.get("songs_ready", 0) + 1
        else:
            counts["songs_blocked"] = counts.get("songs_blocked", 0) + 1
        counts["courses_changed"] = counts.get("courses_changed", 0) + sum(
            int(value.get("changed", False)) for value in row["courses"].values()
        )
        songs_report.append(row)
        proposed_songs.append(updated_song)

    return {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": {
            "tjaRoot": str(tja_root),
            "courseCount": len(candidates),
            "mapping": mapping_source or str(DEFAULT_MAPPING_PATH),
            "mappingCount": len(song_tja_mapping),
        },
        "policy": {"lowConfidenceScore": LOW_CONFIDENCE_SCORE, "blockedWritesPreserveExisting": True},
        "counts": {"songs": len(songs_report), **counts},
        "songs": songs_report,
        "proposedSongData": proposed_songs,
    }


def write_song_data_atomically(path: Path, songs: List[Dict[str, Any]], *, backup: bool = True) -> Path | None:
    path = path.resolve()
    backup_path = None
    if backup:
        backup_path = path.with_suffix(path.suffix + ".before-tja-roll-sync")
        shutil.copy2(path, backup_path)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(songs, handle, ensure_ascii=False, indent=4)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
    return backup_path


def write_audit_report(report: Mapping[str, Any], path: Path = DEFAULT_REPORT) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {key: value for key, value in report.items() if key != "proposedSongData"}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="审计并可选同步本地 TJA 连打元数据")
    parser.add_argument("--song-data", type=Path, default=DEFAULT_SONG_DATA)
    parser.add_argument("--tja-root", type=Path, default=DEFAULT_TJA_ROOT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--mapping", type=Path, default=DEFAULT_MAPPING_PATH)
    parser.add_argument("--write", action="store_true", help="仅写入未被审计阻断的歌曲")
    args = parser.parse_args(argv)
    songs = json.loads(args.song_data.read_text(encoding="utf-8"))
    mapping = load_song_tja_mapping(args.mapping) if args.mapping.is_file() else {}
    report = audit_song_data(
        songs,
        tja_root=args.tja_root,
        song_tja_mapping=mapping,
        mapping_source=str(args.mapping),
    )
    write_audit_report(report, args.report)
    if args.write:
        ready = [row for row in report["songs"] if row.get("ready")]
        proposed = {int(song["id"]): song for song in report["proposedSongData"]}
        output = [_json_copy(proposed.get(int(song.get("id") or 0), song)) if any(int(x.get("songId") or 0) == int(song.get("id") or 0) and x.get("ready") for x in report["songs"]) else song for song in songs]
        backup = write_song_data_atomically(args.song_data, output)
        report["write"] = {"written": len(ready), "backup": str(backup) if backup else None}
        write_audit_report(report, args.report)
    print(json.dumps({"counts": report["counts"], "report": str(args.report), "write": bool(args.write)}, ensure_ascii=False))
    return 0 if not report["counts"].get("songs_blocked") else 2


if __name__ == "__main__":
    raise SystemExit(main())
