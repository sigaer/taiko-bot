from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set
from taiko_bot.settings import get_settings

BASE = get_settings().root_dir
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"
STATIC_PROGRESS_PATH = BASE / "songs" / "song_difficulty.json"

LEVEL_STAR_FIELD = {
    1: "level_1",
    2: "level_2",
    3: "level_3",
    4: "level_4",
    5: "level_5",
}
STAR_PROGRESS_LEVELS = (4, 5)


@dataclass(frozen=True)
class ProgressChartItem:
    song_id: int
    level: int
    title: str


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, "", "-"):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_title(base_title: str, level: int) -> str:
    title = str(base_title or "").strip()
    if not title:
        return title
    if level == 5 and "里" not in title and "裏" not in title:
        return f"{title}（里）"
    return title


@lru_cache(maxsize=1)
def load_song_index() -> Dict[int, Dict[str, Any]]:
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        songs = json.load(f)
    return {int(song["id"]): song for song in songs if song.get("id") is not None}


def is_song_on_shelf(status: Any) -> bool:
    """与 score_calculator / 曲库其它模块保持一致的在架判定。"""
    return status not in (1, "1", "已下架")


@lru_cache(maxsize=1)
def load_active_song_ids() -> Set[int]:
    active: Set[int] = set()
    for song_id, song in load_song_index().items():
        if not is_song_on_shelf(song.get("shelf_status")):
            continue
        active.add(song_id)
    return active


@lru_cache(maxsize=1)
def _load_rating_entries() -> List[Dict[str, Any]]:
    with open(RATING_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    songs = payload.get("songs") or {}
    if isinstance(songs, dict):
        return list(songs.values())
    if isinstance(songs, list):
        return songs
    return []


def _pick_title(song: Dict[str, Any] | None, chart: Dict[str, Any]) -> str:
    title = (
        (chart.get("song_name_cn") or "").strip()
        or (song or {}).get("song_name", "")
        or (song or {}).get("song_name_jp", "")
        or chart.get("曲名", "")
        or f"ID{chart.get('id')}"
    )
    level = int(chart.get("level", 4) or 4)
    return _normalize_title(str(title), level)


def _sort_items(items: Iterable[ProgressChartItem]) -> List[ProgressChartItem]:
    song_index = load_song_index()
    return sorted(
        items,
        key=lambda item: (
            int((song_index.get(item.song_id) or {}).get("sort", 10**9) or 10**9),
            item.song_id,
            item.level,
        ),
    )


@lru_cache(maxsize=1)
def _load_static_progress_map() -> Dict[str, List[int]]:
    with open(STATIC_PROGRESS_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        return {}
    result: Dict[str, List[int]] = {}
    for key, raw_items in payload.items():
        if not isinstance(raw_items, list):
            continue
        result[str(key)] = raw_items
    return result


def _build_static_progress_title(song_id: int, level: int, progress_key: str) -> str:
    song = load_song_index().get(song_id)
    base_title = (
        (song or {}).get("song_name")
        or (song or {}).get("song_name_jp")
        or f"ID{song_id}"
    )
    title = _normalize_title(str(base_title), level)
    if song_id == 775:
        if progress_key == "10.1":
            title += "（普通谱面）"
        elif progress_key == "10.6":
            title += "（达人谱面）"
    elif song_id == 1037:
        if progress_key == "10.0":
            title += "（全普通）"
        elif progress_key == "10.4":
            title += "（全达人）"
    return title


@lru_cache(maxsize=1)
def available_pass_progress_keys() -> Set[str]:
    active_song_ids = load_active_song_ids()
    keys: Set[str] = set()
    for key, raw_items in _load_static_progress_map().items():
        if not re.fullmatch(r"\d+\.\d", key):
            continue
        for raw_id in raw_items:
            if not isinstance(raw_id, int):
                continue
            song_id = raw_id - 100000 if raw_id >= 100000 else raw_id
            if song_id in active_song_ids:
                keys.add(key)
                break
    return keys


def query_progress_items_by_pass_const(progress_key: str) -> List[ProgressChartItem]:
    if progress_key not in _load_static_progress_map():
        return []
    active_song_ids = load_active_song_ids()
    dedup: Dict[tuple[int, int], ProgressChartItem] = {}
    for raw_id in _load_static_progress_map().get(progress_key, []):
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
        dedup[key] = ProgressChartItem(
            song_id=song_id,
            level=level,
            title=_build_static_progress_title(song_id, level, progress_key),
        )
    return _sort_items(dedup.values())


@lru_cache(maxsize=1)
def available_const_progress_keys() -> Set[str]:
    keys: Set[str] = set()
    active_song_ids = load_active_song_ids()
    for chart in _load_rating_entries():
        try:
            song_id = int(chart.get("id"))
        except (TypeError, ValueError):
            continue
        if song_id not in active_song_ids:
            continue
        const_value = _to_float(chart.get("score"))
        if const_value is None:
            continue
        keys.add(f"{const_value:.1f}")
    return keys


def query_progress_items_by_const(const_value: float) -> List[ProgressChartItem]:
    active_song_ids = load_active_song_ids()
    song_index = load_song_index()
    dedup: Dict[tuple[int, int], ProgressChartItem] = {}
    for chart in _load_rating_entries():
        score = _to_float(chart.get("score"))
        if score is None or abs(score - const_value) >= 1e-6:
            continue
        try:
            song_id = int(chart.get("id"))
            level = int(chart.get("level"))
        except (TypeError, ValueError):
            continue
        if song_id not in active_song_ids:
            continue
        key = (song_id, level)
        if key in dedup:
            continue
        dedup[key] = ProgressChartItem(
            song_id=song_id,
            level=level,
            title=_pick_title(song_index.get(song_id), chart),
        )
    return _sort_items(dedup.values())


@lru_cache(maxsize=1)
def available_star_progress_values() -> Set[int]:
    values: Set[int] = set()
    for song_id in load_active_song_ids():
        song = load_song_index().get(song_id)
        if not song:
            continue
        for level in STAR_PROGRESS_LEVELS:
            try:
                star_value = int(song.get(LEVEL_STAR_FIELD[level]))
            except (TypeError, ValueError):
                continue
            if 1 <= star_value <= 10:
                values.add(star_value)
    return values


def query_progress_items_by_star(star_value: int) -> List[ProgressChartItem]:
    if star_value < 1 or star_value > 10:
        return []
    items: List[ProgressChartItem] = []
    for song_id in load_active_song_ids():
        song = load_song_index().get(song_id)
        if not song:
            continue
        title = (
            (song.get("song_name") or "").strip()
            or (song.get("song_name_jp") or "").strip()
            or f"ID{song_id}"
        )
        for level in STAR_PROGRESS_LEVELS:
            try:
                value = int(song.get(LEVEL_STAR_FIELD[level]))
            except (TypeError, ValueError):
                continue
            if value != star_value:
                continue
            items.append(
                ProgressChartItem(
                    song_id=song_id,
                    level=level,
                    title=_normalize_title(title, level),
                )
            )
    return _sort_items(items)
