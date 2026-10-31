from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
import heapq
from ..chart.catalog import _get_recommend_identity_key
from ..chart.roll import compute_rating_roll_breakdown, compute_rating_roll_capacity
from ..score.forecast import ChartPerformanceForecast, build_chart_performance_forecast
from .support import chart_title_key, clamp, entry_age_days, safe_float, safe_int
from .entries import resolve_best_entry_for_chart, resolve_chart_feature
from .target_score import required_dims_for_target_accuracy, score_target_tolerance, target_score_required_dims
from .center import TARGET_RECOMMENDATION_PRIMARY_TOPN, TARGET_RECOMMENDATION_PROFILE_DISCOUNT, _build_rating_results_profile, _build_score_history_profile, _const_match, _discount_user_profile, _profile_match, _single_dim_overflow_slack, _score_target_capacity_pressure_penalty, _score_target_likelihood

ROLL_SPEED_CAP = 35.0
STABLE_RATE_QUANTILE = 0.55
PB_RATE_QUANTILE = 0.85
STABLE_ROLL_QUANTILE = 0.6
PB_ROLL_QUANTILE = 0.8
EXACT_POOL_MIN = 12
POOLED_POOL_MIN = 20
EXACT_POOL_RECENT_DAYS = 365
EXACT_POOL_RECENT_THRESHOLD = 40
SAME_LEVEL_NEIGHBORS = 12
TOTAL_NEIGHBORS = 20
NEIGHBOR_DISTANCE_DENOMINATOR = 0.18
CHART_EVIDENCE_MAX_DISTANCE = 0.85
CHART_EVIDENCE_MIN_SCORE_CAP_SAMPLES = 6
STABLE_CHART_SCORE_CAP_QUANTILE = 0.55
PB_CHART_SCORE_CAP_QUANTILE = 0.85
STABLE_CHART_SCORE_CAP_SLACK = 0.008
PB_CHART_SCORE_CAP_SLACK = 0.012
CHART_ROLL_EVIDENCE_MIN_SAMPLES = 3
HARD_MISMATCH_CONST_GAP = 2.25
STABLE_LIKELIHOOD_THRESHOLD = 18.0
PB_LIKELIHOOD_THRESHOLD = 10.0
HIGH_CONST_CAP_START = 10.8
HIGH_CONST_CAP_WINDOW = 0.25
HIGH_CONST_CAP_WIDEN_WINDOW = 0.4
HIGH_CONST_CAP_MIN_SAMPLES = 3
HARD_CONST_EXTRAPOLATION_LIMIT = 1.2
HARD_CONST_EXTRAPOLATION_SAMPLE_COUNT = 8
STABLE_CAP_QUANTILE = 0.65
PB_CAP_QUANTILE = 0.9
STABLE_CAP_SLACK = 0.01
PB_CAP_SLACK = 0.02
STABLE_CAP_CONST_DECAY = 0.12
PB_CAP_CONST_DECAY = 0.1
MIN_CAP_RATIO = 0.25
OBJECTIVE_HARD_SINGLE_RATIO = 2.25
OBJECTIVE_HARD_SECOND_RATIO = 1.85
OBJECTIVE_HARD_CONST_RATIO = 1.3
OBJECTIVE_SCORE_CAP_MAX_PENALTY = 0.18
PRECISION_EVIDENCE_LIMIT = 60
PRECISION_EVIDENCE_DENOMINATOR = 0.1
PRECISION_EVIDENCE_MAX_DISTANCE = 1.2
PRECISION_EVIDENCE_MIN_SCORE_CAP_SAMPLES = 8
STABLE_ACCURACY_CAP_QUANTILE = 0.82
PB_ACCURACY_CAP_QUANTILE = 0.985
STABLE_ACCURACY_CAP_SLACK = 0.004
PB_ACCURACY_CAP_SLACK = 0.002
STABLE_ACCURACY_POWER_CAP_QUANTILE = 0.9
PB_ACCURACY_POWER_CAP_QUANTILE = 0.985
STABLE_ACCURACY_POWER_CAP_SLACK = 0.3
PB_ACCURACY_POWER_CAP_SLACK = 0.15
PRECISION_ACCURACY_CAP_MAX = 0.999
PRECISION_ACCURACY_POWER_CAP_MAX = 15.5
PRECISION_ACCURACY_SOFT_WIDTH = 0.012
PRECISION_ACCURACY_POWER_SOFT_WIDTH = 0.35
PRECISION_MAX_LIKELIHOOD_PENALTY = 18.0
STABLE_FEATURE_SCORE_CAP_QUANTILE = 0.7
PB_FEATURE_SCORE_CAP_QUANTILE = 0.92
STABLE_FEATURE_SCORE_CAP_SLACK = 0.01
PB_FEATURE_SCORE_CAP_SLACK = 0.015
STABLE_ESTIMATION_DIM_TOLERANCE = {'big_song': 0.08, 'stamina': 0.08, 'speed': 0.06, 'accuracy_power': 0.08, 'rhythm': 0.05, 'complex': 0.08}
PB_ESTIMATION_DIM_TOLERANCE = {'big_song': 0.16, 'stamina': 0.15, 'speed': 0.12, 'accuracy_power': 0.15, 'rhythm': 0.08, 'complex': 0.12}
TARGET_REACH_HISTORY_WEIGHT_MAX = 0.75
TARGET_REACH_LOAD_EXPONENT = 1.6
TARGET_REACH_DIM_WEIGHTS = {'accuracy_power': 0.3, 'accuracy_rate': 0.25, 'hit_rate': 0.1, 'big_song': 0.08, 'stamina': 0.07, 'speed': 0.08, 'rhythm': 0.05, 'complex': 0.07}

@dataclass(frozen=True)
class ScoreEstimateSnapshot:
    score: int
    raw_score: float
    good_rate: float
    hit_rate: float
    roll_speed_ips: float
    pred_good: int
    pred_ok: int
    pred_ng: int
    pred_pound: int
    neighbor_count: int
    profile_match: float

@dataclass(frozen=True)
class ChartScoreEstimate:
    song_id: int
    level: int
    current_score: Optional[int]
    goku_score: int
    score_ceiling_35ips: int
    above_goku: bool
    reliability: float
    data_sufficiency: str
    stable: Optional[ScoreEstimateSnapshot]
    pb: Optional[ScoreEstimateSnapshot]

@dataclass(frozen=True)
class HistorySample:
    song_id: int
    level: int
    identity: Tuple[str, int, int] | Tuple[str, str, int]
    title_key: str
    const_value: float
    good_rate: float
    accuracy_rate: float
    accuracy_power: float
    hit_rate: float
    score_ratio: float
    roll_speed_ips: Optional[float]
    age_days: Optional[int]
    weight: float
    vector: Tuple[float, float, float, float, float, float, float, float]

@dataclass(frozen=True)
class DifficultyBandCap:
    stable_ratio: float
    pb_ratio: float
    sample_count: int
    has_evidence: bool

@dataclass(frozen=True)
class PrecisionEvidenceProfile:
    stable_accuracy_cap: float
    pb_accuracy_cap: float
    stable_accuracy_power_cap: float
    pb_accuracy_power_cap: float
    sample_count: int
    has_evidence: bool

