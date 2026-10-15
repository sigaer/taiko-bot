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


def main() -> int:
    parser = argparse.ArgumentParser(description="为查配置重建当前在线曲目索引")
    parser.add_argument("--tja-root", help="TJA 根目录，默认自动选择最新 ESE_autosync")
    parser.add_argument("--song-data", default=str(DEFAULT_SONG_DATA_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--report-output", default=str(DEFAULT_REPORT_PATH))
    args = parser.parse_args()

    song_data_path = Path(args.song_data)
    output_path = Path(args.output)
    report_path = Path(args.report_output)
    tja_root = Path(args.tja_root) if args.tja_root else resolve_latest_tja_root(DEFAULT_GIT_ROOT)

    with song_data_path.open("r", encoding="utf-8") as f:
        song_data = json.load(f)

    online_songs = [song for song in song_data if song.get("shelf_status") == 0]
    print(f"[INFO] 使用 TJA 根目录: {tja_root}")
    print(f"[INFO] 在线曲目数: {len(online_songs)}")

    tja_files = find_tja_files(str(tja_root))
    print(f"[INFO] 扫描到 TJA 文件: {len(tja_files)}")
    candidates = [build_candidate_summary(path, tja_root) for path in tja_files]
    exact_map, normalized_map, base_map = build_candidate_indexes(candidates)

    selected_records: List[Tuple[Dict[str, object], List[Dict[str, object]]]] = []
    unresolved: List[Dict[str, object]] = []

    for idx, song in enumerate(online_songs, start=1):
        candidate, debug = select_candidate(
            song, candidates, exact_map, normalized_map, base_map, tja_root
        )
        if candidate is None:
            unresolved.append(
                {
                    "id": song.get("id"),
                    "song_name_jp": song.get("song_name_jp"),
                    "song_name": song.get("song_name"),
                    "reason": debug,
                }
            )
            continue

        song_records, record_error = build_song_records(song, candidate.path)
        if song_records is None:
            unresolved.append(
                {
                    "id": song.get("id"),
                    "song_name_jp": song.get("song_name_jp"),
                    "song_name": song.get("song_name"),
                    "reason": record_error,
                    "selected_path": candidate.rel_path,
                    "selected_debug": debug,
                }
            )
            continue

        selected_records.append((song, song_records))
        if idx % 100 == 0:
            print(f"[INFO] 已处理 {idx}/{len(online_songs)} 首")

    report = {
        "tja_root": str(tja_root),
        "online_song_count": len(online_songs),
        "matched_song_count": len(selected_records),
        "unresolved_count": len(unresolved),
        "unresolved": unresolved,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if unresolved:
        print(f"[ERR] 仍有 {len(unresolved)} 首歌曲未能唯一匹配，详情见 {report_path}")
        return 1

    result = build_filtered_index(selected_records)
    output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[OK] 已生成 {output_path}")
    print(f"[OK] 覆盖在线曲目 {len(selected_records)} 首")
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
