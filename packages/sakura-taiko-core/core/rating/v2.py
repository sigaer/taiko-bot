from __future__ import annotations
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, Iterable, Literal, Sequence
from ..models.calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef
from dataclasses import replace
from heapq import nlargest
from .v1 import calc_y

def _calc_ln_rating(rating: float, dimension_value: float, accuracy: float) -> float:
    base = min(rating, dimension_value)
    upper = max(rating, dimension_value)
    if dimension_value <= rating:
        if dimension_value <= 0:
            return base
        return base + min(accuracy / dimension_value, 1.0) * math.log(upper - base + 1.0)

    rt1 = base + min(accuracy / max(dimension_value, 1e-9), 1.0) * math.log(
        upper - base + 1.0
    )
    rt2 = math.sqrt(base * upper)
    if accuracy <= rating:
        weight_one, weight_two = 1.0, 0.0
    elif accuracy >= dimension_value:
        weight_one, weight_two = 0.0, 1.0
    else:
        denominator = max(dimension_value - rating, 1e-9)
        weight_one = (accuracy - rating) / denominator
        weight_two = (dimension_value - accuracy) / denominator
    return rt1 * weight_one + rt2 * weight_two

def _accuracy_for_profile(rating: float, accuracy: float, profile: str) -> float:
    if profile == "v2-center-20261010":
        return _calc_accuracy_rating(rating, accuracy)
    if profile == "v2-client-20261010":
        return _calc_ln_rating(rating, accuracy, accuracy)
    raise ValueError("unknown v2 algorithm profile")
V2_DIM_COLUMNS = ["体力", "手速", "爆发", "精度", "节奏", "复合"]

WEIGHTS_A = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

WEIGHTS_B = [20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1]

V2_COL_TO_ATTR = {
    "AI_rating": "AI_rating",
    "综合Rating": "AI_rating",
    "体力": "stamina_rt",
    "手速": "handspeed_rt",
    "爆发": "burst_rt",
    "精度": "accuracy_rt",
    "节奏": "rhythm_rt",
    "复合": "complex_rt",
}

DONDARU_EXCEPTIONS = frozenset(
    {
        (775, 4),
        (775, 5),
        (1032, 5),
        (1037, 4),
        (1356, 4),
    }
)

def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default

def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))

def _calc_p(x: float, y: float, p1: float = 150.0) -> float:
    term = p1**2 - ((x - y) ** 2) / 2.0
    if term < 0:
        return p1
    return p1 - math.sqrt(term)

def _calc_w(x: float, y: float) -> float:
    term = 25 - ((x - 15.5) ** 2) / 25.0 - ((y - 23.0) ** 2) / 69.0
    if term < 0:
        return 0.5
    return max(math.sqrt(term) - 4.0, 0.5)

def _calc_single_rating(x: float, y: float) -> float:
    p = _calc_p(x, y)
    w = _calc_w(x, y)
    if abs(p) < 1e-9:
        x = max(x, 1e-9)
        y = max(y, 1e-9)
        return math.exp(w * math.log(x) + (1.0 - w) * math.log(y))
    value = w * (x**p) + (1.0 - w) * (y**p)
    value = max(value, 0.0)
    return value ** (1.0 / p)

def _calc_accuracy_rating(rating: float, accuracy: float) -> float:
    base = min(rating, accuracy)
    upper = max(rating, accuracy)
    return base + math.log(upper - base + 1.0)

