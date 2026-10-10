from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.score import progress as _progress

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Tuple

from .progress_catalog import load_active_song_ids


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


StarProgressSummary = _progress.StarProgressSummary


def build_star_progress_summary(progress_items, best_map):
    return _progress.build_star_progress_summary(progress_items, best_map,
        active_song_ids=load_active_song_ids())
