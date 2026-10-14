from __future__ import annotations


from sakura_taiko_core.models.calculation import V2RatingResult, FullScoreRef

from sakura_taiko_core.rating.v2 import V2_COL_TO_ATTR

from sakura_taiko_core.rating import v2 as domain_v2

from sakura_taiko_core.score import v2 as domain_score_v2

from .taiko_domain_adapter import identity_inputs

from functools import lru_cache, partial

from pathlib import Path

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .memory import bounded_memoize, budget, rating_result_bytes

from .b30_render import render_b30_image

from sakura_taiko_core.models.calculation import V2SongData

ROOT_DIR = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

V2_DIM_COLUMNS = ["体力", "手速", "爆发", "精度", "节奏", "复合"]

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
}

V2_TREND_SHORT_LABELS = {
    "体力": "体力",
    "手速": "手速",
    "爆发": "爆发",
    "精度": "精度",
    "节奏": "节奏",
    "复合": "复合",
    "综合Rating": "综合",
}

V2_TREND_COLORS = {
    "体力": "#F28E2B",
    "手速": "#E15759",
    "爆发": "#B07AA1",
    "精度": "#76B7B2",
    "节奏": "#59A14F",
    "复合": "#4E79A7",
    "综合Rating": "#111111",
}

def _calculate_v2_from_chart(chart, *, accuracy_per, bad_per):
    return domain_v2._calculate_v2_from_chart(chart, accuracy_per=accuracy_per, bad_per=bad_per,
        profile="v2-center-20261010")

@bounded_memoize("taiko.rating_v2", 100_000,
                 budget("TAIKO_V2_CACHE_MAX_BYTES", 64 * 1024**2),
                 weight=rating_result_bytes)
def _calculate_v2_from_chart_cached(
    chart: V2SongData,
    accuracy_per: float,
    bad_per: float,
) -> V2RatingResult:
    return _calculate_v2_from_chart(
        chart,
        accuracy_per=accuracy_per,
        bad_per=bad_per,
    )

def _build_result_from_entry(entry, song_map):
    return domain_score_v2.result_from_entry(entry, song_map, profile="v2-center-20261010",
        calculate=_calculate_v2_from_chart_cached)

def compute_all_v2_from_userdata_records(userdata_records, *, song_map):
    active_song_map = song_map
    default_ids, _ = identity_inputs()
    return domain_score_v2.compute_all_v2_from_userdata_records(userdata_records,
        song_map=active_song_map, profile="v2-center-20261010", default_ids=default_ids,
        calculate=_calculate_v2_from_chart_cached)

def _extract_userdata_records(payload: Any) -> List[Dict[str, Any]]:
    records = payload.get("songs", []) if isinstance(payload, dict) else payload
    return records if isinstance(records, list) else []

@lru_cache(maxsize=4)
def _calc_full_score_refs_for_snapshot(revision, songs):
    return domain_v2._calc_full_score_refs_for_snapshot(revision, songs, profile="v2-center-20261010")

def _calc_full_score_refs(snapshot) -> Dict[str, FullScoreRef]:
    return _calc_full_score_refs_for_snapshot(
        snapshot.revision,
        tuple(snapshot.song_map.values()),
    )

def aggregate_topN_value_v2(results, col, N, *, snapshot):
    return domain_v2.aggregate_topN_value_v2(results, col, N,
        full_score_refs=_calc_full_score_refs(snapshot) if N == 20 and results else None)

def compute_dim_topN_means_v2(results, N=20, *, snapshot):
    return domain_v2.compute_dim_topN_means_v2(results, N,
        full_score_refs=_calc_full_score_refs(snapshot) if N == 20 and results else None)

def render_b20_v2_image(user_id: int | str, N: int = 20, *, userdata, snapshot, **prepared) -> bytes:
    payload = userdata
    current_results = compute_all_v2_from_userdata_records(
        _extract_userdata_records(payload),
        song_map=snapshot.song_map,
    )
    rating_map = {
        (result.song_id, result.level): float(result.AI_rating)
        for result in current_results
    }

    def entry_rating_getter(entry: Dict[str, Any]) -> Optional[float]:
        try:
            key = (int(entry.get("song_no", 0)), int(entry.get("level", 0)))
        except Exception:
            return None
        value = rating_map.get(key)
        if value is not None:
            return value
        result = _build_result_from_entry(entry, snapshot.song_map)
        return float(result.AI_rating) if result is not None else None

    return render_b30_image(
        user_id,
        N=N,
        userdata=userdata, **prepared,
        rating_label=f"Rating b{N} v2",
        results_from_userdata_fn=lambda _: current_results,
        results_from_records_fn=lambda records: compute_all_v2_from_userdata_records(records,song_map=snapshot.song_map),
        aggregate_topn_value_fn=partial(aggregate_topN_value_v2,snapshot=snapshot),
        compute_dim_topn_means_fn=partial(compute_dim_topN_means_v2,snapshot=snapshot),
        trend_dim_columns=V2_DIM_COLUMNS,
        trend_short_labels=V2_TREND_SHORT_LABELS,
        trend_colors=V2_TREND_COLORS,
        entry_rating_getter=entry_rating_getter,
        card_rating_resolver=entry_rating_getter,
        min_level=3,
    )

def render_b20_v2_dim_image(
    user_id: int | str,
    dim: str,
    N: int = 20,
    font_path: str | None = "assets/fonts/DDFont.ttf",
    *, userdata, snapshot,
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
    current_results = compute_all_v2_from_userdata_records(
        _extract_userdata_records(payload),
        song_map=snapshot.song_map,
    )

    normalized_rows: List[Dict[str, Any]] = []
    for result in current_results:
        value = getattr(result, attr, None)
        if value is None:
            continue
        normalized_rows.append(
            {
                "song_id": int(result.song_id),
                "level": int(result.level),
                "title": str(result.song_name or ""),
                "score": int(result.high_score or 0),
                "accuracy_rate": float(result.accuracy or 0.0) * 100.0,
                "dim_score": float(value),
            }
        )

    normalized_rows.sort(key=lambda row: (-row["dim_score"], -row["score"], row["title"]))
    top_rows = normalized_rows[: max(1, int(N))]
    if not top_rows:
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
        title_text=f"{dim} best{len(top_rows)} (v2)",
        rows=top_rows,
        assets_base=ROOT_DIR / "assets",
        font_path=font_path,
        dim_label=dim,
    )
