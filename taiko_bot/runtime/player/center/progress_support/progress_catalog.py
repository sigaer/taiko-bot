from __future__ import annotations


from taiko_application.query import ProgressQueryContext

from taiko_application.query import progress as application_progress

from sakura_taiko_core.chart import progress_catalog as domain_progress

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, List

from ..recommendation_support.chart_availability import load_cn_available_chart_keys

BASE = __import__("taiko_bot.runtime.player.center.recommendation_support.paths", fromlist=["ROOT"]).ROOT

SONG_DATA_PATH = BASE / "songs" / "song_data.json"

RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"

STATIC_PROGRESS_PATH = BASE / "songs" / "song_difficulty.json"

@lru_cache(maxsize=1)
def load_song_index() -> Dict[int, Dict[str, Any]]:
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        songs = json.load(f)
    return {int(song["id"]): song for song in songs if song.get("id") is not None}

@lru_cache(maxsize=1)
def load_active_song_ids():
    return domain_progress.active_song_ids_from_index(load_song_index())

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

def query_progress_items_by_pass_const(progress_key: str):
    return application_progress.query_progress_items_by_pass_const(
        ProgressQueryContext(
            catalog=_progress_inputs(
                "song_index", "active_song_ids", "static_progress_map"
            ),
            value=progress_key,
        )
    )

def query_progress_items_by_const(const_value: float):
    return application_progress.query_progress_items_by_const(
        ProgressQueryContext(
            catalog=_progress_inputs("song_index", "active_song_ids", "rating_entries"),
            value=const_value,
        )
    )

def load_star_progress_chart_keys():
    return application_progress.load_star_progress_chart_keys(
        ProgressQueryContext(
            catalog=_progress_inputs("song_index", "cn_available_chart_keys")
        )
    )

def query_progress_items_by_star(star_value: int):
    return application_progress.query_progress_items_by_star(
        ProgressQueryContext(
            catalog=_progress_inputs("song_index", "cn_available_chart_keys"),
            value=star_value,
        )
    )

def _progress_inputs(*fields):
    providers={
        "song_index":load_song_index,
        "active_song_ids":load_active_song_ids,
        "rating_entries":_load_rating_entries,
        "static_progress_map":_load_static_progress_map,
        "cn_available_chart_keys":lambda:load_cn_available_chart_keys(SONG_DATA_PATH),
    }
    return domain_progress.ProgressCatalogInputs(**{name:providers[name]() for name in fields})


@lru_cache(maxsize=1)
def available_pass_progress_keys():
    return application_progress.available_pass_progress_keys(
        ProgressQueryContext(
            catalog=_progress_inputs("active_song_ids", "static_progress_map")
        )
    )


@lru_cache(maxsize=1)
def available_const_progress_keys():
    return application_progress.available_const_progress_keys(
        ProgressQueryContext(
            catalog=_progress_inputs("active_song_ids", "rating_entries")
        )
    )


@lru_cache(maxsize=1)
def available_star_progress_values():
    return application_progress.available_star_progress_values(
        ProgressQueryContext(
            catalog=_progress_inputs("song_index", "cn_available_chart_keys")
        )
    )
