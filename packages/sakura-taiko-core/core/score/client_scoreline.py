from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from .scoreline import RATING_CONFIG, _RATING_ALIAS_TO_KEY, _SORTED_RATING_ALIASES, _safe_int, _safe_float, _score_target_map, _extract_roll_times, _extract_balloons

_DIFF_PREFIXES = [('里谱', 5, '里谱'), ('里', 5, '里谱'), ('鬼', 4, '表谱'), ('魔王', 4, '表谱'), ('表谱', 4, '表谱'), ('表', 4, '表谱'), ('松', 3, '松谱'), ('困难', 3, '松谱')]

@dataclass(frozen=True)
class ScoreLineRequest:
    rating_key: str
    rating_display: str
    song_query: str
    speed_ips: float
    level: int
    level_label: str

def _normalize_title(text: str) -> str:
    normalized = str(text or '').strip()
    normalized = normalized.replace('〜', '～')
    normalized = normalized.replace('~', '～')
    for src in ('‐', '‑', '‒', '–', '—', '―', '－', 'ｰ'):
        normalized = normalized.replace(src, '-')
    normalized = normalized.replace('【限定】', '')
    normalized = normalized.replace('(裏)', '')
    normalized = normalized.replace('(裏譜面)', '')
    normalized = re.sub('\\s+', '', normalized)
    return normalized.lower()

def build_scoreline_dataset(score_rows, roll_rows, song_rows) -> Tuple[int, int]:
    roll_by_id: Dict[int, Dict[str, Any]] = {}
    roll_by_title: Dict[str, Dict[str, Any]] = {}
    for row in roll_rows:
        song_id = _safe_int(row.get('id'), -1)
        if song_id >= 0:
            roll_by_id[song_id] = row
        for key in (row.get('song_name_jp'), row.get('song_name')):
            normalized = _normalize_title(str(key or ''))
            if normalized and normalized not in roll_by_title:
                roll_by_title[normalized] = row
    song_by_id: Dict[int, Dict[str, Any]] = {}
    song_by_title: Dict[str, Dict[str, Any]] = {}
    for row in song_rows:
        song_id = _safe_int(row.get('id'), -1)
        if song_id >= 0:
            song_by_id[song_id] = row
        for key in (row.get('song_name_jp'), row.get('song_name')):
            normalized = _normalize_title(str(key or ''))
            if normalized and normalized not in song_by_title:
                song_by_title[normalized] = row
    merged: List[Dict[str, Any]] = []
    matched_count = 0
    for row in score_rows:
        level = _safe_int(row.get('level'), 4)
        base_title = str(row.get('title') or '').strip()
        normalized_title = _normalize_title(base_title)
        resolved_id = row.get('id')
        roll_row: Optional[Dict[str, Any]] = None
        song_row: Optional[Dict[str, Any]] = None
        match_source = 'none'
        if resolved_id is not None and str(resolved_id).isdigit():
            resolved_id = int(resolved_id)
            roll_row = roll_by_id.get(resolved_id)
            song_row = song_by_id.get(resolved_id)
            if roll_row or song_row:
                match_source = 'id'
        else:
            resolved_id = None
        if roll_row is None:
            roll_row = roll_by_title.get(normalized_title)
            if roll_row is not None:
                match_source = 'title'
        if song_row is None:
            song_row = song_by_title.get(normalized_title)
            if song_row is not None and match_source == 'none':
                match_source = 'title'
        if resolved_id is None:
            if roll_row is not None:
                resolved_id = _safe_int(roll_row.get('id'), None)
            elif song_row is not None:
                resolved_id = _safe_int(song_row.get('id'), None)
        if match_source != 'none':
            matched_count += 1
        max_combo = _safe_int(row.get('max_combo'), 0)
        if max_combo <= 0 and roll_row is not None:
            combos = roll_row.get('max_combo')
            if isinstance(combos, list) and 1 <= level <= len(combos):
                max_combo = _safe_int(combos[level - 1], 0)
        title_jp = str((song_row or {}).get('song_name_jp') or (roll_row or {}).get('song_name_jp') or base_title).strip()
        title_cn = str((song_row or {}).get('song_name') or (roll_row or {}).get('song_name') or title_jp).strip()
        initial_points = _safe_int(row.get('initial_points'), 0)
        ok_points = initial_points // 2 // 10 * 10
        goku_score = _safe_int(row.get('goku_score'), 0)
        roll_times = _extract_roll_times(roll_row, level)
        balloons = _extract_balloons(roll_row, level)
        merged.append({'id': resolved_id, 'title': base_title, 'title_jp': title_jp, 'title_cn': title_cn, 'level': level, 'difficulty_label': '里谱' if level == 5 else '表谱', 'tenjo_score': _safe_int(row.get('tenjo_score'), 0), 'goku_score': goku_score, 'rating_scores': _score_target_map(goku_score), 'roll_required': _safe_int(row.get('roll_required'), 0), 'roll_speed_ips': row.get('roll_speed_ips'), 'max_combo': max_combo, 'initial_points': initial_points, 'ok_points': ok_points, 'selected_version': row.get('selected_version'), 'roll_times': roll_times, 'roll_total_seconds': round(sum(roll_times), 6), 'balloons': balloons, 'balloon_hits': sum(balloons), 'match_source': match_source})
    return (merged, matched_count)

