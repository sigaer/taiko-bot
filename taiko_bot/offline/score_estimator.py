from __future__ import annotations


from dataclasses import dataclass
from sakura_taiko_core.recommendation.estimator import (
    ROLL_SPEED_CAP,
    STABLE_RATE_QUANTILE,
    PB_RATE_QUANTILE,
    STABLE_ROLL_QUANTILE,
    PB_ROLL_QUANTILE,
    EXACT_POOL_MIN,
    POOLED_POOL_MIN,
    EXACT_POOL_RECENT_DAYS,
    EXACT_POOL_RECENT_THRESHOLD,
    SAME_LEVEL_NEIGHBORS,
    TOTAL_NEIGHBORS,
    NEIGHBOR_DISTANCE_DENOMINATOR,
    CHART_EVIDENCE_MAX_DISTANCE,
    CHART_EVIDENCE_MIN_SCORE_CAP_SAMPLES,
    STABLE_CHART_SCORE_CAP_QUANTILE,
    PB_CHART_SCORE_CAP_QUANTILE,
    STABLE_CHART_SCORE_CAP_SLACK,
    PB_CHART_SCORE_CAP_SLACK,
    CHART_ROLL_EVIDENCE_MIN_SAMPLES,
    HARD_MISMATCH_CONST_GAP,
    STABLE_LIKELIHOOD_THRESHOLD,
    PB_LIKELIHOOD_THRESHOLD,
    HIGH_CONST_CAP_START,
    HIGH_CONST_CAP_WINDOW,
    HIGH_CONST_CAP_WIDEN_WINDOW,
    HIGH_CONST_CAP_MIN_SAMPLES,
    HARD_CONST_EXTRAPOLATION_LIMIT,
    HARD_CONST_EXTRAPOLATION_SAMPLE_COUNT,
    STABLE_CAP_QUANTILE,
    PB_CAP_QUANTILE,
    STABLE_CAP_SLACK,
    PB_CAP_SLACK,
    STABLE_CAP_CONST_DECAY,
    PB_CAP_CONST_DECAY,
    MIN_CAP_RATIO,
    OBJECTIVE_HARD_SINGLE_RATIO,
    OBJECTIVE_HARD_SECOND_RATIO,
    OBJECTIVE_HARD_CONST_RATIO,
    OBJECTIVE_SCORE_CAP_MAX_PENALTY,
    PRECISION_EVIDENCE_LIMIT,
    PRECISION_EVIDENCE_DENOMINATOR,
    PRECISION_EVIDENCE_MAX_DISTANCE,
    PRECISION_EVIDENCE_MIN_SCORE_CAP_SAMPLES,
    STABLE_ACCURACY_CAP_QUANTILE,
    PB_ACCURACY_CAP_QUANTILE,
    STABLE_ACCURACY_CAP_SLACK,
    PB_ACCURACY_CAP_SLACK,
    STABLE_ACCURACY_POWER_CAP_QUANTILE,
    PB_ACCURACY_POWER_CAP_QUANTILE,
    STABLE_ACCURACY_POWER_CAP_SLACK,
    PB_ACCURACY_POWER_CAP_SLACK,
    PRECISION_ACCURACY_CAP_MAX,
    PRECISION_ACCURACY_POWER_CAP_MAX,
    PRECISION_ACCURACY_SOFT_WIDTH,
    PRECISION_ACCURACY_POWER_SOFT_WIDTH,
    PRECISION_MAX_LIKELIHOOD_PENALTY,
    STABLE_FEATURE_SCORE_CAP_QUANTILE,
    PB_FEATURE_SCORE_CAP_QUANTILE,
    STABLE_FEATURE_SCORE_CAP_SLACK,
    PB_FEATURE_SCORE_CAP_SLACK,
    STABLE_ESTIMATION_DIM_TOLERANCE,
    PB_ESTIMATION_DIM_TOLERANCE,
    TARGET_REACH_HISTORY_WEIGHT_MAX,
    TARGET_REACH_LOAD_EXPONENT,
    TARGET_REACH_DIM_WEIGHTS,
    ScoreEstimateSnapshot,
    ChartScoreEstimate,
    HistorySample,
    DifficultyBandCap,
    PrecisionEvidenceProfile,
    TargetReachEstimate,
    TargetReachContext,
    _history_recency_weight,
    _round_to_1000,
    _weighted_quantile,
    _chart_vector,
    _vector_distance,
    _score_ceiling_35ips,
    _infer_observed_roll_speed_ips,
    _select_exact_pool,
    _select_neighbors,
    _neighbor_weights,
    _select_precision_evidence,
    _select_chart_evidence,
    _chart_evidence_weights,
    _chart_evidence_score_cap,
    _roll_speed_from_chart_evidence,
    _precision_evidence_weights,
    _build_precision_evidence_profile,
    _sigmoid_margin,
    _target_record_freshness,
    _target_performance_requirements,
    _target_reach_context,
    _feature_fit_score_cap,
    _estimate_reliability,
    _samples_in_const_window,
    _const_window_weights,
    _difficulty_band_cap,
    _raw_chart_objective_load,
    _raw_objective_ratios,
    _has_raw_objective_hard_mismatch,
    _objective_score_cap_ratio,
    _dims_within_capacity,
    _candidate_precision_penalty,
    _build_snapshot_from_target_score,
)
from sakura_taiko_core.recommendation import estimator as domain_estimator
from .taiko_domain_adapter import identity_inputs, with_host_clock
_candidate_score_likelihood = with_host_clock(domain_estimator._candidate_score_likelihood)
_estimate_snapshot_for_target = with_host_clock(domain_estimator._estimate_snapshot_for_target)
_estimate_target_reach = with_host_clock(domain_estimator._estimate_target_reach)
_estimate_with_profile = with_host_clock(domain_estimator._estimate_with_profile)
estimate_target_reach_batch = with_host_clock(domain_estimator.estimate_target_reach_batch)
forecast_chart_performance_batch = with_host_clock(domain_estimator.forecast_chart_performance_batch)


