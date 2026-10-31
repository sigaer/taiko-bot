from __future__ import annotations
import math
from dataclasses import dataclass
from datetime import date, datetime
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple
from ..models.calculation import SongMetrics, RatingResult, SongStats
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table, _calc_accuracy_for_record, aggregate_topN_value
from ..dimension.v1 import compute_AD_AE_AF_AG, compute_six_dims

def safe_int(value: Any, default: int=0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def safe_float(value: Any, default: float=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))

def normalize_title_key(value: Any) -> str:
    text = str(value or '').strip()
    if not text:
        return ''
    text = text.replace('（', '(').replace('）', ')')
    for suffix in ('(里谱)', '(裏譜)', '(裏)', '(ura)'):
        if text.casefold().endswith(suffix.casefold()):
            text = text[:-len(suffix)].strip()
            break
    return ' '.join(text.casefold().split())

def chart_title_key(chart: Dict[str, Any]) -> str:
    return normalize_title_key(chart.get('title_cn') or chart.get('title_jp') or chart.get('title'))

def song_data_title_key(song: Dict[str, Any]) -> str:
    return normalize_title_key(song.get('song_name') or song.get('song_name_cn') or song.get('song_name_jp') or song.get('title_cn') or song.get('title_jp') or song.get('title'))

def rating_feature_from_raw(raw: Dict[str, Any]) -> Dict[str, float]:
    metrics = compute_AD_AE_AF_AG(raw)
    return {'const': safe_float(raw.get('score'), 0.0), 'stamina': clamp(metrics.stamina, 0.0, 100.0), 'speed': clamp(metrics.speed, 0.0, 100.0), 'rhythm': clamp(metrics.rhythm, 0.0, 100.0), 'complex': clamp(metrics.complex_proc, 0.0, 100.0), 'hs_change': clamp(safe_float(raw.get('HS变化', raw.get('hs_change')), 0.0), 0.0, 100.0)}

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

def build_played_title_level_keys(records: Iterable[Dict[str, Any]], title_keys_by_id: Dict[int, str]) -> set[Tuple[str, int]]:
    played: set[Tuple[str, int]] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        song_id = safe_int(record.get('song_no'), -1)
        level = safe_int(record.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        title_key = title_keys_by_id.get(song_id, '')
        if title_key:
            played.add((title_key, level))
    return played

def entry_age_days(entry: Optional[Dict[str, Any]], *, today: date) -> Optional[int]:
    if not isinstance(entry, dict):
        return None
    raw_value = entry.get('update_datetime') or entry.get('highscore_datetime')
    if raw_value is None:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    candidates = [text]
    trimmed = text[:19].replace('T', ' ')
    if trimmed and trimmed not in candidates:
        candidates.append(trimmed)
    replaced = text.replace('T', ' ')
    if replaced and replaced not in candidates:
        candidates.append(replaced)
    for candidate in candidates:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y/%m/%d %H:%M:%S', '%Y-%m-%d', '%Y/%m/%d'):
            try:
                parsed = datetime.strptime(candidate, fmt)
            except ValueError:
                continue
            return max(0, (today - parsed.date()).days)
    iso_candidate = text.replace('Z', '+00:00')
    try:
        parsed = datetime.fromisoformat(iso_candidate)
    except ValueError:
        return None
    return max(0, (today - parsed.date()).days)

def played_score_freshness_weight(age_days: Optional[int]) -> float:
    if age_days is None or age_days > 365:
        return 0.0
    if age_days <= 30:
        return 1.0
    if age_days <= 90:
        return 0.75
    if age_days <= 180:
        return 0.45
    return clamp(0.45 * (365 - age_days) / (365 - 180), 0.0, 0.45)
