from __future__ import annotations
from typing import Any, Dict, Iterable, List, Literal
from sakura_taiko_core.rating.v1 import aggregate_topN_value, compute_dim_topN_means
from .context import RecommendationContext

MODEL = "v1"
RATING_AGGREGATION = "per-dimension-top20"
RATING_TOP_N = 20
RATING_DUPLICATE_HANDLING = "preserve"
ORDINARY_BASIS = (
    "rating",
    "big_song",
    "stamina",
    "speed",
    "accuracy_power",
    "rhythm",
    "complex",
)
TARGET_KEYS = ("goku", "ziya", "fenya", "jinya", "full_combo", "dondaful")
DimensionKey = Literal[
    "big_song", "stamina", "speed", "accuracy_power", "rhythm", "complex"
]
DIMENSION_COLUMNS: tuple[tuple[DimensionKey, str], ...] = (
    ("big_song", "大歌力"),
    ("stamina", "体力"),
    ("speed", "高速处理"),
    ("accuracy_power", "精度力"),
    ("rhythm", "节奏处理"),
    ("complex", "复合处理"),
)


def _round(value: Any, digits: int = 6) -> float:
    return round(float(value or 0.0), digits)


def project_player_rating(context: RecommendationContext):
    results = context.rating_results
    overall = (
        aggregate_topN_value(results, "AI_rating", RATING_TOP_N) if results else 0.0
    )
    dimensions = compute_dim_topN_means(results, RATING_TOP_N) if results else {}
    return {
        "model": MODEL,
        "aggregation": RATING_AGGREGATION,
        "topN": RATING_TOP_N,
        "duplicateHandling": RATING_DUPLICATE_HANDLING,
        "overallRating": _round(overall) if overall > 0 else None,
        "sampleCount": len(results),
        "dimensions": [
            {"key": key, "value": _round(dimensions.get(column, 0.0))}
            for key, column in DIMENSION_COLUMNS
        ],
    }


def project_ordinary_recommendations(context: RecommendationContext):
    rows, basis = context.rows, context.basis
    if basis not in ORDINARY_BASIS:
        raise ValueError(f"unsupported ordinary recommendation basis: {basis}")
    items = []
    for row in rows:
        song_id = int(row.get("song_id", 0) or 0)
        level = int(row.get("level", 0) or 0)
        if song_id <= 0 or level <= 0:
            continue
        items.append(
            {
                "songId": song_id,
                "level": level,
                "title": str(row.get("title", "") or ""),
                "isUnplayed": bool(row.get("is_unplayed", False)),
                "candidateIndicator": _round(row.get("song_indicator", 0.0)),
                "referenceIndicator": _round(row.get("reference_indicator", 0.0)),
                "deviationRatio": _round(row.get("indicator_deviation_percent", 0.0)),
                "inStrictRange": bool(row.get("is_in_strict_range", False)),
            }
        )
    return {"model": MODEL, "basis": basis, "items": items}


def project_target_recommendations(context: RecommendationContext):
    result = context.target_result
    items: List[Dict[str, Any]] = []
    for row in result.rows:
        song_id = int(row.get("song_id", 0) or 0)
        level = int(row.get("level", 0) or 0)
        if song_id <= 0 or level <= 0:
            continue
        target_score = row.get("target_score")
        gap_value = row.get("gap_value")
        items.append(
            {
                "songId": song_id,
                "level": level,
                "star": str(row.get("star", "-") or "-"),
                "title": str(row.get("title", "") or ""),
                "currentScore": (
                    int(row["score"]) if row.get("score") is not None else None
                ),
                "targetScore": int(target_score) if target_score is not None else None,
                "targetKey": result.target_key,
                "gapKind": str(row.get("gap_kind", "unplayed") or "unplayed"),
                "gapValue": int(gap_value) if gap_value is not None else None,
                "progressPercent": _round(row.get("progress", 0.0), 2),
                "targetRecommendationIndex": _round(row.get("recommend_index", 0.0), 2),
                "isUnplayed": bool(row.get("is_unplayed", False)),
            }
        )
    return {
        "model": MODEL,
        "target": result.target_key,
        "candidateCount": int(result.candidate_count),
        "requiredCount": int(result.required_count),
        "isEnough": bool(result.is_enough),
        "items": items,
    }