import contextlib
import heapq
import io
import math
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from taiko_bot.runtime.player.center.duplicate_versions import duplicate_identity_key
from .evaluation_roll import compute_rating_roll_breakdown, compute_rating_roll_capacity
from .performance_forecast import (
    ChartPerformanceForecast,
    build_chart_performance_forecast,
)
from .score_prediction_support import (
    RATING_PATH,
    SCORELINE_PATH,
    SONG_DATA_PATH,
    build_best_entry_map,
    chart_title_key,
    clamp,
    entry_age_days,
    load_candidate_charts,
    load_rating_support,
    load_song_title_keys,
    resolve_best_entry_for_chart,
    resolve_chart_feature,
    resolve_scoreline_chart,
    _chart_resolver,
    safe_float,
    safe_int,
)
from .score_calculator import compute_all_from_userdata_records
from .target_score_core import (
    required_dims_for_target_accuracy,
    score_target_tolerance,
    target_score_required_dims,
)
from .target_recommend import (
    TARGET_RECOMMENDATION_PRIMARY_TOPN,
    TARGET_RECOMMENDATION_PROFILE_DISCOUNT,
    _build_rating_results_profile,
    _build_score_history_profile,
    _const_match,
    _discount_user_profile,
    _profile_match,
    _single_dim_overflow_slack,
    _score_target_capacity_pressure_penalty,
    _score_target_likelihood,
)


@dataclass(frozen=True)
class ScoreEstimatorProfile(domain_estimator.ScoreEstimatorProfile):
    scoreline_path: Path
    rating_path: Path
    song_data_path: Path


