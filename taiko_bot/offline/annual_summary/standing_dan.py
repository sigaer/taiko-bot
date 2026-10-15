"""StrongDan standing presentation (V4.1) — current-version Dan strength overlay.

Frozen product model (V4/V4.1, no further tuning):

* candidate domain: ``dan_id >= 七段 (12)`` and ``mark >= 1`` (mark0 未合格 is not an
  achievement); levels below 七段 keep their records but never compete.
* ``strength = danBase[dan] + completionBonus(dan, mark)`` — completion interacts with
  dan difficulty (gold premium grows with dan, gold rainbow grows faster).
* gate: ``strength(十段, 赤合格)`` = 1.90; anything at or above it is a strongDan.
* presentation identity: ``dan x family`` (24 legal buckets), never completion-only.

This module only *describes* the overlay. The ordinary 45-key FinalTitle model is
untouched: ``titleKey`` keeps its original value and this overlay is presentation-only.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Optional, Tuple

from .constants import ALGORITHM_VERSION
from .dan_state import DanState

#: dan_id -> 段位名（中文 canonical，前端按 locale 渲染）
DAN_NAMES_ZH: Dict[int, str] = {
    1: "五级", 2: "四级", 3: "三级", 4: "二级", 5: "一级", 6: "初段", 7: "二段", 8: "三段",
    9: "四段", 10: "五段", 11: "六段", 12: "七段", 13: "八段", 14: "九段", 15: "十段",
    16: "玄人", 17: "名人", 18: "超人", 19: "达人",
}

#: canonical mark -> completion family（Evidence 用）
MARK_FAMILY: Dict[int, str] = {
    1: "red",
    2: "red",
    3: "red_rainbow",
    4: "gold",
    5: "gold",
    6: "gold_rainbow",
}

#: canonical completion terminology（zh key 由前端按 locale 渲染）
MARK_COMPLETION_ZH: Dict[int, str] = {
    1: "赤合格",
    2: "赤合格金粹",
    3: "赤虹合格",
    4: "金合格",
    5: "金粹金合格",
    6: "金虹合格",
}

#: completion-quality ratio inside one dan (gold premium = mark4 - mark1)
MARK_BONUS_RATIO: Dict[int, float] = {
    1: 0.0,
    2: 0.10,
    4: 1.0,
    5: 1.10,
}

STANDING_DAN_MIN = 12          # 七段
STANDING_MARK_MIN = 1
GATE_DAN = 15                  # 十段
GATE_MARK = 1                  # 赤合格

DAN_BASE: Dict[int, float] = {
    1: 0.00, 2: 0.06, 3: 0.13, 4: 0.21, 5: 0.30, 6: 0.40, 7: 0.51, 8: 0.63, 9: 0.76,
    10: 0.90, 11: 1.05, 12: 1.25, 13: 1.45, 14: 1.65, 15: 1.90, 16: 2.15, 17: 2.45,
    18: 2.80, 19: 3.25,
}


def gold_premium(dan: int) -> float:
    """金合格 premium over 赤合格; higher dan means less tolerance, so it grows."""
    return (0.17 + 0.14 * ((dan - 12) / 7.0)) * DAN_BASE[dan]


def k6(dan: int) -> float:
    """金虹合格 premium multiplier — frozen V4.1 value."""
    return 3.744 + 0.016 * (dan - 12)


def kr(dan: int) -> float:
    """赤虹合格 premium multiplier — frozen V4.1 value."""
    return 0.40 + 0.02 * (dan - 12)


def completion_bonus(dan: int, mark: int) -> float:
    """Per-dan completion bonus (dan-interacting; not a fixed global bonus)."""
    premium = gold_premium(dan)
    if mark == 3:
        return kr(dan) * premium
    if mark == 6:
        return premium + k6(dan) * premium
    return MARK_BONUS_RATIO[mark] * premium


def strength(dan: int, mark: int) -> float:
    """Frozen V4.1 strength: ``danBase + completionBonus``."""
    return DAN_BASE[dan] + completion_bonus(dan, mark)


#: 十段 · 赤合格
STRONG_DAN_THRESHOLD = strength(GATE_DAN, GATE_MARK)


def current_version_best(state: DanState) -> Optional[Tuple[float, int, int]]:
    """argmax(strength, dan_id, mark) over the candidate domain, or None."""
    best: Optional[Tuple[float, int, int]] = None
    for dan_id, mark in (state.marks or {}).items():
        if dan_id < STANDING_DAN_MIN:
            continue
        if not mark or mark < STANDING_MARK_MIN:
            continue
        value = strength(dan_id, mark)
        candidate = (value, dan_id, mark)
        if best is None or candidate > best:      # strength, then dan, then mark
            best = candidate
    return best


def resolve_standing_presentation(state: DanState) -> Optional[Dict[str, Any]]:
    """Resolved strongDan standing overlay, or None when the account is below the gate."""
    best = current_version_best(state)
    if best is None:
        return None
    value, dan_id, mark = best
    if round(value, 4) + 1e-9 < round(STRONG_DAN_THRESHOLD, 4):
        return None
    family = MARK_FAMILY[mark]
    dan_name = DAN_NAMES_ZH[dan_id]
    completion = MARK_COMPLETION_ZH[mark]
    return {
        "danId": dan_id,
        "mark": mark,
        "family": family,
        "strength": round(value, 4),
        "threshold": round(STRONG_DAN_THRESHOLD, 4),
        "titleKey": f"standing_{dan_id}_{family}",
        "evidenceKey": f"standing_{dan_id}_{family}",
        "evidenceValue": {
            "dan": dan_id,
            "mark": mark,
            "family": family,
            "completion": completion,
        },
        # Locale-independent fallbacks; the Viewer renders these through its locale table.
        "danName": dan_name,
        "completionText": completion,
        "evidenceText": f"{dan_name} · {completion}",
        "provenance": "current_version",
        "source": "dojo" if state.has_dojo_detail else "profile",
        # The overlay belongs to the standing branches only: even when a strong dan
        # event exists, the overlay evidence is the current-version standing.
        "algorithmVersion": ALGORITHM_VERSION,
    }


def standing_strength_matrix() -> Dict[str, Dict[str, float]]:
    """Exported matrix (diagnostics / contract tests)."""
    return {
        str(dan): {str(mark): round(strength(dan, mark), 4) for mark in range(1, 7)}
        for dan in range(1, 20)
    }


def strength_floor(value: float) -> float:
    """Small helper kept for callers that need a stable 4-decimal compare."""
    return math.floor(value * 10000) / 10000
