from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

DOWN_SHELF_STATUSES = (1, '1', '已下架')

def is_chart_level_available(song: dict[str, Any], level: int) -> bool:
    """判断国服曲库中是否实际实装了指定难度。"""
    value = song.get(f'level_{level}')
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() not in ('', '-')
    return True

def on_shelf_song_ids(rows) -> set[int]:
    on_shelf_ids: set[int] = set()
    for item in rows:
        try:
            song_id = int(item.get('id'))
        except Exception:
            continue
        if item.get('shelf_status') in DOWN_SHELF_STATUSES:
            continue
        on_shelf_ids.add(song_id)
    return on_shelf_ids

def cn_available_chart_keys(merged_rows, raw_rows=None) -> set[tuple[int, int]]:
    """返回国服当前在架且已实装的鬼/里谱 (song_id, level)。

    ``song_data.json`` 会用日服谱面库补充元数据，其中个别难度可能并未在
    国服实装。同目录下的 ``song_data_raw.json`` 是 Wahlap 国服原始快照，
    存在时以它的难度字段为准，再用合并曲库的上下架状态做二次约束。
    """
    shelf_status_by_id: dict[int, Any] = {}
    for item in merged_rows:
        try:
            shelf_status_by_id[int(item.get('id'))] = item.get('shelf_status')
        except Exception:
            continue
    source_rows = raw_rows if raw_rows is not None else merged_rows
    available: set[tuple[int, int]] = set()
    for item in source_rows:
        if item.get('shelf_status') in DOWN_SHELF_STATUSES:
            continue
        try:
            song_id = int(item.get('id'))
        except Exception:
            continue
        if shelf_status_by_id.get(song_id) in DOWN_SHELF_STATUSES:
            continue
        for level in (4, 5):
            if is_chart_level_available(item, level):
                available.add((song_id, level))
    return available
