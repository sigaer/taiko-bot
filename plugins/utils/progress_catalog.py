from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.chart import progress_catalog as _progress

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set
from taiko_bot.settings import get_settings

from .song_visibility import is_song_publicly_visible

BASE = get_settings().root_dir
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"
STATIC_PROGRESS_PATH = BASE / "songs" / "song_difficulty.json"

LEVEL_STAR_FIELD = _progress.LEVEL_STAR_FIELD
STAR_PROGRESS_LEVELS = _progress.STAR_PROGRESS_LEVELS


ProgressChartItem = _progress.ProgressChartItem


_to_float = _progress._to_float


_normalize_title = _progress._normalize_title


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


_pick_title = _progress._pick_title


def _sort_items(items):
    return _progress._sort_items(items, catalog=_domain_catalog())


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


def _build_static_progress_title(song_id, level, progress_key):
    return _progress._build_static_progress_title(song_id, level, progress_key, catalog=_domain_catalog())


@lru_cache(maxsize=1)
def available_pass_progress_keys():
    return _progress.available_pass_progress_keys(catalog=_domain_catalog(static=True))


def query_progress_items_by_pass_const(progress_key):
    return _progress.query_progress_items_by_pass_const(progress_key, catalog=_domain_catalog(static=True))


@lru_cache(maxsize=1)
def available_const_progress_keys():
    return _progress.available_const_progress_keys(catalog=_domain_catalog(rating=True))


def query_progress_items_by_const(const_value):
    return _progress.query_progress_items_by_const(const_value, catalog=_domain_catalog(rating=True))


@lru_cache(maxsize=1)
def available_star_progress_values():
    return _progress.available_star_progress_values(catalog=_domain_catalog())


def query_progress_items_by_star(star_value):
    return _progress.query_progress_items_by_star(star_value, catalog=_domain_catalog())

def _domain_catalog(*, rating=False, static=False):
    return _progress.ProgressCatalogInputs(song_index=load_song_index(),
        active_song_ids=load_active_song_ids(), rating_entries=_load_rating_entries() if rating else [],
        static_progress_map=_load_static_progress_map() if static else {}, profile="progress-client-20261010")