def build_chart_index(rows) -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[Tuple[str, int], List[Dict[str, Any]]]]:
    by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in rows:
        song_id = row.get('id')
        level = _safe_int(row.get('level'), 4)
        if song_id is not None:
            try:
                by_id[int(song_id), level] = row
            except Exception:
                pass
        for key in (row.get('title'), row.get('title_jp'), row.get('title_cn')):
            normalized = _normalize_title(str(key or ''))
            if not normalized:
                continue
            by_title.setdefault((normalized, level), []).append(row)
    return (by_id, by_title)

def get_scoreline_entry(song_id: Optional[int], level: int, fallback_title: str='', *, by_id, by_title) -> Optional[Dict[str, Any]]:
    if song_id is not None:
        row = by_id.get((song_id, level))
        if row is not None:
            return row
    normalized = _normalize_title(fallback_title)
    if not normalized:
        return None
    rows = by_title.get((normalized, level), [])
    if len(rows) == 1:
        return rows[0]
    return None

def available_levels_for_song(song_id: Optional[int], fallback_title: str='', *, by_id, by_title) -> List[int]:
    levels = set()
    if song_id is not None:
        for key in by_id:
            if key[0] == song_id:
                levels.add(key[1])
    normalized = _normalize_title(fallback_title)
    if normalized:
        for key in by_title:
            if key[0] == normalized:
                levels.add(key[1])
    return sorted(levels)

def parse_scoreline_request(text: str) -> ScoreLineRequest:
    compact = str(text or '').strip()
    match = re.match('^分数线\\s+(.+?)\\s+(-?[0-9]+)\\s*$', compact)
    if not match:
        raise ValueError('用法：分数线 [评价名] [里/表/松]歌曲别名 [连打秒速整数]')
    spec = re.sub('\\s+', ' ', match.group(1).strip())
    speed_ips = float(match.group(2))
    if speed_ips < 0 or speed_ips > 60:
        raise ValueError('？')
    rating_key: Optional[str] = None
    for alias in _SORTED_RATING_ALIASES:
        if spec.startswith(alias):
            rating_key = _RATING_ALIAS_TO_KEY[alias]
            spec = spec[len(alias):].strip()
            break
    if rating_key is None:
        for alias in _SORTED_RATING_ALIASES:
            if spec.endswith(alias):
                rating_key = _RATING_ALIAS_TO_KEY[alias]
                spec = spec[:-len(alias)].strip()
                break
    if rating_key is None:
        raise ValueError('评价名仅支持：极、紫雅、粉雅、金雅、银粹、铜粹、白粹。')
    if not spec:
        raise ValueError('请在评价名后提供歌曲别名或id。')
    level = 4
    level_label = '表谱'
    for prefix, diff_level, diff_label in _DIFF_PREFIXES:
        if spec.startswith(prefix):
            level = diff_level
            level_label = diff_label
            spec = spec[len(prefix):].strip()
            break
    if not spec:
        raise ValueError('请在难度前缀后提供歌曲别名或id。')
    return ScoreLineRequest(rating_key=rating_key, rating_display=str(RATING_CONFIG[rating_key]['display']), song_query=spec, speed_ips=speed_ips, level=level, level_label=level_label)
