from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.recommendation import client as _target, client_selection as _selection

import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata

from .duplicate_versions import (
    default_song_id_for_query,
    duplicate_identity_key,
    normalize_song_title,
)
from .score_calculator import (
    build_const_table,
    calc_y,
    compute_AD_AE_AF_AG,
    compute_AI,
    compute_P,
    compute_Q,
    compute_all_from_userdata_records,
    compute_six_dims,
    load_rating_config,
    lookup_const_score,
)

ROOT_DIR = get_settings().root_dir
SCORELINE_PATH = ROOT_DIR / "songs" / "taiko_goku_onis.json"
RATING_PATH = ROOT_DIR / "songs" / "rating_structured_with_ids.json"
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

SCORE_TARGETS = _target.SCORE_TARGETS
FULL_COMBO_TARGET = _target.FULL_COMBO_TARGET
DONDAFUL_TARGET = _target.DONDAFUL_TARGET
TARGET_DISPLAY = _target.TARGET_DISPLAY
_TARGET_ALIASES = _target._TARGET_ALIASES
_TARGET_ALIAS_KEYS_SORTED = _target._TARGET_ALIAS_KEYS_SORTED
_STAR_FILTER_ALIASES = _target._STAR_FILTER_ALIASES

PROFILE_KEYS = _target.PROFILE_KEYS
SCORE_TARGET_DIM_WEIGHTS = _target.SCORE_TARGET_DIM_WEIGHTS
FULL_COMBO_DIM_WEIGHTS = _target.FULL_COMBO_DIM_WEIGHTS
DONDAFUL_DIM_WEIGHTS = _target.DONDAFUL_DIM_WEIGHTS


TargetRecommendationResult = _selection.TargetRecommendationResult


parse_target_recommendation_key = _target.parse_target_recommendation_key


target_recommendation_displays = _target.target_recommendation_displays


parse_target_recommendation_star_filter = _target.parse_target_recommendation_star_filter


parse_target_recommendation_request = _target.parse_target_recommendation_request


_safe_int = _target._safe_int


_safe_float = _target._safe_float


_clamp = _target._clamp


_mean = _target._mean


def _load_userdata_payload(user_id: str | int) -> Dict[str, Any]:
    return get_cached_userdata(str(user_id))


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


_target_accuracy_hint = _target._target_accuracy_hint


_candidate_dimensions = _target._candidate_dimensions


_profile_weights = _target._profile_weights


_profile_match_score = _target._profile_match_score


_format_gap_text = _target._format_gap_text


_achieved_target = _target._achieved_target


_target_text = _target._target_text


_build_row = _target._build_row


def compute_target_recommendations_for_user(user_id, target_key, *, star_filter=None):
    userdata = _load_userdata_payload(user_id)
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
