from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from .center import SCORE_TARGETS, FULL_COMBO_TARGET, DONDAFUL_TARGET, UserProfile, _safe_int, _safe_float, _chart_title_key, _build_owned_score_target_row_from_reach, _build_full_combo_row, _build_dondaful_row

def build_reach_candidates(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, target_key, normalized_star_filter):
    reach_candidates: List[Dict[str, Any]] = []
    for chart in charts:
        song_id = _safe_int(chart.get('id'), -1)
        key = (song_id, _safe_int(chart.get('level'), -1))
        chart_star = star_by_key.get(key, '-')
        if normalized_star_filter and chart_star != normalized_star_filter:
            continue
        entry = best_map.get(key)
        title_key = _chart_title_key(chart) or title_keys_by_id.get(song_id, '')
        if entry is None and title_key and ((title_key, key[1]) in played_title_level_keys):
            continue
        feature = features_by_key.get(key)
        if feature is None and title_key:
            feature = features_by_title_level.get((title_key, key[1]))
        rating_scores = chart.get('rating_scores')
        if not feature or not isinstance(rating_scores, dict):
            continue
        requested_score = _safe_int(rating_scores.get(target_key), 0)
        if requested_score <= 0:
            continue
        if entry and _safe_int(entry.get('high_score'), 0) >= requested_score:
            continue
        reach_candidates.append({'chart': chart, 'feature': feature, 'entry': entry, 'targets': rating_scores})
    return reach_candidates

def select_target_rows(charts, best_map, star_by_key, title_keys_by_id, played_title_level_keys, features_by_key, features_by_title_level, const_table, profile, score_reaches_by_key, target_key, normalized_star_filter, limit):
    rows: List[Dict[str, Any]] = []
    for chart in charts:
        song_id = _safe_int(chart.get('id'), -1)
        key = (song_id, _safe_int(chart.get('level'), -1))
        chart_star = star_by_key.get(key, '-')
        if normalized_star_filter and chart_star != normalized_star_filter:
            continue
        entry = best_map.get(key)
        title_key = _chart_title_key(chart) or title_keys_by_id.get(song_id, '')
        if entry is None and title_key and ((title_key, key[1]) in played_title_level_keys):
            continue
        if target_key in SCORE_TARGETS:
            row = _build_owned_score_target_row_from_reach(chart=chart, entry=entry, requested_target_key=target_key, reaches_by_target=score_reaches_by_key.get(key, {}))
        else:
            feature = features_by_key.get(key)
            if feature is None and title_key:
                feature = features_by_title_level.get((title_key, key[1]))
            if feature is None:
                assert profile is not None
                feature = {'const': profile.difficulty_capacity, 'stamina': profile.dim_capacity.get('stamina', 50.0), 'speed': profile.dim_capacity.get('speed', 50.0), 'rhythm': profile.dim_capacity.get('rhythm', 50.0), 'complex': profile.dim_capacity.get('complex', 50.0), 'hs_change': 0.0}
        if target_key == FULL_COMBO_TARGET:
            assert profile is not None
            row = _build_full_combo_row(chart=chart, entry=entry, profile=profile, feature=feature, const_table=const_table)
        elif target_key == DONDAFUL_TARGET:
            assert profile is not None
            row = _build_dondaful_row(chart=chart, entry=entry, profile=profile, feature=feature, const_table=const_table)
        if row is not None:
            if target_key in {FULL_COMBO_TARGET, DONDAFUL_TARGET} and _safe_float(row.get('recommend_index'), 0.0) <= 0.0:
                continue
            row['star'] = chart_star
            rows.append(row)
    if target_key == FULL_COMBO_TARGET:
        rows.sort(key=lambda row: (-float(row.get('recommend_index', 0.0) or 0.0), bool(row.get('is_unplayed')), _safe_int(row.get('_sort_gap_primary'), 10 ** 9), _safe_int(row.get('_sort_gap_secondary'), 10 ** 9), str(row.get('title', ''))))
    elif target_key == DONDAFUL_TARGET:
        rows.sort(key=lambda row: (-float(row.get('recommend_index', 0.0) or 0.0), bool(row.get('is_unplayed')), _safe_int(row.get('_sort_gap_primary'), 10 ** 9), _safe_int(row.get('_sort_gap_secondary'), 10 ** 9), str(row.get('title', ''))))
    else:
        rows.sort(key=lambda row: (-float(row.get('recommend_likelihood', row.get('recommend_index', 0.0)) or 0.0), -float(row.get('target_band_likelihood', row.get('target_band_index', 0.0)) or 0.0), str(row.get('title', ''))))
    required = max(1, int(limit))
    selected = rows[:required]
    for row in selected:
        for key in tuple(row.keys()):
            if key.startswith('_'):
                row.pop(key, None)
    return (selected, len(rows))