@dataclass(frozen=True)
class TargetReachEstimate:
    """A conservative, current-skill estimate for one score target."""
    likelihood: float
    objective_load: float
    history_confidence: float
    required_good_rate: float
    required_hit_rate: float
    required_accuracy_rate: float
    required_accuracy_power: float
    roll_speed_ips: float
    used_roll_evidence: bool
    required_dims: Dict[str, float]
    single_attempt_probability: float = 0.0
    three_attempt_probability: float = 0.0
    stable_score: int = 0
    pb_score: int = 0
    forecast_confidence: float = 0.0

@dataclass(frozen=True)
class TargetReachContext:
    evidence: List[Tuple[HistorySample, float]]
    weights: List[float]
    history_confidence: float
    good_rate_cap: float
    hit_rate_cap: float
    accuracy_rate_cap: float
    accuracy_power_cap: float
    roll_speed_ips: float
    used_roll_evidence: bool

@dataclass(frozen=True)
class ScoreEstimatorProfile:
    user_profile: Any
    stable_profile: Any
    pb_profile: Any
    best_map: Dict[Tuple[int, int], Dict[str, Any]]
    title_keys_by_id: Dict[int, str]
    features_by_key: Dict[Tuple[int, int], Dict[str, float]]
    features_by_title_level: Dict[Tuple[str, int], Dict[str, float]]
    const_table: List[Tuple[float, float]]
    samples: List[HistorySample]
    chart_by_key: Dict[Tuple[int, int], Dict[str, Any]]
    default_ids: Mapping[int, int]

def _history_recency_weight(age_days: Optional[int]) -> float:
    if age_days is None:
        return 0.2
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.75
    if age_days <= 180:
        return 0.45
    return 0.2

def _round_to_1000(value: float) -> int:
    return int(math.floor(max(0.0, float(value)) / 1000.0 + 0.5) * 1000)

def _weighted_quantile(values: Iterable[Optional[float]], weights: Iterable[float], quantile: float, *, default: float) -> float:
    pairs = [(float(value), max(0.0, float(weight))) for value, weight in zip(values, weights) if value is not None and math.isfinite(float(value)) and (float(weight) > 0)]
    if not pairs:
        return default
    pairs.sort(key=lambda item: item[0])
    total = sum((weight for _, weight in pairs))
    if total <= 0:
        return default
    target = clamp(quantile, 0.0, 1.0) * total
    cumulative = 0.0
    for value, weight in pairs:
        cumulative += weight
        if cumulative >= target:
            return value
    return pairs[-1][0]

def _chart_vector(chart: Dict[str, Any], feature: Dict[str, float]) -> Tuple[float, float, float, float, float, float, float, float]:
    return (safe_float(feature.get('const'), 0.0) / 15.5, safe_float(feature.get('stamina'), 0.0) / 100.0, safe_float(feature.get('speed'), 0.0) / 100.0, safe_float(feature.get('rhythm'), 0.0) / 100.0, safe_float(feature.get('complex'), 0.0) / 100.0, safe_float(feature.get('hs_change'), 0.0) / 100.0, safe_float(chart.get('max_combo'), 0.0) / 2000.0, compute_rating_roll_capacity(chart).variable_roll_seconds / 20.0)

def _vector_distance(left: Tuple[float, float, float, float, float, float, float, float], right: Tuple[float, float, float, float, float, float, float, float]) -> float:
    diffs = [l - r for l, r in zip(left, right)]
    return 2.2 * diffs[0] ** 2 + 1.4 * diffs[1] ** 2 + 1.6 * diffs[2] ** 2 + 1.2 * diffs[3] ** 2 + 1.2 * diffs[4] ** 2 + 0.8 * diffs[5] ** 2 + 0.6 * diffs[6] ** 2 + 0.5 * diffs[7] ** 2

def _score_ceiling_35ips(chart: Dict[str, Any]) -> int:
    note_count = max(0, safe_int(chart.get('max_combo'), 0))
    good_points = max(0, safe_int(chart.get('initial_points'), 0))
    roll_hits = compute_rating_roll_breakdown(chart, ROLL_SPEED_CAP).effective_roll_hits
    return note_count * good_points + roll_hits * 100

def _infer_observed_roll_speed_ips(chart: Dict[str, Any], pound_cnt: int) -> Optional[float]:
    capacity = compute_rating_roll_capacity(chart)
    if capacity.variable_roll_seconds <= 0:
        return None
    return clamp((max(0, pound_cnt) - capacity.fixed_balloon_hits) / capacity.variable_roll_seconds, 0.0, ROLL_SPEED_CAP)

def _build_history_samples(best_map: Dict[Tuple[int, int], Dict[str, Any]], title_keys_by_id: Dict[int, str], features_by_key: Dict[Tuple[int, int], Dict[str, float]], features_by_title_level: Dict[Tuple[str, int], Dict[str, float]], const_table: List[Tuple[float, float]], *, default_ids, chart_by_key, today: date) -> List[HistorySample]:
    samples: List[HistorySample] = []
    for (song_id, level), entry in best_map.items():
        if level not in (4, 5):
            continue
        title_key = title_keys_by_id.get(song_id, '')
        chart = chart_by_key.get((song_id, level))
        if chart is None:
            continue
        feature = resolve_chart_feature(song_id=song_id, level=level, title_key=title_key, features_by_key=features_by_key, features_by_title_level=features_by_title_level)
        if feature is None:
            continue
        total_notes = max(0, safe_int(chart.get('max_combo'), 0))
        if total_notes <= 0:
            continue
        good_cnt = max(0, safe_int(entry.get('good_cnt'), 0))
        ok_cnt = max(0, safe_int(entry.get('ok_cnt'), 0))
        hit_cnt = min(total_notes, max(good_cnt, good_cnt + ok_cnt))
        good_rate = clamp(good_cnt / total_notes, 0.0, 1.0)
        accuracy_rate = clamp((good_cnt + ok_cnt * 0.5) / total_notes, 0.0, 1.0)
        accuracy_dims = required_dims_for_target_accuracy(feature=feature, target_accuracy=accuracy_rate, const_table=const_table)
        accuracy_power = safe_float(accuracy_dims.get('accuracy_power'), 0.0) if isinstance(accuracy_dims, dict) else 0.0
        hit_rate = clamp(hit_cnt / total_notes, good_rate, 1.0)
        ceiling = max(1, _score_ceiling_35ips(chart))
        high_score = max(0, safe_int(entry.get('high_score'), 0))
        score_ratio = clamp(min(high_score, ceiling) / ceiling, 0.0, 1.0)
        observed_roll_speed = _infer_observed_roll_speed_ips(chart, max(0, safe_int(entry.get('pound_cnt'), 0)))
        age_days = entry_age_days(entry, today=today)
        weight = _history_recency_weight(age_days) * clamp(score_ratio, 0.55, 1.0)
        identity = _get_recommend_identity_key(song_id, level, default_ids=default_ids)
        samples.append(HistorySample(song_id=song_id, level=level, identity=identity, title_key=title_key, const_value=safe_float(feature.get('const'), 0.0), good_rate=good_rate, accuracy_rate=accuracy_rate, accuracy_power=accuracy_power, hit_rate=hit_rate, score_ratio=score_ratio, roll_speed_ips=observed_roll_speed, age_days=age_days, weight=weight, vector=_chart_vector(chart, feature)))
    return samples

