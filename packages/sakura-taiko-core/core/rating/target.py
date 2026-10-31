from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table

@dataclass(frozen=True)
class SongRatingTargetResult:
    reachable: bool
    target_rating: float
    achieved_rating: float
    max_rating: float
    good_count: int
    ok_count: int
    note_count: int
    accuracy: float

def _rating_for_ok_count(note_count: int, ok_count: int, const_score: float) -> float:
    accuracy = 1.0 - 0.5 * ok_count / note_count
    precision_score = calc_y(accuracy, normalization_factor=15.5, algorithm='comprehensive')
    return compute_AI(const_score, precision_score, compute_P(const_score, precision_score), compute_Q(const_score, precision_score))

def compute_song_rating_target(song_info: Dict[str, Any], target_rating: float, *, const_table) -> SongRatingTargetResult:
    note_count = int(song_info.get('combo', 0) or 0)
    if note_count <= 0:
        raise ValueError('谱面音符数数据不完整。')
    const_score = lookup_const_score(float(song_info.get('score', 0) or 0), const_table)
    max_rating = _rating_for_ok_count(note_count, 0, const_score)
    if max_rating + 1e-12 < target_rating:
        return SongRatingTargetResult(False, target_rating, max_rating, max_rating, note_count, 0, note_count, 1.0)
    low, high = (0, note_count)
    while low < high:
        mid = (low + high + 1) // 2
        if _rating_for_ok_count(note_count, mid, const_score) + 1e-12 >= target_rating:
            low = mid
        else:
            high = mid - 1
    ok_count = low
    good_count = note_count - ok_count
    accuracy = 1.0 - 0.5 * ok_count / note_count
    achieved_rating = _rating_for_ok_count(note_count, ok_count, const_score)
    return SongRatingTargetResult(True, target_rating, achieved_rating, max_rating, good_count, ok_count, note_count, accuracy)
