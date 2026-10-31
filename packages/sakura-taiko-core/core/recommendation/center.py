from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from ..models.calculation import SongMetrics, RatingResult, SongStats
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table, _calc_accuracy_for_record, aggregate_topN_value
from ..dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims
from .support import normalize_title_key as support_normalize_title_key, chart_title_key as support_chart_title_key, song_data_title_key as support_song_data_title_key, rating_feature_from_raw as support_rating_feature_from_raw, build_played_title_level_keys as support_build_played_title_level_keys, entry_age_days as support_entry_age_days, played_score_freshness_weight as support_played_score_freshness_weight
from .target_score import score_target_tolerance as core_score_target_tolerance, required_dims_for_target_accuracy as core_required_dims_for_target_accuracy, target_score_required_dims as core_target_score_required_dims
from ..chart.roll import compute_rating_roll_breakdown

DEFAULT_ROLL_SPEED_IPS = 25.0
TARGET_RECOMMENDATION_LIMIT = 20
TARGET_RECOMMENDATION_MIN_IMAGE_ROWS = 10
TARGET_RECOMMENDATION_PROFILE_DISCOUNT = 0.98
TARGET_RECOMMENDATION_PRIMARY_TOPN = 20
TARGET_RECOMMENDATION_ALT_TOPN = 40
SCORE_TARGETS = {'goku', 'ziya', 'fenya', 'jinya'}
SCORE_TARGET_ORDER = ('jinya', 'fenya', 'ziya', 'goku')
NEXT_SCORE_TARGET: Dict[str, str] = {'jinya': 'fenya', 'fenya': 'ziya', 'ziya': 'goku'}
SCORE_TARGET_RANK = {key: index for index, key in enumerate(SCORE_TARGET_ORDER)}
FULL_COMBO_TARGET = 'full_combo'
DONDAFUL_TARGET = 'dondaful'
TARGET_DISPLAY: Dict[str, str] = {'goku': '极', 'ziya': '紫雅', 'fenya': '粉雅', 'jinya': '金雅', FULL_COMBO_TARGET: '全连', DONDAFUL_TARGET: '全良'}
_TARGET_ALIASES: Dict[str, str] = {'goku': 'goku', '极': 'goku', '極': 'goku', 'ziya': 'ziya', '紫雅': 'ziya', '紫': 'ziya', 'fenya': 'fenya', '粉雅': 'fenya', '粉': 'fenya', 'jinya': 'jinya', '金雅': 'jinya', '金': 'jinya', 'fc': FULL_COMBO_TARGET, 'fullcombo': FULL_COMBO_TARGET, 'full_combo': FULL_COMBO_TARGET, '全连': FULL_COMBO_TARGET, '全連': FULL_COMBO_TARGET, 'df': DONDAFUL_TARGET, 'dondaful': DONDAFUL_TARGET, 'allgood': DONDAFUL_TARGET, '全良': DONDAFUL_TARGET}
_TARGET_ALIAS_KEYS_SORTED = sorted(_TARGET_ALIASES.keys(), key=len, reverse=True)
_STAR_FILTER_ALIASES: Dict[str, str] = {'1': '1', '一': '1', '2': '2', '二': '2', '3': '3', '三': '3', '4': '4', '四': '4', '5': '5', '五': '5', '6': '6', '六': '6', '7': '7', '七': '7', '8': '8', '八': '8', '9': '9', '九': '9', '10': '10', '十': '10'}
DIM_KEYS = ('stamina', 'speed', 'rhythm', 'complex')
USER_DIM_COLUMNS = {'big_song': '大歌力', 'stamina': '体力', 'speed': '高速处理', 'accuracy_power': '精度力', 'rhythm': '节奏处理', 'complex': '复合处理'}
RAW_DIM_SCALE = 15.5 / 100.0
TARGET_SCORE_DIM_KEYS = ('big_song', 'stamina', 'speed', 'accuracy_power', 'rhythm', 'complex')
TARGET_SCORE_DIM_THRESHOLDS = {'big_song': 0.75, 'stamina': 0.75, 'speed': 0.5, 'accuracy_power': 1.0, 'rhythm': 0.3, 'complex': 0.75}
TARGET_SCORE_EDGE_STARTS = {'big_song': 0.94, 'stamina': 0.94, 'speed': 0.9, 'accuracy_power': 0.98, 'rhythm': 0.92, 'complex': 0.9}
TARGET_SCORE_EDGE_WEIGHTS = {'big_song': 4.0, 'stamina': 3.0, 'speed': 7.0, 'accuracy_power': 4.0, 'rhythm': 5.0, 'complex': 6.0}
TARGET_SCORE_EDGE_WIDTH = 0.12
TARGET_SCORE_EDGE_MAX_PENALTY = 20.0
TARGET_SCORE_MULTIDIM_DIMS = ('big_song', 'stamina', 'speed', 'rhythm', 'complex')
TARGET_SCORE_MULTIDIM_START = 0.95
TARGET_SCORE_MULTIDIM_WIDTH = 0.1
TARGET_SCORE_MULTIDIM_MIN_NORM = 0.25
TARGET_SCORE_MULTIDIM_DOMINANT_RATIO = 2.8
TARGET_SCORE_MULTIDIM_WEIGHT = 5.0
TARGET_SCORE_MULTIDIM_THREE_DIM_BONUS = 0.75
TARGET_SCORE_MULTIDIM_MAX_PENALTY = 4.0
TARGET_SCORE_MULTIDIM_OVERFLOW_TRIGGER = 0.92
TARGET_SCORE_SINGLE_DIM_OVERFLOW_SLACK = 0.15
TARGET_SCORE_MULTIDIM_OVERFLOW_PENALTY = 0.5
FULL_COMBO_TARGET_ACCURACY = 0.9
DONDAFUL_TARGET_ACCURACY = 0.995
FULL_COMBO_DIM_THRESHOLDS = {'speed': 0.5, 'complex': 0.6}
DONDAFUL_DIM_THRESHOLDS = {'rhythm': 0.35, 'accuracy_power': 0.5}
FULL_COMBO_SOFT_FREE_ZONES = {'speed': 0.2, 'complex': 0.2, 'big_song': 0.3, 'stamina': 0.3, 'rhythm': 0.25}
FULL_COMBO_SOFT_WEIGHTS = {'speed': 12.0, 'complex': 10.0, 'big_song': 4.0, 'stamina': 3.0, 'rhythm': 2.0}
FULL_COMBO_HARD_DIVISORS = {'speed': 0.5, 'complex': 0.6, 'big_song': 1.0, 'stamina': 1.0, 'rhythm': 0.8}
FULL_COMBO_HARD_WEIGHTS = {'speed': 34.0, 'complex': 30.0, 'big_song': 12.0, 'stamina': 8.0, 'rhythm': 6.0}
FULL_COMBO_EDGE_STARTS = {'speed': 0.9, 'complex': 0.88, 'big_song': 0.95}
FULL_COMBO_EDGE_WEIGHTS = {'speed': 10.0, 'complex': 8.0, 'big_song': 4.0}
DONDAFUL_SOFT_FREE_ZONES = {'accuracy_power': 0.68, 'rhythm': 0.15, 'big_song': 0.35, 'speed': 0.35, 'complex': 0.35, 'stamina': 0.35}
DONDAFUL_SOFT_WEIGHTS = {'accuracy_power': 8.0, 'rhythm': 12.0, 'big_song': 3.0, 'speed': 2.0, 'complex': 2.0, 'stamina': 2.0}
DONDAFUL_HARD_DIVISORS = {'accuracy_power': 0.5, 'rhythm': 0.35, 'big_song': 1.0, 'speed': 0.8, 'complex': 1.0, 'stamina': 1.0}
DONDAFUL_HARD_WEIGHTS = {'accuracy_power': 36.0, 'rhythm': 30.0, 'big_song': 10.0, 'speed': 8.0, 'complex': 8.0, 'stamina': 8.0}
HS_CHANGE_MEMORIZATION_THRESHOLD = 80.0
HS_CHANGE_NORMALIZATION_RANGE = 20.0
HS_CHANGE_CURVE_EXPONENT = 0.65
SCORE_TARGET_HS_CHANGE_MAX_PENALTY = 14.0
FULL_COMBO_HS_CHANGE_MAX_PENALTY = 18.0
DONDAFUL_HS_CHANGE_MAX_PENALTY = 12.0

