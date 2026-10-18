from taiko_bot.offline.paths import root as _runtime_root

from sakura_taiko_core.chart.matching import (
    COURSE_TO_LEVEL_FIELD,
    COURSE_TO_COMBO_INDEX,
    VARIANT_HINT_PATTERN,
    COLLAB_MARKER_PATTERN,
    TRAILING_PAREN_PATTERN,
    TRAILING_VERSION_PATTERN,
    MANUAL_PATH_OVERRIDES,
    CandidateSummary,
    normalize_text,
    strip_variant_suffix,
    clean_subtitle,
    parse_song_bpm_range,
    build_song_keys,
    count_variant_penalty,
    extract_ascii_tokens,
    build_candidate_indexes,
    collect_song_course_levels,
    collect_song_course_combos,
    choose_candidate_pool,
    score_candidate,
    build_filtered_index,
)
from sakura_taiko_core.chart import matching as _domain_matching

import argparse
import fcntl
import tempfile
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

ROOT_DIR = Path(str(_runtime_root()))
DEFAULT_GIT_ROOT = Path("/home/sigaer/git")
DEFAULT_SONG_DATA_PATH = ROOT_DIR / "songs/song_data.json"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "songs/analyze_result_filtered.json"
DEFAULT_REPORT_PATH = ROOT_DIR / "songs/analyze_result_filtered_report.json"




from .chart_analysis import (  # noqa: E402
    TjaFileData,
    analyze_tja_file,
    estimate_section_note_count,
    find_tja_files,
    index_record_bpms,
    load_tja_file,
    parse_bpm_number,
)


def resolve_latest_tja_root(git_root: Path) -> Path:
    candidates = [
        path
        for path in git_root.iterdir()
        if path.is_dir() and path.name.startswith("ESE_autosync")
    ]
    if not candidates:
        raise FileNotFoundError(f"未在 {git_root} 下找到任何 ESE_autosync 目录")
    return max(candidates, key=lambda path: (path.stat().st_mtime, path.name))


def find_override_path(song_id: int, tja_root: Path) -> Optional[str]:
    suffix = MANUAL_PATH_OVERRIDES.get(song_id)
    if not suffix:
        return None
    path = tja_root / suffix
    if path.exists():
        return str(path)
    return None


