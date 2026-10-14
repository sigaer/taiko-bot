"""Public on-shelf catalog still consumed by update-change rendering."""
from __future__ import annotations
import json
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, Set
from .song_visibility import is_song_publicly_visible
from taiko_bot.settings import get_settings
BASE = get_settings().root_dir
SONG_DATA_PATH = BASE / "songs/song_data.json"

@lru_cache(maxsize=1)
def load_song_index() -> Dict[int, Dict[str, Any]]:
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        songs = json.load(f)
    return {int(song["id"]): song for song in songs if song.get("id") is not None}

def is_song_on_shelf(song: Dict[str, Any]) -> bool:
    """与 score_calculator / 曲库其它模块保持一致的对外可见判定。"""
    return is_song_publicly_visible(song)

@lru_cache(maxsize=1)
def load_active_song_ids() -> Set[int]:
    active: Set[int] = set()
    for song_id, song in load_song_index().items():
        if not is_song_on_shelf(song):
            continue
        active.add(song_id)
    return active
