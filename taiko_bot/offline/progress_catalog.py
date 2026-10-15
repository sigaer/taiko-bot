"""Public on-shelf catalog still consumed by update-change rendering."""
from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root
import json
from pathlib import Path
from functools import lru_cache
from typing import Any, Dict, Set
from sakura_taiko_core.chart import progress_catalog as domain_progress
BASE = Path(str(_runtime_root()))
SONG_DATA_PATH = BASE / "songs/song_data.json"

@lru_cache(maxsize=1)
def load_song_index() -> Dict[int, Dict[str, Any]]:
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        songs = json.load(f)
    return {int(song["id"]): song for song in songs if song.get("id") is not None}

@lru_cache(maxsize=1)
def load_active_song_ids():
    return domain_progress.active_song_ids_from_index(load_song_index())
