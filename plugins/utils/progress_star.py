from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from .progress_catalog import load_active_song_ids


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class StarProgressSummary:
    total_count: int
    played_count: int
    unplayed_count: int
    clear_count: int
    full_count: int
    dondaful_count: int
    blank_rank_count: int
    rank_counts: Dict[int, int]


def build_star_progress_summary(
    progress_items: Iterable[Tuple[int, int, str]],
    best_map: Dict[Tuple[int, int], Dict[str, Any]],
) -> StarProgressSummary:
    seen: set[Tuple[int, int]] = set()
    total_count = 0
    played_count = 0
    clear_count = 0
    full_count = 0
    dondaful_count = 0
    blank_rank_count = 0
    rank_counts = {rank_value: 0 for rank_value in range(2, 9)}
    active_song_ids = load_active_song_ids()

    for song_id, level, _ in progress_items:
        key = (_safe_int(song_id), _safe_int(level))
        if key in seen:
            continue
        if key[0] not in active_song_ids:
            continue
        seen.add(key)
        total_count += 1

        entry = best_map.get(key)
        if not isinstance(entry, dict):
            continue
        played_count += 1

        has_dondaful = _safe_int(entry.get("dondaful_combo_cnt", 0)) > 0
        has_full = _safe_int(entry.get("full_combo_cnt", 0)) > 0
        has_clear = _safe_int(entry.get("clear_cnt", 0)) > 0
        if has_dondaful:
            dondaful_count += 1
        elif has_full:
            full_count += 1
        elif has_clear:
            clear_count += 1

        rank_value = _safe_int(entry.get("best_score_rank", 0))
        if 2 <= rank_value <= 8:
            rank_counts[rank_value] += 1
        else:
            blank_rank_count += 1

    return StarProgressSummary(
        total_count=total_count,
        played_count=played_count,
        unplayed_count=max(0, total_count - played_count),
        clear_count=clear_count,
        full_count=full_count,
        dondaful_count=dondaful_count,
        blank_rank_count=blank_rank_count,
        rank_counts=rank_counts,
    )
