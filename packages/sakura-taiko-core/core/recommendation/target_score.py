from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from ..models.calculation import SongMetrics, RatingResult, SongStats
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table, _calc_accuracy_for_record, aggregate_topN_value
from ..dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims
from ..chart.roll import compute_rating_roll_breakdown
from .support import clamp, safe_float, safe_int

def score_target_tolerance(chart: Dict[str, Any], target_score: int, speed_ips: float) -> Optional[Dict[str, int | float | bool]]:
    """Return the score target's canonical good/ok tolerance at one roll speed."""
    note_count = safe_int(chart.get('max_combo'), 0)
    good_points = safe_int(chart.get('initial_points'), 0)
    ok_points = safe_int(chart.get('ok_points'), 0)
    delta = good_points - ok_points
    if note_count <= 0 or good_points <= 0 or delta <= 0 or (target_score <= 0):
        return None
    roll_score = compute_rating_roll_breakdown(chart, speed_ips).effective_roll_hits * 100
    max_score = note_count * good_points + roll_score
    min_score = note_count * ok_points + roll_score
    if max_score < target_score:
        return {'reachable': False, 'max_ok': -1, 'max_score': max_score, 'min_score': min_score}
    if min_score >= target_score:
        max_ok = note_count
    else:
        max_ok = max(0, min(note_count, (max_score - target_score) // delta))
    return {'reachable': True, 'max_ok': int(max_ok), 'max_score': max_score, 'min_score': min_score}

def required_dims_for_target_accuracy(*, feature: Dict[str, float], target_accuracy: float, const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    const_value = safe_float(feature.get('const'), 0.0)
    if const_value <= 0 or not const_table:
        return None
    M = float(lookup_const_score(const_value, const_table))
    N = float(calc_y(target_accuracy, normalization_factor=15.5, algorithm='comprehensive'))
    P = float(compute_P(M, N))
    Q = float(compute_Q(M, N))
    AI = float(compute_AI(M, N, P, Q))
    metrics = SongMetrics(complex_proc=safe_float(feature.get('complex'), 0.0), stamina=safe_float(feature.get('stamina'), 0.0), speed=safe_float(feature.get('speed'), 0.0), rhythm=safe_float(feature.get('rhythm'), 0.0))
    six_dims = compute_six_dims(AI, M, N, metrics)
    return {'big_song': float(six_dims.get('大歌力', 0.0)), 'stamina': float(six_dims.get('体力', 0.0)), 'speed': float(six_dims.get('高速处理', 0.0)), 'accuracy_power': float(six_dims.get('精度力', 0.0)), 'rhythm': float(six_dims.get('节奏处理', 0.0)), 'complex': float(six_dims.get('复合处理', 0.0))}

def target_score_required_dims(*, chart: Dict[str, Any], feature: Dict[str, float], target_score: int, tolerance: Dict[str, int | float | bool], const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    note_count = max(1, safe_int(chart.get('max_combo'), 1))
    max_ok = max(0, safe_int(tolerance.get('max_ok'), 0))
    ok_allow_ratio = clamp(max_ok / note_count, 0.0, 1.0)
    target_accuracy = clamp(1.0 - 0.5 * ok_allow_ratio, 0.0, 1.0)
    return required_dims_for_target_accuracy(feature=feature, target_accuracy=target_accuracy, const_table=const_table)