def _exclude_target_records(records: List[Dict[str, Any]], *, exclude_song_id: Optional[int], exclude_level: Optional[int], default_ids) -> List[Dict[str, Any]]:
    if exclude_song_id is None or exclude_level is None:
        return records
    target_identity = _get_recommend_identity_key(exclude_song_id, exclude_level, default_ids=default_ids)
    filtered: List[Dict[str, Any]] = []
    for record in records:
        record_level = safe_int(record.get('level'), -1)
        if record_level != exclude_level:
            filtered.append(record)
            continue
        record_song_id = safe_int(record.get('song_no', record.get('song_id', record.get('id', -1))), -1)
        if record_song_id < 0:
            filtered.append(record)
            continue
        record_identity = _get_recommend_identity_key(record_song_id, record_level, default_ids=default_ids)
        if record_identity == target_identity:
            continue
        filtered.append(record)
    return filtered

def _build_estimator_user_profiles(rating_results, best_map: Dict[Tuple[int, int], Dict[str, Any]], charts: List[Dict[str, Any]], features_by_key: Dict[Tuple[int, int], Dict[str, float]]) -> Tuple[Any, Any]:
    fallback = _build_score_history_profile(best_map, charts, features_by_key)
    if not rating_results:
        stable_profile = _discount_user_profile(fallback, TARGET_RECOMMENDATION_PROFILE_DISCOUNT)
        return (stable_profile, fallback)
    pb_profile = _build_rating_results_profile(rating_results, fallback, top_n=TARGET_RECOMMENDATION_PRIMARY_TOPN)
    stable_profile = _discount_user_profile(pb_profile, TARGET_RECOMMENDATION_PROFILE_DISCOUNT)
    return (stable_profile, pb_profile)

def _select_exact_pool(samples: List[HistorySample], level: int) -> List[HistorySample]:
    exact = [sample for sample in samples if sample.level == level]
    if len(exact) < EXACT_POOL_RECENT_THRESHOLD:
        return exact
    recent = [sample for sample in exact if sample.age_days is not None and sample.age_days <= EXACT_POOL_RECENT_DAYS]
    return recent

def _select_neighbors(samples: List[HistorySample], target_vector: Tuple[float, float, float, float, float, float, float, float], level: int) -> List[Tuple[HistorySample, float]]:
    exact_ranked: List[Tuple[HistorySample, float]] = []
    pooled_ranked: List[Tuple[HistorySample, float]] = []
    for sample in samples:
        distance = _vector_distance(sample.vector, target_vector)
        if sample.level == level:
            exact_ranked.append((sample, distance))
        else:
            pooled_ranked.append((sample, distance))
    exact_ranked.sort(key=lambda item: item[1])
    pooled_ranked.sort(key=lambda item: item[1])
    picked: List[Tuple[HistorySample, float]] = exact_ranked[:SAME_LEVEL_NEIGHBORS]
    picked_ids = {(sample.song_id, sample.level) for sample, _ in picked}
    for sample, distance in pooled_ranked:
        if len(picked) >= TOTAL_NEIGHBORS:
            break
        key = (sample.song_id, sample.level)
        if key in picked_ids:
            continue
        picked.append((sample, distance))
        picked_ids.add(key)
    return picked

def _neighbor_weights(neighbors: List[Tuple[HistorySample, float]], level: int) -> List[float]:
    weights: List[float] = []
    for sample, distance in neighbors:
        base = math.exp(-distance ** 2 / NEIGHBOR_DISTANCE_DENOMINATOR)
        weights.append(base * (1.15 if sample.level == level else 0.7))
    return weights

def _select_precision_evidence(samples: List[HistorySample], target_vector: Tuple[float, float, float, float, float, float, float, float]) -> List[Tuple[HistorySample, float]]:
    ranked = [(sample, _vector_distance(sample.vector, target_vector)) for sample in samples if sample.accuracy_rate > 0 and sample.accuracy_power > 0]
    return [item for item in heapq.nsmallest(PRECISION_EVIDENCE_LIMIT, ranked, key=lambda item: item[1]) if item[1] <= PRECISION_EVIDENCE_MAX_DISTANCE]

def _select_chart_evidence(samples: List[HistorySample], target_vector: Tuple[float, float, float, float, float, float, float, float], level: int) -> Tuple[List[Tuple[HistorySample, float]], List[Tuple[HistorySample, float]]]:
    exact: List[Tuple[HistorySample, float]] = []
    pooled: List[Tuple[HistorySample, float]] = []
    precision: List[Tuple[HistorySample, float]] = []
    for sample in samples:
        item = (sample, _vector_distance(sample.vector, target_vector))
        if sample.level == level:
            exact.append(item)
        else:
            pooled.append(item)
        if sample.accuracy_rate > 0 and sample.accuracy_power > 0:
            precision.append(item)
    exact = [item for item in exact if item[1] <= CHART_EVIDENCE_MAX_DISTANCE]
    pooled = [item for item in pooled if item[1] <= CHART_EVIDENCE_MAX_DISTANCE]
    picked = heapq.nsmallest(SAME_LEVEL_NEIGHBORS, exact, key=lambda item: item[1])
    if len(picked) < TOTAL_NEIGHBORS:
        picked.extend(heapq.nsmallest(TOTAL_NEIGHBORS - len(picked), pooled, key=lambda item: item[1]))
    precision_picked = [item for item in heapq.nsmallest(PRECISION_EVIDENCE_LIMIT, precision, key=lambda item: item[1]) if item[1] <= PRECISION_EVIDENCE_MAX_DISTANCE]
    return (picked, precision_picked)

def _chart_evidence_weights(evidence: List[Tuple[HistorySample, float]], level: int) -> List[float]:
    return [max(0.0, sample.weight) * math.exp(-distance / 0.35) * (1.15 if sample.level == level else 0.75) for sample, distance in evidence]

def _chart_evidence_score_cap(evidence: List[Tuple[HistorySample, float]], level: int) -> DifficultyBandCap:
    if len(evidence) < CHART_EVIDENCE_MIN_SCORE_CAP_SAMPLES:
        return DifficultyBandCap(1.0, 1.0, len(evidence), False)
    weights = _chart_evidence_weights(evidence, level)
    stable_ratio = clamp(_weighted_quantile((sample.score_ratio for sample, _ in evidence), weights, STABLE_CHART_SCORE_CAP_QUANTILE, default=1.0) + STABLE_CHART_SCORE_CAP_SLACK, MIN_CAP_RATIO, 1.0)
    pb_ratio = clamp(_weighted_quantile((sample.score_ratio for sample, _ in evidence), weights, PB_CHART_SCORE_CAP_QUANTILE, default=stable_ratio) + PB_CHART_SCORE_CAP_SLACK, stable_ratio, 1.0)
    return DifficultyBandCap(stable_ratio, pb_ratio, len(evidence), True)

def _roll_speed_from_chart_evidence(evidence: List[Tuple[HistorySample, float]], pool_samples: List[HistorySample], level: int, quantile: float) -> float:
    roll_evidence = [item for item in evidence if item[0].roll_speed_ips is not None]
    if len(roll_evidence) >= CHART_ROLL_EVIDENCE_MIN_SAMPLES:
        return clamp(_weighted_quantile((sample.roll_speed_ips for sample, _ in roll_evidence), _chart_evidence_weights(roll_evidence, level), quantile, default=25.0), 0.0, ROLL_SPEED_CAP)
    return clamp(_weighted_quantile((sample.roll_speed_ips for sample in pool_samples), (sample.weight for sample in pool_samples), quantile, default=25.0), 0.0, ROLL_SPEED_CAP)