@dataclass(frozen=True)
class UserProfile:
    played_count: int
    score_ratio_median: float
    accuracy_median: float
    combo_median: float
    rating_capacity: float
    difficulty_capacity: float
    dim_capacity: Dict[str, float]
    user_dim_capacity: Dict[str, float]

def parse_target_recommendation_key(raw: str) -> Optional[str]:
    token = str(raw or '').strip().lower()
    if not token:
        return None
    return _TARGET_ALIASES.get(token)

def target_recommendation_displays() -> str:
    return '极、紫雅、粉雅、金雅、全连、全良'

def parse_target_recommendation_star_filter(raw: str) -> Optional[str]:
    token = str(raw or '').strip()
    if not token:
        return None
    token = token.translate(str.maketrans('０１２３４５６７８９', '0123456789'))
    token = token.lower().replace(' ', '')
    if token.endswith('星'):
        token = token[:-1]
    token = token.strip()
    if not token:
        return None
    return _STAR_FILTER_ALIASES.get(token)

def parse_target_recommendation_request(raw: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    tail = str(raw or '').strip()
    if not tail:
        return (None, None, 'empty')
    parts = tail.split()
    if not parts:
        return (None, None, 'empty')
    first_token = parts[0].strip()
    extra_tokens = list(parts[1:])
    target_key = parse_target_recommendation_key(first_token)
    compact_extra = ''
    if target_key is None:
        lowered = first_token.lower()
        for alias in _TARGET_ALIAS_KEYS_SORTED:
            if not lowered.startswith(alias):
                continue
            target_key = _TARGET_ALIASES.get(alias)
            compact_extra = first_token[len(alias):].strip()
            if target_key:
                break
    if target_key is None:
        return (None, None, 'invalid_target')
    if compact_extra:
        extra_tokens.insert(0, compact_extra)
    if len(extra_tokens) > 1:
        return (target_key, None, 'too_many_args')
    if not extra_tokens:
        return (target_key, None, None)
    star_filter = parse_target_recommendation_star_filter(extra_tokens[0])
    if star_filter is None:
        return (target_key, None, 'invalid_star')
    return (target_key, star_filter, None)

def _safe_int(value: Any, default: int=0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _safe_float(value: Any, default: float=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

def _completion_rate(entry: Optional[Dict[str, Any]], total_notes: int) -> float:
    if not entry:
        return 0.0
    if total_notes <= 0:
        total_notes = _safe_int(entry.get('good_cnt'), 0) + _safe_int(entry.get('ok_cnt'), 0) + _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0)
    if total_notes <= 0:
        return 0.0
    if _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0:
        return 100.0
    good = _safe_int(entry.get('good_cnt'), 0)
    ok = _safe_int(entry.get('ok_cnt'), 0)
    return _clamp((good + ok * 0.5) / total_notes * 100.0, 0.0, 100.0)

def _good_rate(entry: Optional[Dict[str, Any]], total_notes: int) -> float:
    if not entry:
        return 0.0
    if total_notes <= 0:
        total_notes = _safe_int(entry.get('good_cnt'), 0) + _safe_int(entry.get('ok_cnt'), 0) + _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0)
    if total_notes <= 0:
        return 0.0
    if _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0:
        return 100.0
    good = _safe_int(entry.get('good_cnt'), 0)
    return _clamp(good / total_notes * 100.0, 0.0, 100.0)

def _candidate_progress(rate: float) -> float:
    return _clamp(rate, 0.0, 99.9)

def _combo_rate(entry: Optional[Dict[str, Any]], total_notes: int) -> float:
    if not entry or total_notes <= 0:
        return 0.0
    if _safe_int(entry.get('full_combo_cnt'), 0) > 0 or _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0:
        return 100.0
    combo = _safe_int(entry.get('combo_cnt'), 0)
    return _clamp(combo / total_notes * 100.0, 0.0, 100.0)

def _format_title(chart: Dict[str, Any]) -> str:
    title = str(chart.get('title_cn') or chart.get('title_jp') or chart.get('title') or '').strip()
    if not title:
        title = f"ID{_safe_int(chart.get('id'), 0)}"
    level = _safe_int(chart.get('level'), 4)
    if level == 5 and '里' not in title and ('(裏' not in title) and ('（裏' not in title):
        title += '(里谱)'
    return title

def _normalize_title_key(value: Any) -> str:
    return support_normalize_title_key(value)

def _chart_title_key(chart: Dict[str, Any]) -> str:
    return support_chart_title_key(chart)

def _song_data_title_key(song: Dict[str, Any]) -> str:
    return support_song_data_title_key(song)

def _rating_feature_from_raw(raw: Dict[str, Any]) -> Dict[str, float]:
    return support_rating_feature_from_raw(raw)

def _is_double_chart(chart: Dict[str, Any]) -> bool:
    title_parts = (chart.get('title'), chart.get('title_jp'), chart.get('title_cn'))
    return any(('双打' in str(part or '') for part in title_parts))

def _format_song_star(value: Any) -> str:
    if value is None:
        return '-'
    if isinstance(value, str):
        text = value.strip()
        return text or '-'
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)

def _build_played_title_level_keys(records: Iterable[Dict[str, Any]], title_keys_by_id: Dict[int, str]) -> set[Tuple[str, int]]:
    return support_build_played_title_level_keys(records, title_keys_by_id)

def _median(values: Iterable[float], default: float) -> float:
    cleaned = [float(v) for v in values if math.isfinite(float(v))]
    if not cleaned:
        return default
    return float(median(cleaned))

