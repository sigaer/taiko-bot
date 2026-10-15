from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from ..score_calculator import aggregate_topN_value, compute_all_from_userdata_records
from .helpers import DAN_GRADE_NAMES, iso_datetime, safe_int


RATING_BIN_MIN = 0.0
RATING_BIN_MAX = 16.0
RATING_BIN_STEP = 0.5
RANK_COUNT = 19


def _dan_grade_from_payload(payload: Any) -> int | None:
    """Return the player's current dan grade (1-19), or None when unranked.

    ``dan_name.grade`` is the currently equipped dan, while ``got_dan_max`` is
    the highest grade passed. Both use the same 1-19 scale, so the equipped dan
    is preferred and the max grade is the fallback for players who only keep
    ``got_dan_max`` populated.
    """
    profile = payload.get("profile") if isinstance(payload, dict) else None
    if not isinstance(profile, dict):
        return None
    costume = profile.get("gameCostume")
    if not isinstance(costume, dict):
        return None
    dan = costume.get("dan_name")
    if isinstance(dan, dict):
        grade = safe_int(dan.get("grade"), 0)
        if 1 <= grade <= RANK_COUNT:
            return grade
    max_grade = safe_int(costume.get("got_dan_max"), 0)
    return max_grade if 1 <= max_grade <= RANK_COUNT else None


def _color_group(order: int) -> str:
    if order < 6:
        return "low"
    if order < 13:
        return "mid"
    return "high"


def _build_rank_distribution(rank_buckets: Dict[int, list[float]]) -> Dict[str, Any]:
    """Bucket per-rank taikob20 values into a normalized ridgeline matrix.

    ``relative`` is normalized against the largest bin across all 19 ranks so the
    mountain heights remain comparable between a crowded lower rank and a sparse
    higher rank. No raw headcount is exposed.
    """
    bin_count = int(round((RATING_BIN_MAX - RATING_BIN_MIN) / RATING_BIN_STEP))
    counts: Dict[tuple[int, int], int] = {}
    global_max = 0
    for grade, ratings in rank_buckets.items():
        for rating in ratings:
            index = int((rating - RATING_BIN_MIN) / RATING_BIN_STEP)
            index = max(0, min(bin_count - 1, index))
            key = (grade, index)
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > global_max:
                global_max = counts[key]

    ranks = []
    for grade in range(1, RANK_COUNT + 1):
        bins = []
        for index in range(bin_count):
            rating_min = round(RATING_BIN_MIN + index * RATING_BIN_STEP, 4)
            rating_max = round(rating_min + RATING_BIN_STEP, 4)
            relative = round(counts.get((grade, index), 0) / global_max, 6) if global_max else 0.0
            bins.append({"ratingMin": rating_min, "ratingMax": rating_max, "relative": relative})
        ranks.append(
            {
                "key": f"grade_{grade}",
                "label": DAN_GRADE_NAMES.get(grade, str(grade)),
                "order": grade,
                "colorGroup": _color_group(grade),
                "bins": bins,
            }
        )

    return {
        "ratingMin": RATING_BIN_MIN,
        "ratingMax": RATING_BIN_MAX,
        "ratingStep": RATING_BIN_STEP,
        "ranks": ranks,
    }


def build_rating_distribution(
    userdata_dir: str | Path,
    rating_path: str | Path,
    *,
    generated_at: datetime | None = None,
) -> Dict[str, Any]:
    """Build an anonymous, four-decimal taikob20 distribution.

    Account identifiers are intentionally omitted: ranking only needs the value
    multiset, including duplicates for stable rank ranges. The 19-grade ridgeline
    distribution is derived from the same scan and carries normalized relative
    heights only.
    """

    values = []
    rank_buckets: Dict[int, list[float]] = {}
    scanned = 0
    discarded = 0
    for path in sorted(Path(userdata_dir).glob("*data.json")):
        scanned += 1
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            records = payload.get("songs", []) if isinstance(payload, dict) else payload
            if not isinstance(records, list):
                raise ValueError("songs must be a list")
            with redirect_stdout(io.StringIO()):
                results = compute_all_from_userdata_records(records, json_path=str(rating_path))
                value = float(aggregate_topN_value(results, "AI_rating", 20)) if results else 0.0
            if value <= 0:
                raise ValueError("invalid taikob20")
            rounded = round(value, 4)
            values.append(rounded)
            grade = _dan_grade_from_payload(payload)
            if grade is not None:
                rank_buckets.setdefault(grade, []).append(rounded)
        except Exception:
            discarded += 1
    values.sort(reverse=True)
    return {
        "generatedAt": iso_datetime(generated_at or datetime.now()),
        "ratings": values,
        "scannedCount": scanned,
        "discardedCount": discarded,
        "distribution": _build_rank_distribution(rank_buckets),
    }