def _precision_evidence_weights(evidence: List[Tuple[HistorySample, float]], level: int) -> List[float]:
    weights: List[float] = []
    for sample, distance in evidence:
        base = math.exp(-distance ** 2 / PRECISION_EVIDENCE_DENOMINATOR)
        level_factor = 1.15 if sample.level == level else 0.85
        weights.append(max(0.0, sample.weight) * base * level_factor)
    return weights

def _build_precision_evidence_profile(evidence: List[Tuple[HistorySample, float]], level: int) -> PrecisionEvidenceProfile:
    if not evidence:
        return PrecisionEvidenceProfile(stable_accuracy_cap=PRECISION_ACCURACY_CAP_MAX, pb_accuracy_cap=PRECISION_ACCURACY_CAP_MAX, stable_accuracy_power_cap=PRECISION_ACCURACY_POWER_CAP_MAX, pb_accuracy_power_cap=PRECISION_ACCURACY_POWER_CAP_MAX, sample_count=0, has_evidence=False)
    samples = [sample for sample, _ in evidence]
    weights = _precision_evidence_weights(evidence, level)
    stable_accuracy_cap = clamp(_weighted_quantile((sample.accuracy_rate for sample in samples), weights, STABLE_ACCURACY_CAP_QUANTILE, default=PRECISION_ACCURACY_CAP_MAX) + STABLE_ACCURACY_CAP_SLACK, 0.0, PRECISION_ACCURACY_CAP_MAX)
    pb_accuracy_cap = clamp(_weighted_quantile((sample.accuracy_rate for sample in samples), weights, PB_ACCURACY_CAP_QUANTILE, default=stable_accuracy_cap) + PB_ACCURACY_CAP_SLACK, stable_accuracy_cap, PRECISION_ACCURACY_CAP_MAX)
    stable_accuracy_power_cap = clamp(_weighted_quantile((sample.accuracy_power for sample in samples), weights, STABLE_ACCURACY_POWER_CAP_QUANTILE, default=PRECISION_ACCURACY_POWER_CAP_MAX) + STABLE_ACCURACY_POWER_CAP_SLACK, 0.0, PRECISION_ACCURACY_POWER_CAP_MAX)
    pb_accuracy_power_cap = clamp(_weighted_quantile((sample.accuracy_power for sample in samples), weights, PB_ACCURACY_POWER_CAP_QUANTILE, default=stable_accuracy_power_cap) + PB_ACCURACY_POWER_CAP_SLACK, stable_accuracy_power_cap, PRECISION_ACCURACY_POWER_CAP_MAX)
    return PrecisionEvidenceProfile(stable_accuracy_cap=stable_accuracy_cap, pb_accuracy_cap=pb_accuracy_cap, stable_accuracy_power_cap=stable_accuracy_power_cap, pb_accuracy_power_cap=pb_accuracy_power_cap, sample_count=len(samples), has_evidence=True)

def _sigmoid_margin(value: float, width: float) -> float:
    if width <= 0:
        return 1.0 if value >= 0 else 0.0
    x = clamp(float(value) / width, -40.0, 40.0)
    return 1.0 / (1.0 + math.exp(-x))

def _target_record_freshness(age_days: Optional[int]) -> float:
    if age_days is None:
        return 0.1
    if age_days <= 90:
        return 1.0
    if age_days <= 180:
        return 0.45
    if age_days <= 365:
        return 0.15
    return 0.05

def _target_performance_requirements(chart: Dict[str, Any], target_score: int, roll_speed_ips: float) -> Optional[Tuple[Dict[str, int | float | bool], float, float, float]]:
    tolerance = score_target_tolerance(chart, target_score, roll_speed_ips)
    if not tolerance or not bool(tolerance.get('reachable')):
        return None
    note_count = max(1, safe_int(chart.get('max_combo'), 1))
    good_points = max(0, safe_int(chart.get('initial_points'), 0))
    ok_points = max(0, safe_int(chart.get('ok_points'), 0))
    min_score = safe_int(tolerance.get('min_score'), 0)
    if target_score >= min_score:
        max_ok = max(0, min(note_count, safe_int(tolerance.get('max_ok'), 0)))
        good_count = note_count - max_ok
        ok_count = max_ok
    else:
        missing_score = max(0, min_score - target_score)
        ng_count = min(note_count, int(math.ceil(missing_score / max(1, ok_points))))
        good_count = 0
        ok_count = note_count - ng_count
    required_good_rate = clamp(good_count / note_count, 0.0, 1.0)
    required_hit_rate = clamp((good_count + ok_count) / note_count, 0.0, 1.0)
    required_accuracy_rate = clamp((good_count + ok_count * 0.5) / note_count, 0.0, 1.0)
    return (tolerance, required_good_rate, required_hit_rate, required_accuracy_rate)

def _target_reach_context(profile: ScoreEstimatorProfile, chart: Dict[str, Any], feature: Dict[str, float]) -> TargetReachContext:
    song_id = safe_int(chart.get('id'), -1)
    level = safe_int(chart.get('level'), -1)
    target_identity = _get_recommend_identity_key(song_id, level, default_ids=profile.default_ids)
    samples = [sample for sample in profile.samples if sample.identity != target_identity]
    evidence = _select_precision_evidence(samples, _chart_vector(chart, feature))
    weights = _precision_evidence_weights(evidence, level)
    positive_weights = [weight for weight in weights if weight > 0]
    total_weight = sum(positive_weights)
    effective_count = total_weight ** 2 / sum((weight ** 2 for weight in positive_weights)) if positive_weights else 0.0
    history_confidence = min(TARGET_REACH_HISTORY_WEIGHT_MAX, TARGET_REACH_HISTORY_WEIGHT_MAX * effective_count / 20.0)
    samples_only = [sample for sample, _ in evidence]
    precision_profile = _build_precision_evidence_profile(evidence, level)
    good_rate_cap = clamp(_weighted_quantile((sample.good_rate for sample in samples_only), weights, STABLE_ACCURACY_CAP_QUANTILE, default=PRECISION_ACCURACY_CAP_MAX) + STABLE_ACCURACY_CAP_SLACK, 0.0, PRECISION_ACCURACY_CAP_MAX)
    hit_rate_cap = clamp(_weighted_quantile((sample.hit_rate for sample in samples_only), weights, STABLE_ACCURACY_CAP_QUANTILE, default=PRECISION_ACCURACY_CAP_MAX) + STABLE_ACCURACY_CAP_SLACK, 0.0, PRECISION_ACCURACY_CAP_MAX)
    used_roll_evidence = any((sample.roll_speed_ips is not None for sample in samples_only))
    roll_speed_ips = _weighted_quantile((sample.roll_speed_ips for sample in samples_only), weights, STABLE_ROLL_QUANTILE, default=25.0)
    return TargetReachContext(evidence=evidence, weights=weights, history_confidence=history_confidence, good_rate_cap=good_rate_cap, hit_rate_cap=hit_rate_cap, accuracy_rate_cap=precision_profile.stable_accuracy_cap, accuracy_power_cap=precision_profile.stable_accuracy_power_cap, roll_speed_ips=clamp(roll_speed_ips, 0.0, ROLL_SPEED_CAP), used_roll_evidence=used_roll_evidence)