def _calculate_v2_from_chart(
    chart: V2SongData,
    *,
    accuracy_per: float,
    bad_per: float,
    profile: str = "v2-center-20261010",
) -> V2RatingResult:
    accuracy_per = _clamp01(accuracy_per)
    bad_per = _clamp01(bad_per)
    accuracy = calc_y(accuracy_per, normalization_factor=15.5, algorithm="comprehensive")

    rt_90 = _calc_single_rating(chart.sub_constant_1, calc_y(0.9, 15.5, "comprehensive"))
    rt_95_ref = _calc_single_rating(
        chart.sub_constant_1, calc_y(0.95, 15.5, "comprehensive")
    )
    rt_95 = _calc_single_rating(chart.main_constant, calc_y(0.95, 15.5, "comprehensive"))
    rt_100_ref = _calc_single_rating(
        chart.main_constant, calc_y(1.0, 15.5, "comprehensive")
    )
    rt_100 = _calc_single_rating(chart.sub_constant_2, calc_y(1.0, 15.5, "comprehensive"))

    x_ini = chart.sub_constant_1 if accuracy_per <= 0.95 else chart.main_constant
    rt_ini = _calc_single_rating(x_ini, accuracy)

    if accuracy_per <= 0.9:
        rating = rt_ini
    elif accuracy_per <= 0.95:
        denom = rt_95_ref - rt_90
        if abs(denom) < 1e-9:
            rating = rt_95
        else:
            rating = rt_90 + (rt_95 - rt_90) * (rt_ini - rt_90) / denom
    else:
        denom = rt_100_ref - rt_95
        if abs(denom) < 1e-9:
            rating = rt_100
        else:
            rating = rt_95 + (rt_100 - rt_95) * (rt_ini - rt_95) / denom

    accuracy_rt = _accuracy_for_profile(rating, accuracy, profile)
    stamina_rt = _calc_single_rating(chart.stamina, accuracy)
    handspeed_rt = _calc_single_rating(chart.handspeed, accuracy)

    burst_rt_base = _calc_single_rating(chart.burst, accuracy)
    burst_hs_factor = (
        min(accuracy / chart.handspeed, 1.0) if chart.handspeed > 0 else 1.0
    )
    burst_candidate = burst_rt_base * burst_hs_factor
    if burst_candidate > handspeed_rt:
        denom = chart.burst - chart.handspeed
        if abs(denom) < 1e-9:
            blend = 1.0 if accuracy > chart.handspeed else 0.0
        else:
            blend = min(max(accuracy - chart.handspeed, 0.0) / denom, 1.0)
        burst_rt = handspeed_rt + blend * (burst_candidate - handspeed_rt)
    else:
        burst_rt = burst_candidate

    complex_rt_base = _calc_single_rating(chart.complex, accuracy)
    complex_penalty = (5000.0 / 9.0) * (max(0.03 - bad_per, 0.0) ** 2) + 0.5
    complex_rt = complex_rt_base * complex_penalty

    rhythm_rt_base = _calc_single_rating(chart.rhythm, accuracy)
    rhythm_rt = rhythm_rt_base * burst_hs_factor

    return V2RatingResult(
        song_id=chart.song_id,
        level=chart.level,
        song_name=chart.title,
        high_score=0,
        accuracy=accuracy_per,
        bad_rate=bad_per,
        AI_rating=rating,
        stamina_rt=stamina_rt,
        handspeed_rt=handspeed_rt,
        burst_rt=burst_rt,
        complex_rt=complex_rt,
        rhythm_rt=rhythm_rt,
        accuracy_rt=accuracy_rt,
    )

def _weighted_average(values: List[float], weights: List[int]) -> float:
    count = min(len(values), len(weights))
    if count <= 0:
        return 0.0
    total = 0.0
    total_weight = 0.0
    for idx in range(count):
        total += values[idx] * weights[idx]
        total_weight += weights[idx]
    return total / total_weight if total_weight > 0 else 0.0

def _calc_full_score_refs_for_snapshot(
    revision: str,
    songs: Tuple[V2SongData, ...],
    profile: str = "v2-center-20261010",
) -> Dict[str, FullScoreRef]:
    _ = revision
    refs: Dict[str, FullScoreRef] = {}
    full_results = [
        _calculate_v2_from_chart(chart, accuracy_per=1.0, bad_per=0.0, profile=profile)
        for chart in songs
    ]
    for col, attr in V2_COL_TO_ATTR.items():
        if col == "综合Rating":
            continue
        values = sorted(
            [float(getattr(result, attr)) for result in full_results],
            reverse=True,
        )
        top20 = values[:20]
        refs[col] = FullScoreRef(
            threshold=14.0,
            fullA=_weighted_average(top20, WEIGHTS_A),
            fullB=_weighted_average(top20, WEIGHTS_B),
        )
    refs["综合Rating"] = refs["AI_rating"]
    return refs

def aggregate_topN_value_v2(results: List[V2RatingResult], col: str, N: int, *, full_score_refs: Mapping[str, FullScoreRef] | None = None) -> float:
    attr = V2_COL_TO_ATTR.get(col)
    if not attr:
        raise KeyError(f"未知维度列名: {col}")

    values = (
        float(getattr(result, attr))
        for result in results
        if getattr(result, attr, None) is not None
    )
    top_values = nlargest(N, values)
    if not top_values:
        return 0.0

    if N != 20:
        return sum(top_values) / len(top_values)

    if full_score_refs is None:
        raise ValueError("v2 Top20 requires explicit full-score references")
    refs = full_score_refs[col]
    playerA = _weighted_average(top_values, WEIGHTS_A)
    playerB = _weighted_average(top_values, WEIGHTS_B)
    if playerB < refs.threshold or refs.fullB <= refs.threshold:
        return playerA
    per = (playerB - refs.threshold) / (refs.fullB - refs.threshold)
    return playerA + per * (15.5 - playerA)

def compute_dim_topN_means_v2(
    results: List[V2RatingResult],
    N: int = 20,
    *, full_score_refs: Mapping[str, FullScoreRef] | None = None,
) -> Dict[str, float]:
    return {
        dim_name: aggregate_topN_value_v2(results, dim_name, N, full_score_refs=full_score_refs)
        for dim_name in V2_DIM_COLUMNS
    }
