from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from .visibility import is_song_publicly_visible

_MISSING_SORT = 10 ** 9

@dataclass(frozen=True)
class PositionResult:
    song_id: int
    title: str
    song_type: str
    rank: Optional[int]
    total_on_shelf: int
    sort: int
    is_on_shelf: bool

def _to_int(value: Any, default: int=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

def _is_on_shelf(item: Dict[str, Any]) -> bool:
    status = item.get('shelf_status', 0)
    if status is None or status == '':
        return True
    try:
        return int(status) == 0
    except (TypeError, ValueError):
        return str(status).strip() in {'0', '未下架'}

def _song_title(item: Dict[str, Any]) -> str:
    song_id = _to_int(item.get('id'), 0)
    return str(item.get('song_name') or item.get('song_name_jp') or f'ID{song_id}').strip()

def _sort_key(item: Dict[str, Any]) -> Tuple[int, int]:
    return (_to_int(item.get('sort'), _MISSING_SORT), _to_int(item.get('id'), 0))

def build_song_catalog(raw, *, profile='position-center-20261010') -> Tuple[Dict[int, Dict[str, Any]], Dict[str, List[Dict[str, Any]]], Dict[str, int]]:
    if profile not in {'position-center-20261010', 'position-client-20261010'}:
        raise ValueError('unknown position profile')
    if not isinstance(raw, list):
        return ({}, {}, {})
    id_index: Dict[int, Dict[str, Any]] = {}
    type_buckets: Dict[str, List[Dict[str, Any]]] = {}
    for item in raw:
        if not isinstance(item, dict):
            continue
        song_id = _to_int(item.get('id'), -1)
        if song_id < 0:
            continue
        id_index[song_id] = item
        song_type = str(item.get('type') or '-').strip() or '-'
        if is_song_publicly_visible(item) if profile == 'position-client-20261010' else _is_on_shelf(item):
            type_buckets.setdefault(song_type, []).append(item)
    type_on_shelf_lists: Dict[str, List[Dict[str, Any]]] = {}
    type_totals: Dict[str, int] = {}
    for song_type, items in type_buckets.items():
        ordered = sorted(items, key=_sort_key)
        type_on_shelf_lists[song_type] = ordered
        type_totals[song_type] = len(ordered)
    return (id_index, type_on_shelf_lists, type_totals)

def get_song_position_by_id(song_id: int, *, catalog, profile='position-center-20261010') -> Optional[PositionResult]:
    if profile not in {'position-center-20261010', 'position-client-20261010'}:
        raise ValueError('unknown position profile')
    id_index, type_lists, type_totals = catalog
    item = id_index.get(int(song_id))
    if not item:
        return None
    if profile == 'position-client-20261010' and not is_song_publicly_visible(item):
        return None
    song_type = str(item.get('type') or '-').strip() or '-'
    on_shelf = True if profile == 'position-client-20261010' else _is_on_shelf(item)
    total_on_shelf = type_totals.get(song_type, 0)
    rank: Optional[int] = None
    if on_shelf:
        ordered = type_lists.get(song_type, [])
        for idx, candidate in enumerate(ordered):
            if _to_int(candidate.get('id')) == int(song_id):
                rank = idx + 1
                break
    return PositionResult(song_id=int(song_id), title=_song_title(item), song_type=song_type, rank=rank, total_on_shelf=total_on_shelf, sort=_to_int(item.get('sort'), 0), is_on_shelf=on_shelf)