def _estimate_target_reach(*, profile: ScoreEstimatorProfile, context: TargetReachContext, chart: Dict[str, Any], feature: Dict[str, float], entry: Optional[Dict[str, Any]], target_score: int, forecast: ChartPerformanceForecast, today: date) -> Optional[TargetReachEstimate]:
    requirements = _target_performance_requirements(chart, target_score, context.roll_speed_ips)
    if requirements is None:
        return None
    tolerance, required_good_rate, required_hit_rate, required_accuracy_rate = requirements
    required_dims = target_score_required_dims(chart=chart, feature=feature, target_score=target_score, tolerance=tolerance, const_table=profile.const_table)
    if not required_dims:
        return None
    required_accuracy_power = safe_float(required_dims.get('accuracy_power'), 0.0)
    capacities = getattr(profile.stable_profile, 'user_dim_capacity', {})
    ratios = {dim: safe_float(required_dims.get(dim), 0.0) / max(0.01, safe_float(capacities.get(dim), 0.0)) for dim in ('big_song', 'stamina', 'speed', 'accuracy_power', 'rhythm', 'complex')}
    load_inputs = {'accuracy_power': required_accuracy_power / max(0.01, context.accuracy_power_cap), 'accuracy_rate': required_accuracy_rate / max(0.01, context.accuracy_rate_cap), 'hit_rate': required_hit_rate / max(0.01, context.hit_rate_cap), **ratios}
    target_load = sum((weight * max(0.0, load_inputs[key]) ** TARGET_REACH_LOAD_EXPONENT for key, weight in TARGET_REACH_DIM_WEIGHTS.items()))
    raw_load = _raw_chart_objective_load(profile, feature)
    objective_load = target_load * 0.65 + raw_load * 0.35
    current_score = safe_int(entry.get('high_score'), 0) if entry is not None else None
    freshness = _target_record_freshness(entry_age_days(entry, today=today)) if entry is not None else 0.0
    single_probability = forecast.single_attempt_probability(target_score)
    likelihood = forecast.reach_probability(target_score, current_score=current_score, record_freshness=freshness, objective_load=objective_load)
    return TargetReachEstimate(likelihood=likelihood, objective_load=objective_load, history_confidence=context.history_confidence, required_good_rate=required_good_rate, required_hit_rate=required_hit_rate, required_accuracy_rate=required_accuracy_rate, required_accuracy_power=required_accuracy_power, roll_speed_ips=context.roll_speed_ips, used_roll_evidence=context.used_roll_evidence, required_dims=required_dims, single_attempt_probability=single_probability, three_attempt_probability=likelihood, stable_score=forecast.stable_score, pb_score=forecast.pb_score, forecast_confidence=forecast.confidence)

def estimate_target_reach_batch(profile: ScoreEstimatorProfile, candidates: Iterable[Dict[str, Any]], *, today: date) -> Dict[Tuple[int, int], Dict[str, TargetReachEstimate]]:
    """Evaluate all score targets for each candidate using one user profile build."""
    candidate_rows = list(candidates)
    forecasts = forecast_chart_performance_batch(profile, candidate_rows, today=today)
    results: Dict[Tuple[int, int], Dict[str, TargetReachEstimate]] = {}
    for candidate in candidate_rows:
        chart = candidate.get('chart')
        feature = candidate.get('feature')
        targets = candidate.get('targets')
        if not isinstance(chart, dict) or not isinstance(feature, dict) or (not isinstance(targets, dict)):
            continue
        key = (safe_int(chart.get('id'), -1), safe_int(chart.get('level'), -1))
        forecast = forecasts.get(key)
        if forecast is None or forecast.is_hard_mismatch:
            continue
        context = _target_reach_context(profile, chart, feature)
        row: Dict[str, TargetReachEstimate] = {}
        entry = candidate.get('entry') if isinstance(candidate.get('entry'), dict) else None
        for target_key, raw_score in targets.items():
            target_score = safe_int(raw_score, 0)
            if target_score <= 0:
                continue
            estimate = _estimate_target_reach(profile=profile, context=context, chart=chart, feature=feature, entry=entry, target_score=target_score, forecast=forecast, today=today)
            if estimate is not None:
                row[str(target_key)] = estimate
        running_probability = 1.0
        for target_key in sorted(row, key=lambda key: safe_int(targets.get(key), 0)):
            estimate = row[target_key]
            corrected = min(running_probability, estimate.likelihood)
            if corrected != estimate.likelihood:
                estimate = replace(estimate, likelihood=corrected, three_attempt_probability=corrected)
                row[target_key] = estimate
            running_probability = corrected
        if row:
            if key[0] >= 0 and key[1] in (4, 5):
                results[key] = row
    return results

def _feature_fit_score_cap(evidence: List[Tuple[HistorySample, float]], level: int) -> DifficultyBandCap:
    if len(evidence) < PRECISION_EVIDENCE_MIN_SCORE_CAP_SAMPLES:
        return DifficultyBandCap(1.0, 1.0, len(evidence), False)
    samples = [sample for sample, _ in evidence]
    weights = _precision_evidence_weights(evidence, level)
    stable_ratio = clamp(_weighted_quantile((sample.score_ratio for sample in samples), weights, STABLE_FEATURE_SCORE_CAP_QUANTILE, default=1.0) + STABLE_FEATURE_SCORE_CAP_SLACK, MIN_CAP_RATIO, 1.0)
    pb_ratio = clamp(_weighted_quantile((sample.score_ratio for sample in samples), weights, PB_FEATURE_SCORE_CAP_QUANTILE, default=stable_ratio) + PB_FEATURE_SCORE_CAP_SLACK, stable_ratio, 1.0)
    return DifficultyBandCap(stable_ratio, pb_ratio, len(samples), True)

