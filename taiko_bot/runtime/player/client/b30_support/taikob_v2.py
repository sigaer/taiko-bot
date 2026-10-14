from __future__ import annotations


from ..recommendation_support import catalog as _domain

from sakura_taiko_core.models import calculation as _models

from sakura_taiko_core.score import v2 as _v2_records

from sakura_taiko_core.parser import client_dataset as _dataset

import csv

from functools import lru_cache

from typing import Any, Dict, List

from taiko_bot.settings import get_settings

ROOT_DIR = get_settings().root_dir

V2_CONSTANTS_CSV = ROOT_DIR / "songs" / "constants_id_v2.csv"

V2_TAIKOB_DIM_ALIASES = {
    "体力": "体力",
    "stamina": "体力",
    "手速": "手速",
    "高速": "手速",
    "高速处理": "手速",
    "handspeed": "手速",
    "speed": "手速",
    "爆发": "爆发",
    "爆发力": "爆发",
    "burst": "爆发",
    "精度": "精度",
    "精度力": "精度",
    "accuracy": "精度",
    "accuracy_power": "精度",
    "节奏": "节奏",
    "节奏处理": "节奏",
    "rhythm": "节奏",
    "复合": "复合",
    "复合处理": "复合",
    "complex": "复合",
    "综合": "综合Rating",
    "综合rating": "综合Rating",
    "rating": "综合Rating",
}

V2_COL_TO_ATTR = {
    "综合Rating": "AI_rating",
    "体力": "stamina_rt",
    "手速": "handspeed_rt",
    "爆发": "burst_rt",
    "精度": "accuracy_rt",
    "节奏": "rhythm_rt",
    "复合": "complex_rt",
}

V2RatingResult = _models.V2RatingResult

@lru_cache(maxsize=1)
def _load_v2_song_map():
    with V2_CONSTANTS_CSV.open("r", encoding="utf-8") as handle:
        return _dataset.v2_client_song_map(csv.DictReader(handle))

def _extract_userdata_records(payload: Any) -> List[Dict[str, Any]]:
    records = payload.get("songs", []) if isinstance(payload, dict) else payload
    return records if isinstance(records, list) else []

def compute_all_v2_from_userdata_records(userdata_records):
    defaults, _, _ = _domain.identity_inputs()
    return _v2_records.compute_all_v2_from_userdata_records(userdata_records,
        song_map=_load_v2_song_map(), profile="v2-client-20261010", default_ids=defaults)

def _build_dimension_rows(
    results: List[V2RatingResult],
    *,
    attr: str,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for result in results:
        dim_score = getattr(result, attr, None)
        if dim_score is None:
            continue
        rows.append(
            {
                "song_id": int(result.song_id),
                "level": int(result.level),
                "title": str(result.song_name or ""),
                "score": int(result.high_score or 0),
                "accuracy_rate": float(result.accuracy or 0.0) * 100.0,
                "dim_score": float(dim_score),
            }
        )
    rows.sort(key=lambda row: (-row["dim_score"], -row["score"], row["title"]))
    return rows

def render_b20_v2_image(user_id: int | str, *, userdata) -> bytes:
    payload = userdata
    userdata = payload if isinstance(payload, dict) else {"songs": payload}
    results = compute_all_v2_from_userdata_records(_extract_userdata_records(payload))
    rows = _build_dimension_rows(results, attr="AI_rating")[:20]

    from .dimension import _render_dimension_table_image, _render_simple_notice

    if not rows:
        return _render_simple_notice(
            "taikob20 v2 暂无可展示的数据。",
            1060,
            24,
            "assets/fonts/DDFont.ttf",
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    return _render_dimension_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"综合Rating best{len(rows)} (v2)",
        rows=rows,
        assets_base=ROOT_DIR / "assets",
        font_path="assets/fonts/DDFont.ttf",
        dim_label="综合Rating",
    )

def render_b20_v2_dim_image(
    user_id: int | str,
    dim: str,
    N: int = 20,
    font_path: str | None = "assets/fonts/DDFont.ttf",
    *, userdata,
) -> bytes:
    attr = V2_COL_TO_ATTR.get(dim)
    from .dimension import _render_dimension_table_image, _render_simple_notice

    if not attr:
        return _render_simple_notice(
            f"不支持的维度：{dim}",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    payload = userdata
    userdata = payload if isinstance(payload, dict) else {"songs": payload}
    results = compute_all_v2_from_userdata_records(_extract_userdata_records(payload))
    rows = _build_dimension_rows(results, attr=attr)[: max(1, int(N))]
    if not rows:
        return _render_simple_notice(
            f"{dim}暂无可展示的数据。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    return _render_dimension_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"{dim} best{len(rows)} (v2)",
        rows=rows,
        assets_base=ROOT_DIR / "assets",
        font_path=font_path,
        dim_label=dim,
    )
