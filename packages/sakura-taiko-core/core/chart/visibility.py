from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple

DOUBLE_TITLE_PREFIX = '【双打】'
DOWN_SHELF_OVERRIDE_SONG_IDS = frozenset({231, 678, 987, 1167, 1200})
HIDDEN_SONG_IDS = frozenset({1429})

def normalize_song_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def normalize_song_title(song: Mapping[str, Any] | None) -> str:
    if not isinstance(song, Mapping):
        return ''
    return str(song.get('song_name') or song.get('song_name_jp') or '').strip()

def is_double_chart_title(title: Any) -> bool:
    return str(title or '').strip().startswith(DOUBLE_TITLE_PREFIX)

def is_song_marked_down_shelf(song_id: Any, shelf_status: Any) -> bool:
    normalized_id = normalize_song_id(song_id)
    if normalized_id in DOWN_SHELF_OVERRIDE_SONG_IDS:
        return True
    return shelf_status in (1, '1', '已下架')

def is_song_publicly_visible(song: Mapping[str, Any] | None=None, *, song_id: Any=None, title: Any=None, shelf_status: Any=None) -> bool:
    if isinstance(song, Mapping):
        song_id = song.get('id', song_id)
        title = normalize_song_title(song) or title
        shelf_status = song.get('shelf_status', shelf_status)
    normalized_id = normalize_song_id(song_id)
    if normalized_id in HIDDEN_SONG_IDS:
        return False
    if is_double_chart_title(title):
        return False
    if is_song_marked_down_shelf(normalized_id, shelf_status):
        return False
    return True

def is_song_id_publicly_visible(song_id, *, song_index):
    normalized_id = normalize_song_id(song_id)
    if normalized_id in HIDDEN_SONG_IDS:
        return False
    song = song_index.get(normalized_id)
    if song is None:
        return normalized_id not in DOWN_SHELF_OVERRIDE_SONG_IDS
    return is_song_publicly_visible(song)
