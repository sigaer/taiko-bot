from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

LEVEL_STAR_FIELD = {1: 'level_1', 2: 'level_2', 3: 'level_3', 4: 'level_4', 5: 'level_5'}
STAR_PROGRESS_LEVELS = (4, 5)

@dataclass(frozen=True)
class ProgressChartItem:
    song_id: int
    level: int
    title: str

def _to_float(value: Any) -> float | None:
    try:
        if value in (None, '', '-'):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None

def _normalize_title(base_title: str, level: int) -> str:
    title = str(base_title or '').strip()
    if not title:
        return title
    if level == 5 and '里' not in title and ('裏' not in title):
        return f'{title}（里）'
    return title

def is_song_on_shelf(status: Any) -> bool:
    """与 score_calculator / 曲库其它模块保持一致的在架判定。"""
    return status not in (1, '1', '已下架')

def active_song_ids_from_index(song_index) -> Set[int]:
    active: Set[int] = set()
    for song_id, song in song_index.items():
        if not is_song_on_shelf(song.get('shelf_status')):
            continue
        active.add(song_id)
    return active

def _pick_title(song: Dict[str, Any] | None, chart: Dict[str, Any]) -> str:
    title = (chart.get('song_name_cn') or '').strip() or (song or {}).get('song_name', '') or (song or {}).get('song_name_jp', '') or chart.get('曲名', '') or f"ID{chart.get('id')}"
    level = int(chart.get('level', 4) or 4)
    return _normalize_title(str(title), level)

def _sort_items(items: Iterable[ProgressChartItem], *, catalog) -> List[ProgressChartItem]:
    song_index = catalog.song_index
    return sorted(items, key=lambda item: (int((song_index.get(item.song_id) or {}).get('sort', 10 ** 9) or 10 ** 9), item.song_id, item.level))

def _build_static_progress_title(song_id: int, level: int, progress_key: str, *, catalog) -> str:
    song = catalog.song_index.get(song_id)
    base_title = (song or {}).get('song_name') or (song or {}).get('song_name_jp') or f'ID{song_id}'
    title = _normalize_title(str(base_title), level)
    if song_id == 775:
        if progress_key == '10.1':
            title += '（普通谱面）'
        elif progress_key == '10.6':
            title += '（达人谱面）'
    elif song_id == 1037:
        if progress_key == '10.0':
            title += '（全普通）'
        elif progress_key == '10.4':
            title += '（全达人）'
    return title

def available_pass_progress_keys(*, catalog) -> Set[str]:
    active_song_ids = catalog.active_song_ids
    keys: Set[str] = set()
    for key, raw_items in catalog.static_progress_map.items():
        if not re.fullmatch('\\d+\\.\\d', key):
            continue
        for raw_id in raw_items:
            if not isinstance(raw_id, int):
                continue
            song_id = raw_id - 100000 if raw_id >= 100000 else raw_id
            if song_id in active_song_ids:
                keys.add(key)
                break
    return keys

def query_progress_items_by_pass_const(progress_key: str, *, catalog) -> List[ProgressChartItem]:
    if progress_key not in catalog.static_progress_map:
        return []
    active_song_ids = catalog.active_song_ids
    dedup: Dict[tuple[int, int], ProgressChartItem] = {}
    for raw_id in catalog.static_progress_map.get(progress_key, []):
        if not isinstance(raw_id, int):
            continue
        is_ura = raw_id >= 100000
        song_id = raw_id - 100000 if is_ura else raw_id
        level = 5 if is_ura else 4
        if song_id not in active_song_ids:
            continue
        key = (song_id, level)
        if key in dedup:
            continue
        dedup[key] = ProgressChartItem(song_id=song_id, level=level, title=_build_static_progress_title(song_id, level, progress_key, catalog=catalog))
    return _sort_items(dedup.values(), catalog=catalog)