def _top_quality_samples(samples: List[Dict[str, float]]) -> List[Dict[str, float]]:
    if not samples:
        return []
    ordered = sorted(samples, key=lambda item: item['quality'], reverse=True)
    take = min(len(ordered), max(12, len(ordered) // 4))
    return ordered[:take]

def _build_score_history_profile(best_map: Dict[Tuple[int, int], Dict[str, Any]], charts: Iterable[Dict[str, Any]], features_by_key: Dict[Tuple[int, int], Dict[str, float]]) -> UserProfile:
    chart_by_key = {(_safe_int(chart.get('id'), -1), _safe_int(chart.get('level'), -1)): chart for chart in charts}
    samples: List[Dict[str, float]] = []
    score_ratios: List[float] = []
    accuracy_rates: List[float] = []
    combo_rates: List[float] = []
    for key, entry in best_map.items():
        chart = chart_by_key.get(key)
        if not chart:
            continue
        total_notes = _safe_int(chart.get('max_combo'), 0)
        if total_notes <= 0:
            continue
        goku_score = _safe_int(chart.get('goku_score'), 0)
        if goku_score <= 0:
            continue
        score = _safe_int(entry.get('high_score'), 0)
        score_ratio = _clamp(score / goku_score, 0.0, 1.08)
        accuracy_rate = _completion_rate(entry, total_notes) / 100.0
        combo_rate = _combo_rate(entry, total_notes) / 100.0
        quality = _clamp(score_ratio * 0.45 + accuracy_rate * 0.35 + combo_rate * 0.2, 0.0, 1.08)
        score_ratios.append(score_ratio)
        accuracy_rates.append(accuracy_rate)
        combo_rates.append(combo_rate)
        feature = features_by_key.get(key, {})
        sample = {'quality': quality, 'const': _safe_float(feature.get('const'), 0.0)}
        for dim in DIM_KEYS:
            sample[dim] = _safe_float(feature.get(dim), 50.0)
        samples.append(sample)
    top_samples = _top_quality_samples(samples)
    if top_samples:
        dim_capacity = {dim: _median((sample[dim] for sample in top_samples), 50.0) for dim in DIM_KEYS}
        difficulty_capacity = _median((sample['const'] for sample in top_samples), 8.5)
    else:
        dim_capacity = {dim: 50.0 for dim in DIM_KEYS}
        difficulty_capacity = 8.5
    return UserProfile(played_count=len(samples), score_ratio_median=_median(score_ratios, 0.8), accuracy_median=_median(accuracy_rates, 0.8), combo_median=_median(combo_rates, 0.45), rating_capacity=difficulty_capacity, difficulty_capacity=difficulty_capacity, dim_capacity=dim_capacity, user_dim_capacity={'big_song': difficulty_capacity, 'stamina': _scale_raw_dim_to_user_dim(dim_capacity.get('stamina', 50.0), difficulty_capacity), 'speed': _scale_raw_dim_to_user_dim(dim_capacity.get('speed', 50.0), difficulty_capacity), 'accuracy_power': difficulty_capacity, 'rhythm': _scale_raw_dim_to_user_dim(dim_capacity.get('rhythm', 50.0), difficulty_capacity), 'complex': _scale_raw_dim_to_user_dim(dim_capacity.get('complex', 50.0), difficulty_capacity)})

def _scale_raw_dim_to_user_dim(raw_value: float, rating_capacity: float) -> float:
    rating_capacity = max(0.1, float(rating_capacity))
    return math.sqrt(max(0.0, rating_capacity * float(raw_value) * RAW_DIM_SCALE))

def _scale_user_dim_to_raw_capacity(user_dim: float, rating_capacity: float) -> float:
    rating_capacity = max(0.1, float(rating_capacity))
    return _clamp(float(user_dim) ** 2 / (rating_capacity * RAW_DIM_SCALE), 0.0, 100.0)

def _aggregate_user_capacity(results: List[Any], column: str, default: float, *, top_n: int=TARGET_RECOMMENDATION_PRIMARY_TOPN) -> float:
    try:
        value = float(aggregate_topN_value(results, column, top_n))
    except Exception:
        value = 0.0
    if value > 0:
        return value
    attr_map = {'AI_rating': 'AI_rating', '大歌力': 'big_song', '体力': 'stamina', '高速处理': 'speed', '精度力': 'accuracy_power', '节奏处理': 'rhythm', '复合处理': 'complex_proc'}
    attr = attr_map.get(column)
    if not attr:
        return default
    values = [float(getattr(result, attr, 0.0) or 0.0) for result in results if float(getattr(result, attr, 0.0) or 0.0) > 0]
    return _median(values, default)

def _build_rating_results_profile(results: List[Any], fallback: UserProfile, *, top_n: int) -> UserProfile:
    rating_capacity = _aggregate_user_capacity(results, 'AI_rating', fallback.rating_capacity, top_n=top_n)
    user_dim_capacity = {key: _aggregate_user_capacity(results, column, fallback.user_dim_capacity.get(key, fallback.rating_capacity), top_n=top_n) for key, column in USER_DIM_COLUMNS.items()}
    difficulty_capacity = max(rating_capacity, user_dim_capacity.get('big_song', 0.0), fallback.difficulty_capacity)
    dim_capacity: Dict[str, float] = {}
    for dim in DIM_KEYS:
        raw_capacity = _scale_user_dim_to_raw_capacity(user_dim_capacity.get(dim, 0.0), rating_capacity)
        if raw_capacity <= 0:
            raw_capacity = fallback.dim_capacity.get(dim, 50.0)
        dim_capacity[dim] = raw_capacity
    return UserProfile(played_count=len(results), score_ratio_median=fallback.score_ratio_median, accuracy_median=fallback.accuracy_median, combo_median=fallback.combo_median, rating_capacity=rating_capacity, difficulty_capacity=difficulty_capacity, dim_capacity=dim_capacity, user_dim_capacity=user_dim_capacity)

def _discount_user_profile(profile: UserProfile, factor: float) -> UserProfile:
    ratio_cap = 1.08
    percentile_cap = 0.999
    scaled_user_dims = {key: max(0.0, float(value or 0.0) * factor) for key, value in profile.user_dim_capacity.items()}
    scaled_raw_dims = {key: _clamp(float(profile.dim_capacity.get(key, 0.0) or 0.0) * factor, 0.0, 100.0) for key in DIM_KEYS}
    return UserProfile(played_count=profile.played_count, score_ratio_median=_clamp(profile.score_ratio_median * factor, 0.0, ratio_cap), accuracy_median=_clamp(profile.accuracy_median * factor, 0.0, percentile_cap), combo_median=_clamp(profile.combo_median * factor, 0.0, percentile_cap), rating_capacity=max(0.0, profile.rating_capacity * factor), difficulty_capacity=max(0.0, profile.difficulty_capacity * factor), dim_capacity=scaled_raw_dims, user_dim_capacity=scaled_user_dims)

def _lower_capacity_profile(primary: UserProfile, secondary: UserProfile) -> UserProfile:
    merged_user_dims = {key: min(float(primary.user_dim_capacity.get(key, 0.0) or 0.0), float(secondary.user_dim_capacity.get(key, 0.0) or 0.0)) for key in set(primary.user_dim_capacity) | set(secondary.user_dim_capacity)}
    merged_raw_dims = {key: min(float(primary.dim_capacity.get(key, 0.0) or 0.0), float(secondary.dim_capacity.get(key, 0.0) or 0.0)) for key in DIM_KEYS}
    return UserProfile(played_count=max(primary.played_count, secondary.played_count), score_ratio_median=min(primary.score_ratio_median, secondary.score_ratio_median), accuracy_median=min(primary.accuracy_median, secondary.accuracy_median), combo_median=min(primary.combo_median, secondary.combo_median), rating_capacity=min(primary.rating_capacity, secondary.rating_capacity), difficulty_capacity=min(primary.difficulty_capacity, secondary.difficulty_capacity), dim_capacity=merged_raw_dims, user_dim_capacity=merged_user_dims)

def _profile_match(profile: UserProfile, feature: Dict[str, float]) -> float:
    penalty = 0.0
    for dim in DIM_KEYS:
        capacity = max(10.0, _safe_float(profile.dim_capacity.get(dim), 50.0))
        value = _safe_float(feature.get(dim), 50.0)
        if value > capacity:
            penalty += (value - capacity) / max(20.0, 100.0 - capacity)
    const_value = _safe_float(feature.get('const'), profile.difficulty_capacity)
    const_excess = max(0.0, const_value - profile.difficulty_capacity)
    penalty += const_excess * 0.22
    return _clamp(100.0 - penalty * 42.0, 0.0, 100.0)

def _const_match(profile: UserProfile, feature: Dict[str, float]) -> float:
    const_value = _safe_float(feature.get('const'), profile.difficulty_capacity)
    return _clamp(100.0 - max(0.0, const_value - profile.difficulty_capacity) * 18.0, 0.0, 100.0)

def _roll_hits(chart: Dict[str, Any], speed_ips: float) -> int:
    return compute_rating_roll_breakdown(chart, speed_ips).effective_roll_hits

def _sigmoid01(value: float, scale: float) -> float:
    if scale <= 0:
        return 1.0 if value >= 0 else 0.0
    x = _clamp(value / scale, -40.0, 40.0)
    return 1.0 / (1.0 + math.exp(-x))

def _profile_probability_factor(profile_match: float, const_match: float) -> float:
    combined = _clamp((profile_match * 0.72 + const_match * 0.28) / 100.0, 0.0, 1.0)
    return _clamp(0.22 + 0.78 * combined ** 1.45, 0.05, 1.0)

def _recommend_index_from_likelihood(likelihood: float) -> float:
    return round(_clamp(likelihood, 0.0, 100.0), 1)

def _entry_age_days(entry: Optional[Dict[str, Any]], *, today: date) -> Optional[int]:
    return support_entry_age_days(entry, today=today)

def _played_score_freshness_weight(age_days: Optional[int]) -> float:
    return support_played_score_freshness_weight(age_days)

def _score_target_tolerance(chart: Dict[str, Any], target_score: int, speed_ips: float) -> Optional[Dict[str, int | float | bool]]:
    return core_score_target_tolerance(chart, target_score, speed_ips)

def _target_score_required_dims(*, chart: Dict[str, Any], feature: Dict[str, float], target_score: int, tolerance: Dict[str, int | float | bool], const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    return core_target_score_required_dims(chart=chart, feature=feature, target_score=target_score, tolerance=tolerance, const_table=const_table)

def _required_dims_for_target_accuracy(*, feature: Dict[str, float], target_accuracy: float, const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    return core_required_dims_for_target_accuracy(feature=feature, target_accuracy=target_accuracy, const_table=const_table)

def _single_dim_overflow_slack(profile: UserProfile, required_dims: Dict[str, float], dim: str) -> float:
    if dim not in TARGET_SCORE_MULTIDIM_DIMS:
        return 0.0
    active_dims = [candidate_dim for candidate_dim in TARGET_SCORE_MULTIDIM_DIMS if _required_capacity_usage_ratio(profile, required_dims, candidate_dim) >= TARGET_SCORE_MULTIDIM_OVERFLOW_TRIGGER]
    if active_dims == [dim]:
        return TARGET_SCORE_SINGLE_DIM_OVERFLOW_SLACK
    if dim in active_dims and len(active_dims) >= 2:
        return -TARGET_SCORE_MULTIDIM_OVERFLOW_PENALTY
    return 0.0

def _exceeds_target_score_dim_limits(profile: UserProfile, required_dims: Dict[str, float]) -> bool:
    for dim in TARGET_SCORE_DIM_KEYS:
        threshold = _safe_float(TARGET_SCORE_DIM_THRESHOLDS.get(dim), 0.0)
        threshold += _single_dim_overflow_slack(profile, required_dims, dim)
        capacity = _safe_float(profile.user_dim_capacity.get(dim), 0.0)
        required = _safe_float(required_dims.get(dim), 0.0)
        if required > capacity + threshold:
            return True
    return False

def _full_combo_required_dims(*, chart: Dict[str, Any], feature: Dict[str, float], const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    return _required_dims_for_target_accuracy(feature=feature, target_accuracy=FULL_COMBO_TARGET_ACCURACY, const_table=const_table)

def _dondaful_required_dims(*, chart: Dict[str, Any], feature: Dict[str, float], const_table: List[Tuple[float, float]]) -> Optional[Dict[str, float]]:
    return _required_dims_for_target_accuracy(feature=feature, target_accuracy=DONDAFUL_TARGET_ACCURACY, const_table=const_table)

def _exceeds_dim_limits(profile: UserProfile, required_dims: Dict[str, float], thresholds: Dict[str, float]) -> bool:
    for dim, allowance in thresholds.items():
        capacity = _safe_float(profile.user_dim_capacity.get(dim), 0.0)
        required = _safe_float(required_dims.get(dim), 0.0)
        if required > capacity + allowance:
            return True
    return False

def _exceeds_full_combo_dim_limits(profile: UserProfile, required_dims: Dict[str, float]) -> bool:
    return _exceeds_dim_limits(profile, required_dims, FULL_COMBO_DIM_THRESHOLDS)

def _exceeds_dondaful_dim_limits(profile: UserProfile, required_dims: Dict[str, float]) -> bool:
    return _exceeds_dim_limits(profile, required_dims, DONDAFUL_DIM_THRESHOLDS)

def _required_capacity_usage_ratio(profile: UserProfile, required_dims: Dict[str, float], dim: str) -> float:
    capacity = max(0.1, _safe_float(profile.user_dim_capacity.get(dim), 0.0))
    required = max(0.0, _safe_float(required_dims.get(dim), 0.0))
    return required / capacity

def _soft_dim_norm(profile: UserProfile, required_dims: Dict[str, float], dim: str, free_zone: float) -> float:
    usage_ratio = _required_capacity_usage_ratio(profile, required_dims, dim)
    if free_zone >= 1.0:
        return 0.0 if usage_ratio <= free_zone else 1.25
    return _clamp((usage_ratio - free_zone) / max(0.01, 1.0 - free_zone), 0.0, 1.25)

def _excess_dim_norm(profile: UserProfile, required_dims: Dict[str, float], dim: str, divisor: float) -> float:
    if divisor <= 0:
        return 0.0
    return _clamp(max(0.0, _safe_float(required_dims.get(dim), 0.0) - _safe_float(profile.user_dim_capacity.get(dim), 0.0)) / divisor, 0.0, 10.0)

def _score_target_capacity_pressure_penalty(profile: UserProfile, required_dims: Dict[str, float]) -> float:
    penalty = 0.0
    for dim, start in TARGET_SCORE_EDGE_STARTS.items():
        usage_ratio = _required_capacity_usage_ratio(profile, required_dims, dim)
        edge_norm = _clamp((usage_ratio - start) / max(0.01, TARGET_SCORE_EDGE_WIDTH), 0.0, 1.5)
        penalty += edge_norm * _safe_float(TARGET_SCORE_EDGE_WEIGHTS.get(dim), 0.0)
    penalty = _clamp(penalty, 0.0, TARGET_SCORE_EDGE_MAX_PENALTY)
    return penalty + _score_target_pair_pressure_penalty(profile, required_dims)

def _score_target_pair_pressure_penalty(profile: UserProfile, required_dims: Dict[str, float]) -> float:
    norms: List[float] = []
    for dim in TARGET_SCORE_MULTIDIM_DIMS:
        usage_ratio = _required_capacity_usage_ratio(profile, required_dims, dim)
        norm = _clamp((usage_ratio - TARGET_SCORE_MULTIDIM_START) / max(0.01, TARGET_SCORE_MULTIDIM_WIDTH), 0.0, 1.0)
        if norm >= TARGET_SCORE_MULTIDIM_MIN_NORM:
            norms.append(norm)
    if len(norms) < 2:
        return 0.0
    norms.sort(reverse=True)
    if len(norms) == 2 and norms[0] > norms[1] * TARGET_SCORE_MULTIDIM_DOMINANT_RATIO:
        return 0.0
    penalty = sum(norms[1:]) * TARGET_SCORE_MULTIDIM_WEIGHT
    if len(norms) >= 3:
        penalty += TARGET_SCORE_MULTIDIM_THREE_DIM_BONUS
    return min(TARGET_SCORE_MULTIDIM_MAX_PENALTY, penalty)

def _full_combo_edge_penalty(profile: UserProfile, required_dims: Dict[str, float]) -> float:
    penalty = 0.0
    for dim, start in FULL_COMBO_EDGE_STARTS.items():
        usage_ratio = _required_capacity_usage_ratio(profile, required_dims, dim)
        edge_norm = _clamp((usage_ratio - start) / 0.2, 0.0, 1.5)
        penalty += edge_norm * _safe_float(FULL_COMBO_EDGE_WEIGHTS.get(dim), 0.0)
    return penalty

def _hs_change_penalty(feature: Dict[str, float], max_penalty: float) -> float:
    hs_change = _safe_float(feature.get('hs_change'), 0.0)
    if hs_change <= HS_CHANGE_MEMORIZATION_THRESHOLD or max_penalty <= 0:
        return 0.0
    normalized = _clamp((hs_change - HS_CHANGE_MEMORIZATION_THRESHOLD) / max(1.0, HS_CHANGE_NORMALIZATION_RANGE), 0.0, 1.0)
    severity = normalized ** HS_CHANGE_CURVE_EXPONENT
    return severity * max_penalty

def _baseline_score_target_likelihood(*, chart: Dict[str, Any], target_score: int, ok_allow_ratio: float, required_good_rate: float, profile: UserProfile, feature: Dict[str, float], profile_match: float, const_match: float) -> float:
    profile_factor = _profile_probability_factor(profile_match, const_match)
    goku_score = max(1, _safe_int(chart.get('goku_score'), target_score))
    const_value = _safe_float(feature.get('const'), profile.difficulty_capacity)
    const_excess = max(0.0, const_value - profile.difficulty_capacity)
    if target_score < goku_score:
        bonus = _unplayed_score_bonus(profile, feature)
        feature_factor = 0.9 + profile_match / 100.0 * 0.2 + bonus
        estimated_score = goku_score * profile.score_ratio_median * feature_factor
        score_margin = estimated_score / max(1, target_score) - 1.0 - const_excess * 0.014
        score_probability = _sigmoid01(score_margin, 0.05)
        estimated_accuracy = _clamp(profile.accuracy_median * (0.91 + profile_match / 100.0 * 0.16) + bonus * 0.35, 0.0, 0.995)
        accuracy_probability = _sigmoid01(estimated_accuracy - required_good_rate, 0.07)
    else:
        feature_factor = 0.88 + profile_match / 100.0 * 0.18
        estimated_score = goku_score * profile.score_ratio_median * feature_factor
        score_margin = estimated_score / max(1, target_score) - 1.0 - const_excess * 0.018
        score_probability = _sigmoid01(score_margin, 0.04)
        accuracy_probability = _sigmoid01(profile.accuracy_median - required_good_rate, 0.06)
    base_probability = score_probability * 0.52 + accuracy_probability * 0.3 + ok_allow_ratio * 0.18
    return _clamp(base_probability * profile_factor * 100.0, 0.0, 100.0)

def _played_score_observed_likelihood(*, chart: Dict[str, Any], entry: Dict[str, Any], target_score: int, note_count: int, ok_allow_ratio: float, required_good_rate: float, profile_match: float, const_match: float) -> float:
    profile_factor = _profile_probability_factor(profile_match, const_match)
    delta = max(1, _safe_int(chart.get('initial_points'), 0) - _safe_int(chart.get('ok_points'), 0))
    score = _safe_int(entry.get('high_score'), 0)
    score_gap = max(0, target_score - score)
    extra_good_ratio = _clamp(score_gap / max(1, delta * note_count), 0.0, 1.0)
    score_probability = _sigmoid01(0.085 - extra_good_ratio, 0.032)
    good_rate = _good_rate(entry, note_count) / 100.0
    accuracy_probability = _sigmoid01(good_rate - required_good_rate, 0.045)
    miss_count = _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0)
    miss_factor = math.exp(-miss_count / max(1.0, note_count * 0.012))
    base_probability = score_probability * 0.54 + accuracy_probability * 0.26 + ok_allow_ratio * 0.14 + miss_factor * 0.06
    return _clamp(base_probability * profile_factor * 100.0, 0.0, 100.0)

def _played_score_penalty(*, entry: Dict[str, Any], baseline_likelihood: float, played_likelihood: float, today: date) -> float:
    if played_likelihood >= baseline_likelihood - 2.0:
        return baseline_likelihood
    freshness_weight = _played_score_freshness_weight(_entry_age_days(entry, today=today))
    if freshness_weight <= 0.0:
        return baseline_likelihood
    return _clamp(baseline_likelihood - (baseline_likelihood - played_likelihood) * freshness_weight * 0.35, 0.0, 100.0)

def _score_target_likelihood(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], target_score: int, tolerance: Dict[str, int | float | bool], profile: UserProfile, feature: Dict[str, float], profile_match: float, const_match: float, today: date) -> float:
    note_count = max(1, _safe_int(chart.get('max_combo'), 1))
    max_ok = max(0, _safe_int(tolerance.get('max_ok'), 0))
    ok_allow_ratio = _clamp(max_ok / note_count, 0.0, 1.0)
    required_good_rate = 1.0 - ok_allow_ratio
    baseline_likelihood = _baseline_score_target_likelihood(chart=chart, target_score=target_score, ok_allow_ratio=ok_allow_ratio, required_good_rate=required_good_rate, profile=profile, feature=feature, profile_match=profile_match, const_match=const_match)
    if not entry:
        return _clamp(baseline_likelihood - _hs_change_penalty(feature, SCORE_TARGET_HS_CHANGE_MAX_PENALTY), 0.0, 100.0)
    played_likelihood = _played_score_observed_likelihood(chart=chart, entry=entry, target_score=target_score, note_count=note_count, ok_allow_ratio=ok_allow_ratio, required_good_rate=required_good_rate, profile_match=profile_match, const_match=const_match)
    likelihood = _played_score_penalty(entry=entry, baseline_likelihood=baseline_likelihood, played_likelihood=played_likelihood, today=today)
    return _clamp(likelihood - _hs_change_penalty(feature, SCORE_TARGET_HS_CHANGE_MAX_PENALTY), 0.0, 100.0)

def _unplayed_score_bonus(profile: UserProfile, feature: Dict[str, float]) -> float:
    const_value = _safe_float(feature.get('const'), profile.difficulty_capacity)
    const_headroom = _clamp(profile.difficulty_capacity - const_value, 0.0, 2.5)
    dim_headrooms = []
    for dim in DIM_KEYS:
        capacity = _safe_float(profile.dim_capacity.get(dim), 50.0)
        value = _safe_float(feature.get(dim), capacity)
        dim_headrooms.append(_clamp((capacity - value) / 100.0, 0.0, 1.0))
    mean_dim_headroom = sum(dim_headrooms) / len(dim_headrooms) if dim_headrooms else 0.0
    return _clamp(const_headroom * 0.035 + mean_dim_headroom * 0.1, 0.0, 0.12)

def _score_recommend_index(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], target_score: int, tolerance: Dict[str, int | float | bool], profile: UserProfile, feature: Dict[str, float], profile_match: float, const_match: float, today: date) -> float:
    likelihood = _score_target_likelihood(chart=chart, entry=entry, target_score=target_score, tolerance=tolerance, profile=profile, feature=feature, profile_match=profile_match, const_match=const_match, today=today)
    return _recommend_index_from_likelihood(likelihood)

def _combo_recommend_index(*, entry: Optional[Dict[str, Any]], chart: Dict[str, Any], profile: UserProfile, required_dims: Optional[Dict[str, float]], feature: Optional[Dict[str, float]]=None) -> float:
    note_count = max(1, _safe_int(chart.get('max_combo'), 1))
    required_dims = required_dims or {}
    feature = feature or {}
    soft_speed = _soft_dim_norm(profile, required_dims, 'speed', FULL_COMBO_SOFT_FREE_ZONES['speed'])
    soft_complex = _soft_dim_norm(profile, required_dims, 'complex', FULL_COMBO_SOFT_FREE_ZONES['complex'])
    soft_big_song = _soft_dim_norm(profile, required_dims, 'big_song', FULL_COMBO_SOFT_FREE_ZONES['big_song'])
    soft_stamina = _soft_dim_norm(profile, required_dims, 'stamina', FULL_COMBO_SOFT_FREE_ZONES['stamina'])
    soft_rhythm = _soft_dim_norm(profile, required_dims, 'rhythm', FULL_COMBO_SOFT_FREE_ZONES['rhythm'])
    soft_fit_penalty = soft_speed * FULL_COMBO_SOFT_WEIGHTS['speed'] + soft_complex * FULL_COMBO_SOFT_WEIGHTS['complex'] + soft_big_song * FULL_COMBO_SOFT_WEIGHTS['big_song'] + soft_stamina * FULL_COMBO_SOFT_WEIGHTS['stamina'] + soft_rhythm * FULL_COMBO_SOFT_WEIGHTS['rhythm']
    speed_excess = _excess_dim_norm(profile, required_dims, 'speed', FULL_COMBO_HARD_DIVISORS['speed'])
    complex_excess = _excess_dim_norm(profile, required_dims, 'complex', FULL_COMBO_HARD_DIVISORS['complex'])
    big_song_excess = _excess_dim_norm(profile, required_dims, 'big_song', FULL_COMBO_HARD_DIVISORS['big_song'])
    stamina_excess = _excess_dim_norm(profile, required_dims, 'stamina', FULL_COMBO_HARD_DIVISORS['stamina'])
    rhythm_excess = _excess_dim_norm(profile, required_dims, 'rhythm', FULL_COMBO_HARD_DIVISORS['rhythm'])
    hard_fit_penalty = speed_excess * FULL_COMBO_HARD_WEIGHTS['speed'] + complex_excess * FULL_COMBO_HARD_WEIGHTS['complex'] + big_song_excess * FULL_COMBO_HARD_WEIGHTS['big_song'] + stamina_excess * FULL_COMBO_HARD_WEIGHTS['stamina'] + rhythm_excess * FULL_COMBO_HARD_WEIGHTS['rhythm']
    edge_penalty = _full_combo_edge_penalty(profile, required_dims)
    hs_change_penalty = _hs_change_penalty(feature, FULL_COMBO_HS_CHANGE_MAX_PENALTY)
    risk_multiplier = 1.0 + min(1.2, max(soft_speed, soft_complex, speed_excess, complex_excess) * 0.55)
    if not entry:
        return _clamp(99.0 - soft_fit_penalty - hard_fit_penalty - edge_penalty - hs_change_penalty, 0.0, 100.0)
    ng_cnt = _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0)
    combo_cnt = _safe_int(entry.get('combo_cnt'), 0)
    combo_gap = max(0, note_count - combo_cnt)
    combo_rate = _combo_rate(entry, note_count) / 100.0
    bad_penalty = ng_cnt * 12.0 * risk_multiplier
    combo_gap_penalty = combo_gap / note_count * 16.0 * risk_multiplier
    progress_bonus = combo_rate * 12.0
    return _clamp(99.0 - soft_fit_penalty - hard_fit_penalty - edge_penalty - hs_change_penalty - bad_penalty - combo_gap_penalty + progress_bonus, 0.0, 100.0)

def _dondaful_recommend_index(*, entry: Optional[Dict[str, Any]], chart: Dict[str, Any], profile: UserProfile, required_dims: Optional[Dict[str, float]], feature: Optional[Dict[str, float]]=None) -> float:
    note_count = max(1, _safe_int(chart.get('max_combo'), 1))
    required_dims = required_dims or {}
    feature = feature or {}
    soft_accuracy = _soft_dim_norm(profile, required_dims, 'accuracy_power', DONDAFUL_SOFT_FREE_ZONES['accuracy_power'])
    soft_rhythm = _soft_dim_norm(profile, required_dims, 'rhythm', DONDAFUL_SOFT_FREE_ZONES['rhythm'])
    soft_big_song = _soft_dim_norm(profile, required_dims, 'big_song', DONDAFUL_SOFT_FREE_ZONES['big_song'])
    soft_speed = _soft_dim_norm(profile, required_dims, 'speed', DONDAFUL_SOFT_FREE_ZONES['speed'])
    soft_complex = _soft_dim_norm(profile, required_dims, 'complex', DONDAFUL_SOFT_FREE_ZONES['complex'])
    soft_stamina = _soft_dim_norm(profile, required_dims, 'stamina', DONDAFUL_SOFT_FREE_ZONES['stamina'])
    soft_fit_penalty = soft_accuracy * DONDAFUL_SOFT_WEIGHTS['accuracy_power'] + soft_rhythm * DONDAFUL_SOFT_WEIGHTS['rhythm'] + soft_big_song * DONDAFUL_SOFT_WEIGHTS['big_song'] + soft_speed * DONDAFUL_SOFT_WEIGHTS['speed'] + soft_complex * DONDAFUL_SOFT_WEIGHTS['complex'] + soft_stamina * DONDAFUL_SOFT_WEIGHTS['stamina']
    accuracy_excess = _excess_dim_norm(profile, required_dims, 'accuracy_power', DONDAFUL_HARD_DIVISORS['accuracy_power'])
    rhythm_excess = _excess_dim_norm(profile, required_dims, 'rhythm', DONDAFUL_HARD_DIVISORS['rhythm'])
    big_song_excess = _excess_dim_norm(profile, required_dims, 'big_song', DONDAFUL_HARD_DIVISORS['big_song'])
    speed_excess = _excess_dim_norm(profile, required_dims, 'speed', DONDAFUL_HARD_DIVISORS['speed'])
    complex_excess = _excess_dim_norm(profile, required_dims, 'complex', DONDAFUL_HARD_DIVISORS['complex'])
    stamina_excess = _excess_dim_norm(profile, required_dims, 'stamina', DONDAFUL_HARD_DIVISORS['stamina'])
    hard_fit_penalty = accuracy_excess * DONDAFUL_HARD_WEIGHTS['accuracy_power'] + rhythm_excess * DONDAFUL_HARD_WEIGHTS['rhythm'] + big_song_excess * DONDAFUL_HARD_WEIGHTS['big_song'] + speed_excess * DONDAFUL_HARD_WEIGHTS['speed'] + complex_excess * DONDAFUL_HARD_WEIGHTS['complex'] + stamina_excess * DONDAFUL_HARD_WEIGHTS['stamina']
    hs_change_penalty = _hs_change_penalty(feature, DONDAFUL_HS_CHANGE_MAX_PENALTY)
    risk_multiplier = 1.0 + min(1.0, max(soft_accuracy, soft_rhythm, accuracy_excess, rhythm_excess) * 0.5)
    if not entry:
        return _clamp(96.0 - soft_fit_penalty - hard_fit_penalty - hs_change_penalty, 0.0, 100.0)
    ng_cnt = _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0)
    ok_cnt = _safe_int(entry.get('ok_cnt'), 0)
    good_rate = _good_rate(entry, note_count) / 100.0
    ng_penalty = ng_cnt * 28.0 * risk_multiplier
    ok_penalty = ok_cnt * 4.8 * risk_multiplier
    good_rate_bonus = good_rate * 10.0
    return _clamp(96.0 - soft_fit_penalty - hard_fit_penalty - hs_change_penalty - ng_penalty - ok_penalty + good_rate_bonus, 0.0, 100.0)

