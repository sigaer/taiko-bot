from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Mapping, Set

from taiko_bot.settings import get_settings

SONG_DATA_PATH = get_settings().root_dir / "songs" / "song_data.json"
DOUBLE_TITLE_PREFIX = "【双打】"

# 当前 taiko_song_database.json 中 isDeleted=1，但 song_data 仍保留在架的曲目。
# 开源 bot 不携带 taiko_song_database.json，因此在这里冻结覆盖表。
DOWN_SHELF_OVERRIDE_SONG_IDS = frozenset({231, 678, 987, 1167, 1200})

# 段位特供曲，仅保留在原始 JSON 中，所有对外逻辑都应忽略。
HIDDEN_SONG_IDS = frozenset({1429})


def normalize_song_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_song_title(song: Mapping[str, Any] | None) -> str:
    if not isinstance(song, Mapping):
        return ""
    return str(song.get("song_name") or song.get("song_name_jp") or "").strip()


def is_double_chart_title(title: Any) -> bool:
    return str(title or "").strip().startswith(DOUBLE_TITLE_PREFIX)


def is_song_marked_down_shelf(song_id: Any, shelf_status: Any) -> bool:
    normalized_id = normalize_song_id(song_id)
    if normalized_id in DOWN_SHELF_OVERRIDE_SONG_IDS:
        return True
    return shelf_status in (1, "1", "已下架")


def is_song_publicly_visible(
    song: Mapping[str, Any] | None = None,
    *,
    song_id: Any = None,
    title: Any = None,
    shelf_status: Any = None,
) -> bool:
    if isinstance(song, Mapping):
        song_id = song.get("id", song_id)
        title = normalize_song_title(song) or title
        shelf_status = song.get("shelf_status", shelf_status)

    normalized_id = normalize_song_id(song_id)
    if normalized_id in HIDDEN_SONG_IDS:
        return False
    if is_double_chart_title(title):
        return False
    if is_song_marked_down_shelf(normalized_id, shelf_status):
        return False
    return True


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


def is_song_id_publicly_visible(song_id: Any) -> bool:
    normalized_id = normalize_song_id(song_id)
    if normalized_id in HIDDEN_SONG_IDS:
        return False
    song = get_song_metadata(normalized_id)
    if song is None:
        return normalized_id not in DOWN_SHELF_OVERRIDE_SONG_IDS
    return is_song_publicly_visible(song)