def _estimate_reliability(profile_match: float, pool_count: int, evidence: List[Tuple[HistorySample, float]], level: int) -> float:
    if not evidence:
        return round(clamp(15.0 + min(pool_count, 40) * 0.35 + profile_match * 0.15, 0.0, 45.0), 2)
    weights = _chart_evidence_weights(evidence, level)
    positive_weights = [weight for weight in weights if weight > 0]
    effective_count = sum(positive_weights) ** 2 / sum((weight ** 2 for weight in positive_weights)) if positive_weights else 0.0
    median_distance = sorted((distance for _, distance in evidence))[len(evidence) // 2]
    pool_confidence = min(1.0, pool_count / 40.0)
    sample_confidence = min(1.0, effective_count / 10.0)
    distance_confidence = math.exp(-median_distance / 0.45)
    match_confidence = clamp(profile_match / 100.0, 0.0, 1.0)
    return round(100.0 * (0.15 * pool_confidence + 0.35 * sample_confidence + 0.3 * distance_confidence + 0.2 * match_confidence), 2)

def _samples_in_const_window(samples: List[HistorySample], target_const: float, window: float) -> List[HistorySample]:
    return [sample for sample in samples if sample.const_value > 0 and abs(sample.const_value - target_const) <= window]

def _const_window_weights(samples: List[HistorySample], target_const: float, window: float) -> List[float]:
    safe_window = max(0.05, float(window))
    return [max(0.0, sample.weight) * math.exp(-(sample.const_value - target_const) ** 2 / safe_window ** 2) for sample in samples]

def _difficulty_band_cap(samples: List[HistorySample], target_const: float) -> DifficultyBandCap:
    if target_const <= 0 or not samples:
        return DifficultyBandCap(1.0, 1.0, 0, False)
    if target_const < HIGH_CONST_CAP_START:
        return DifficultyBandCap(1.0, 1.0, 0, False)
    selected: List[HistorySample] = []
    used_window = HIGH_CONST_CAP_WINDOW
    for window in (HIGH_CONST_CAP_WINDOW, HIGH_CONST_CAP_WIDEN_WINDOW):
        selected = _samples_in_const_window(samples, target_const, window)
        used_window = window
        if len(selected) >= HIGH_CONST_CAP_MIN_SAMPLES:
            break
    if len(selected) < HIGH_CONST_CAP_MIN_SAMPLES:
        hardest = sorted([sample for sample in samples if sample.const_value > 0], key=lambda sample: sample.const_value, reverse=True)[:HARD_CONST_EXTRAPOLATION_SAMPLE_COUNT]
        max_const = max((sample.const_value for sample in hardest), default=0.0)
        if hardest and target_const - max_const <= HARD_CONST_EXTRAPOLATION_LIMIT:
            selected = hardest
            used_window = max(HIGH_CONST_CAP_WIDEN_WINDOW, target_const - max_const + 0.1)
        else:
            return DifficultyBandCap(1.0, 1.0, len(selected), False)
    max_const = max((sample.const_value for sample in selected), default=target_const)
    const_gap = max(0.0, target_const - max_const)
    weights = _const_window_weights(selected, target_const, used_window)
    stable_ratio = _weighted_quantile((sample.score_ratio for sample in selected), weights, STABLE_CAP_QUANTILE, default=1.0)
    pb_ratio = _weighted_quantile((sample.score_ratio for sample in selected), weights, PB_CAP_QUANTILE, default=stable_ratio)
    stable_ratio = clamp(stable_ratio + STABLE_CAP_SLACK - STABLE_CAP_CONST_DECAY * const_gap, MIN_CAP_RATIO, 1.0)
    pb_ratio = clamp(pb_ratio + PB_CAP_SLACK - PB_CAP_CONST_DECAY * const_gap, stable_ratio, 1.0)
    return DifficultyBandCap(stable_ratio, pb_ratio, len(selected), True)

def _raw_chart_objective_load(profile: ScoreEstimatorProfile, feature: Dict[str, float]) -> float:
    stable = profile.stable_profile
    target_const = safe_float(feature.get('const'), 0.0)
    const_capacity = max(0.1, safe_float(getattr(stable, 'difficulty_capacity', 0.0), 0.0))
    const_ratio = target_const / const_capacity if target_const > 0 else 0.0
    raw_capacities = getattr(stable, 'dim_capacity', {})
    raw_ratios = [safe_float(feature.get(dim), 0.0) / max(5.0, safe_float(raw_capacities.get(dim), 0.0)) for dim in ('stamina', 'speed', 'rhythm', 'complex')]
    return 0.32 * const_ratio ** 1.6 + 0.14 * raw_ratios[0] ** 1.6 + 0.2 * raw_ratios[1] ** 1.6 + 0.16 * raw_ratios[2] ** 1.6 + 0.18 * raw_ratios[3] ** 1.6

def _raw_objective_ratios(capacity_profile: Any, feature: Dict[str, float]) -> tuple[float, list[float]]:
    const_capacity = max(0.1, safe_float(getattr(capacity_profile, 'difficulty_capacity', 0.0), 0.0))
    const_value = safe_float(feature.get('const'), 0.0)
    const_ratio = const_value / const_capacity if const_value > 0 else 0.0
    raw_capacities = getattr(capacity_profile, 'dim_capacity', {})
    raw_ratios = sorted((safe_float(feature.get(dim), 0.0) / max(5.0, safe_float(raw_capacities.get(dim), 0.0)) for dim in ('stamina', 'speed', 'rhythm', 'complex')), reverse=True)
    return (const_ratio, raw_ratios)

def _has_raw_objective_hard_mismatch(capacity_profile: Any, feature: Dict[str, float]) -> bool:
    const_ratio, raw_ratios = _raw_objective_ratios(capacity_profile, feature)
    if not raw_ratios:
        return const_ratio >= 1.5
    if raw_ratios[0] >= OBJECTIVE_HARD_SINGLE_RATIO:
        return True
    return len(raw_ratios) >= 2 and raw_ratios[1] >= OBJECTIVE_HARD_SECOND_RATIO and (const_ratio >= OBJECTIVE_HARD_CONST_RATIO)

def _objective_score_cap_ratio(capacity_profile: Any, feature: Dict[str, float]) -> float:
    const_ratio, raw_ratios = _raw_objective_ratios(capacity_profile, feature)
    top = raw_ratios[0] if raw_ratios else 0.0
    second = raw_ratios[1] if len(raw_ratios) >= 2 else 0.0
    pressure = 0.5 * max(0.0, top - 1.0) + 0.3 * max(0.0, second - 1.0) + 0.2 * max(0.0, const_ratio - 1.0)
    return 1.0 - min(OBJECTIVE_SCORE_CAP_MAX_PENALTY, pressure * 0.22)

def _dims_within_capacity(capacity_profile: Any, required_dims: Optional[Dict[str, float]], dim_tolerances: Dict[str, float]) -> bool:
    if required_dims is None:
        return True
    for dim, raw_threshold in dim_tolerances.items():
        threshold = max(0.01, safe_float(raw_threshold, 0.0))
        threshold += _single_dim_overflow_slack(capacity_profile, required_dims, dim)
        capacity = safe_float(getattr(capacity_profile, 'user_dim_capacity', {}).get(dim), 0.0)
        required = safe_float(required_dims.get(dim), 0.0)
        if required > capacity + threshold:
            return False
    return True

def _candidate_precision_penalty(*, chart: Dict[str, Any], feature: Dict[str, float], profile: ScoreEstimatorProfile, tolerance: Dict[str, int | float | bool], accuracy_cap: float, accuracy_power_cap: float) -> Optional[float]:
    note_count = max(1, safe_int(chart.get('max_combo'), 1))
    max_ok = max(0, safe_int(tolerance.get('max_ok'), 0))
    required_accuracy_rate = clamp(1.0 - 0.5 * max_ok / note_count, 0.0, 1.0)
    precision_dims = required_dims_for_target_accuracy(feature=feature, target_accuracy=required_accuracy_rate, const_table=profile.const_table)
    required_accuracy_power = safe_float(precision_dims.get('accuracy_power'), 0.0) if isinstance(precision_dims, dict) else 0.0
    if required_accuracy_rate > accuracy_cap or required_accuracy_power > accuracy_power_cap:
        return None
    accuracy_pressure = clamp((required_accuracy_rate - (accuracy_cap - PRECISION_ACCURACY_SOFT_WIDTH)) / PRECISION_ACCURACY_SOFT_WIDTH, 0.0, 1.0)
    power_pressure = clamp((required_accuracy_power - (accuracy_power_cap - PRECISION_ACCURACY_POWER_SOFT_WIDTH)) / PRECISION_ACCURACY_POWER_SOFT_WIDTH, 0.0, 1.0)
    return clamp(accuracy_pressure * 10.0 + power_pressure * 8.0, 0.0, PRECISION_MAX_LIKELIHOOD_PENALTY)

def _candidate_score_likelihood(*, chart: Dict[str, Any], feature: Dict[str, float], profile: ScoreEstimatorProfile, capacity_profile: Any, target_score: int, roll_speed_ips: float, profile_match: float, const_match: float, dim_tolerances: Dict[str, float], accuracy_cap: float, accuracy_power_cap: float, today: date) -> Optional[float]:
    tolerance = score_target_tolerance(chart, target_score, roll_speed_ips)
    if not tolerance or not bool(tolerance.get('reachable')):
        return None
    required_dims = target_score_required_dims(chart=chart, feature=feature, target_score=target_score, tolerance=tolerance, const_table=profile.const_table)
    if not _dims_within_capacity(capacity_profile, required_dims, dim_tolerances):
        return None
    precision_penalty = _candidate_precision_penalty(chart=chart, feature=feature, profile=profile, tolerance=tolerance, accuracy_cap=accuracy_cap, accuracy_power_cap=accuracy_power_cap)
    if precision_penalty is None:
        return None
    likelihood = _score_target_likelihood(chart=chart, entry=None, target_score=target_score, tolerance=tolerance, profile=capacity_profile, feature=feature, profile_match=profile_match, const_match=const_match, today=today)
    capacity_penalty = _score_target_capacity_pressure_penalty(capacity_profile, required_dims) if isinstance(required_dims, dict) else 0.0
    return clamp(likelihood - precision_penalty - capacity_penalty, 0.0, 100.0)

def _build_snapshot_from_target_score(*, chart: Dict[str, Any], ceiling: int, profile_match: float, target_score: int, roll_speed_ips: float, neighbor_count: int) -> ScoreEstimateSnapshot:
    note_count = max(0, safe_int(chart.get('max_combo'), 0))
    good_points = max(0, safe_int(chart.get('initial_points'), 0))
    ok_points = max(0, safe_int(chart.get('ok_points'), 0))
    pred_pound = compute_rating_roll_breakdown(chart, roll_speed_ips).effective_roll_hits
    roll_score = pred_pound * 100
    max_score = note_count * good_points + roll_score
    min_score = note_count * ok_points + roll_score
    delta = max(1, good_points - ok_points)
    if note_count <= 0 or good_points <= 0:
        pred_good = pred_ok = pred_ng = 0
        raw_score = 0.0
    elif target_score >= min_score:
        pred_ok = max(0, min(note_count, (max_score - target_score) // delta))
        pred_good = note_count - pred_ok
        pred_ng = 0
        raw_score = pred_good * good_points + pred_ok * ok_points + roll_score
    else:
        missing_score = max(0, min_score - target_score)
        if ok_points > 0:
            pred_ng = max(0, min(note_count, math.ceil(missing_score / ok_points)))
            pred_ok = note_count - pred_ng
        else:
            pred_ng = note_count
            pred_ok = 0
        pred_good = 0
        raw_score = pred_ok * ok_points + roll_score
    raw_score = min(float(ceiling), max(0.0, float(raw_score)))
    good_rate = pred_good / note_count if note_count > 0 else 0.0
    hit_rate = (pred_good + pred_ok) / note_count if note_count > 0 else 0.0
    return ScoreEstimateSnapshot(score=_round_to_1000(raw_score), raw_score=float(raw_score), good_rate=float(good_rate), hit_rate=float(hit_rate), roll_speed_ips=float(roll_speed_ips), pred_good=int(pred_good), pred_ok=int(pred_ok), pred_ng=int(pred_ng), pred_pound=pred_pound, neighbor_count=neighbor_count, profile_match=float(profile_match))

def _estimate_snapshot_for_target(*, chart: Dict[str, Any], feature: Dict[str, float], profile: ScoreEstimatorProfile, capacity_profile: Any, pool_samples: List[HistorySample], neighbor_samples: List[Tuple[HistorySample, float]], profile_match: float, const_match: float, roll_quantile: float, likelihood_threshold: float, cap_ratio: float, dim_tolerances: Dict[str, float], accuracy_cap: float, accuracy_power_cap: float, today: date) -> Optional[ScoreEstimateSnapshot]:
    global_roll = _roll_speed_from_chart_evidence(neighbor_samples, pool_samples, safe_int(chart.get('level'), -1), roll_quantile)
    neighbor_count = len(neighbor_samples)
    ceiling = _score_ceiling_35ips(chart)
    capped_ceiling = max(0, min(ceiling, int(math.floor(ceiling * clamp(cap_ratio, 0.0, 1.0)))))
    high_unit = capped_ceiling // 1000
    if high_unit <= 0:
        return None
    best_score = 0
    low_unit = 1
    while low_unit <= high_unit:
        mid_unit = (low_unit + high_unit) // 2
        candidate_score = mid_unit * 1000
        likelihood = _candidate_score_likelihood(chart=chart, feature=feature, profile=profile, capacity_profile=capacity_profile, target_score=candidate_score, roll_speed_ips=global_roll, profile_match=profile_match, const_match=const_match, dim_tolerances=dim_tolerances, accuracy_cap=accuracy_cap, accuracy_power_cap=accuracy_power_cap, today=today)
        if likelihood is not None and likelihood >= likelihood_threshold:
            best_score = candidate_score
            low_unit = mid_unit + 1
        else:
            high_unit = mid_unit - 1
    if best_score <= 0:
        return None
    return _build_snapshot_from_target_score(chart=chart, ceiling=ceiling, profile_match=profile_match, target_score=best_score, roll_speed_ips=clamp(global_roll, 0.0, ROLL_SPEED_CAP), neighbor_count=neighbor_count)

def _estimate_with_profile(profile: ScoreEstimatorProfile, song_id: int, level: int, *, today: date) -> ChartScoreEstimate:
    if level not in (4, 5):
        raise ValueError(f'unsupported level: {level}')
    title_key = profile.title_keys_by_id.get(song_id, '')
    chart = profile.chart_by_key.get((song_id, level))
    if chart is None:
        return ChartScoreEstimate(song_id=song_id, level=level, current_score=None, goku_score=0, score_ceiling_35ips=0, above_goku=False, reliability=0.0, data_sufficiency='insufficient_data', stable=None, pb=None)
    title_key = title_key or chart_title_key(chart)
    feature = resolve_chart_feature(song_id=song_id, level=level, title_key=title_key, features_by_key=profile.features_by_key, features_by_title_level=profile.features_by_title_level)
    if feature is None:
        return ChartScoreEstimate(song_id=song_id, level=level, current_score=None, goku_score=max(0, safe_int(chart.get('goku_score'), 0)), score_ceiling_35ips=_score_ceiling_35ips(chart), above_goku=False, reliability=0.0, data_sufficiency='insufficient_data', stable=None, pb=None)
    current_entry = resolve_best_entry_for_chart(profile.best_map, song_id=song_id, level=level, title_key=title_key, title_keys_by_id=profile.title_keys_by_id, default_ids=profile.default_ids)
    current_score = max(0, safe_int(current_entry.get('high_score'), 0)) if current_entry is not None else None
    target_identity = _get_recommend_identity_key(song_id, level, default_ids=profile.default_ids)
    filtered_samples = [sample for sample in profile.samples if sample.identity != target_identity]
    exact_pool = _select_exact_pool(filtered_samples, level)
    pooled_pool = filtered_samples
    if not pooled_pool:
        return ChartScoreEstimate(song_id=song_id, level=level, current_score=current_score, goku_score=max(0, safe_int(chart.get('goku_score'), 0)), score_ceiling_35ips=_score_ceiling_35ips(chart), above_goku=False, reliability=0.0, data_sufficiency='insufficient_data', stable=None, pb=None)
    pool_samples = exact_pool if len(exact_pool) >= EXACT_POOL_MIN else pooled_pool
    target_vector = _chart_vector(chart, feature)
    neighbors, precision_evidence = _select_chart_evidence(filtered_samples, target_vector, level)
    precision_profile = _build_precision_evidence_profile(precision_evidence, level)
    stable_profile_match = _profile_match(profile.stable_profile, feature)
    stable_const_match = _const_match(profile.stable_profile, feature)
    pb_profile_match = _profile_match(profile.pb_profile, feature)
    pb_const_match = _const_match(profile.pb_profile, feature)
    reliability = _estimate_reliability(stable_profile_match, len(pool_samples), neighbors, level)
    target_const = safe_float(feature.get('const'), 0.0)
    band_cap = _difficulty_band_cap(filtered_samples, target_const)
    high_difficulty_band_cap = band_cap
    if target_const >= HIGH_CONST_CAP_START:
        feature_fit_cap = _feature_fit_score_cap(precision_evidence, level)
        if feature_fit_cap.has_evidence:
            band_cap = DifficultyBandCap(stable_ratio=min(band_cap.stable_ratio, feature_fit_cap.stable_ratio), pb_ratio=min(band_cap.pb_ratio, feature_fit_cap.pb_ratio), sample_count=max(band_cap.sample_count, feature_fit_cap.sample_count), has_evidence=band_cap.has_evidence or feature_fit_cap.has_evidence)
    chart_evidence_cap = _chart_evidence_score_cap(neighbors, level)
    if chart_evidence_cap.has_evidence:
        band_cap = DifficultyBandCap(stable_ratio=min(band_cap.stable_ratio, chart_evidence_cap.stable_ratio), pb_ratio=min(band_cap.pb_ratio, chart_evidence_cap.pb_ratio), sample_count=max(band_cap.sample_count, chart_evidence_cap.sample_count), has_evidence=True)
    band_cap = DifficultyBandCap(stable_ratio=min(band_cap.stable_ratio, _objective_score_cap_ratio(profile.stable_profile, feature)), pb_ratio=min(band_cap.pb_ratio, _objective_score_cap_ratio(profile.pb_profile, feature)), sample_count=band_cap.sample_count, has_evidence=band_cap.has_evidence)
    max_history_const = max((sample.const_value for sample in filtered_samples if sample.const_value > 0), default=0.0)
    lacks_high_difficulty_evidence = target_const >= HIGH_CONST_CAP_START and (not high_difficulty_band_cap.has_evidence) and (target_const - max_history_const > HARD_CONST_EXTRAPOLATION_LIMIT)
    stable_const_gap = max(0.0, target_const - safe_float(getattr(profile.stable_profile, 'difficulty_capacity', 0.0), 0.0))
    if lacks_high_difficulty_evidence and stable_const_gap >= HARD_MISMATCH_CONST_GAP or _has_raw_objective_hard_mismatch(profile.stable_profile, feature):
        return ChartScoreEstimate(song_id=song_id, level=level, current_score=current_score, goku_score=max(0, safe_int(chart.get('goku_score'), 0)), score_ceiling_35ips=_score_ceiling_35ips(chart), above_goku=False, reliability=reliability, data_sufficiency='hard_mismatch', stable=None, pb=None)
    stable = _estimate_snapshot_for_target(chart=chart, feature=feature, profile=profile, capacity_profile=profile.stable_profile, pool_samples=pool_samples, neighbor_samples=neighbors, profile_match=stable_profile_match, const_match=stable_const_match, roll_quantile=STABLE_ROLL_QUANTILE, likelihood_threshold=STABLE_LIKELIHOOD_THRESHOLD, cap_ratio=band_cap.stable_ratio, dim_tolerances=STABLE_ESTIMATION_DIM_TOLERANCE, accuracy_cap=precision_profile.stable_accuracy_cap, accuracy_power_cap=precision_profile.stable_accuracy_power_cap, today=today)
    pb = _estimate_snapshot_for_target(chart=chart, feature=feature, profile=profile, capacity_profile=profile.pb_profile, pool_samples=pool_samples, neighbor_samples=neighbors, profile_match=pb_profile_match, const_match=pb_const_match, roll_quantile=PB_ROLL_QUANTILE, likelihood_threshold=PB_LIKELIHOOD_THRESHOLD, cap_ratio=band_cap.pb_ratio, dim_tolerances=PB_ESTIMATION_DIM_TOLERANCE, accuracy_cap=precision_profile.pb_accuracy_cap, accuracy_power_cap=precision_profile.pb_accuracy_power_cap, today=today)
    ceiling = _score_ceiling_35ips(chart)
    if stable is None:
        return ChartScoreEstimate(song_id=song_id, level=level, current_score=current_score, goku_score=max(0, safe_int(chart.get('goku_score'), 0)), score_ceiling_35ips=ceiling, above_goku=False, reliability=reliability, data_sufficiency='hard_mismatch', stable=None, pb=None)
    if pb is None:
        pb = stable
    if pb.raw_score < stable.raw_score:
        pb = stable
    goku_score = max(0, safe_int(chart.get('goku_score'), 0))
    above_goku = stable.score > goku_score or pb.score > goku_score
    return ChartScoreEstimate(song_id=song_id, level=level, current_score=current_score, goku_score=goku_score, score_ceiling_35ips=ceiling, above_goku=above_goku, reliability=reliability, data_sufficiency='ok', stable=stable, pb=pb)

def forecast_chart_performance_batch(profile: ScoreEstimatorProfile, candidates: Iterable[Dict[str, Any]], *, today: date) -> Dict[Tuple[int, int], ChartPerformanceForecast]:
    """Build one shared score-survival forecast per chart from one user profile."""
    forecasts: Dict[Tuple[int, int], ChartPerformanceForecast] = {}
    for candidate in candidates:
        chart = candidate.get('chart') if isinstance(candidate, dict) else None
        if not isinstance(chart, dict):
            continue
        key = (safe_int(chart.get('id'), -1), safe_int(chart.get('level'), -1))
        if key in forecasts or key[0] < 0 or key[1] not in (4, 5):
            continue
        estimate = _estimate_with_profile(profile, key[0], key[1], today=today)
        forecasts[key] = build_chart_performance_forecast(song_id=key[0], level=key[1], stable_score=estimate.stable.score if estimate.stable is not None else None, pb_score=estimate.pb.score if estimate.pb is not None else None, score_ceiling=estimate.score_ceiling_35ips, reliability=estimate.reliability, data_sufficiency=estimate.data_sufficiency)
    return forecasts
