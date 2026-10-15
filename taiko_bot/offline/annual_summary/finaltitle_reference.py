"""Frozen population reference for the FinalTitle personality model.

The Copy-3A audit model is *population-relative*: every dimension is a mid-rank
percentile inside the annual population (and the style signals are additionally
residualised inside volume / rating deciles).  The per-user generator has no
access to the population, so the reference is frozen into a versioned data file
that ships with the algorithm:

    plugins/utils/annual_summary/data/finaltitle_reference_v1.json

Regenerate it with::

    python3 -m taiko_bot.offline.annual_summary finaltitle-reference \
        --corpus <dir of built summaries> --output <file>

``TAIKO_FINALTITLE_REFERENCE`` overrides the path (used by the regression
harness to reproduce the exact audit population).

Everything here is pure data + rank math -- no behaviour is invented at runtime.
"""
from __future__ import annotations

import bisect
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

REFERENCE_VERSION = "finaltitle-reference-v1"
DEFAULT_REFERENCE_PATH = Path(__file__).resolve().parent / "data" / "finaltitle_reference_v1.json"
REFERENCE_ENV = "TAIKO_FINALTITLE_REFERENCE"
BUCKETS = 10

#: residual columns keyed by feature name (volume-controlled)
RESIDUAL_COLUMNS = (
    "charts_per_play",
    "months_per_active",
    "obsession_share",
    "favorite_share",
    "challenge_share",
    "late_share",
    "dondaful_share",
    "full_combo_share",
    "near_ok",
    "milestones",
)
#: residual columns keyed by feature name (rating-controlled)
RESIDUAL_SKILL_COLUMNS = ("pound_speed", "hardship")
#: plain percentile columns
PERCENTILE_COLUMNS = ("play", "days", "rating", "streak", "speed_pref", "kiwami")
#: percentile columns whose population is "present values only"
PRESENT_ONLY_COLUMNS = ("speed_pref", "kiwami")
#: percentile columns filled with the population median when missing
MEDIAN_FILLED_COLUMNS = ("days", "rating")


def _percentile_in_sorted(sorted_values: Sequence[float], value: float) -> Optional[float]:
    """Mid-rank percentile of ``value`` inside an already sorted population.

    Values are compared at the stored precision (6 decimals) so a lookup never
    misses its own tie block because of float formatting noise.
    """
    total = len(sorted_values)
    if not total:
        return None
    value = round(float(value), 6)
    less = bisect.bisect_left(sorted_values, value)
    equal = bisect.bisect_right(sorted_values, value) - less
    if equal == 0:
        # Not a member: rank it as if inserted (fractional position).
        rank = less + 0.5
    else:
        rank = less + (equal + 1) / 2
    return (rank - 0.5) / total