def _write_json_atomic(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            os.fchmod(handle.fileno(), path.stat().st_mode & 0o777 if path.exists() else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _load_previous_index(path: Path):
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    for section in ("by_bpm", "by_level", "by_tag", "song_meta"):
        if not isinstance(payload.get(section), dict):
            raise ValueError(f"Invalid previous pattern index: {section}")
    for rows in (payload["by_bpm"], payload["by_level"], payload["by_tag"]):
        for ids in rows.values():
            if not isinstance(ids, list) or any(
                not isinstance(item, str) or "||" not in item
                or item.rsplit("||", 1)[0] not in payload["song_meta"] for item in ids
            ):
                raise ValueError("Invalid previous pattern index references")
    ids = [int(song["id"]) for song in payload["song_meta"].values()]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate previous pattern song IDs")
    return payload


def _retain_unresolved(result, previous, songs):
    """Re-key last-good entries through the canonical indexer's song identity."""
    old_keys = {int(song["id"]): key for key, song in previous["song_meta"].items()}
    new_keys = {int(song["id"]): key for key, song in result["song_meta"].items()}
    retained = {old_keys[int(song["id"])]: new_keys[int(song["id"])] for song in songs}
    for section in ("by_bpm", "by_level", "by_tag"):
        for key, ids in previous[section].items():
            keep = []
            for item in ids:
                song_key, course = item.rsplit("||", 1)
                if song_key in retained:
                    keep.append(f"{retained[song_key]}||{course}")
            if keep:
                result[section][key] = sorted(set(result[section].get(key, [])) | set(keep))


def rebuild_pattern_index(
    song_data, *, tja_root: Path, song_tja_mapping=None,
    output_path: Path = DEFAULT_OUTPUT_PATH,
    report_path: Path = DEFAULT_REPORT_PATH, allow_partial: bool = False,
):
    """Refresh derived public data; unresolved songs may retain last-good entries.

    CLI remains strict by default. Daily updates opt into partial progress so an
    unavailable new TJA cannot indefinitely block unrelated new/modified charts.
    No chart matching, parser or tag thresholds are implemented here.
    """
    output_path, report_path, tja_root = map(Path, (output_path, report_path, tja_root))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.with_suffix(output_path.suffix + ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if not tja_root.is_dir():
            raise FileNotFoundError(tja_root)
        online_songs = [song for song in song_data if song.get("shelf_status") == 0]
        if not online_songs or len({int(song["id"]) for song in online_songs}) != len(online_songs):
            raise ValueError("Empty or duplicate online song catalog")
        mapping = {}
        if song_tja_mapping is not None:
            from .song_tja_mapping import normalize_song_tja_mapping
            mapping = normalize_song_tja_mapping(song_tja_mapping)
        previous = _load_previous_index(output_path)
        tja_files = find_tja_files(str(tja_root))
        candidates = [build_candidate_summary(path, tja_root) for path in tja_files]
        indexes = build_candidate_indexes(candidates)
        selected_records, unresolved, failed_songs = [], [], []
        for song in online_songs:
            song_id = int(song["id"])
            if song_id in mapping:
                relative = mapping[song_id]
                path = tja_root / relative
                debug = {"reason": "song_id_mapping", "path": relative}
                if not relative or not path.is_file() or not path.resolve().is_relative_to(tja_root.resolve()):
                    path = None
                    debug["reason"] = "mapped_tja_missing"
            else:
                candidate, debug = select_candidate(song, candidates, *indexes, tja_root)
                path = candidate.path if candidate is not None else None
            records, error = build_song_records(song, path) if path is not None else (None, debug)
            if not records:
                unresolved.append({"id": song_id, "song_name_jp": song.get("song_name_jp"), "reason": error})
                failed_songs.append(song)
            else:
                selected_records.append((song, records))
        previous_ids = {int(song["id"]) for song in previous["song_meta"].values()} if previous else set()
        retained = [song for song in failed_songs if int(song["id"]) in previous_ids] if allow_partial else []
        retained_ids = {int(song["id"]) for song in retained}
        report = {
            "tja_root": str(tja_root), "online_song_count": len(online_songs),
            "matched_song_count": len(selected_records), "unresolved_count": len(unresolved),
            "retained_song_ids": sorted(retained_ids),
            "skipped_song_ids": [int(song["id"]) for song in failed_songs if int(song["id"]) not in retained_ids],
            "unresolved": unresolved,
        }
        _write_json_atomic(report_path, report)
        if not selected_records or (unresolved and not allow_partial):
            raise ValueError(f"Pattern index not published: {len(unresolved)} unresolved songs; see {report_path}")
        result = build_filtered_index(selected_records + [(song, []) for song in retained])
        if retained:
            _retain_unresolved(result, previous, retained)
        if previous is not None:
            _write_json_atomic(output_path.with_suffix(output_path.suffix + ".previous"), previous)
        _write_json_atomic(output_path, result)
        return report


def main() -> int:
    parser = argparse.ArgumentParser(description="为查配置重建当前在线曲目索引")
    parser.add_argument("--tja-root", help="TJA 根目录，默认自动选择最新 ESE_autosync")
    parser.add_argument("--song-data", default=str(DEFAULT_SONG_DATA_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--mapping", help="复用歌曲 ID 到 TJA 的现有映射文件")
    parser.add_argument("--allow-partial", action="store_true", help="匹配失败的旧歌曲沿用上次索引，新歌曲记录为暂缺")
    args = parser.parse_args()
    from .song_tja_mapping import load_song_tja_mapping
    mapping = load_song_tja_mapping(Path(args.mapping)) if args.mapping else None
    report = rebuild_pattern_index(
        json.loads(Path(args.song_data).read_text(encoding="utf-8")),
        tja_root=Path(args.tja_root) if args.tja_root else resolve_latest_tja_root(DEFAULT_GIT_ROOT),
        song_tja_mapping=mapping, output_path=Path(args.output),
        report_path=Path(args.report_output), allow_partial=args.allow_partial,
    )
    print(json.dumps(report, ensure_ascii=False))
    return 0


def build_candidate_summary(path: str, root: Path) -> CandidateSummary:
    return _domain_matching.build_candidate_summary(
        path, str(Path(path).relative_to(root)), load_tja_file(path)
    )

def select_candidate(song, candidates, exact_map, normalized_map, base_map, tja_root):
    return _domain_matching.select_candidate(
        song, candidates, exact_map, normalized_map, base_map,
        override_path=find_override_path(int(song.get("id", 0)), tja_root),
    )

def build_song_records(song, tja_path):
    return _domain_matching.build_song_records(song, analyze_tja_file(tja_path))


if __name__ == "__main__":
    raise SystemExit(main())