def _build_score_target_row(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], target_key: str, profile: UserProfile, feature: Dict[str, float], roll_speed_ips: float, const_table: Optional[List[Tuple[float, float]]]=None, today: date) -> Optional[Dict[str, Any]]:
    rating_scores = chart.get('rating_scores')
    if not isinstance(rating_scores, dict):
        return None
    target_score = _safe_int(rating_scores.get(target_key), 0)
    if target_score <= 0:
        return None
    if entry and _safe_int(entry.get('high_score'), 0) >= target_score:
        return None
    tolerance = _score_target_tolerance(chart, target_score, roll_speed_ips)
    if not tolerance or not bool(tolerance.get('reachable')):
        return None
    required_dims: Optional[Dict[str, float]] = None
    if const_table:
        required_dims = _target_score_required_dims(chart=chart, feature=feature, target_score=target_score, tolerance=tolerance, const_table=const_table)
        if required_dims is not None and _exceeds_target_score_dim_limits(profile, required_dims):
            return None
    score: Optional[int] = _safe_int(entry.get('high_score'), 0) if entry else None
    progress = _candidate_progress(_good_rate(entry, _safe_int(chart.get('max_combo'), 0)))
    gap_text = '未游玩' if score is None else f'差{max(0, target_score - score)}'
    profile_score = _profile_match(profile, feature)
    const_score = _const_match(profile, feature)
    likelihood = _score_target_likelihood(chart=chart, entry=entry, target_score=target_score, tolerance=tolerance, profile=profile, feature=feature, profile_match=profile_score, const_match=const_score, today=today)
    return {'song_id': _safe_int(chart.get('id'), 0), 'level': _safe_int(chart.get('level'), 4), 'target_key': target_key, 'title': _format_title(chart), 'score': score, 'progress': progress, 'target_text': str(target_score), 'gap_text': gap_text, 'target_score': target_score, 'gap_kind': 'unplayed' if score is None else 'score', 'gap_value': None if score is None else max(0, target_score - score), 'recommend_likelihood': likelihood, 'recommend_index': _recommend_index_from_likelihood(likelihood), 'is_unplayed': entry is None, '_required_dims': required_dims}

