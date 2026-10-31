from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from ..recommendation.support import safe_int, normalize_title_key

def build_chart_lookup(rows):
    by_id: Dict[Tuple[int, int], Dict[str, Any]] = {}
    by_title: Dict[Tuple[str, int], List[Dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        row_level = safe_int(row.get('level'), -1)
        if row_level not in (4, 5):
            continue
        row_id = safe_int(row.get('id'), -1)
        if row_id >= 0:
            by_id[row_id, row_level] = row
        for raw_title in (row.get('title'), row.get('title_jp'), row.get('title_cn')):
            title_key = normalize_title_key(raw_title)
            if title_key:
                by_title.setdefault((title_key, row_level), []).append(row)
    return (by_id, by_title)

def resolve_chart(song_id, level, fallback_title='', *, by_id, by_title, group_ids, default_id):
    if song_id is not None:
        ordered_ids = sorted(set(group_ids), key=lambda value: (value != default_id, value))
        for candidate_id in ordered_ids:
            row = by_id.get((candidate_id, level))
            if row is not None:
                return row
    title_key = normalize_title_key(fallback_title)
    if not title_key:
        return None
    rows = by_title.get((title_key, level), [])
    if not rows:
        return None
    rows = sorted(rows, key=lambda row: (safe_int(row.get('id'), 10 ** 9) != (default_id or -1), safe_int(row.get('id'), 10 ** 9)))
    return rows[0]
