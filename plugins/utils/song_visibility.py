from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.chart import visibility as _visibility

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Set

from taiko_bot.settings import get_settings

SONG_DATA_PATH = get_settings().root_dir / "songs" / "song_data.json"
DOUBLE_TITLE_PREFIX = _visibility.DOUBLE_TITLE_PREFIX

# 当前 taiko_song_database.json 中 isDeleted=1，但 song_data 仍保留在架的曲目。
# 开源 bot 不携带 taiko_song_database.json，因此在这里冻结覆盖表。
DOWN_SHELF_OVERRIDE_SONG_IDS = _visibility.DOWN_SHELF_OVERRIDE_SONG_IDS

# 段位特供曲，仅保留在原始 JSON 中，所有对外逻辑都应忽略。
HIDDEN_SONG_IDS = _visibility.HIDDEN_SONG_IDS


normalize_song_id = _visibility.normalize_song_id


normalize_song_title = _visibility.normalize_song_title


is_double_chart_title = _visibility.is_double_chart_title


is_song_marked_down_shelf = _visibility.is_song_marked_down_shelf


is_song_publicly_visible = _visibility.is_song_publicly_visible


@lru_cache(maxsize=1)
def load_song_index() -> Dict[int, Dict[str, Any]]:
    path = Path(SONG_DATA_PATH)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
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


def get_song_metadata(song_id: Any) -> Dict[str, Any] | None:
    normalized_id = normalize_song_id(song_id)
    if normalized_id is None:
        return None
    return load_song_index().get(normalized_id)


@lru_cache(maxsize=1)
def load_public_song_ids() -> Set[int]:
    return {
        song_id
        for song_id, song in load_song_index().items()
        if is_song_publicly_visible(song)
    }


def is_song_id_publicly_visible(song_id):
    return _visibility.is_song_id_publicly_visible(song_id, song_index=load_song_index())
