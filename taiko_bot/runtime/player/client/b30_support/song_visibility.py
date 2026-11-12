from __future__ import annotations


from sakura_taiko_core.chart import visibility as _visibility

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict

from taiko_bot.settings import get_settings

SONG_DATA_PATH = get_settings().root_dir / "songs" / "song_data.json"

normalize_song_id = _visibility.normalize_song_id

def load_song_index() -> Dict[int, Dict[str, Any]]:
    from taiko_bot.public_catalog_cache import revision
    path = Path(SONG_DATA_PATH)
    if not path.exists():
        return {}
    return _load_song_index(revision(path))

@lru_cache(maxsize=2)
def _load_song_index(key):
    with open(key[0], "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, list):
        return {}
    result: Dict[int, Dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        normalized_id = normalize_song_id(item.get("id"))
        if normalized_id is None:
            continue
        result[normalized_id] = item
    return result

load_song_index.cache_clear = _load_song_index.cache_clear

def is_song_id_publicly_visible(song_id):
    return _visibility.is_song_id_publicly_visible(song_id, song_index=load_song_index())
