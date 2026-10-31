from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from .client import TARGET_DISPLAY, _safe_int, _safe_float, _achieved_target, _candidate_dimensions, _build_row
from ..rating.v1 import build_const_table
from ..chart.identity import normalize_song_title, duplicate_identity_key, default_song_id_for_query

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

def _userdata_records(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    records = payload.get('songs')
    return records if isinstance(records, list) else []

def build_song_maps(song_rows) -> Tuple[Dict[int, Dict[str, Any]], Dict[Tuple[int, int], str]]:
    by_id: Dict[int, Dict[str, Any]] = {}
    star_map: Dict[Tuple[int, int], str] = {}
    for row in song_rows:
        if not isinstance(row, dict):
            continue
        song_id = _safe_int(row.get('id'), -1)
        if song_id < 0 or row.get('shelf_status') in (1, '1', '已下架'):
            continue
        by_id[song_id] = row
        for level in (4, 5):
            raw_star = row.get(f'level_{level}')
            if raw_star is None:
                continue
            if isinstance(raw_star, str):
                text = raw_star.strip()
                if not text or text == '-':
                    continue
                star_map[song_id, level] = text
            else:
                star_value = _safe_float(raw_star, -1.0)
                if star_value < 0:
                    continue
                star_map[song_id, level] = str(int(star_value)) if float(star_value).is_integer() else str(star_value)
    return (by_id, star_map)

def build_rating_lookup(config) -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[Tuple[str, int], Dict[str, Any]], List[Tuple[float, float]]]:
    const_table = build_const_table(config['const_table']['const_to_score'])
    songs = config.get('songs', {})
    if isinstance(songs, dict):
        rows = list(songs.values())
    else:
        rows = songs if isinstance(songs, list) else []
    by_id_level: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_title_level: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        song_id = _safe_int(row.get('id'), -1)
        level = _safe_int(row.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        by_id_level[song_id, level] = row
        title_key = normalize_song_title(row.get('song_name_cn') or row.get('song_name') or row.get('曲名') or row.get('title'))
        if title_key:
            current = by_title_level.get((title_key, level))
            if current is None or _safe_float(row.get('score'), 0.0) > _safe_float(current.get('score'), 0.0):
                by_title_level[title_key, level] = row
    return (by_id_level, by_title_level, const_table)

def build_best_entry_map(records: Iterable[Dict[str, Any]], *, groups_by_id, groups_by_title) -> Dict[Tuple[str, int, int], Dict[str, Any]]:
    best: Dict[Tuple[str, int, int], Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        song_id = _safe_int(record.get('song_no'), -1)
        level = _safe_int(record.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        key = duplicate_identity_key(song_id, level, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
        current = best.get(key)
        if current is None or (_safe_int(record.get('dondaful_combo_cnt'), 0), _safe_int(record.get('full_combo_cnt'), 0), _safe_int(record.get('high_score'), 0)) > (_safe_int(current.get('dondaful_combo_cnt'), 0), _safe_int(current.get('full_combo_cnt'), 0), _safe_int(current.get('high_score'), 0)):
            best[key] = record
    return best

def select_target_recommendations(userdata, target_key, *, star_filter: str | None=None, user_profile, best_map, song_maps, rating_lookup, scoreline_rows, groups_by_id, groups_by_title) -> TargetRecommendationResult:
    records = _userdata_records(userdata)
    if not records:
        return TargetRecommendationResult(target_key=target_key, target_display=TARGET_DISPLAY[target_key], rows=[], candidate_count=0, required_count=20, is_enough=False, message='暂无可用成绩数据，请先更新后再试。', userdata=userdata)
    song_rows_by_id, star_map = song_maps
    rating_by_id_level, rating_by_title_level, const_table = rating_lookup
    rows: List[Dict[str, Any]] = []
    for chart in scoreline_rows:
        song_id = _safe_int(chart.get('id'), -1)
        level = _safe_int(chart.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        default_id = default_song_id_for_query(song_id, title=str(chart.get('title_cn') or chart.get('title_jp') or chart.get('title') or ''), groups_by_id=groups_by_id, groups_by_title=groups_by_title)
        song_meta = song_rows_by_id.get(default_id or song_id)
        if song_meta is not None and song_meta.get('shelf_status') in (1, '1', '已下架'):
            continue
        star_value = star_map.get((default_id or song_id, level)) or star_map.get((song_id, level)) or '-'
        if star_filter and star_value != star_filter:
            continue
        rating_row = rating_by_id_level.get((default_id or song_id, level))
        if rating_row is None:
            title_key = normalize_song_title(chart.get('title_cn') or chart.get('title_jp') or chart.get('title'))
            rating_row = rating_by_title_level.get((title_key, level))
        if rating_row is None:
            continue
        entry = best_map.get(duplicate_identity_key(default_id or song_id, level, groups_by_id=groups_by_id, groups_by_title=groups_by_title))
        if _achieved_target(target_key, chart, entry):
            continue
        candidate_dims = _candidate_dimensions(chart, rating_row, const_table, target_key)
        row = _build_row(chart, star_value, entry, candidate_dims, user_profile, target_key)
        rows.append(row)
    rows.sort(key=lambda row: (-_safe_float(row.get('recommend_index'), 0.0), -_safe_float(row.get('profile_match'), 0.0), -_safe_float(row.get('progress'), 0.0), _safe_float(row.get('candidate_rating'), 0.0), _safe_int(row.get('song_id'), 10 ** 9)))
    limited_rows = rows[:20]
    if not limited_rows:
        message = '当前条件下没有找到合适的候选曲目。'
    elif len(rows) < 20:
        message = f'已找到 {len(rows)} 首候选曲目。'
    else:
        message = f'已找到 {len(rows)} 首候选曲目，返回前 20 首。'
    return TargetRecommendationResult(target_key=target_key, target_display=TARGET_DISPLAY[target_key], rows=limited_rows, candidate_count=len(rows), required_count=20, is_enough=bool(limited_rows), message=message, userdata=userdata)
