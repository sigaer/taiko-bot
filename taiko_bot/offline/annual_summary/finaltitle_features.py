"""FinalTitle feature extraction (production port of the Copy-3A audit extractor).

The audit computed every FinalTitle dimension from a fixed feature table extracted
from the *built summary*.  This module reproduces that extraction exactly, so the
population reference and the per-user scoring stay bit-compatible with the frozen
Copy-3B-0.1 model (see ``docs`` / the Copy-3B implementation report).

``visible_pages`` mirrors ``metricAvailable`` + the Finale narrative page list from
``taiko_viewer/utils/annualSummary.ts`` (the real shipped selector).
"""
from __future__ import annotations

import collections
import math
from typing import Any, Dict, List, Optional

#: The ten typed narrative pages that drive the L2 "limited evidence" gate.
TYPED_PAGES = (
    "timeOfDay",
    "calendar",
    "speedProfile",
    "challenge",
    "nearDondaful",
    "obsession",
    "favoriteShift",
    "monthly",
    "weekday",
    "lateNight",
)


def _num(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _section(summary: Dict[str, Any], key: str):
    node = (summary.get("sections") or {}).get(key) or {}
    return node.get("data"), node.get("status")


def _payload_present(data: Any) -> bool:
    if data is None:
        return False
    if isinstance(data, (list, tuple, str)):
        return len(data) > 0
    return True


def _available(status: Any, data: Any) -> bool:
    if status:
        return status != "unavailable" and _payload_present(data)
    return _payload_present(data)


def _has_song(value: Any) -> bool:
    """``mapSong`` returns null when the payload carries no song number."""
    return isinstance(value, dict) and bool(_num(value.get("songNo"), 0))


def visible_pages(summary: Dict[str, Any]) -> List[str]:
    """Page keys the shipped Finale selector would consider publishable."""
    pages: List[str] = []

    data, status = _section(summary, "timeOfDay")
    if isinstance(data, dict) and isinstance(data.get("hourlyCounts"), list) and _available(status, data):
        pages.append("timeOfDay")

    data, status = _section(summary, "calendarActivity")
    days = data.get("days") if isinstance(data, dict) else None
    if isinstance(days, list) and len(days) and _available(status, data):
        pages.append("calendar")

    data, status = _section(summary, "speedProfile")
    if _available(status, data):
        pages.append("speedProfile")

    data, status = _section(summary, "challenge")
    if isinstance(data, dict) and _has_song(data) and _available(status, data):
        pages.append("challenge")

    data, status = _section(summary, "nearDondaful")
    if isinstance(data, dict) and _has_song(data) and _available(status, data):
        pages.append("nearDondaful")

    data, status = _section(summary, "obsessionSong")
    if isinstance(data, dict) and _has_song(data) and _available(status, data):
        pages.append("obsession")

    data, status = _section(summary, "favoriteShift")
    if (
        isinstance(data, dict)
        and _has_song(data.get("oldFavorite"))
        and _has_song(data.get("newFavorite"))
        and _available(status, data)
    ):
        pages.append("favoriteShift")

    data, status = _section(summary, "monthlyFavorites")
    monthly = [row for row in (data or []) if isinstance(row, dict) and _has_song(row.get("song"))]
    if monthly and _available(status, data):
        pages.append("monthly")

    data, status = _section(summary, "weekdayActivity")
    counts = data.get("counts") if isinstance(data, dict) else None
    if isinstance(counts, list) and len(counts) == 7 and _available(status, data):
        pages.append("weekday")

    data, status = _section(summary, "lateNight")
    if isinstance(data, dict) and _has_song(data.get("song")) and _available(status, data):
        pages.append("lateNight")

    return pages


def summary_features(summary: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the final-title feature row from a built annual summary."""
    overview_node = summary.get("overview") or {}
    overview = overview_node.get("data") or {}
    period = summary.get("period") or {}
    profile = summary.get("profileCard") or {}

    keyword, _ = _section(summary, "keyword")
    radar = (keyword or {}).get("radarValues") or {}
    speed, speed_status = _section(summary, "speedProfile")
    speed = speed or {}
    pound, _ = _section(summary, "pound")
    pound = pound or {}
    challenge, challenge_status = _section(summary, "challenge")
    challenge = challenge or {}
    near, near_status = _section(summary, "nearDondaful")
    near = near or {}
    favorite, _ = _section(summary, "favoriteSong")
    favorite = favorite or {}
    obsession, _ = _section(summary, "obsessionSong")
    obsession = obsession or {}
    calendar, _ = _section(summary, "calendarActivity")
    calendar = calendar or {}
    time_of_day, _ = _section(summary, "timeOfDay")
    time_of_day = time_of_day or {}
    late, _ = _section(summary, "lateNight")
    late = late or {}
    rating, rating_status = _section(summary, "ratingRank")
    rating = rating or {}
    breakthrough, _ = _section(summary, "breakthrough")
    breakthrough = breakthrough or {}
    milestones, _ = _section(summary, "milestones")
    milestones = milestones or []
    achievements = (summary.get("achievements") or {}).get("current") or {}
    monthly, _ = _section(summary, "monthlyFavorites")
    monthly = monthly or []
    weekday, _ = _section(summary, "weekdayActivity")
    weekday = weekday or {}
    shift, _ = _section(summary, "favoriteShift")
    shift = shift or {}

    clear_charts = _num(overview.get("currentClearCharts"), 0) or _num(achievements.get("clearCharts"), 0)
    dondaful_charts = _num(overview.get("currentDondafulCharts"), 0) or _num(achievements.get("dondafulCharts"), 0)
    full_combo_charts = _num(overview.get("currentFullComboCharts"), 0) or _num(achievements.get("fullComboCharts"), 0)
    kiwami_charts = _num(overview.get("currentKiwamiCharts"), 0) or _num(achievements.get("extremeCharts"), 0)
    play_count = _num(overview.get("playCount"), 0)
    active_days = _num(period.get("activeDays"))
    if active_days is None:
        active_days = _num(calendar.get("activeDays"), 0)

    hourly = time_of_day.get("hourlyCounts") or []
    late_hours = sum(hourly[22:24]) + sum(hourly[0:6]) if len(hourly) == 24 else None

    hardship = [_num(item.get("hardshipScore")) for item in milestones if isinstance(item, dict)]
    hardship = [value for value in hardship if value is not None]

    pages = visible_pages(summary)
    return {
        "mode": summary.get("mode"),
        "old_breakthrough_type": (breakthrough or {}).get("type"),
        # volume / endurance
        "play_count": play_count,
        "active_days": active_days,
        "total_days": _num(period.get("totalDays"), 0),
        "longest_streak": _num(calendar.get("longestStreak"), 0),
        # exploration
        "unique_songs": _num(overview.get("uniqueSongs"), 0),
        "unique_charts": _num(overview.get("uniqueCharts"), 0),
        "monthly_count": len(monthly),
        "weekday_total": _num(weekday.get("totalPlays"), 0),
        # devotion
        "favorite_plays": _num(favorite.get("playCount"), 0),
        "obsession_days": _num(obsession.get("activeDays"), 0),
        "obsession_plays": _num(obsession.get("playCount"), 0),
        # speed / precision
        "speed": _num(speed.get("speed")),
        "speed_charts": _num(speed.get("chartCount"), 0),
        "pound_speed": _num(pound.get("speed")),
        "near_ok": _num(near.get("okCount")),
        "dondaful_charts": dondaful_charts,
        "dondaful_share": (dondaful_charts / clear_charts) if clear_charts else None,
        "full_combo_share": (full_combo_charts / clear_charts) if clear_charts else None,
        "clear_charts": clear_charts,
        "kiwami_charts": kiwami_charts,
        "challenge_plays": _num(challenge.get("playCount"), 0) if challenge_status else None,
        "rating": _num(rating.get("rating")),
        "rating_status": rating_status,
        # growth
        "breakthrough": bool(breakthrough),
        "milestone_count": len(milestones),
        "hardship_max": max(hardship) if hardship else None,
        "milestone_types": dict(collections.Counter(str(item.get("type")) for item in milestones if isinstance(item, dict))),
        # nocturnal
        "late_days": _num(late.get("activeDays"), 0),
        "late_plays": _num(late.get("playCount"), 0),
        "late_hour_plays": late_hours,
        # statuses used by gates
        "near_status": near_status,
        "speed_status": speed_status,
        # narrative visibility (drives the L2 gate)
        "visible_pages": pages,
        "page_count": len([page for page in TYPED_PAGES if page in pages]),
    }
