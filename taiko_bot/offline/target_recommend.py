from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root


from sakura_taiko_core.recommendation.center import (
    DEFAULT_ROLL_SPEED_IPS,
    TARGET_RECOMMENDATION_LIMIT,
    TARGET_RECOMMENDATION_MIN_IMAGE_ROWS,
    TARGET_RECOMMENDATION_PROFILE_DISCOUNT,
    TARGET_RECOMMENDATION_PRIMARY_TOPN,
    TARGET_RECOMMENDATION_ALT_TOPN,
    SCORE_TARGETS,
    SCORE_TARGET_ORDER,
    NEXT_SCORE_TARGET,
    SCORE_TARGET_RANK,
    FULL_COMBO_TARGET,
    DONDAFUL_TARGET,
    TARGET_DISPLAY,
    _TARGET_ALIASES,
    _TARGET_ALIAS_KEYS_SORTED,
    _STAR_FILTER_ALIASES,
    DIM_KEYS,
    USER_DIM_COLUMNS,
    RAW_DIM_SCALE,
    TARGET_SCORE_DIM_KEYS,
    TARGET_SCORE_DIM_THRESHOLDS,
    TARGET_SCORE_EDGE_STARTS,
    TARGET_SCORE_EDGE_WEIGHTS,
    TARGET_SCORE_EDGE_WIDTH,
    TARGET_SCORE_EDGE_MAX_PENALTY,
    TARGET_SCORE_MULTIDIM_DIMS,
    TARGET_SCORE_MULTIDIM_START,
    TARGET_SCORE_MULTIDIM_WIDTH,
    TARGET_SCORE_MULTIDIM_MIN_NORM,
    TARGET_SCORE_MULTIDIM_DOMINANT_RATIO,
    TARGET_SCORE_MULTIDIM_WEIGHT,
    TARGET_SCORE_MULTIDIM_THREE_DIM_BONUS,
    TARGET_SCORE_MULTIDIM_MAX_PENALTY,
    TARGET_SCORE_MULTIDIM_OVERFLOW_TRIGGER,
    TARGET_SCORE_SINGLE_DIM_OVERFLOW_SLACK,
    TARGET_SCORE_MULTIDIM_OVERFLOW_PENALTY,
    FULL_COMBO_TARGET_ACCURACY,
    DONDAFUL_TARGET_ACCURACY,
    FULL_COMBO_DIM_THRESHOLDS,
    DONDAFUL_DIM_THRESHOLDS,
    FULL_COMBO_SOFT_FREE_ZONES,
    FULL_COMBO_SOFT_WEIGHTS,
    FULL_COMBO_HARD_DIVISORS,
    FULL_COMBO_HARD_WEIGHTS,
    FULL_COMBO_EDGE_STARTS,
    FULL_COMBO_EDGE_WEIGHTS,
    DONDAFUL_SOFT_FREE_ZONES,
    DONDAFUL_SOFT_WEIGHTS,
    DONDAFUL_HARD_DIVISORS,
    DONDAFUL_HARD_WEIGHTS,
    HS_CHANGE_MEMORIZATION_THRESHOLD,
    HS_CHANGE_NORMALIZATION_RANGE,
    HS_CHANGE_CURVE_EXPONENT,
    SCORE_TARGET_HS_CHANGE_MAX_PENALTY,
    FULL_COMBO_HS_CHANGE_MAX_PENALTY,
    DONDAFUL_HS_CHANGE_MAX_PENALTY,
    UserProfile,
    parse_target_recommendation_key,
    target_recommendation_displays,
    parse_target_recommendation_star_filter,
    parse_target_recommendation_request,
    _safe_int,
    _safe_float,
    _clamp,
    _completion_rate,
    _good_rate,
    _candidate_progress,
    _combo_rate,
    _format_title,
    _normalize_title_key,
    _chart_title_key,
    _song_data_title_key,
    _rating_feature_from_raw,
    _is_double_chart,
    _format_song_star,
    _build_played_title_level_keys,
    _median,
    _top_quality_samples,
    _build_score_history_profile,
    _scale_raw_dim_to_user_dim,
    _scale_user_dim_to_raw_capacity,
    _aggregate_user_capacity,
    _build_rating_results_profile,
    _discount_user_profile,
    _lower_capacity_profile,
    _profile_match,
    _const_match,
    _roll_hits,
    _sigmoid01,
    _profile_probability_factor,
    _recommend_index_from_likelihood,
    _played_score_freshness_weight,
    _score_target_tolerance,
    _target_score_required_dims,
    _required_dims_for_target_accuracy,
    _single_dim_overflow_slack,
    _exceeds_target_score_dim_limits,
    _full_combo_required_dims,
    _dondaful_required_dims,
    _exceeds_dim_limits,
    _exceeds_full_combo_dim_limits,
    _exceeds_dondaful_dim_limits,
    _required_capacity_usage_ratio,
    _soft_dim_norm,
    _excess_dim_norm,
    _score_target_capacity_pressure_penalty,
    _score_target_pair_pressure_penalty,
    _full_combo_edge_penalty,
    _hs_change_penalty,
    _baseline_score_target_likelihood,
    _played_score_observed_likelihood,
    _unplayed_score_bonus,
    _combo_recommend_index,
    _dondaful_recommend_index,
    _build_full_combo_row,
    _build_dondaful_row,
    _score_band_likelihood,
    _score_target_owner,
    _build_owned_score_target_row_from_reach,
)
from sakura_taiko_core.recommendation import center as domain_center, selection as domain_selection
from .taiko_domain_adapter import with_host_clock
_build_owned_score_target_row = with_host_clock(domain_center._build_owned_score_target_row)
_build_score_target_row = with_host_clock(domain_center._build_score_target_row)
_entry_age_days = with_host_clock(domain_center._entry_age_days)
_played_score_penalty = with_host_clock(domain_center._played_score_penalty)
_score_recommend_index = with_host_clock(domain_center._score_recommend_index)
_score_target_likelihood = with_host_clock(domain_center._score_target_likelihood)


