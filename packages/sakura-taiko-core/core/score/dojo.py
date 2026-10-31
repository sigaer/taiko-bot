from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

LEVEL_MARK_TO_ICON = {0: 1, 1: 2, 2: 4, 3: 6, 4: 3, 5: 5, 6: 7}

def _safe_int(value: Any, default: int=0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _safe_optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None

def level_mark_to_icon(level_mark: Any) -> int:
    numeric = _safe_optional_int(level_mark)
    if numeric is None or numeric < 0:
        return 1
    return LEVEL_MARK_TO_ICON.get(numeric, 1)

def _normalize_song_metrics(row: Dict[str, Any], prefix: str, index: int) -> Dict[str, Any]:
    return {'score': _safe_optional_int(row.get(f'{prefix}_play_score_{index}')), 'good': _safe_optional_int(row.get(f'{prefix}_good_cnt_{index}')), 'ok': _safe_optional_int(row.get(f'{prefix}_ok_cnt_{index}')), 'bad': _safe_optional_int(row.get(f'{prefix}_ng_cnt_{index}')), 'drumroll': _safe_optional_int(row.get(f'{prefix}_pound_cnt_{index}')), 'hit': _safe_optional_int(row.get(f'{prefix}_hit_cnt_{index}')), 'combo': _safe_optional_int(row.get(f'{prefix}_combo_cnt_{index}'))}

def normalize_dojo_scores(payload: Any, *, grade_names) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {'scores': [], 'levelList': []}
    if isinstance(payload.get('scores'), list):
        return {'scores': [item for item in payload.get('scores') or [] if isinstance(item, dict)], 'levelList': list(payload.get('levelList') or [])}
    raw = payload
    if isinstance(raw.get('data'), dict):
        raw = raw['data']
    if isinstance(raw.get('dojoScoreInfo'), dict):
        raw = raw['dojoScoreInfo']
    rows = raw.get('ary_player_dan_score') or []
    level_list = list(raw.get('levelList') or [])
    normalized_rows: List[Dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dan_id = _safe_int(row.get('dan_id'), 0)
        if dan_id <= 0:
            continue
        level_mark = None
        if 0 < dan_id <= len(level_list):
            level_mark = _safe_optional_int(level_list[dan_id - 1])
        highscore_dan_result = _safe_optional_int(row.get('highscore_dan_result'))
        if level_mark is None:
            level_mark = highscore_dan_result
        arrival_song_cnt = max(0, min(3, _safe_int(row.get('arrival_song_cnt'), 0)))
        songs: List[Dict[str, Any]] = []
        for index in range(1, 4):
            songs.append({'index': index, 'reached': index <= arrival_song_cnt, 'highscore': _normalize_song_metrics(row, 'highscore', index), 'odaibest': _normalize_song_metrics(row, 'odaibest', index)})
        normalized_rows.append({'dan_id': dan_id, 'grade': grade_names.get(dan_id, f'段位{dan_id}'), 'arrival_song_cnt': arrival_song_cnt, 'high_score': _safe_optional_int(row.get('high_score')), 'highscore_dan_result': highscore_dan_result, 'highscore_soul_gauge_total': _safe_optional_int(row.get('highscore_soul_gauge_total')), 'highscore_combo_cnt_total': _safe_optional_int(row.get('highscore_combo_cnt_total')), 'odaibest_soul_gauge_total': _safe_optional_int(row.get('odaibest_soul_gauge_total')), 'odaibest_combo_cnt_total': _safe_optional_int(row.get('odaibest_combo_cnt_total')), 'highscore_datetime': row.get('highscore_datetime'), 'update_datetime': row.get('update_datetime'), 'level_mark': level_mark, 'level_icon': level_mark_to_icon(level_mark), 'songs': songs})
    normalized_rows.sort(key=lambda item: int(item.get('dan_id') or 0))
    return {'scores': normalized_rows, 'levelList': level_list}

def build_dojo_score_map(payload: Any, *, grade_names) -> Dict[int, Dict[str, Any]]:
    dojo = normalize_dojo_scores(payload, grade_names=grade_names)
    return {int(item.get('dan_id') or 0): item for item in dojo.get('scores') or [] if isinstance(item, dict) and int(item.get('dan_id') or 0) > 0}
