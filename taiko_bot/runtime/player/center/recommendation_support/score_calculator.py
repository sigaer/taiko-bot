from __future__ import annotations
from .paths import ROOT as _ROOT


from sakura_taiko_core.rating.v1 import build_const_table

from sakura_taiko_core.models.calculation import RatingResult

from sakura_taiko_core.score import calculation as domain_calculation

from sakura_taiko_core.recommendation import candidates as domain_candidates

from .taiko_domain_adapter import identity_inputs


import json

import os

from pathlib import Path

from typing import Dict, List, Optional, Any

from io import BytesIO

from .chart_availability import load_cn_available_chart_keys, load_on_shelf_song_ids

from .duplicate_versions import build_duplicate_song_groups

if os.environ.get("TAIKO_COMPUTE_ONLY") != "1":
    from .recommend_image import render_recommend_image_bytes

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

def build_all_stats_from_records(records, json_path="./songs/rating_structured_with_ids.json", *, collapse_duplicate_versions=True):
    cfg = load_rating_config(json_path)
    default_ids, _ = identity_inputs()
    return domain_candidates.build_all_stats_from_records(records, cfg,
        collapse_duplicate_versions=collapse_duplicate_versions, default_ids=default_ids)

def generate_recommend_image(
    recs: List[Dict[str, Any]],
    title: str = "Taiko 推荐歌曲",
    subtitle: Optional[str] = None,
    user_id: int | None = None,
    userdata: Optional[Dict[str, Any]] = None,
    font_path: Optional[str] = None,
    dpi: int = 170,
    fontsize_title: int = 20,
    fontsize_subtitle: int = 12,
    fontsize_body: int = 11,
    line_spacing: float = 1.10,  # 行距倍数：1.05~1.20 都可；你要接近 1 倍就 1.05~1.10
    left_margin: float = 0.012,
    top_margin_axes: float = 0.975,
    max_rows: Optional[int] = None,  # 可选：限制最多显示多少行（例如 30）
) -> BytesIO:
    _ = (
        dpi,
        fontsize_title,
        fontsize_subtitle,
        fontsize_body,
        line_spacing,
        left_margin,
        top_margin_axes,
    )
    if max_rows is not None and max_rows > 0:
        recs = recs[:max_rows]
    return render_recommend_image_bytes(
        recs,
        title=title,
        subtitle=subtitle,
        user_id=user_id,
        userdata=userdata,
        font_path=font_path,
    )

def recommend_songs(all_stats, songs_cfg, const_table, best_key="rating", limit=20):
    default_ids, _ = identity_inputs()
    return domain_candidates.recommend_songs(all_stats, songs_cfg, const_table, best_key, limit,
        default_ids=default_ids, cn_available_chart_keys=load_cn_available_chart_keys(),
        on_shelf_song_ids=load_on_shelf_song_ids())

def compute_recommendations_from_records(
    records: list,
    best_key: str = "rating",
    limit: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
) -> List[dict]:
    """Calculate recommendations from already authorized records."""
    all_stats, songs_cfg, const_table = build_all_stats_from_records(
        records, json_path=json_path
    )
    return recommend_songs(
        all_stats, songs_cfg, const_table, best_key=best_key, limit=limit
    )

from .recommend_image import render_recommend_image_bytes
