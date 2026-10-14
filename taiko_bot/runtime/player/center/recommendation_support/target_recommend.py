from __future__ import annotations
from .paths import ROOT as _ROOT


from sakura_taiko_core.recommendation.center import DEFAULT_ROLL_SPEED_IPS, TARGET_RECOMMENDATION_LIMIT, TARGET_RECOMMENDATION_MIN_IMAGE_ROWS, SCORE_TARGETS, TARGET_DISPLAY, UserProfile, target_recommendation_displays, parse_target_recommendation_star_filter, parse_target_recommendation_request, _safe_int, _chart_title_key, _build_played_title_level_keys

from sakura_taiko_core.recommendation import center as domain_center, selection as domain_selection

import contextlib

import io

from dataclasses import dataclass

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Tuple

from .score_calculator import compute_all_from_userdata_records

from .score_prediction_support import build_best_entry_map as support_build_best_entry_map, load_candidate_charts as support_load_candidate_charts, load_rating_support as support_load_rating_support, load_song_star_map as support_load_song_star_map, load_song_title_keys as support_load_song_title_keys

BASE = _ROOT

SCORELINE_PATH = BASE / "songs" / "taiko_goku_onis.json"

RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"

SONG_DATA_PATH = BASE / "songs" / "song_data.json"

@dataclass(frozen=True)
class TargetRecommendationResult:
    target_key: str
    target_display: str
    rows: List[Dict[str, Any]]
    candidate_count: int
    required_count: int
    is_enough: bool
    message: str
    userdata: Dict[str, Any]


def _build_best_entry_map(records: Iterable[Dict[str, Any]]) -> Dict[Tuple[int, int], Dict[str, Any]]:
    return support_build_best_entry_map(records)

def _load_rating_support(
    rating_path: str | Path,
) -> Tuple[
    Dict[Tuple[int, int], Dict[str, float]],
    Dict[Tuple[str, int], Dict[str, float]],
    List[Tuple[float, float]],
]:
    return support_load_rating_support(rating_path)

def _load_song_title_keys(song_data_path: str | Path) -> Dict[int, str]:
    return support_load_song_title_keys(song_data_path)

def _load_song_star_map(song_data_path: str | Path) -> Dict[Tuple[int, int], str]:
    return support_load_song_star_map(song_data_path)

def _load_candidate_charts(
    scoreline_path: str | Path,
    song_data_path: str | Path,
) -> List[Dict[str, Any]]:
    return support_load_candidate_charts(scoreline_path, song_data_path)

def _build_user_profile(records, best_map, charts, features_by_key, rating_path):
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            rating_results = compute_all_from_userdata_records(records, rating_path)
    except Exception:
        rating_results = []
    return domain_center.build_user_profile(rating_results, best_map, charts, features_by_key)

def compute_target_recommendations_from_userdata(userdata: dict, target_key: str, *, limit: int=TARGET_RECOMMENDATION_LIMIT, star_filter: str | None=None, scoreline_path: str | Path=SCORELINE_PATH, rating_path: str | Path=RATING_PATH, song_data_path: str | Path=SONG_DATA_PATH, roll_speed_ips: float=DEFAULT_ROLL_SPEED_IPS) -> TargetRecommendationResult:
    if target_key not in TARGET_DISPLAY:
        raise ValueError(f'unsupported target: {target_key}')
    normalized_star_filter = None
    if star_filter is not None:
        normalized_star_filter = parse_target_recommendation_star_filter(star_filter)
        if normalized_star_filter is None:
            raise ValueError(f'unsupported star filter: {star_filter}')
    raw_records = userdata.get('songs')
    records = raw_records if isinstance(raw_records, list) else []
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    star_by_key = _load_song_star_map(song_data_path)
    for chart in charts:
        song_id = _safe_int(chart.get('id'), -1)
        title_key = _chart_title_key(chart)
        if song_id >= 0 and title_key:
            title_keys_by_id.setdefault(song_id, title_key)
    played_title_level_keys = _build_played_title_level_keys(records, title_keys_by_id)
    features_by_key, features_by_title_level, const_table = _load_rating_support(rating_path)
    profile: Optional[UserProfile] = None
    score_reaches_by_key: Dict[Tuple[int, int], Dict[str, Any]] = {}
    if target_key in SCORE_TARGETS:
        from .score_estimator import build_score_estimator_profile, estimate_target_reach_batch
        reach_candidates = domain_selection.build_reach_candidates(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, target_key, normalized_star_filter)
        estimator_profile = build_score_estimator_profile(records, scoreline_path=scoreline_path, rating_path=rating_path, song_data_path=song_data_path)
        score_reaches_by_key = estimate_target_reach_batch(estimator_profile, reach_candidates)
    else:
        profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    selected, candidate_count = domain_selection.select_target_rows(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, const_table, profile, score_reaches_by_key, target_key, normalized_star_filter, limit)
    display = TARGET_DISPLAY[target_key]
    minimum_rows = TARGET_RECOMMENDATION_MIN_IMAGE_ROWS
    is_enough = len(selected) >= minimum_rows
    if is_enough:
        message = ''
    else:
        star_hint = f'且为「{normalized_star_filter}星」' if normalized_star_filter else ''
        message = f'这次只找到 {len(selected)}/{minimum_rows} 首适合冲「{display}」{star_hint}的候选，暂不生成推荐图。可以先更新成绩后再试，或换一个目标。'
    return TargetRecommendationResult(target_key=target_key, target_display=display, rows=selected, candidate_count=candidate_count, required_count=minimum_rows, is_enough=is_enough, message=message, userdata=userdata)