def _build_full_combo_row(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], profile: UserProfile, feature: Dict[str, float], const_table: Optional[List[Tuple[float, float]]]=None) -> Optional[Dict[str, Any]]:
    if entry and (_safe_int(entry.get('full_combo_cnt'), 0) > 0 or _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0):
        return None
    total_notes = _safe_int(chart.get('max_combo'), 0)
    required_dims = _full_combo_required_dims(chart=chart, feature=feature, const_table=const_table) if const_table else None
    if required_dims is not None and _exceeds_full_combo_dim_limits(profile, required_dims):
        return None
    score: Optional[int] = _safe_int(entry.get('high_score'), 0) if entry else None
    progress = _candidate_progress(_combo_rate(entry, total_notes))
    bad_count = _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0) if entry else total_notes + 1
    combo_gap = max(0, total_notes - _safe_int(entry.get('combo_cnt'), 0)) if entry else total_notes + 1
    if not entry:
        gap_text = '未游玩'
    elif bad_count > 0:
        gap_text = f'不可 {bad_count}'
    else:
        gap_text = f'连击差 {combo_gap}'
    recommend_index = _combo_recommend_index(entry=entry, chart=chart, profile=profile, required_dims=required_dims, feature=feature)
    return {'song_id': _safe_int(chart.get('id'), 0), 'level': _safe_int(chart.get('level'), 4), 'title': _format_title(chart), 'score': score, 'progress': progress, 'target_text': '全连', 'gap_text': gap_text, 'target_score': None, 'gap_kind': 'unplayed' if not entry else 'bad' if bad_count > 0 else 'combo', 'gap_value': None if not entry else bad_count if bad_count > 0 else combo_gap, 'recommend_index': recommend_index, 'is_unplayed': entry is None, '_sort_gap_primary': bad_count, '_sort_gap_secondary': combo_gap}

