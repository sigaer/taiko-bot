from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from ..models.calculation import SongMetrics, RatingResult, SongStats
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table, _calc_accuracy_for_record, aggregate_topN_value
from ..dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims

SCORE_TARGETS = {'goku', 'ziya', 'fenya', 'jinya'}
FULL_COMBO_TARGET = 'full_combo'
DONDAFUL_TARGET = 'dondaful'
TARGET_DISPLAY: Dict[str, str] = {'goku': '极', 'ziya': '紫雅', 'fenya': '粉雅', 'jinya': '金雅', FULL_COMBO_TARGET: '全连', DONDAFUL_TARGET: '全良'}
_TARGET_ALIASES: Dict[str, str] = {'goku': 'goku', '极': 'goku', '極': 'goku', 'ziya': 'ziya', '紫雅': 'ziya', '紫': 'ziya', 'fenya': 'fenya', '粉雅': 'fenya', '粉': 'fenya', 'jinya': 'jinya', '金雅': 'jinya', '金': 'jinya', 'fc': FULL_COMBO_TARGET, 'fullcombo': FULL_COMBO_TARGET, 'full_combo': FULL_COMBO_TARGET, '全连': FULL_COMBO_TARGET, '全連': FULL_COMBO_TARGET, 'df': DONDAFUL_TARGET, 'dondaful': DONDAFUL_TARGET, 'allgood': DONDAFUL_TARGET, '全良': DONDAFUL_TARGET}
_TARGET_ALIAS_KEYS_SORTED = sorted(_TARGET_ALIASES.keys(), key=len, reverse=True)
_STAR_FILTER_ALIASES: Dict[str, str] = {'1': '1', '一': '1', '2': '2', '二': '2', '3': '3', '三': '3', '4': '4', '四': '4', '5': '5', '五': '5', '6': '6', '六': '6', '7': '7', '七': '7', '8': '8', '八': '8', '9': '9', '九': '9', '10': '10', '十': '10'}
PROFILE_KEYS = ('rating', 'const', 'big_song', 'stamina', 'speed', 'accuracy_power', 'rhythm', 'complex_proc')
SCORE_TARGET_DIM_WEIGHTS = {'big_song': 0.85, 'stamina': 1.0, 'speed': 1.1, 'accuracy_power': 0.95, 'rhythm': 1.0, 'complex_proc': 1.0}
FULL_COMBO_DIM_WEIGHTS = {'big_song': 0.55, 'stamina': 0.7, 'speed': 1.2, 'accuracy_power': 0.6, 'rhythm': 0.85, 'complex_proc': 1.2}
DONDAFUL_DIM_WEIGHTS = {'big_song': 0.55, 'stamina': 0.55, 'speed': 0.75, 'accuracy_power': 1.35, 'rhythm': 1.2, 'complex_proc': 0.9}

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

def _mean(values: Iterable[float]) -> float:
    items = [float(value) for value in values if math.isfinite(float(value))]
    return sum(items) / len(items) if items else 0.0

def _target_accuracy_hint(target_key: str) -> float:
    if target_key == 'goku':
        return 0.985
    if target_key == 'ziya':
        return 0.97
    if target_key == 'fenya':
        return 0.95
    if target_key == 'jinya':
        return 0.91
    if target_key == FULL_COMBO_TARGET:
        return 0.935
    if target_key == DONDAFUL_TARGET:
        return 0.995
    return 0.95

def _candidate_dimensions(chart: Dict[str, Any], rating_row: Dict[str, Any], const_table: List[Tuple[float, float]], target_key: str) -> Dict[str, float]:
    const_value = _safe_float(rating_row.get('score'), 0.0)
    const_score = lookup_const_score(const_value, const_table)
    accuracy = calc_y(_target_accuracy_hint(target_key), normalization_factor=15.5, algorithm='comprehensive')
    metrics = compute_AD_AE_AF_AG(rating_row)
    p_param = compute_P(const_score, accuracy)
    q_weight = compute_Q(const_score, accuracy)
    rating = compute_AI(const_score, accuracy, p_param, q_weight)
    dims = compute_six_dims(rating, const_score, accuracy, metrics)
    dims['rating'] = float(rating)
    dims['const'] = float(const_value)
    dims['max_combo'] = float(_safe_int(chart.get('max_combo'), 0))
    return dims

def _profile_weights(target_key: str) -> Dict[str, float]:
    if target_key == FULL_COMBO_TARGET:
        return FULL_COMBO_DIM_WEIGHTS
    if target_key == DONDAFUL_TARGET:
        return DONDAFUL_DIM_WEIGHTS
    return SCORE_TARGET_DIM_WEIGHTS

