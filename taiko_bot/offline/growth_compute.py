from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from taiko_store import PublicationError

os.environ["TAIKO_COMPUTE_ONLY"] = "1"
PROCESS_STARTED_AT = time.perf_counter()
from taiko_bot.offline import score_calculator as score
IMPORT_COMPLETE_AT = time.perf_counter()

DIMENSIONS = (("big_song", "大歌力"), ("stamina", "体力"), ("speed", "高速处理"), ("accuracy_power", "精度力"), ("rhythm", "节奏处理"), ("complex", "复合处理"))
DIMENSION_ORDER = {key: index for index, (key, _) in enumerate(DIMENSIONS)}

class _AggregateRow:
    def __init__(self, item):
        self.AI_rating = item.rating
        self.big_song = item.daigouryoku
        self.stamina = item.stamina
        self.speed = item.speed
        self.accuracy_power = item.accuracy_power
        self.rhythm = item.rhythm
        self.complex_proc = item.complex

def _round(value: Any, digits: int = 6) -> float:
    return round(float(value or 0.0), digits)

def _project(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projected = []
    for row in items:
        song_id = int(row.get("song_id", 0) or 0)
        level = int(row.get("level", 0) or 0)
        if song_id <= 0 or level <= 0:
            continue
        projected.append({"songId": song_id, "level": level, "title": str(row.get("title", "") or ""), "isUnplayed": bool(row.get("is_unplayed", False)), "candidateIndicator": _round(row.get("song_indicator", 0.0)), "referenceIndicator": _round(row.get("reference_indicator", 0.0)), "deviationRatio": _round(row.get("indicator_deviation_percent", 0.0)), "inStrictRange": bool(row.get("is_in_strict_range", False))})
    return projected

def _priority(dimensions: dict[str, float], sample_count: int, data_mode: str):
    sufficiency = "insufficient" if data_mode == "INSUFFICIENT" or sample_count <= 0 else "ready" if sample_count >= 20 else "limited"
    valid = [(key, value) for key, value in dimensions.items() if value > 0]
    valid.sort(key=lambda item: (item[1], DIMENSION_ORDER[item[0]]))
    if not valid or sufficiency == "insufficient":
        return None, [], sufficiency, "insufficient-evidence"
    minimum = valid[0][1]
    tied = [key for key, value in valid if abs(value - minimum) <= 1e-6]
    return valid[0][0], tied, sufficiency, "lowest-valid-dimension"

def compute_growth(user_id: int, *, data_mode: str = "FULL_HISTORY", limit: int = 3) -> dict[str, Any]:
    analysis_started_at = time.perf_counter()
    all_stats, songs_cfg, const_table = score.build_all_stats_for_user(user_id, collapse_duplicate_versions=False)
    stats = score.collapse_stats_for_recommendation(all_stats)
    analysis_duration_ms = (time.perf_counter() - analysis_started_at) * 1000
    rated_stats = [_AggregateRow(item) for item in all_stats if float(item.rating) > 0 and item.level >= 4]
    aggregation_started_at = time.perf_counter()
    dimensions = {key: _round(score.aggregate_topN_value(rated_stats, column, 20)) for key, column in DIMENSIONS}
    overall = _round(score.aggregate_topN_value(rated_stats, "AI_rating", 20)) if rated_stats else None
    priority, tied, sufficiency, basis = _priority(dimensions, len(rated_stats), data_mode)
    aggregation_duration_ms = (time.perf_counter() - aggregation_started_at) * 1000
    recommendation_basis = priority if sufficiency == "ready" and priority else "rating"
    ranking_started_at = time.perf_counter()
    recommendations = score.recommend_songs(stats, songs_cfg, const_table, best_key=recommendation_basis, limit=limit)
    ranking_duration_ms = (time.perf_counter() - ranking_started_at) * 1000
    used_fallback = recommendation_basis == "rating"
    fallback_duration_ms = 0.0
    if priority and sufficiency == "ready" and not recommendations:
        fallback_started_at = time.perf_counter()
        recommendations = score.recommend_songs(stats, songs_cfg, const_table, best_key="rating", limit=limit)
        fallback_duration_ms = (time.perf_counter() - fallback_started_at) * 1000
        used_fallback = True
        recommendation_basis = "rating"
    return {"playerState": {"overallRating": overall, "dimensions": [{"key": key, "value": dimensions[key]} for key, _ in DIMENSIONS], "priorityDimension": priority, "tiedDimensions": tied, "dataSufficiency": sufficiency, "basis": basis, "sampleCount": len(rated_stats)}, "todayPlan": {"basis": recommendation_basis, "mode": "general-fallback" if used_fallback else "dimension", "usedFallback": used_fallback, "items": _project(recommendations[:limit])}, "timing": {"startupImportMs": round((IMPORT_COMPLETE_AT - PROCESS_STARTED_AT) * 1000, 2), "analysisBuildMs": round(analysis_duration_ms, 2), "stateAggregationMs": round(aggregation_duration_ms, 2), "rankingMs": round(ranking_duration_ms, 2), "fallbackRankingMs": round(fallback_duration_ms, 2)}}

def main() -> int:
    parser = argparse.ArgumentParser(description="Lightweight Viewer Growth compute bridge")
    parser.add_argument("growth")
    parser.add_argument("--user", type=int, required=True)
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--data-mode", default="FULL_HISTORY")
    args = parser.parse_args()
    payload = compute_growth(args.user, data_mode=args.data_mode, limit=max(1, min(10, args.limit)))
    serialization_started_at = time.perf_counter()
    json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    serialization_duration_ms = (time.perf_counter() - serialization_started_at) * 1000
    payload["timing"]["serializationMs"] = round(serialization_duration_ms, 2)
    payload["timing"]["totalPythonMs"] = round((time.perf_counter() - PROCESS_STARTED_AT) * 1000, 2)
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    return 0

def entrypoint():
    try:
        return main()
    except PublicationError:
        print("Score publication is unavailable", file=sys.stderr)
        return 75


if __name__ == "__main__":
    raise SystemExit(entrypoint())