def _build_dondaful_row(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], profile: UserProfile, feature: Dict[str, float], const_table: Optional[List[Tuple[float, float]]]=None) -> Optional[Dict[str, Any]]:
    if entry and _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0:
        return None
    total_notes = _safe_int(chart.get('max_combo'), 0)
    required_dims = _dondaful_required_dims(chart=chart, feature=feature, const_table=const_table) if const_table else None
    if required_dims is not None and _exceeds_dondaful_dim_limits(profile, required_dims):
        return None
    score: Optional[int] = _safe_int(entry.get('high_score'), 0) if entry else None
    progress = _candidate_progress(_good_rate(entry, total_notes))
    ng_cnt = _safe_int(entry.get('ng_cnt', entry.get('bad_cnt')), 0) if entry else total_notes + 1
    ok_cnt = _safe_int(entry.get('ok_cnt'), 0) if entry else total_notes + 1
    miss_count = ok_cnt + ng_cnt
    if not entry:
        gap_text = '未游玩'
    else:
        gap_text = f'可+不可 {miss_count}'
    recommend_index = _dondaful_recommend_index(entry=entry, chart=chart, profile=profile, required_dims=required_dims, feature=feature)
    return {'song_id': _safe_int(chart.get('id'), 0), 'level': _safe_int(chart.get('level'), 4), 'title': _format_title(chart), 'score': score, 'progress': progress, 'target_text': '全良', 'gap_text': gap_text, 'target_score': None, 'gap_kind': 'unplayed' if not entry else 'misses', 'gap_value': None if not entry else miss_count, 'recommend_index': recommend_index, 'is_unplayed': entry is None, '_sort_gap_primary': miss_count, '_sort_gap_secondary': ng_cnt}

