from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from .support import safe_int, normalize_title_key, song_data_title_key, chart_title_key, rating_feature_from_raw, _format_song_star, _is_double_chart
from ..chart.identity import duplicate_identity_key, duplicate_identity_key_by_title

def rating_features(payload) -> Dict[Tuple[int, int], Dict[str, float]]:
    songs = payload.get('songs') if isinstance(payload, dict) else None
    if not isinstance(songs, dict):
        return {}
    features: Dict[Tuple[int, int], Dict[str, float]] = {}
    for raw in songs.values():
        if not isinstance(raw, dict):
            continue
        song_id = safe_int(raw.get('id'), -1)
        level = safe_int(raw.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        features[song_id, level] = rating_feature_from_raw(raw)
    return features

def rating_features_by_title_level(payload) -> Dict[Tuple[str, int], Dict[str, float]]:
    songs = payload.get('songs') if isinstance(payload, dict) else None
    if not isinstance(songs, dict):
        return {}
    features: Dict[Tuple[str, int], Dict[str, float]] = {}
    for raw in songs.values():
        if not isinstance(raw, dict):
            continue
        level = safe_int(raw.get('level'), -1)
        if level not in (4, 5):
            continue
        title_key = normalize_title_key(raw.get('song_name_cn') or raw.get('song_name') or raw.get('曲名') or raw.get('title_cn') or raw.get('title'))
        if not title_key:
            continue
        feature = rating_feature_from_raw(raw)
        key = (title_key, level)
        current = features.get(key)
        if current is None or feature.get('const', 0.0) > current.get('const', 0.0):
            features[key] = feature
    return features

def song_title_keys(payload) -> Dict[int, str]:
    if not isinstance(payload, list):
        return {}
    keys: Dict[int, str] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        song_id = safe_int(raw.get('id'), -1)
        if song_id < 0:
            continue
        title_key = song_data_title_key(raw)
        if title_key:
            keys[song_id] = title_key
    return keys

def song_star_map(payload) -> Dict[Tuple[int, int], str]:
    if not isinstance(payload, list):
        return {}
    star_map: Dict[Tuple[int, int], str] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        song_id = safe_int(raw.get('id'), -1)
        if song_id < 0:
            continue
        for level in (4, 5):
            star = _format_song_star(raw.get(f'level_{level}'))
            if star != '-':
                star_map[song_id, level] = star
    return star_map

def candidate_charts(payload, *, cn_available_keys, on_shelf_ids, groups_by_id, groups_by_title) -> List[Dict[str, Any]]:
    if not isinstance(payload, list):
        return []
    charts: List[Dict[str, Any]] = []
    seen: set[Tuple[str, int, int] | Tuple[str, str, int]] = set()
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        song_id = safe_int(raw.get('id'), -1)
        level = safe_int(raw.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        if cn_available_keys:
            if (song_id, level) not in cn_available_keys:
                continue
        elif on_shelf_ids and song_id not in on_shelf_ids:
            continue
        if _is_double_chart(raw):
            continue
        title_key = chart_title_key(raw) or ''
        key = duplicate_identity_key(song_id, level, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
        if title_key:
            key = duplicate_identity_key_by_title(title_key, level, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
        if key in seen:
            continue
        seen.add(key)
        charts.append(raw)
    return charts
