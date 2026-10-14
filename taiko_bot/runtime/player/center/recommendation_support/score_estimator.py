from __future__ import annotations
from .paths import ROOT as _ROOT


from dataclasses import dataclass

from sakura_taiko_core.recommendation import estimator as domain_estimator

from .taiko_domain_adapter import identity_inputs, with_host_clock

estimate_target_reach_batch = with_host_clock(domain_estimator.estimate_target_reach_batch)

import contextlib

import io

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Dict, List, Optional

from .score_prediction_support import RATING_PATH, SCORELINE_PATH, SONG_DATA_PATH, build_best_entry_map, load_candidate_charts, load_rating_support, load_song_title_keys, _chart_resolver

from .score_calculator import compute_all_from_userdata_records

@dataclass(frozen=True)
class ScoreEstimatorProfile(domain_estimator.ScoreEstimatorProfile):
    scoreline_path: Path
    rating_path: Path
    song_data_path: Path

def _build_history_samples(best_map, title_keys_by_id, features_by_key, features_by_title_level, const_table, *, scoreline_path, song_data_path, chart_by_key=None):
    default_ids, _ = identity_inputs(song_data_path)
    charts = chart_by_key if chart_by_key is not None else _resolved_chart_inputs(
        title_keys_by_id, [], best_map, scoreline_path, song_data_path, keys=set(best_map))
    from datetime import date
    return domain_estimator._build_history_samples(best_map, title_keys_by_id, features_by_key, features_by_title_level,
        const_table, chart_by_key=charts, default_ids=default_ids, today=date.today())

def _exclude_target_records(records, *, exclude_song_id, exclude_level, song_data_path):
    default_ids, _ = identity_inputs(song_data_path)
    return domain_estimator._exclude_target_records(records, exclude_song_id=exclude_song_id,
        exclude_level=exclude_level, default_ids=default_ids)

def _build_estimator_user_profiles(records, best_map, charts, features_by_key, rating_path):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rating_results=compute_all_from_userdata_records(records, rating_path)
    except Exception:
        rating_results=[]
    return domain_estimator._build_estimator_user_profiles(rating_results, best_map, charts, features_by_key)

def build_score_estimator_profile(records: List[Dict[str, Any]], *, scoreline_path: str | Path=SCORELINE_PATH, rating_path: str | Path=RATING_PATH, song_data_path: str | Path=SONG_DATA_PATH, exclude_song_id: Optional[int]=None, exclude_level: Optional[int]=None) -> ScoreEstimatorProfile:
    scoreline_path = Path(scoreline_path)
    rating_path = Path(rating_path)
    song_data_path = Path(song_data_path)
    best_map = build_best_entry_map(records, song_data_path=song_data_path)
    profile_records = _exclude_target_records(records, exclude_song_id=exclude_song_id, exclude_level=exclude_level, song_data_path=song_data_path)
    profile_best_map = build_best_entry_map(profile_records, song_data_path=song_data_path) if profile_records is not records else best_map
    charts = load_candidate_charts(scoreline_path, song_data_path)
    title_keys_by_id = load_song_title_keys(song_data_path)
    features_by_key, features_by_title_level, const_table = load_rating_support(rating_path)
    stable_profile, pb_profile = _build_estimator_user_profiles(profile_records, profile_best_map, charts, features_by_key, rating_path)
    chart_by_key = _resolved_chart_inputs(title_keys_by_id, charts, best_map, scoreline_path, song_data_path)
    samples = _build_history_samples(profile_best_map, title_keys_by_id, features_by_key, features_by_title_level, const_table, scoreline_path=scoreline_path, song_data_path=song_data_path, chart_by_key=chart_by_key)
    return ScoreEstimatorProfile(user_profile=stable_profile, stable_profile=stable_profile, pb_profile=pb_profile, best_map=best_map, title_keys_by_id=title_keys_by_id, features_by_key=features_by_key, features_by_title_level=features_by_title_level, const_table=const_table, samples=samples, scoreline_path=scoreline_path, rating_path=rating_path, song_data_path=song_data_path, chart_by_key=chart_by_key, default_ids=identity_inputs(song_data_path)[0])

def _resolved_chart_inputs(title_keys_by_id, charts, best_map, scoreline_path, song_data_path, *, keys=None):
    if keys is None:
        keys=set(best_map)|{(sid,level) for sid in title_keys_by_id for level in (4,5)}
        keys|={(int(chart["id"]),int(chart["level"])) for chart in charts}
    resolve=_chart_resolver(scoreline_path,song_data_path)
    return {key:resolve(*key,title_keys_by_id.get(key[0],"")) for key in keys}