def _score_band_likelihood(row_by_target: Dict[str, Dict[str, Any]], target_key: str) -> float:
    current = _clamp(_safe_float(row_by_target[target_key].get('recommend_likelihood'), 0.0), 0.0, 100.0)
    next_key = NEXT_SCORE_TARGET.get(target_key)
    if not next_key:
        return current
    next_row = row_by_target.get(next_key)
    if not next_row:
        return current
    next_likelihood = _clamp(_safe_float(next_row.get('recommend_likelihood'), 0.0), 0.0, 100.0)
    return max(0.0, current - next_likelihood)

def _score_target_owner(row_by_target: Dict[str, Dict[str, Any]]) -> Optional[str]:
    if not row_by_target:
        return None
    return max(row_by_target, key=lambda key: (_score_band_likelihood(row_by_target, key), SCORE_TARGET_RANK.get(key, -1)))

def _build_owned_score_target_row(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], requested_target_key: str, profile: UserProfile, feature: Dict[str, float], roll_speed_ips: float, const_table: Optional[List[Tuple[float, float]]]=None, today: date) -> Optional[Dict[str, Any]]:
    row_by_target: Dict[str, Dict[str, Any]] = {}
    for score_target in SCORE_TARGET_ORDER:
        row = _build_score_target_row(chart=chart, entry=entry, target_key=score_target, profile=profile, feature=feature, roll_speed_ips=roll_speed_ips, const_table=const_table, today=today)
        if row is not None:
            row_by_target[score_target] = row
    requested_row = row_by_target.get(requested_target_key)
    if requested_row is None:
        return None
    if _score_target_owner(row_by_target) != requested_target_key:
        return None
    required_dims = requested_row.get('_required_dims')
    edge_penalty = _score_target_capacity_pressure_penalty(profile, required_dims) if isinstance(required_dims, dict) else 0.0
    if edge_penalty > 0:
        adjusted_likelihood = _clamp(_safe_float(requested_row.get('recommend_likelihood'), 0.0) - edge_penalty, 0.0, 100.0)
        requested_row['recommend_likelihood'] = adjusted_likelihood
        requested_row['recommend_index'] = _recommend_index_from_likelihood(adjusted_likelihood)
    band_likelihood = _score_band_likelihood(row_by_target, requested_target_key)
    band_likelihood = _clamp(band_likelihood - edge_penalty, 0.0, 100.0)
    requested_row['target_band_likelihood'] = band_likelihood
    requested_row['target_band_index'] = _recommend_index_from_likelihood(band_likelihood)
    return requested_row

