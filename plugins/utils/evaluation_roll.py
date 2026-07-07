from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


ROTTER_TARMINATION_BALLOON_ROLL_SECONDS = 4.6


@dataclass(frozen=True)
class SpecialBalloonOverride:
    hits: int
    seconds: float


_SPECIAL_BALLOON_OVERRIDES: Dict[tuple[int, int], Tuple[SpecialBalloonOverride, ...]] = {
    (311, 4): (SpecialBalloonOverride(hits=444, seconds=0.501),),
    (402, 4): (SpecialBalloonOverride(hits=999, seconds=ROTTER_TARMINATION_BALLOON_ROLL_SECONDS),),
    (402, 5): (SpecialBalloonOverride(hits=766, seconds=ROTTER_TARMINATION_BALLOON_ROLL_SECONDS),),
    (890, 4): (SpecialBalloonOverride(hits=938, seconds=4.171),),
    (1066, 4): (SpecialBalloonOverride(hits=765, seconds=1.101),),
    (1350, 4): (SpecialBalloonOverride(hits=390, seconds=2.178),),
    (1367, 4): (SpecialBalloonOverride(hits=876, seconds=2.836),),
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _normalize_balloons(raw: Any) -> list[int]:
    if not isinstance(raw, list):
        return []
    return [_safe_int(item, -1) for item in raw if _safe_int(item, -1) >= 0]


@dataclass(frozen=True)
class RatingRollBreakdown:
    raw_roll_seconds: float
    raw_roll_hits: int
    raw_balloon_hits: int
    preserved_balloon_hits: int
    replaced_balloon_hits: int
    special_balloon_seconds: float
    special_balloon_hits: int
    effective_balloon_hits: int
    effective_roll_hits: int
    adjusted: bool


def _special_balloon_override(entry: Dict[str, Any]) -> tuple[int, float]:
    song_id = _safe_int(entry.get("id"), -1)
    level = _safe_int(entry.get("level"), -1)
    overrides = _SPECIAL_BALLOON_OVERRIDES.get((song_id, level))
    if not overrides:
        return 0, 0.0

    target_hits = tuple(max(0, override.hits) for override in overrides)
    balloons = _normalize_balloons(entry.get("balloons"))
    if balloons:
        replaced_hits = sum(value for value in balloons if value in target_hits)
    else:
        replaced_hits = sum(target_hits)
        if _safe_int(entry.get("balloon_hits"), 0) < replaced_hits:
            return 0, 0.0

    if replaced_hits <= 0:
        return 0, 0.0
    replaced_seconds = sum(
        max(0.0, override.seconds)
        for override in overrides
        if override.hits in target_hits
    )
    return replaced_hits, replaced_seconds


def compute_rating_roll_breakdown(
    entry: Dict[str, Any],
    speed_ips: float,
) -> RatingRollBreakdown:
    raw_roll_seconds = max(0.0, _safe_float(entry.get("roll_total_seconds"), 0.0))
    raw_roll_hits = max(0, int(round(raw_roll_seconds * speed_ips)))
    raw_balloon_hits = max(0, _safe_int(entry.get("balloon_hits"), 0))

    replaced_balloon_hits, special_balloon_seconds = _special_balloon_override(entry)
    replaced_balloon_hits = min(raw_balloon_hits, max(0, replaced_balloon_hits))
    preserved_balloon_hits = max(0, raw_balloon_hits - replaced_balloon_hits)
    special_balloon_hits = (
        max(0, int(round(special_balloon_seconds * speed_ips)))
        if special_balloon_seconds > 0
        else 0
    )
    effective_balloon_hits = preserved_balloon_hits + special_balloon_hits
    effective_roll_hits = raw_roll_hits + effective_balloon_hits

    return RatingRollBreakdown(
        raw_roll_seconds=raw_roll_seconds,
        raw_roll_hits=raw_roll_hits,
        raw_balloon_hits=raw_balloon_hits,
        preserved_balloon_hits=preserved_balloon_hits,
        replaced_balloon_hits=replaced_balloon_hits,
        special_balloon_seconds=special_balloon_seconds,
        special_balloon_hits=special_balloon_hits,
        effective_balloon_hits=effective_balloon_hits,
        effective_roll_hits=effective_roll_hits,
        adjusted=replaced_balloon_hits > 0,
    )
