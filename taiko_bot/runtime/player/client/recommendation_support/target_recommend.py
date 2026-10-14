from __future__ import annotations


from . import catalog as _domain

from sakura_taiko_core.recommendation import client as _target, client_selection as _selection

import json

from functools import lru_cache

from typing import Any, Dict, List

from taiko_bot.settings import get_settings


from .score_calculator import compute_all_from_userdata_records, load_rating_config

ROOT_DIR = get_settings().root_dir

SCORELINE_PATH = ROOT_DIR / "songs" / "taiko_goku_onis.json"

RATING_PATH = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

target_recommendation_displays = _target.target_recommendation_displays

parse_target_recommendation_request = _target.parse_target_recommendation_request


_userdata_records = _selection._userdata_records

@lru_cache(maxsize=1)
def _load_song_rows() -> List[Dict[str, Any]]:
    payload = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []

def _build_song_maps():
    return _selection.build_song_maps(_load_song_rows())

@lru_cache(maxsize=1)
def _load_scoreline_rows() -> List[Dict[str, Any]]:
    payload = json.loads(SCORELINE_PATH.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []

@lru_cache(maxsize=1)
def _load_rating_lookup():
    return _selection.build_rating_lookup(load_rating_config(RATING_PATH))

def _build_best_entry_map(records):
    _, by_id, by_title = _domain.identity_inputs()
    return _selection.build_best_entry_map(records, groups_by_id=by_id, groups_by_title=by_title)

def _build_user_profile(records):
    return _target.build_user_profile(compute_all_from_userdata_records(records, json_path=RATING_PATH))

def compute_target_recommendations_from_userdata(userdata, target_key, *, star_filter=None):
    records = _userdata_records(userdata)
    if not records:
        return _selection.select_target_recommendations(userdata, target_key, star_filter=star_filter,
            user_profile={}, best_map={}, song_maps=({}, {}), rating_lookup=({}, {}, []),
            scoreline_rows=[], groups_by_id={}, groups_by_title={})
    _, by_id, by_title = _domain.identity_inputs()
    return _selection.select_target_recommendations(userdata, target_key, star_filter=star_filter,
        user_profile=_build_user_profile(records), best_map=_build_best_entry_map(records),
        song_maps=_build_song_maps(), rating_lookup=_load_rating_lookup(), scoreline_rows=_load_scoreline_rows(),
        groups_by_id=by_id, groups_by_title=by_title)
