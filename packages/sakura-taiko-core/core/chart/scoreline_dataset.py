from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from ..score.scoreline import _safe_int, _normalize_title, _normalize_title_aggressive, _append_title_index, _pick_unique_candidate, deduplicate_scoreline_rows, _extract_roll_times, _extract_balloons, _score_target_map, DIFFICULTY_LEVEL_LABELS, _prefer_scoreline_row
from .roll_metadata import resolve_chart_roll_metadata

def build_scoreline_dataset(score_rows, song_rows, stream_rows) -> Tuple[int, int]:
    score_rows = deduplicate_scoreline_rows(score_rows, song_rows)
    song_by_id: Dict[int, Dict[str, Any]] = {}
    song_by_title: Dict[str, List[Dict[str, Any]]] = {}
    song_by_title_aggressive: Dict[str, List[Dict[str, Any]]] = {}
    for row in song_rows:
        song_id = _safe_int(row.get('id'), -1)
        if song_id >= 0:
            song_by_id[song_id] = row
        for key in (row.get('song_name_jp'), row.get('song_name')):
            _append_title_index(song_by_title, key, row)
            _append_title_index(song_by_title_aggressive, key, row, aggressive=True)
    merged: List[Dict[str, Any]] = []
    matched_count = 0
    for row in score_rows:
        level = _safe_int(row.get('level'), 4)
        base_title = str(row.get('title') or '').strip()
        normalized_title = _normalize_title(base_title)
        normalized_title_aggressive = _normalize_title_aggressive(base_title)
        resolved_id = row.get('id')
        song_row: Optional[Dict[str, Any]] = None
        match_source = 'none'
        if resolved_id is not None and str(resolved_id).isdigit():
            resolved_id = int(resolved_id)
            song_row = song_by_id.get(resolved_id)
            if song_row:
                match_source = 'id'
        else:
            resolved_id = None
        if song_row is None:
            song_row = _pick_unique_candidate(song_by_title, normalized_title)
            if song_row is not None and match_source == 'none':
                match_source = 'title'
            elif normalized_title_aggressive:
                song_row = _pick_unique_candidate(song_by_title_aggressive, normalized_title_aggressive)
                if song_row is not None and match_source == 'none':
                    match_source = 'title_aggressive'
        if resolved_id is None:
            if song_row is not None:
                resolved_id = _safe_int(song_row.get('id'), None)
        if match_source != 'none':
            matched_count += 1
        max_combo = _safe_int(row.get('max_combo'), 0)
        if max_combo <= 0 and song_row is not None:
            combos = song_row.get('max_combo')
            if isinstance(combos, list) and 1 <= level <= len(combos):
                max_combo = _safe_int(combos[level - 1], 0)
        title_jp = str((song_row or {}).get('song_name_jp') or base_title).strip()
        title_cn = str((song_row or {}).get('song_name') or title_jp).strip()
        initial_points = _safe_int(row.get('initial_points'), 0)
        ok_points = initial_points // 2 // 10 * 10
        goku_score = _safe_int(row.get('goku_score'), 0)
        roll_times = _extract_roll_times(song_row, level)
        balloons = _extract_balloons(song_row, level)
        roll_times, balloons = resolve_chart_roll_metadata(_safe_int(resolved_id, -1), level, roll_times, balloons)
        merged_row = {'id': resolved_id, 'title': base_title, 'title_jp': title_jp, 'title_cn': title_cn, 'level': level, 'difficulty_label': DIFFICULTY_LEVEL_LABELS.get(level, f'level={level}'), 'tenjo_score': _safe_int(row.get('tenjo_score'), 0), 'goku_score': goku_score, 'rating_scores': _score_target_map(goku_score), 'roll_required': _safe_int(row.get('roll_required'), 0), 'roll_speed_ips': row.get('roll_speed_ips'), 'max_combo': max_combo, 'initial_points': initial_points, 'ok_points': ok_points, 'selected_version': row.get('selected_version'), 'roll_times': roll_times, 'roll_total_seconds': round(sum(roll_times), 6), 'balloons': balloons, 'balloon_hits': sum(balloons), 'match_source': match_source}
        merged.append(merged_row)
    stream_identity_keys = set()
    for row in stream_rows:
        if not isinstance(row, dict):
            continue
        level = _safe_int(row.get('level'), -1)
        song_id = _safe_int(row.get('id'), -1)
        if song_id >= 0:
            stream_identity_keys.add(('id', song_id, level))
        normalized_title = _normalize_title(str(row.get('title') or ''))
        if normalized_title:
            stream_identity_keys.add(('title', normalized_title, level))
    unknown_rows: List[Dict[str, Any]] = []
    for row in merged:
        level = _safe_int(row.get('level'), -1)
        song_id = _safe_int(row.get('id'), -1)
        normalized_title = _normalize_title(str(row.get('title') or ''))
        known = song_id >= 0 and ('id', song_id, level) in stream_identity_keys
        if not known and normalized_title:
            known = ('title', normalized_title, level) in stream_identity_keys
        if not known:
            unknown_rows.append(row)
    merged = [dict(row) for row in stream_rows if isinstance(row, dict)]
    merged.extend(unknown_rows)
    return (merged, matched_count)

def build_chart_index(rows) -> Tuple[Dict[Tuple[int, int], Dict[str, Any]], Dict[Tuple[str, int], List[Dict[str, Any]]]]:
    by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in rows:
        song_id = row.get('id')
        level = _safe_int(row.get('level'), 4)
        if song_id is not None:
            try:
                key = (int(song_id), level)
                by_id[key] = _prefer_scoreline_row(by_id.get(key), row)
            except Exception:
                pass
        for key in (row.get('title'), row.get('title_jp'), row.get('title_cn')):
            normalized = _normalize_title(str(key or ''))
            if not normalized:
                continue
            by_title.setdefault((normalized, level), []).append(row)
    return (by_id, by_title)

def get_scoreline_entry(song_id: Optional[int], level: int, fallback_title: str='', *, by_id, by_title, group_ids, default_id) -> Optional[Dict[str, Any]]:
    if song_id is not None:
        ordered_ids = sorted(set(group_ids), key=lambda value: (value != default_id, value))
        for candidate_id in ordered_ids:
            row = by_id.get((candidate_id, level))
            if row is not None:
                return row
    normalized = _normalize_title(fallback_title)
    if not normalized:
        return None
    rows = by_title.get((normalized, level), [])
    if rows:
        rows = sorted(rows, key=lambda row: (_safe_int(row.get('id'), 10 ** 9) != (default_id or -1), _safe_int(row.get('id'), 10 ** 9)))
        return rows[0]
    return None

def available_levels_for_song(song_id: Optional[int], fallback_title: str='', *, by_id, by_title, group_ids, default_id) -> List[int]:
    levels = set()
    if song_id is not None:
        for key in by_id:
            if key[0] in group_ids:
                levels.add(key[1])
    normalized = _normalize_title(fallback_title)
    if normalized:
        for key in by_title:
            if key[0] == normalized:
                levels.add(key[1])
    return sorted(levels)