def _build_owned_score_target_row_from_reach(*, chart: Dict[str, Any], entry: Optional[Dict[str, Any]], requested_target_key: str, reaches_by_target: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Build a score-target row from the batch current-skill reach estimator."""
    rating_scores = chart.get('rating_scores')
    if not isinstance(rating_scores, dict):
        return None
    row_by_target: Dict[str, Dict[str, Any]] = {}
    for score_target in SCORE_TARGET_ORDER:
        target_score = _safe_int(rating_scores.get(score_target), 0)
        reach = reaches_by_target.get(score_target)
        if target_score <= 0 or reach is None:
            continue
        if entry and _safe_int(entry.get('high_score'), 0) >= target_score:
            continue
        likelihood = _clamp(_safe_float(getattr(reach, 'likelihood', 0.0)) * 100.0, 0.0, 100.0)
        score: Optional[int] = _safe_int(entry.get('high_score'), 0) if entry else None
        row_by_target[score_target] = {'song_id': _safe_int(chart.get('id'), 0), 'level': _safe_int(chart.get('level'), 4), 'target_key': score_target, 'title': _format_title(chart), 'score': score, 'progress': _candidate_progress(_good_rate(entry, _safe_int(chart.get('max_combo'), 0))), 'target_text': str(target_score), 'gap_text': '未游玩' if score is None else f'差{max(0, target_score - score)}', 'target_score': target_score, 'gap_kind': 'unplayed' if score is None else 'score', 'gap_value': None if score is None else max(0, target_score - score), 'recommend_likelihood': likelihood, 'recommend_index': _recommend_index_from_likelihood(likelihood), 'is_unplayed': entry is None}
    requested_row = row_by_target.get(requested_target_key)
    if requested_row is None or _score_target_owner(row_by_target) != requested_target_key:
        return None
    if _safe_float(requested_row.get('recommend_likelihood'), 0.0) < 18.0:
        return None
    band_likelihood = _score_band_likelihood(row_by_target, requested_target_key)
    requested_row['target_band_likelihood'] = band_likelihood
    requested_row['target_band_index'] = _recommend_index_from_likelihood(band_likelihood)
    return requested_row

def build_user_profile(rating_results, best_map: Dict[Tuple[int, int], Dict[str, Any]], charts: Iterable[Dict[str, Any]], features_by_key: Dict[Tuple[int, int], Dict[str, float]]) -> UserProfile:
    fallback = _build_score_history_profile(best_map, charts, features_by_key)
    if not rating_results:
        return fallback
    primary_profile = _build_rating_results_profile(rating_results, fallback, top_n=TARGET_RECOMMENDATION_PRIMARY_TOPN)
    alternate_profile = _build_rating_results_profile(rating_results, fallback, top_n=TARGET_RECOMMENDATION_ALT_TOPN)
    discounted_primary = _discount_user_profile(primary_profile, TARGET_RECOMMENDATION_PROFILE_DISCOUNT)
    return _lower_capacity_profile(discounted_primary, alternate_profile)
