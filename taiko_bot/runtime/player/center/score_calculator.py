from __future__ import annotations


from sakura_taiko_core.rating.v1 import build_const_table, lookup_const_score, calc_accuracy, _calc_accuracy_for_record, calc_y, accuracy_to_score, compute_P, compute_Q, compute_AI, get_top20_weighted_average, get_top20_median, top_value_compensate, aggregate_topN_value, compute_dim_topN_means, RatingAlgorithm, ACCURACY_WEIGHTS, CN_COL_TO_ATTR, TOP20_COMPENSATE_TABLE

from sakura_taiko_core.models.calculation import SongMetrics, RatingResult, SongStats

from sakura_taiko_core.score import calculation as domain_calculation

from .taiko_domain_adapter import identity_inputs

import json

from pathlib import Path

from typing import Callable, Dict, Iterable, List, Optional, Any, Literal, Tuple, Set

from .duplicate_versions import build_duplicate_song_groups, duplicate_identity_key

PAIR_ID_GROUPS = build_duplicate_song_groups()

def load_rating_config(json_path: str | Path) -> dict:
    """
    读取 rating_structured.json：
    {
      "songs": {...},
      "const_table": {
        "const_to_score": { "1.0": 0.05, ... }
      }
    }
    """
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)

def compute_all_from_userdata_records(
    userdata_records: List[Dict[str, Any]],
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    *,
    collapse_duplicate_versions: bool = False,
) -> List[RatingResult]:
    """
    给定用户数据记录（songs 列表），计算所有曲目的综合 AI 和六维属性。
    """
    cfg = load_rating_config(json_path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)
    return _compute_results_from_userdata_records(
        userdata_records,
        cfg,
        const_table,
        collapse_duplicate_versions=collapse_duplicate_versions,
    )

def _compute_results_from_userdata_records(userdata_records, cfg, const_table, *, collapse_duplicate_versions=False):
    default_ids, _ = identity_inputs()
    return domain_calculation._compute_results_from_userdata_records(
        userdata_records, cfg, const_table, collapse_duplicate_versions=collapse_duplicate_versions,
        duplicate_groups=PAIR_ID_GROUPS, default_ids=default_ids)