class FinalTitleReference:
    """Loaded frozen reference; all lookups are pure functions of the payload."""

    def __init__(self, payload: Dict[str, Any]):
        if payload.get("version") != REFERENCE_VERSION:
            raise ValueError(f"unsupported finaltitle reference: {payload.get('version')!r}")
        self.payload = payload
        self.population_size = int((payload.get("population") or {}).get("size") or 0)
        self.columns: Dict[str, List[float]] = {
            key: [float(value) for value in (payload.get("columns") or {}).get(key) or []]
            for key in PERCENTILE_COLUMNS
        }
        self.medians: Dict[str, float] = {
            str(key): float(value) for key, value in (payload.get("medians") or {}).items()
        }
        self.dan_level_percentile: Dict[int, float] = {
            int(key): float(value) for key, value in (payload.get("danLevelPercentile") or {}).items()
        }
        self.residual: Dict[str, List[Dict[str, Any]]] = (payload.get("residual") or {})
        self.residual_skill: Dict[str, List[Dict[str, Any]]] = (payload.get("residualSkill") or {})

    # ------------------------------------------------------------------ ranks
    def median(self, column: str) -> Optional[float]:
        """Population median of the *present* values (audit fills missing with it)."""
        if column in self.medians:
            return self.medians[column]
        values = self.columns.get(column) or []
        if not values:
            return None
        return values[len(values) // 2]

    def percentile(self, column: str, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        return _percentile_in_sorted(self.columns.get(column, []), float(value))

    def _bucket_for(self, buckets: List[Dict[str, Any]], control: Optional[float]) -> Optional[Dict[str, Any]]:
        if not buckets or control is None:
            return None
        for bucket in buckets:
            low = bucket.get("lo")
            high = bucket.get("hi")
            if low is not None and control < low:
                continue
            if high is not None and control > high:
                continue
            return bucket
        # Outside every bucket range (possible with duplicated edges): nearest by distance.
        def distance(bucket: Dict[str, Any]) -> float:
            low, high = bucket.get("lo"), bucket.get("hi")
            if low is not None and control < low:
                return low - control
            if high is not None and control > high:
                return control - high
            return 0.0

        return min(buckets, key=distance)

    def _residual_from(
        self, table: Dict[str, List[Dict[str, Any]]], column: str, control: Optional[float], value: Optional[float]
    ) -> Optional[float]:
        if value is None or control is None:
            return None
        bucket = self._bucket_for(table.get(column) or [], control)
        if not bucket:
            return None
        values = [float(item) for item in bucket.get("values") or []]
        if len(values) < 40:
            return None
        return _percentile_in_sorted(values, float(value))

    def residual_percentile(self, column: str, volume: Optional[float], value: Optional[float]) -> Optional[float]:
        return self._residual_from(self.residual, column, volume, value)

    def residual_skill_percentile(self, column: str, rating: Optional[float], value: Optional[float]) -> Optional[float]:
        return self._residual_from(self.residual_skill, column, rating, value)

    def dan_level_rank(self, dan_id: Optional[int]) -> float:
        if not dan_id or dan_id <= 0:
            return 0.0
        return float(self.dan_level_percentile.get(int(dan_id), 0.0))

    def fingerprint(self) -> str:
        return str((self.payload.get("population") or {}).get("fingerprint") or self.payload.get("builtAt") or "")


_CACHE: Dict[str, FinalTitleReference] = {}


def reference_path() -> Path:
    override = os.environ.get(REFERENCE_ENV)
    return Path(override) if override else DEFAULT_REFERENCE_PATH


def load_reference(path: Optional[str | Path] = None) -> FinalTitleReference:
    resolved = Path(path) if path else reference_path()
    key = str(resolved)
    if key not in _CACHE:
        with resolved.open("r", encoding="utf-8") as handle:
            _CACHE[key] = FinalTitleReference(json.load(handle))
    return _CACHE[key]

# ---------------------------------------------------------------- builder
def _ranks(values: Sequence[float]) -> List[float]:
    """Average ranks (1-based) with ties, identical to the audit ``rank()``."""
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(order):
        end = index
        while end + 1 < len(order) and values[order[end + 1]] == values[order[index]]:
            end += 1
        average = (index + end) / 2 + 1
        for position in range(index, end + 1):
            ranks[order[position]] = average
        index = end + 1
    return ranks


def _percentiles(values: Sequence[float]) -> List[float]:
    if not values:
        return []
    total = len(values)
    return [(rank - 0.5) / total for rank in _ranks(list(values))]


def _median(values: Sequence[float]) -> Optional[float]:
    present = sorted(value for value in values if value is not None)
    if not present:
        return None
    middle = len(present) // 2
    if len(present) % 2:
        return float(present[middle])
    return (present[middle - 1] + present[middle]) / 2


def _deciles(control: Sequence[float], signal: Sequence[Optional[float]]) -> List[Dict[str, Any]]:
    """Present values of ``signal`` bucketed into equal-count deciles of ``control``."""
    present = [index for index, value in enumerate(signal) if value is not None]
    buckets: List[Dict[str, Any]] = []
    if len(present) < 40:
        return buckets
    order = sorted(present, key=lambda index: control[index])
    size = max(1, -(-len(order) // BUCKETS))
    for start in range(0, len(order), size):
        members = order[start:start + size]
        controls = [control[index] for index in members]
        buckets.append({
            "lo": round(min(controls), 6),
            "hi": round(max(controls), 6),
            # sorted by signal value: the lookup uses mid-rank percentiles
            "values": sorted(round(float(signal[index]), 6) for index in members),
        })
    return buckets


def build_reference(
    feature_rows: Sequence[Dict[str, Any]],
    *,
    attained_dan_by_id: Optional[Dict[str, int]] = None,
    source: str = "",
    fingerprint: str = "",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Compute the frozen reference from a population of extracted feature rows."""
    rows = list(feature_rows)
    if not rows:
        raise ValueError("finaltitle reference needs a non-empty population")

    play = [float(row.get("play_count") or 0) for row in rows]
    # the audit treats a falsy active_days (0 / missing) as "no calendar data"
    raw_days = [row.get("active_days") or None for row in rows]
    days_median = _median([value for value in raw_days if value is not None])
    days = [float(value if value is not None else (days_median or 0)) for value in raw_days]
    raw_rating = [row.get("rating") for row in rows]
    rating_median = _median([value for value in raw_rating if value is not None])
    rating = [float(value if value is not None else (rating_median or 0)) for value in raw_rating]
    streak = [float(row.get("longest_streak") or 0) for row in rows]
    speed_pref = [row.get("speed") for row in rows]
    kiwami = [float(row.get("kiwami_charts") or 0) for row in rows]

    play_pct = _percentiles(play)
    days_pct = _percentiles(days)
    volume = [(a + b) / 2 for a, b in zip(play_pct, days_pct)]
    rating_control = _percentiles(rating)

    def ratio(part: Any, whole: Any) -> Optional[float]:
        try:
            part_value = float(part)
            whole_value = float(whole)
        except (TypeError, ValueError):
            return None
        return (part_value / whole_value) if whole_value else None

    signals: Dict[str, List[Optional[float]]] = {
        "charts_per_play": [ratio(row.get("unique_charts"), row.get("play_count")) for row in rows],
        "months_per_active": [ratio(row.get("monthly_count"), row.get("active_days")) for row in rows],
        "obsession_share": [ratio(row.get("obsession_days"), row.get("active_days")) for row in rows],
        "favorite_share": [ratio(row.get("favorite_plays"), row.get("play_count")) for row in rows],
        "challenge_share": [ratio(row.get("challenge_plays"), row.get("play_count")) for row in rows],
        "late_share": [ratio(row.get("late_days"), row.get("active_days")) for row in rows],
        "dondaful_share": [row.get("dondaful_share") for row in rows],
        "full_combo_share": [row.get("full_combo_share") for row in rows],
        "near_ok": [row.get("near_ok") for row in rows],
        "milestones": [row.get("milestone_count") if row.get("mode") == "version_observed" else None for row in rows],
    }
    skill_signals: Dict[str, List[Optional[float]]] = {
        "pound_speed": [row.get("pound_speed") for row in rows],
        "hardship": [row.get("hardship_max") for row in rows],
    }

    attained = [int((attained_dan_by_id or {}).get(str(row.get("id")), 0) or 0) for row in rows]
    passed = [value for value in attained if value >= 1]
    dan_level_percentile: Dict[str, float] = {}
    if passed:
        for dan_id in range(1, 20):
            below = sum(1 for value in passed if value < dan_id)
            equal = sum(1 for value in passed if value == dan_id)
            dan_level_percentile[str(dan_id)] = round((below + 0.5 * equal) / len(passed), 6)

    return {
        "version": REFERENCE_VERSION,
        "population": {
            "size": len(rows),
            "source": source,
            "fingerprint": fingerprint,
            "attainedDanPopulation": len(passed),
        },
        "builtAt": generated_at,
        "columns": {
            "play": [round(value, 6) for value in sorted(play)],
            "days": [round(value, 6) for value in sorted(days)],
            "rating": [round(value, 6) for value in sorted(rating)],
            "streak": [round(value, 6) for value in sorted(streak)],
            "speed_pref": [round(float(value), 6) for value in sorted(value for value in speed_pref if value is not None)],
            "kiwami": [round(value, 6) for value in sorted(kiwami)],
        },
        "medians": {
            "days": round(float(days_median or 0), 6),
            "rating": round(float(rating_median or 0), 6),
        },
        "residual": {key: _deciles(volume, values) for key, values in signals.items()},
        "residualSkill": {key: _deciles(rating_control, values) for key, values in skill_signals.items()},
        "danLevelPercentile": dan_level_percentile,
    }