def _profile_match_score(user_profile: Dict[str, float], candidate_dims: Dict[str, float], target_key: str) -> float:
    weights = _profile_weights(target_key)
    total = 0.0
    total_weight = 0.0
    for key, weight in weights.items():
        user_value = max(0.8, _safe_float(user_profile.get(key), 0.0))
        candidate_value = max(0.0, _safe_float(candidate_dims.get(key), 0.0))
        if candidate_value <= user_value:
            dim_score = 1.0 - (user_value - candidate_value) / max(user_value, 1.0) * 0.22
        else:
            dim_score = 1.0 - (candidate_value - user_value) / max(user_value * 0.8, 1.4) * 0.55
        total += _clamp(dim_score, 0.0, 1.0) * weight
        total_weight += weight
    rating_gap = max(0.0, _safe_float(candidate_dims.get('rating'), 0.0) - _safe_float(user_profile.get('rating'), 0.0))
    const_gap = max(0.0, _safe_float(candidate_dims.get('const'), 0.0) - _safe_float(user_profile.get('const'), 0.0))
    penalty = min(18.0, rating_gap * 2.6 + const_gap * 3.2)
    return _clamp(total / max(total_weight, 1e-06) * 100.0 - penalty, 0.0, 100.0)

def _format_gap_text(target_key: str, chart: Dict[str, Any], entry: Optional[Dict[str, Any]]) -> Tuple[str, Optional[int], float]:
    max_combo = _safe_int(chart.get('max_combo'), 0)
    if target_key in SCORE_TARGETS:
        target_score = _safe_int((chart.get('rating_scores') or {}).get(target_key), 0)
        current_score = _safe_int(entry.get('high_score'), 0) if entry else 0
        gap = max(0, target_score - current_score)
        progress = current_score / max(target_score, 1)
        text = f'-{gap}' if current_score else f'差{gap}'
        return (text, target_score, _clamp(progress, 0.0, 1.05))
    if target_key == FULL_COMBO_TARGET:
        combo = _safe_int(entry.get('combo_cnt'), 0) if entry else 0
        if combo <= 0 or max_combo <= 0:
            return ('未游玩', None, 0.0)
        remain = max(0, max_combo - combo)
        return (f'剩{remain}连', None, _clamp(combo / max(max_combo, 1), 0.0, 1.0))
    good_cnt = _safe_int(entry.get('good_cnt'), 0) if entry else 0
    if good_cnt <= 0 or max_combo <= 0:
        return ('未游玩', None, 0.0)
    remain = max(0, max_combo - good_cnt)
    return (f'剩{remain}良', None, _clamp(good_cnt / max(max_combo, 1), 0.0, 1.0))

def _achieved_target(target_key: str, chart: Dict[str, Any], entry: Optional[Dict[str, Any]]) -> bool:
    if entry is None:
        return False
    if target_key in SCORE_TARGETS:
        target_score = _safe_int((chart.get('rating_scores') or {}).get(target_key), 0)
        return _safe_int(entry.get('high_score'), 0) >= target_score > 0
    if target_key == FULL_COMBO_TARGET:
        return _safe_int(entry.get('full_combo_cnt'), 0) > 0 or _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0
    return _safe_int(entry.get('dondaful_combo_cnt'), 0) > 0

def _target_text(target_key: str, chart: Dict[str, Any]) -> str:
    if target_key in SCORE_TARGETS:
        return str(_safe_int((chart.get('rating_scores') or {}).get(target_key), 0))
    return TARGET_DISPLAY[target_key]

def _build_row(chart: Dict[str, Any], star_value: str, entry: Optional[Dict[str, Any]], candidate_dims: Dict[str, float], user_profile: Dict[str, float], target_key: str) -> Dict[str, Any]:
    gap_text, target_score, progress = _format_gap_text(target_key, chart, entry)
    profile_score = _profile_match_score(user_profile, candidate_dims, target_key)
    current_score = _safe_int(entry.get('high_score'), 0) if entry else None
    progress_bonus = progress * (22.0 if target_key in SCORE_TARGETS else 28.0)
    missing_penalty = 0.0 if entry else 7.5
    rec_index = _clamp(profile_score + progress_bonus - missing_penalty, 0.0, 100.0)
    song_id = _safe_int(chart.get('id'), 0)
    level = _safe_int(chart.get('level'), 4)
    title = str(chart.get('title_cn') or chart.get('title_jp') or chart.get('title') or f'ID{song_id}').strip()
    return {'song_id': song_id, 'level': level, 'star': star_value, 'title': title, 'score': current_score if current_score else None, 'target_text': _target_text(target_key, chart), 'gap_text': gap_text, 'recommend_index': rec_index, 'profile_match': profile_score, 'progress': progress, 'target_score': target_score or 0, 'candidate_rating': _safe_float(candidate_dims.get('rating'), 0.0)}

def build_user_profile(results) -> Dict[str, float]:
    results.sort(key=lambda item: float(item.AI_rating), reverse=True)
    top = results[:20]
    if not top:
        return {key: 0.0 for key in PROFILE_KEYS}
    return {'rating': _mean((item.AI_rating for item in top)), 'const': _mean((item.const_value for item in top)), 'big_song': _mean((item.big_song for item in top)), 'stamina': _mean((item.stamina for item in top)), 'speed': _mean((item.speed for item in top)), 'accuracy_power': _mean((item.accuracy_power for item in top)), 'rhythm': _mean((item.rhythm for item in top)), 'complex_proc': _mean((item.complex_proc for item in top))}
