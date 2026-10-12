"""Unchanged Dani display rules and shared scalar helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional, Tuple

WHITE = (255, 255, 255)

BLACK = (0, 0, 0)

TEXT_MAIN = (60, 36, 19)

TEXT_SUB = (118, 87, 58)

CARD_FILL = (255, 250, 244, 242)

CARD_STROKE = (98, 63, 37, 235)

FOOTER_FILL = (28, 18, 18, 190)

FOOTER_STROKE = (255, 230, 190, 182)

BAR_FAIL = (110, 118, 130)

BAR_PASS = (255, 164, 96)

BAR_GOLD = (255, 126, 216)

BAR_NEUTRAL = (188, 156, 126)

RATE_BAR_BG = (52, 44, 44, 166)

FORMULA_GOOD = "good_over_total"

FORMULA_OK = "total_minus_ok_minus_1_over_total"

GRADE_ALIASES = [("級", "级"), ("级", "級"), ("達人", "达人"), ("达人", "達人")]

FOOTER_OK_COUNT_GRADES = {"十段", "玄人", "名人", "超人", "達人"}

_NUMERIC_DAN_ALIASES = {
    1: "初段",
    2: "二段",
    3: "三段",
    4: "四段",
    5: "五段",
    6: "六段",
    7: "七段",
    8: "八段",
    9: "九段",
    10: "十段",
}

_NUMERIC_KYU_ALIASES = {1: "一級", 2: "二級", 3: "三級", 4: "四級", 5: "五級"}

CURRENT_DANI_VERSION = "2026"

DOJO_DATA_VERSION = "2025"

SUPPORTED_DANI_VERSIONS = {"2020", "2021", "2022", "2023", "2024", "2025", "2026"}

DANI_VERSION_PREFIXES = ("虹版", "虹", "ニジイロ")

DANI_VERSION_PATTERN = re.compile("^(?:20)?(2[0-6])\\s*(.+)$")

NIJIIRO_2026_KYU_GRADES = {"五級", "四級", "三級", "二級", "一級"}

NIJIIRO_2026_GOLD_SOUL_GAUGE_BY_GRADE = {
    "五級": 95,
    "四級": 95,
    "三級": 97,
    "二級": 97,
    "一級": 100,
}

NIJIIRO_2026_DAN_GRADES = {
    "初段",
    "二段",
    "三段",
    "四段",
    "五段",
    "六段",
    "七段",
    "八段",
    "九段",
    "十段",
    "玄人",
    "名人",
    "超人",
    "達人",
}

DANI_DYNAMIC_PROFILE_MIN_RATED_SONGS = 10

DANI_DYNAMIC_PRESSURE_CLAMP = 0.5

DANI_DYNAMIC_ROLE_WEIGHT = 0.6

DANI_DYNAMIC_ABSOLUTE_WEIGHT = 0.25

DANI_DYNAMIC_CONST_WEIGHT = 0.15

DANI_DYNAMIC_CONST_MIN_FACTOR = 0.15

DANI_DYNAMIC_RATE_LOAD_LIMIT = 0.03

DANI_DYNAMIC_RATE_LOAD_WEIGHTS = {
    "accuracy_power": 0.55,
    "overall": 0.25,
    "big_song": 0.2,
}

DANI_DYNAMIC_RATE_LOAD_COST_POWER = 2.0

DANI_DYNAMIC_ACCURACY_OVER_TOLERANCE = 0.5

DANI_DYNAMIC_ACCURACY_OVER_WEIGHT = 30.0

DANI_DYNAMIC_REFERENCE_DISTANCE_SCALE = 0.35

DANI_DYNAMIC_PRESSURE_TIGHTEN_COST_SCALE = 0.002

DANI_DYNAMIC_PRESSURE_LOOSEN_COST_SCALE = 0.03

DANI_DYNAMIC_LOOSEN_PRESSURE_WEIGHT = 1.5

DANI_DYNAMIC_LOOSEN_WEIGHT_MIN = 0.75

DANI_DYNAMIC_LOOSEN_WEIGHT_MAX = 1.25

DANI_DYNAMIC_MIN_LOOSEN_SHARE_FACTOR = 0.5

DANI_DYNAMIC_SOFT_MIN_OK_LIMIT = 7

DANI_DYNAMIC_NEAR_FULL_COST_SCALE = 0.5

DANI_DYNAMIC_DIMENSION_SPECS: Tuple[Tuple[str, str, float], ...] = (
    ("accuracy_power", "accuracy_power", 0.3),
    ("rhythm", "rhythm", 0.2),
    ("complex_proc", "complex", 0.2),
    ("speed", "speed", 0.15),
    ("stamina", "stamina", 0.1),
    ("big_song", "daigouryoku", 0.05),
)

STRUCTURE_ROLE_DIMENSION_SPECS: Tuple[Tuple[str, str], ...] = (
    ("stamina", "体力"),
    ("speed", "高速处理"),
    ("rhythm", "节奏处理"),
    ("complex_proc", "复合处理"),
)

LEVEL_STAR_FIELD = {
    1: "level_1",
    2: "level_2",
    3: "level_3",
    4: "level_4",
    5: "level_5",
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


def _safe_optional_int(value: Any) -> Optional[int]:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _difficulty_level(value: Any) -> int:
    raw = str(value).strip()
    if raw.startswith("level"):
        raw = raw[5:]
    return max(1, _safe_int(raw, 4))


def _normalize_song_title(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\u3000", " ").strip()
    text = re.sub("\\s+", " ", text)
    text = text.replace("（裏譜面）", "").replace("(裏譜面)", "")
    text = text.replace("（裏）", "").replace("(裏)", "")
    text = re.sub("\\s*[‐‑–—-]\\s*", "-", text)
    text = text.replace("’", "'")
    return text


def _status_color(icon_index: int) -> Tuple[int, int, int]:
    if icon_index in {3, 5, 7}:
        return BAR_GOLD
    if icon_index in {2, 4, 6}:
        return BAR_PASS
    if icon_index <= 0:
        return BAR_NEUTRAL
    return BAR_FAIL


def _metric_display_text(
    kind: str,
    current: float | int,
    target: float | int,
    *,
    has_entry: bool,
    estimated: bool = False,
) -> str:
    labels = {
        "rate": "良率",
        "good": "良",
        "ok": "可",
        "bad": "不可",
        "drumroll": "连打",
        "hit": "击打",
    }
    estimated_labels = {
        "rate": "目标良率",
        "good": "目标良数",
        "ok": "目标可数",
        "bad": "目标不可数",
        "drumroll": "目标连打数",
        "hit": "目标击打数",
    }
    label = labels.get(kind, kind)
    if estimated:
        label = estimated_labels.get(kind, f"目标{label}")
    if kind == "rate":
        if not has_entry:
            return f"{label} --/{float(target):.2f}%"
        return f"{label} {float(current):.2f}%/{float(target):.2f}%"
    if kind in {"bad", "ok"}:
        if target:
            if not has_entry:
                return f"{label} --<{int(target)}"
            return f"{label} {int(current)}<{int(target)}"
        if not has_entry:
            return f"{label} --"
        return f"{label} {int(current)}"
    if target:
        if not has_entry:
            return f"{label} --/{int(target)}"
        return f"{label} {int(current)}/{int(target)}"
    if not has_entry:
        return f"{label} --"
    return f"{label} {int(current)}"