import contextlib
import io
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import median
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .evaluation_roll import compute_rating_roll_breakdown
from .target_score_core import (
    required_dims_for_target_accuracy as core_required_dims_for_target_accuracy,
    score_target_tolerance as core_score_target_tolerance,
    target_score_required_dims as core_target_score_required_dims,
)
from taiko_bot.runtime.player.center.duplicate_versions import duplicate_identity_key, duplicate_identity_key_by_title
from .score_calculator import (
    aggregate_topN_value,
    compute_all_from_userdata_records,
)
from .score_prediction_support import (
    build_best_entry_map as support_build_best_entry_map,
    build_played_title_level_keys as support_build_played_title_level_keys,
    chart_title_key as support_chart_title_key,
    entry_age_days as support_entry_age_days,
    load_candidate_charts as support_load_candidate_charts,
    load_json as support_load_json,
    load_rating_features as support_load_rating_features,
    load_rating_features_by_title_level as support_load_rating_features_by_title_level,
    load_rating_support as support_load_rating_support,
    load_song_star_map as support_load_song_star_map,
    load_song_title_keys as support_load_song_title_keys,
    load_userdata as support_load_userdata,
    normalize_title_key as support_normalize_title_key,
    played_score_freshness_weight as support_played_score_freshness_weight,
    rating_feature_from_raw as support_rating_feature_from_raw,
    song_data_title_key as support_song_data_title_key,
)


BASE = Path(str(_runtime_root()))
USERDATA_DIR = BASE / "userdata"
SCORELINE_PATH = BASE / "songs" / "taiko_goku_onis.json"
RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"


@dataclass(frozen=True)
class TargetRecommendationResult:
    target_key: str
    target_display: str
    rows: List[Dict[str, Any]]
    candidate_count: int
    required_count: int
    is_enough: bool
    message: str
    userdata: Dict[str, Any]


def _load_json(path: str | Path) -> Any:
    return support_load_json(path)


def _load_userdata(user_id: str | int, userdata_dir: str | Path | None) -> Dict[str, Any]:
    return support_load_userdata(user_id, userdata_dir)


