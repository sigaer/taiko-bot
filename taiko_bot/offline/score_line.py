from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

from sakura_taiko_core.chart import scoreline_dataset as domain_scoreline_dataset

from sakura_taiko_core.score.scoreline import (
    RATING_CONFIG,
    _RATING_ALIAS_TO_KEY,
    _SORTED_RATING_ALIASES,
    _DIFF_PREFIXES,
    DIFFICULTY_LEVEL_LABELS,
    ScoreLineRequest,
    _safe_int,
    _safe_float,
    _round_up_to_10,
    _normalize_title,
    _normalize_title_aggressive,
    _score_target_map,
    _extract_roll_times,
    _extract_balloons,
    _append_title_index,
    _pick_unique_candidate,
    _scoreline_row_quality,
    _prefer_scoreline_row,
    deduplicate_scoreline_rows,
    compute_roll_hits,
    compute_scoreline_result,
    parse_scoreline_request,
)


import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from taiko_bot.runtime.player.center.duplicate_versions import default_song_id_for_query, group_ids_for_query
from .chart_roll_metadata import resolve_chart_roll_metadata
from .evaluation_roll import compute_rating_roll_breakdown

BASE = Path(str(_runtime_root()))
SCORE_PATH = BASE / "songs" / "song_score.json"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
ALL_LEVELS_STREAM_PATH = BASE / "songs" / "taiko_goku_all_levels_stream.json"
UNIFIED_PATH = BASE / "songs" / "taiko_goku_onis.json"


def _source_paths() -> List[Path]:
    return [SCORE_PATH, SONG_DATA_PATH, ALL_LEVELS_STREAM_PATH]




def _scoreline_source_mtime_ns() -> int:
    return max(path.stat().st_mtime_ns for path in _source_paths())


def _ensure_scoreline_dataset_current() -> int:
    source_mtime_ns = _scoreline_source_mtime_ns()
    if not UNIFIED_PATH.exists() or UNIFIED_PATH.stat().st_mtime_ns < source_mtime_ns:
        rebuild_scoreline_dataset(UNIFIED_PATH)
    return UNIFIED_PATH.stat().st_mtime_ns


def rebuild_scoreline_dataset(output_path: Path | None=None) -> Tuple[int, int]:
    output_path = output_path or UNIFIED_PATH
    score_rows = json.loads(SCORE_PATH.read_text(encoding='utf-8'))
    song_rows = json.loads(SONG_DATA_PATH.read_text(encoding='utf-8'))
    stream_rows = json.loads(ALL_LEVELS_STREAM_PATH.read_text(encoding='utf-8'))
    if not isinstance(stream_rows, list):
        raise ValueError(f'全难度流式分数线数据不是列表: {ALL_LEVELS_STREAM_PATH}')
    merged, matched_count = domain_scoreline_dataset.build_scoreline_dataset(score_rows, song_rows, stream_rows)
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    _load_scoreline_data.cache_clear()
    _build_chart_index.cache_clear()
    return (len(merged), matched_count)


@lru_cache(maxsize=4)
def _load_scoreline_data(dataset_mtime_ns: int) -> List[Dict[str, Any]]:
    # mtime is only used as the cache key so long-running processes reload on file changes.
    _ = dataset_mtime_ns
    return json.loads(UNIFIED_PATH.read_text(encoding="utf-8"))


def load_scoreline_data(scoreline_path: str | Path | None = None) -> List[Dict[str, Any]]:
    requested_path = Path(scoreline_path) if scoreline_path is not None else UNIFIED_PATH
    if requested_path == UNIFIED_PATH:
        return _load_scoreline_data(_ensure_scoreline_dataset_current())
    return json.loads(requested_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def _build_chart_index(dataset_mtime_ns: int) -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[Tuple[str, int], List[Dict[str, Any]]]]:
    return domain_scoreline_dataset.build_chart_index(_load_scoreline_data(dataset_mtime_ns))








if __name__ == "__main__":
    total, matched = rebuild_scoreline_dataset()
    print(f"rebuilt {UNIFIED_PATH} rows={total} matched={matched}")
