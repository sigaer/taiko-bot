from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.chart import roll as _roll

from dataclasses import dataclass
from typing import Any, Dict, Tuple


ROTTER_TARMINATION_BALLOON_ROLL_SECONDS = _roll.ROTTER_TARMINATION_BALLOON_ROLL_SECONDS


SpecialBalloonOverride = _roll.SpecialBalloonOverride


_SPECIAL_BALLOON_OVERRIDES = _roll._SPECIAL_BALLOON_OVERRIDES


_safe_int = _roll._safe_int


_safe_float = _roll._safe_float


_normalize_balloons = _roll._normalize_balloons


RatingRollBreakdown = _roll.RatingRollBreakdown


_special_balloon_override = _roll._special_balloon_override


compute_rating_roll_breakdown = _roll.compute_rating_roll_breakdown
