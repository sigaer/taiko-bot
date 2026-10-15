"""Shared candidate rules for the score-driven annual sections.

Near Dondaful, KEEP TRYING and HIGH SCORE all answer a question about the
player's *hardest* eligible charts.  Each of them used to walk the whole score
archive on its own, which let an easy chart or a retired chart win a section
that is supposed to describe the top of the player's range.  The pipeline is
therefore shared and ordered:

    every score
        -> drop double charts
        -> drop charts that are no longer on the shelf
        -> keep the highest difficulty tier still present
        -> each section applies its own ranking inside that tier

Difficulty priority
-------------------
``level`` is the difficulty code carried by both the score archive and
``song_data.json`` (``level_1`` .. ``level_5``): 1 = 简单, 2 = 普通, 3 = 困难,
4 = 鬼, 5 = 里.  Business priority treats 鬼 and 里 as one top tier, so the
ordering is ``4 = 5 > 3 > 2 > 1`` and the tier of a chart is its level with
5 folded onto 4.  This mirrors the ``level not in (4, 5)`` oni-tier convention
already used by score_calculator / score_estimator / score_prediction_support.

Doubles
-------
``song_data.json`` still has no structured player-count flag, so the only
canonical marker is the ``【双打】`` display prefix.  It is applied here once
instead of three times in three sections.

Availability
------------
``shelf_status`` is the canonical availability field, with the same meaning it
has in ``plugins/utils/progress_catalog.is_song_on_shelf``: 1 / "1" / "已下架"
means the chart is off the shelf.  Nothing is inferred from artwork, URLs or
song titles here.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple

from .helpers import safe_int

#: Business difficulty priority. 鬼 (4) and 里 (5) share the highest tier.
DIFFICULTY_PRIORITY: Dict[int, int] = {1: 1, 2: 2, 3: 3, 4: 4, 5: 4}

#: Display marker carried by every 双打 chart in both locales.
DOUBLE_CHART_MARKER = "【双打】"

#: ``shelf_status`` values that mean "已下架".
OFF_SHELF_STATUS = frozenset({1, "1", "已下架"})


def difficulty_priority(level: Any) -> int:
    """Difficulty priority of a chart level; 0 means "unknown / never eligible"."""
    return DIFFICULTY_PRIORITY.get(safe_int(level, 0), 0)


def is_double_chart(song_meta: Optional[Dict[str, Any]]) -> bool:
    entry = song_meta or {}
    label = f"{entry.get('song_name') or ''}{entry.get('song_name_jp') or ''}"
    return DOUBLE_CHART_MARKER in label


def is_on_shelf(song_meta: Optional[Dict[str, Any]]) -> bool:
    entry = song_meta or {}
    return entry.get("shelf_status") not in OFF_SHELF_STATUS


def is_eligible_chart(song_meta: Optional[Dict[str, Any]]) -> bool:
    """True when the chart may take part in a score-driven section.

    Charts that are missing from the catalog entirely are kept: the catalog
    cannot prove them retired or double, and dropping them would silently
    remove legitimate candidates.
    """
    if not song_meta:
        return True
    return is_on_shelf(song_meta) and not is_double_chart(song_meta)


def eligible_keys(song_meta: Dict[int, Dict[str, Any]]) -> set:
    """Every ``song_no`` whose charts pass :func:`is_eligible_chart`."""
    return {song_no for song_no, entry in song_meta.items() if is_eligible_chart(entry)}


def highest_difficulty_tier(
    keys: Iterable[Tuple[int, int]],
    song_meta: Dict[int, Dict[str, Any]],
) -> int:
    """Highest difficulty priority among the eligible charts in ``keys``."""
    tier = 0
    for song_no, level in keys:
        if not is_eligible_chart(song_meta.get(song_no)):
            continue
        tier = max(tier, difficulty_priority(level))
    return tier


def is_eligible_candidate(
    song_no: int,
    level: Any,
    song_meta: Dict[int, Dict[str, Any]],
    *,
    tier: int,
) -> bool:
    """Eligibility test for one chart inside an already resolved tier."""
    if not is_eligible_chart(song_meta.get(song_no)):
        return False
    return difficulty_priority(level) == tier