def _build_best_entry_map(records: Iterable[Dict[str, Any]]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    return support_build_best_entry_map(records)


def _load_rating_features(rating_path: str | Path) -> Dict[Tuple[int, int], Dict[str, float]]:
    return support_load_rating_features(rating_path)


def _load_rating_features_by_title_level(
    rating_path: str | Path,
) -> Dict[Tuple[str, int], Dict[str, float]]:
    return support_load_rating_features_by_title_level(rating_path)


def _load_rating_support(
    rating_path: str | Path,
) -> Tuple[
    Dict[Tuple[int, int], Dict[str, float]],
    Dict[Tuple[str, int], Dict[str, float]],
    List[Tuple[float, float]],
]:
    return support_load_rating_support(rating_path)


def _load_song_title_keys(song_data_path: str | Path) -> Dict[int, str]:
    return support_load_song_title_keys(song_data_path)


def _load_song_star_map(song_data_path: str | Path) -> Dict[Tuple[int, int], str]:
    return support_load_song_star_map(song_data_path)


def _load_candidate_charts(
    scoreline_path: str | Path,
    song_data_path: str | Path,
) -> List[Dict[str, Any]]:
    return support_load_candidate_charts(scoreline_path, song_data_path)


def _build_user_profile(records, best_map, charts, features_by_key, rating_path):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rating_results = compute_all_from_userdata_records(records, rating_path)
    except Exception:
        rating_results = []
    return domain_center.build_user_profile(rating_results, best_map, charts, features_by_key)


def compute_target_recommendations_for_user(user_id: str | int, target_key: str, *, limit: int=TARGET_RECOMMENDATION_LIMIT, star_filter: str | None=None, userdata_dir: str | Path | None=None, scoreline_path: str | Path=SCORELINE_PATH, rating_path: str | Path=RATING_PATH, song_data_path: str | Path=SONG_DATA_PATH, roll_speed_ips: float=DEFAULT_ROLL_SPEED_IPS) -> TargetRecommendationResult:
    if target_key not in TARGET_DISPLAY:
        raise ValueError(f'unsupported target: {target_key}')
    normalized_star_filter = None
    if star_filter is not None:
        normalized_star_filter = parse_target_recommendation_star_filter(star_filter)
        if normalized_star_filter is None:
            raise ValueError(f'unsupported star filter: {star_filter}')
    userdata = _load_userdata(user_id, userdata_dir)
    raw_records = userdata.get('songs')
    records = raw_records if isinstance(raw_records, list) else []
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    star_by_key = _load_song_star_map(song_data_path)
    for chart in charts:
        song_id = _safe_int(chart.get('id'), -1)
        title_key = _chart_title_key(chart)
        if song_id >= 0 and title_key:
            title_keys_by_id.setdefault(song_id, title_key)
    played_title_level_keys = _build_played_title_level_keys(records, title_keys_by_id)
    features_by_key, features_by_title_level, const_table = _load_rating_support(rating_path)
    profile: Optional[UserProfile] = None
    score_reaches_by_key: Dict[Tuple[int, int], Dict[str, Any]] = {}
    if target_key in SCORE_TARGETS:
        from .score_estimator import build_score_estimator_profile, estimate_target_reach_batch
        reach_candidates = domain_selection.build_reach_candidates(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, target_key, normalized_star_filter)
        estimator_profile = build_score_estimator_profile(records, scoreline_path=scoreline_path, rating_path=rating_path, song_data_path=song_data_path)
        score_reaches_by_key = estimate_target_reach_batch(estimator_profile, reach_candidates)
    else:
        profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    selected, candidate_count = domain_selection.select_target_rows(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, const_table, profile, score_reaches_by_key, target_key, normalized_star_filter, limit)
    display = TARGET_DISPLAY[target_key]
    minimum_rows = TARGET_RECOMMENDATION_MIN_IMAGE_ROWS
    is_enough = len(selected) >= minimum_rows
    if is_enough:
        message = ''
    else:
        star_hint = f'且为「{normalized_star_filter}星」' if normalized_star_filter else ''
        message = f'这次只找到 {len(selected)}/{minimum_rows} 首适合冲「{display}」{star_hint}的候选，暂不生成推荐图。可以先更新成绩后再试，或换一个目标。'
    return TargetRecommendationResult(target_key=target_key, target_display=display, rows=selected, candidate_count=candidate_count, required_count=minimum_rows, is_enough=is_enough, message=message, userdata=userdata)