def _build_history_samples(best_map, title_keys_by_id, features_by_key, features_by_title_level, const_table, *, scoreline_path, song_data_path, chart_by_key=None):
    default_ids, _ = identity_inputs(song_data_path)
    charts = chart_by_key if chart_by_key is not None else _resolved_chart_inputs(
        title_keys_by_id, [], best_map, scoreline_path, song_data_path, keys=set(best_map))
    from datetime import date
    return domain_estimator._build_history_samples(best_map, title_keys_by_id, features_by_key, features_by_title_level,
        const_table, chart_by_key=charts, default_ids=default_ids, today=date.today())


def _exclude_target_records(records, *, exclude_song_id, exclude_level, song_data_path):
    default_ids, _ = identity_inputs(song_data_path)
    return domain_estimator._exclude_target_records(records, exclude_song_id=exclude_song_id,
        exclude_level=exclude_level, default_ids=default_ids)


def _build_estimator_user_profiles(records, best_map, charts, features_by_key, rating_path):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rating_results=compute_all_from_userdata_records(records, rating_path)
    except Exception:
        rating_results=[]
    return domain_estimator._build_estimator_user_profiles(rating_results, best_map, charts, features_by_key)


def build_score_estimator_profile(records: List[Dict[str, Any]], *, scoreline_path: str | Path=SCORELINE_PATH, rating_path: str | Path=RATING_PATH, song_data_path: str | Path=SONG_DATA_PATH, exclude_song_id: Optional[int]=None, exclude_level: Optional[int]=None) -> ScoreEstimatorProfile:
    scoreline_path = Path(scoreline_path)
    rating_path = Path(rating_path)
    song_data_path = Path(song_data_path)
    best_map = build_best_entry_map(records, song_data_path=song_data_path)
    profile_records = _exclude_target_records(records, exclude_song_id=exclude_song_id, exclude_level=exclude_level, song_data_path=song_data_path)
    profile_best_map = build_best_entry_map(profile_records, song_data_path=song_data_path) if profile_records is not records else best_map
    charts = load_candidate_charts(scoreline_path, song_data_path)
    title_keys_by_id = load_song_title_keys(song_data_path)
    features_by_key, features_by_title_level, const_table = load_rating_support(rating_path)
    stable_profile, pb_profile = _build_estimator_user_profiles(profile_records, profile_best_map, charts, features_by_key, rating_path)
    chart_by_key = _resolved_chart_inputs(title_keys_by_id, charts, best_map, scoreline_path, song_data_path)
    samples = _build_history_samples(profile_best_map, title_keys_by_id, features_by_key, features_by_title_level, const_table, scoreline_path=scoreline_path, song_data_path=song_data_path, chart_by_key=chart_by_key)
    return ScoreEstimatorProfile(user_profile=stable_profile, stable_profile=stable_profile, pb_profile=pb_profile, best_map=best_map, title_keys_by_id=title_keys_by_id, features_by_key=features_by_key, features_by_title_level=features_by_title_level, const_table=const_table, samples=samples, scoreline_path=scoreline_path, rating_path=rating_path, song_data_path=song_data_path, chart_by_key=chart_by_key, default_ids=identity_inputs(song_data_path)[0])


def estimate_chart_score_from_records(
    records: List[Dict[str, Any]],
    song_id: int,
    level: int,
    *,
    scoreline_path: str | Path = SCORELINE_PATH,
    rating_path: str | Path = RATING_PATH,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> ChartScoreEstimate:
    profile = build_score_estimator_profile(
        records,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
        exclude_song_id=song_id,
        exclude_level=level,
    )
    return _estimate_with_profile(profile, song_id, level)



def _resolved_chart_inputs(title_keys_by_id, charts, best_map, scoreline_path, song_data_path, *, keys=None):
    if keys is None:
        keys=set(best_map)|{(sid,level) for sid in title_keys_by_id for level in (4,5)}
        keys|={(int(chart["id"]),int(chart["level"])) for chart in charts}
    resolve=_chart_resolver(scoreline_path,song_data_path)
    return {key:resolve(*key,title_keys_by_id.get(key[0],"")) for key in keys}