def available_const_progress_keys(*, catalog) -> Set[str]:
    keys: Set[str] = set()
    active_song_ids = catalog.active_song_ids
    for chart in catalog.rating_entries:
        try:
            song_id = int(chart.get('id'))
        except (TypeError, ValueError):
            continue
        if song_id not in active_song_ids:
            continue
        const_value = _to_float(chart.get('score'))
        if const_value is None:
            continue
        keys.add(f'{const_value:.1f}')
    return keys

def query_progress_items_by_const(const_value: float, *, catalog) -> List[ProgressChartItem]:
    active_song_ids = catalog.active_song_ids
    song_index = catalog.song_index
    dedup: Dict[tuple[int, int], ProgressChartItem] = {}
    for chart in catalog.rating_entries:
        score = _to_float(chart.get('score'))
        if score is None or abs(score - const_value) >= 1e-06:
            continue
        try:
            song_id = int(chart.get('id'))
            level = int(chart.get('level'))
        except (TypeError, ValueError):
            continue
        if song_id not in active_song_ids:
            continue
        key = (song_id, level)
        if key in dedup:
            continue
        dedup[key] = ProgressChartItem(song_id=song_id, level=level, title=_pick_title(song_index.get(song_id), chart))
    return _sort_items(dedup.values(), catalog=catalog)

def load_star_progress_chart_keys(*, catalog) -> Set[tuple[int, int]]:
    """仅统计国行已上架、已实装的单人鬼/里谱，不纳入其他曲目。"""
    song_index = catalog.song_index
    if catalog.profile == 'progress-client-20261010':
        return {(song_id, level) for song_id in catalog.active_song_ids
                if song_index.get(song_id) for level in STAR_PROGRESS_LEVELS}
    if catalog.profile != 'progress-center-20261010':
        raise ValueError('unknown progress profile')
    keys: Set[tuple[int, int]] = set()
    for song_id, level in catalog.cn_available_chart_keys:
        if level not in STAR_PROGRESS_LEVELS:
            continue
        song = song_index.get(song_id)
        if not song or song.get('shelf_status') not in (None, 0, '0', '未下架'):
            continue
        if any(('双打' in str(song.get(field) or '') for field in ('song_name', 'song_name_jp'))):
            continue
        keys.add((song_id, level))
    return keys

def available_star_progress_values(*, catalog) -> Set[int]:
    values: Set[int] = set()
    song_index = catalog.song_index
    for song_id, level in load_star_progress_chart_keys(catalog=catalog):
        try:
            star_value = int(song_index[song_id].get(LEVEL_STAR_FIELD[level]))
        except (TypeError, ValueError):
            continue
        if 1 <= star_value <= 10:
            values.add(star_value)
    return values

def query_progress_items_by_star(star_value: int, *, catalog) -> List[ProgressChartItem]:
    if star_value < 1 or star_value > 10:
        return []
    items: List[ProgressChartItem] = []
    song_index = catalog.song_index
    for song_id, level in load_star_progress_chart_keys(catalog=catalog):
        song = song_index[song_id]
        try:
            value = int(song.get(LEVEL_STAR_FIELD[level]))
        except (TypeError, ValueError):
            continue
        if value != star_value:
            continue
        title = (song.get('song_name') or '').strip() or (song.get('song_name_jp') or '').strip() or f'ID{song_id}'
        items.append(ProgressChartItem(song_id=song_id, level=level, title=_normalize_title(title, level)))
    return _sort_items(items, catalog=catalog)

@dataclass(frozen=True)
class ProgressCatalogInputs:
    song_index: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    active_song_ids: Set[int] = field(default_factory=set)
    rating_entries: List[Dict[str, Any]] = field(default_factory=list)
    static_progress_map: Dict[str, List[int]] = field(default_factory=dict)
    cn_available_chart_keys: Set[Tuple[int, int]] = field(default_factory=set)
    profile: str = 'progress-center-20261010'
