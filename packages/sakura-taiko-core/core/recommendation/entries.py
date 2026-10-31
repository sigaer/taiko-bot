from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from .support import safe_int
from ..chart.catalog import _get_recommend_identity_key

def build_best_entry_map(records: Iterable[Dict[str, Any]], *, default_ids=None) -> Dict[Tuple[int, int], Dict[str, Any]]:
    best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    deduped: Dict[Tuple[str, int, int] | Tuple[str, str, int], Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        song_id = safe_int(record.get('song_no'), -1)
        level = safe_int(record.get('level'), -1)
        if song_id < 0 or level not in (4, 5):
            continue
        score = safe_int(record.get('high_score'), 0)
        key = (song_id, level)
        current = best.get(key)
        if current is None or score > safe_int(current.get('high_score'), 0):
            best[key] = record
        identity = _get_recommend_identity_key(song_id, level, default_ids=default_ids)
        current_group = deduped.get(identity)
        if current_group is None or score > safe_int(current_group.get('high_score'), 0):
            deduped[identity] = record
    grouped_best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for record in deduped.values():
        grouped_best[safe_int(record.get('song_no'), -1), safe_int(record.get('level'), -1)] = record
    return grouped_best

def resolve_chart_feature(*, song_id: int, level: int, title_key: str, features_by_key: Dict[Tuple[int, int], Dict[str, float]], features_by_title_level: Dict[Tuple[str, int], Dict[str, float]]) -> Optional[Dict[str, float]]:
    feature = features_by_key.get((song_id, level))
    if feature is not None:
        return feature
    if title_key:
        return features_by_title_level.get((title_key, level))
    return None

def resolve_best_entry_for_chart(best_map: Dict[Tuple[int, int], Dict[str, Any]], *, song_id: int, level: int, title_key: str, title_keys_by_id: Dict[int, str], default_ids=None) -> Optional[Dict[str, Any]]:
    entry = best_map.get((song_id, level))
    if entry is not None:
        return entry
    target_identity = _get_recommend_identity_key(song_id, level, default_ids=default_ids)
    best_entry: Optional[Dict[str, Any]] = None
    best_score = -1
    for (candidate_id, candidate_level), record in best_map.items():
        if candidate_level != level:
            continue
        candidate_title_key = title_keys_by_id.get(candidate_id, '')
        if _get_recommend_identity_key(candidate_id, candidate_level, default_ids=default_ids) != target_identity:
            if not title_key or candidate_title_key != title_key:
                continue
        score = safe_int(record.get('high_score'), 0)
        if score > best_score:
            best_score = score
            best_entry = record
    return best_entry
