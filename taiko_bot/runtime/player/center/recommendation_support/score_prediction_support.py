from __future__ import annotations
from .paths import ROOT as _ROOT


from sakura_taiko_core.recommendation import catalog_inputs as domain_catalog_inputs

from sakura_taiko_core.chart import identity as domain_identity, scoreline_lookup, scoreline_dataset

from sakura_taiko_core.recommendation import entries as domain_entries

from .taiko_domain_adapter import identity_inputs

import json

import os


from pathlib import Path

from typing import Any, Dict, List, Tuple

from .chart_availability import load_cn_available_chart_keys, load_on_shelf_song_ids

from .score_calculator import build_const_table, load_rating_config

BASE = _ROOT



SCORELINE_PATH = BASE / "songs" / "taiko_goku_onis.json"

RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"

SONG_DATA_PATH = BASE / "songs" / "song_data.json"

def load_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def build_best_entry_map(records, *, song_data_path=SONG_DATA_PATH):
    default_ids, _ = identity_inputs(song_data_path)
    return domain_entries.build_best_entry_map(records, default_ids=default_ids)

def load_rating_features(rating_path: str | Path=RATING_PATH) -> Dict[Tuple[int, int], Dict[str, float]]:
    try:
        payload = load_json(rating_path)
    except Exception:
        return {}
    return domain_catalog_inputs.rating_features(payload)

def load_rating_features_by_title_level(rating_path: str | Path=RATING_PATH) -> Dict[Tuple[str, int], Dict[str, float]]:
    try:
        payload = load_json(rating_path)
    except Exception:
        return {}
    return domain_catalog_inputs.rating_features_by_title_level(payload)

def load_rating_support(
    rating_path: str | Path = RATING_PATH,
) -> Tuple[
    Dict[Tuple[int, int], Dict[str, float]],
    Dict[Tuple[str, int], Dict[str, float]],
    List[Tuple[float, float]],
]:
    features_by_key = load_rating_features(rating_path)
    features_by_title_level = load_rating_features_by_title_level(rating_path)
    try:
        cfg = load_rating_config(rating_path)
        const_map = cfg["const_table"]["const_to_score"]
        const_table = build_const_table(const_map)
    except Exception:
        const_table = []
    return features_by_key, features_by_title_level, const_table

def load_song_title_keys(song_data_path: str | Path=SONG_DATA_PATH) -> Dict[int, str]:
    try:
        payload = load_json(song_data_path)
    except Exception:
        return {}
    return domain_catalog_inputs.song_title_keys(payload)

def load_song_star_map(song_data_path: str | Path=SONG_DATA_PATH) -> Dict[Tuple[int, int], str]:
    try:
        payload = load_json(song_data_path)
    except Exception:
        return {}
    return domain_catalog_inputs.song_star_map(payload)

def load_candidate_charts(scoreline_path: str | Path=SCORELINE_PATH, song_data_path: str | Path=SONG_DATA_PATH) -> List[Dict[str, Any]]:
    from .score_line import load_scoreline_data
    from .duplicate_versions import _group_cache
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_catalog_inputs.candidate_charts(load_scoreline_data(scoreline_path), cn_available_keys=load_cn_available_chart_keys(song_data_path), on_shelf_ids=load_on_shelf_song_ids(song_data_path), groups_by_id=by_id, groups_by_title=by_title)

def _chart_resolver(scoreline_path, song_data_path):
    """Load one catalog view; Core owns its lookup and identity policy."""
    from . import score_line, duplicate_versions
    requested_path=Path(scoreline_path)
    if requested_path == SCORELINE_PATH:
        by_id,by_title=score_line._build_chart_index(score_line._ensure_scoreline_dataset_current())
        resolve=scoreline_dataset.get_scoreline_entry
        group_path=duplicate_versions.SONG_DATA_PATH
    else:
        by_id,by_title=scoreline_lookup.build_chart_lookup(score_line.load_scoreline_data(requested_path))
        resolve=scoreline_lookup.resolve_chart
        group_path=song_data_path
    _,groups_by_id,groups_by_title=duplicate_versions._group_cache(group_path)
    context=dict(groups_by_id=groups_by_id,groups_by_title=groups_by_title)
    def lookup(song_id,level,fallback_title=''):
        return resolve(song_id,level,fallback_title,by_id=by_id,by_title=by_title,
            group_ids=domain_identity.group_ids_for_query(song_id=song_id,title=fallback_title,**context),
            default_id=domain_identity.default_song_id_for_query(song_id,title=fallback_title,**context))
    return lookup
