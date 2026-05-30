from __future__ import annotations

import io
import json
import math
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from taiko_bot.settings import get_settings

from .dojo_score import (
    build_dojo_score_map,
    get_dan_id_by_grade_name,
    level_mark_to_icon,
    normalize_dojo_scores,
)

BASE = get_settings().root_dir
CURRENT_CONFIG_PATH = BASE / "songs" / "grade_dojo_nijiiro_2025_simple.json"
HISTORY_CONFIG_PATH = BASE / "songs" / "grade_dojo_nijiiro_history_simple.json"
USERDATA_DIR = BASE / "userdata"
UP_TEMPLATE_PATH = BASE / "assets" / "templates" / "dani_up.png"
DOWN_TEMPLATE_PATH = BASE / "assets" / "templates" / "dani_down.png"
DIFF_DIR = BASE / "assets" / "icons" / "diff"
DANI_DIR = BASE / "assets" / "icons" / "dani"
FONT_PATH = BASE / "assets" / "fonts" / "FZPW_GBK.ttf"
DDFONT_PATH = BASE / "assets" / "fonts" / "DDFont.ttf"

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

GRADE_ALIASES = [
    ("級", "级"),
    ("级", "級"),
    ("達人", "达人"),
    ("达人", "達人"),
]

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
_NUMERIC_KYU_ALIASES = {
    1: "一級",
    2: "二級",
    3: "三級",
    4: "四級",
    5: "五級",
}
CURRENT_DANI_VERSION = "2025"
SUPPORTED_DANI_VERSIONS = {"2020", "2021", "2022", "2023", "2024", "2025"}
DANI_VERSION_PREFIXES = ("虹", "虹版", "ニジイロ")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
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


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(FONT_PATH), size)
    except Exception:
        return ImageFont.load_default()


def _load_ddfont(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(str(DDFONT_PATH), size)
    except Exception:
        return _load_font(size)


def _font_y_offset(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))


def _draw_text_with_stroke(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_width: int = 3,
    stroke_fill: Tuple[int, int, int] = BLACK,
    anchor: Optional[str] = None,
) -> None:
    x, y = pos
    y += _font_y_offset(font)
    try:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
            anchor=anchor,
        )
    except TypeError:
        for dx in range(-stroke_width, stroke_width + 1):
            for dy in range(-stroke_width, stroke_width + 1):
                if dx == 0 and dy == 0:
                    continue
                draw.text(
                    (x + dx, y + dy), text, font=font, fill=stroke_fill, anchor=anchor
                )
        draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _truncate_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "…"
    if draw.textlength(ellipsis, font=font) >= max_width:
        return ellipsis
    left = 0
    right = len(text)
    while left < right:
        mid = (left + right + 1) // 2
        candidate = text[:mid] + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            left = mid
        else:
            right = mid - 1
    return text[:left] + ellipsis


def _grade_alias_variants(canonical: str) -> set[str]:
    variants = {canonical}
    changed = True
    while changed:
        changed = False
        for item in list(variants):
            for left, right in GRADE_ALIASES:
                if left in item:
                    nxt = item.replace(left, right)
                    if nxt not in variants:
                        variants.add(nxt)
                        changed = True
    return variants


def _normalize_numeric_grade_input(text: str) -> str:
    raw = str(text).strip()
    if not raw:
        return raw

    dan_match = re.fullmatch(r"(\d+)段", raw)
    if dan_match:
        num = int(dan_match.group(1))
        return _NUMERIC_DAN_ALIASES.get(num, raw)

    kyu_match = re.fullmatch(r"(\d+)[级級]", raw)
    if kyu_match:
        num = int(kyu_match.group(1))
        return _NUMERIC_KYU_ALIASES.get(num, raw)

    return raw


@lru_cache(maxsize=8)
def _load_grade_payload(version: str) -> Dict[str, Any]:
    version = str(version or CURRENT_DANI_VERSION)
    if version == CURRENT_DANI_VERSION:
        payload = json.loads(CURRENT_CONFIG_PATH.read_text(encoding="utf-8"))
        return {"year": version, "grades": payload.get("grades") or []}

    history_payload = json.loads(HISTORY_CONFIG_PATH.read_text(encoding="utf-8"))
    versions = history_payload.get("versions") or {}
    version_payload = versions.get(version)
    if not isinstance(version_payload, dict):
        raise KeyError(version)
    return version_payload


@lru_cache(maxsize=8)
def _load_grade_index(version: str = CURRENT_DANI_VERSION) -> Dict[str, Dict[str, Any]]:
    payload = _load_grade_payload(version)
    index: Dict[str, Dict[str, Any]] = {}
    for grade in payload["grades"]:
        canonical = str(grade["grade"]).strip()
        for item in _grade_alias_variants(canonical):
            index[item] = grade
    return index


def parse_dani_progress_request(text: str) -> Optional[Dict[str, str]]:
    raw = str(text).strip()
    if raw.endswith("进度"):
        raw = raw[:-2]
    raw = raw.strip()
    raw = raw.replace("一", "初")
    if not raw:
        return None

    version = CURRENT_DANI_VERSION
    explicit_version = False
    for prefix in DANI_VERSION_PREFIXES:
        if raw.startswith(prefix):
            remain = raw[len(prefix) :].strip()
            match = re.match(r"^(20\d{2})\s*(.+)$", remain)
            if not match:
                return None
            version = match.group(1)
            raw = match.group(2).strip()
            explicit_version = True
            break

    if version not in SUPPORTED_DANI_VERSIONS:
        return None

    raw = _normalize_numeric_grade_input(raw)
    grade = _load_grade_index(version).get(raw)
    if not grade:
        return None
    return {
        "version": version,
        "grade": str(grade["grade"]),
        "explicitVersion": "1" if explicit_version else "0",
    }


def normalize_dani_grade_name(text: str) -> Optional[str]:
    request = parse_dani_progress_request(text)
    return request["grade"] if request else None


def _load_history_dojo_payload_for_dan(
    user_id: int, dan_id: int
) -> Optional[Dict[str, Any]]:
    if dan_id <= 0:
        return None
    history_dir = USERDATA_DIR / str(user_id)
    if not history_dir.exists():
        return None

    for history_file in sorted(history_dir.glob("data_*.json"), reverse=True):
        try:
            payload = json.loads(history_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict) or "dojo" not in payload:
            continue

        dojo_payload = normalize_dojo_scores(payload.get("dojo") or {})
        if dan_id in build_dojo_score_map(dojo_payload):
            return dojo_payload
    return None


def _footer_uses_ok_count(grade: Dict[str, Any]) -> bool:
    pass_cond = (grade or {}).get("conditions", {}).get("pass", {})
    return pass_cond.get("okCountLessThan") is not None


def _render_notice(text: str) -> bytes:
    base = Image.open(UP_TEMPLATE_PATH).convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    draw.rounded_rectangle((132, 208, 1148, 512), radius=36, fill=(255, 251, 244, 240))
    _draw_text_with_stroke(
        draw, (640, 272), "段位进度", _load_font(42), WHITE, 4, BLACK, "mm"
    )
    _draw_text_with_stroke(
        draw, (640, 372), text, _load_font(28), TEXT_MAIN, 3, WHITE, "mm"
    )
    base.alpha_composite(overlay)
    buf = io.BytesIO()
    base.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=1)
def _load_song_note_map() -> Dict[Tuple[int, int], int]:
    payload = json.loads(
        (BASE / "songs" / "song_data.json").read_text(encoding="utf-8")
    )
    mapping: Dict[Tuple[int, int], int] = {}
    for song in payload:
        sid = _safe_int(song.get("id"), -1)
        combos = song.get("max_combo") or []
        if sid < 0 or not isinstance(combos, list):
            continue
        for level, value in enumerate(combos, start=1):
            if value in (None, "-"):
                continue
            try:
                mapping[(sid, level)] = int(value)
            except Exception:
                continue
    return mapping


def _note_count(song: Dict[str, Any]) -> int:
    note_count = _safe_int(song.get("noteCount"), 0)
    if note_count > 0:
        return note_count
    return _load_song_note_map().get(
        (_safe_int(song.get("id")), _difficulty_level(song.get("difficulty"))), 0
    )


def _accuracy_formula(song: Dict[str, Any]) -> str:
    formula = str(song.get("accuracyFormula") or "").strip()
    if formula in {FORMULA_GOOD, FORMULA_OK}:
        return formula
    return FORMULA_GOOD


def _build_best_entry_map(
    user_scores: List[Dict[str, Any]],
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for row in user_scores:
        try:
            key = (int(row["song_no"]), int(row["level"]))
            score = int(row.get("high_score", 0) or 0)
        except Exception:
            continue
        if key not in best or score > int(best[key].get("high_score", 0) or 0):
            best[key] = row
    return best


def _entry_counts(entry: Optional[Dict[str, Any]]) -> Dict[str, int]:
    if not entry:
        return {"score": 0, "good": 0, "ok": 0, "bad": 0, "drumroll": 0, "hit": 0}
    hit_value = _safe_optional_int(entry.get("hit_cnt"))
    if hit_value is None:
        hit_value = (
            _safe_int(entry.get("good_cnt"), 0)
            + _safe_int(entry.get("ok_cnt"), 0)
            + _safe_int(entry.get("pound_cnt"), 0)
        )
    return {
        "score": _safe_int(entry.get("high_score"), 0),
        "good": _safe_int(entry.get("good_cnt"), 0),
        "ok": _safe_int(entry.get("ok_cnt"), 0),
        "bad": _safe_int(entry.get("ng_cnt", entry.get("bad_cnt")), 0),
        "drumroll": _safe_int(entry.get("pound_cnt"), 0),
        "hit": hit_value,
    }


def _accuracy_percent(counts: Dict[str, int], note_count: int, formula: str) -> float:
    if note_count <= 0:
        return 0.0
    if (
        counts.get("score", 0) <= 0
        and counts.get("good", 0) <= 0
        and counts.get("ok", 0) <= 0
        and counts.get("bad", 0) <= 0
        and counts.get("drumroll", 0) <= 0
    ):
        return 0.0
    value = (counts["good"] + counts["ok"] * 0.5) / float(note_count)
    return max(0.0, min(100.0, value * 100.0))


def _all_good(counts: Dict[str, int], note_count: int) -> bool:
    return counts["ok"] == 0 and counts["bad"] == 0


def _full_combo(counts: Dict[str, int]) -> bool:
    return counts["bad"] == 0


def _rate_from_good_target(note_count: int, good_target: int) -> float:
    if note_count <= 0:
        return 0.0
    clamped_good = max(0, min(note_count, good_target))
    value = (
        (clamped_good + 0.5 * (note_count - clamped_good)) / float(note_count) * 100.0
    )
    return max(0.0, min(100.0, value))


def _rate_from_ok_limit(note_count: int, ok_limit: int) -> float:
    if note_count <= 0:
        return 0.0
    max_ok = max(0, ok_limit - 1)
    value = (note_count - 0.5 * max_ok) / float(note_count) * 100.0
    return max(0.0, min(100.0, value))


def _rate_target_list(note_counts: List[int], cond: Dict[str, Any]) -> List[float]:
    if cond.get("goodCountAtLeast") is not None:
        good_targets = _scalar_or_list(cond.get("goodCountAtLeast"), note_counts)
        return [
            _rate_from_good_target(note_count, good_target)
            for note_count, good_target in zip(note_counts, good_targets)
        ]
    if cond.get("okCountLessThan") is not None:
        ok_limits = _scalar_or_list(cond.get("okCountLessThan"), note_counts)
        return [
            _rate_from_ok_limit(note_count, ok_limit)
            for note_count, ok_limit in zip(note_counts, ok_limits)
        ]
    gauge = float(_safe_int(cond.get("soulGaugePercent"), 0))
    return [gauge for _ in note_counts]


def _rate_target_total(
    note_count: int, cond: Dict[str, Any], song_notes: List[int]
) -> float:
    if note_count <= 0:
        return 0.0
    bad_raw = cond.get("badCountLessThan")
    if isinstance(bad_raw, list):
        total_bad = sum(max(0, _safe_int(item) - 1) for item in bad_raw)
    else:
        total_bad = max(0, _safe_int(bad_raw) - 1)
    if cond.get("goodCountAtLeast") is not None:
        raw = cond.get("goodCountAtLeast")
        total_good = (
            sum(_scalar_or_list(raw, song_notes))
            if isinstance(raw, list)
            else _safe_int(raw)
        )
        total_ok = max(0, note_count - total_good - total_bad)
        value = (total_good + 0.5 * total_ok) / float(note_count) * 100.0
        return max(0.0, min(100.0, value))
    if cond.get("okCountLessThan") is not None:
        raw = cond.get("okCountLessThan")
        if isinstance(raw, list):
            total_ok = sum(max(0, _safe_int(item) - 1) for item in raw)
        else:
            total_ok = max(0, _safe_int(raw) - 1)
        total_good = max(0, note_count - total_ok - total_bad)
        value = (total_good + 0.5 * total_ok) / float(note_count) * 100.0
        return max(0.0, min(100.0, value))
    return float(_safe_int(cond.get("soulGaugePercent"), 0))


def _allocate_proportional(total: int, weights: List[int]) -> List[int]:
    if total <= 0 or not weights or sum(weights) <= 0:
        return [0 for _ in weights]
    raw = [total * weight / float(sum(weights)) for weight in weights]
    ints = [int(math.floor(item)) for item in raw]
    remain = total - sum(ints)
    order = sorted(
        range(len(weights)), key=lambda idx: raw[idx] - ints[idx], reverse=True
    )
    for idx in order[:remain]:
        ints[idx] += 1
    return ints


def _scalar_or_list(value: Any, weights: List[int]) -> List[int]:
    if isinstance(value, list):
        numbers = [_safe_int(item, 0) for item in value]
        if len(numbers) < len(weights):
            numbers.extend([0] * (len(weights) - len(numbers)))
        return numbers[: len(weights)]
    return _allocate_proportional(_safe_int(value, 0), weights)


def _derive_song_targets(grade: Dict[str, Any]) -> Dict[str, Any]:
    songs = grade["songs"]
    notes = [_note_count(song) for song in songs]
    formulas = [_accuracy_formula(song) for song in songs]
    pass_cond = grade["conditions"]["pass"]
    gold_cond = grade["conditions"]["gold"]
    pass_good_raw = pass_cond.get("goodCountAtLeast")
    pass_ok_raw = pass_cond.get("okCountLessThan")
    pass_bad_raw = pass_cond.get("badCountLessThan")
    pass_drumroll_raw = pass_cond.get("drumrollCountAtLeast")
    pass_hit_raw = pass_cond.get("hitCountAtLeast")
    gold_good_raw = gold_cond.get("goodCountAtLeast")
    gold_ok_raw = gold_cond.get("okCountLessThan")
    gold_bad_raw = gold_cond.get("badCountLessThan")
    gold_drumroll_raw = gold_cond.get("drumrollCountAtLeast")
    gold_hit_raw = gold_cond.get("hitCountAtLeast")

    return {
        "notes": notes,
        "formulas": formulas,
        "has_rate_target": pass_good_raw is not None or pass_ok_raw is not None,
        "rate_per_song": isinstance(pass_good_raw, list)
        or isinstance(pass_ok_raw, list),
        "pass_rate": _rate_target_list(notes, pass_cond),
        "gold_rate": _rate_target_list(notes, gold_cond),
        "pass_good": _scalar_or_list(pass_good_raw, notes),
        "gold_good": _scalar_or_list(gold_good_raw, notes),
        "pass_ok": _scalar_or_list(pass_ok_raw, notes),
        "gold_ok": _scalar_or_list(gold_ok_raw, notes),
        "has_bad_target": pass_bad_raw is not None,
        "bad_per_song": isinstance(pass_bad_raw, list),
        "pass_bad": _scalar_or_list(pass_bad_raw, notes),
        "gold_bad": _scalar_or_list(gold_bad_raw, notes),
        "has_drumroll_target": pass_drumroll_raw is not None,
        "drumroll_per_song": isinstance(pass_drumroll_raw, list),
        "pass_drumroll": _scalar_or_list(pass_drumroll_raw, notes),
        "gold_drumroll": _scalar_or_list(gold_drumroll_raw, notes),
        "has_hit_target": pass_hit_raw is not None,
        "hit_per_song": isinstance(pass_hit_raw, list),
        "pass_hit": _scalar_or_list(pass_hit_raw, notes),
        "gold_hit": _scalar_or_list(gold_hit_raw, notes),
    }


def _best_tier(pass_ok: bool, gold_ok: bool, full_combo: bool, all_good: bool) -> int:
    if gold_ok:
        if all_good:
            return 7
        if full_combo:
            return 5
        return 3
    if pass_ok:
        if all_good:
            return 6
        if full_combo:
            return 4
        return 2
    return 1


def _metric_pass(value: float, target: float) -> bool:
    return target > 0 and value >= target


def _metric_pass_bad(current: int, target_raw: int) -> bool:
    return target_raw > 0 and current < target_raw


def _status_color(icon_index: int) -> Tuple[int, int, int]:
    if icon_index in {3, 5, 7}:
        return BAR_GOLD
    if icon_index in {2, 4, 6}:
        return BAR_PASS
    if icon_index <= 0:
        return BAR_NEUTRAL
    return BAR_FAIL


def _metric_ratio(kind: str, current: float | int, target: float | int) -> float:
    target_value = float(target)
    current_value = float(current)
    if target_value <= 0:
        return 0.0
    if kind in {"bad", "ok"}:
        if current_value <= 0:
            return 1.0
        if current_value < target_value:
            return 1.0
        return max(0.0, min(1.0, target_value / current_value))
    return max(0.0, min(1.0, current_value / target_value))


def _metric_icon_index(
    kind: str,
    current: float | int,
    pass_target: float | int,
    gold_target: float | int,
    full_combo: bool,
    all_good: bool,
) -> int:
    if kind in {"bad", "ok"}:
        pass_ok = _metric_pass_bad(int(current), int(pass_target))
        gold_ok = _metric_pass_bad(int(current), int(gold_target))
    else:
        pass_ok = _metric_pass(float(current), float(pass_target))
        gold_ok = _metric_pass(float(current), float(gold_target))
    return _best_tier(pass_ok, gold_ok, full_combo, all_good)


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


def _build_primary_metric(
    grade: Dict[str, Any],
    derived: Dict[str, Any],
    idx: int,
    counts: Dict[str, int],
    accuracy: float,
    full_combo: bool,
    all_good: bool,
) -> Dict[str, Any]:
    pass_cond = grade["conditions"]["pass"]
    gold_cond = grade["conditions"]["gold"]

    if pass_cond.get("goodCountAtLeast") is not None:
        kind = "good"
        current = counts["good"]
        pass_target = derived["pass_good"][idx]
        gold_target = derived["gold_good"][idx]
        estimated = not isinstance(pass_cond.get("goodCountAtLeast"), list)
    elif pass_cond.get("okCountLessThan") is not None:
        kind = "ok"
        current = counts["ok"]
        pass_target = derived["pass_ok"][idx]
        gold_target = derived["gold_ok"][idx]
        estimated = not isinstance(pass_cond.get("okCountLessThan"), list)
    elif pass_cond.get("hitCountAtLeast") is not None:
        kind = "hit"
        current = counts["hit"]
        pass_target = derived["pass_hit"][idx]
        gold_target = derived["gold_hit"][idx]
        estimated = not isinstance(pass_cond.get("hitCountAtLeast"), list)
    else:
        kind = "rate"
        current = accuracy
        pass_target = derived["pass_rate"][idx]
        gold_target = derived["gold_rate"][idx]
        estimated = False

    return {
        "kind": kind,
        "current": current,
        "passTarget": pass_target,
        "goldTarget": gold_target,
        "icon": _metric_icon_index(
            kind, current, pass_target, gold_target, full_combo, all_good
        ),
        "ratio": _metric_ratio(kind, current, pass_target),
        "estimated": estimated,
        "comparable": True,
    }


@lru_cache(maxsize=64)
def _load_rgba(path: str) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        return Image.open(path).convert("RGBA")
    except Exception:
        return None


def _paste_fit(
    base: Image.Image, image: Optional[Image.Image], box: Tuple[int, int, int, int]
) -> None:
    if image is None:
        return
    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    ratio = min(width / image.width, height / image.height)
    size = (
        max(1, int(round(image.width * ratio))),
        max(1, int(round(image.height * ratio))),
    )
    resized = image.resize(size, Image.LANCZOS)
    pos = (x1 + (width - resized.width) // 2, y1 + (height - resized.height) // 2)
    base.alpha_composite(resized, pos)


def _paste_stretch(
    base: Image.Image, image: Optional[Image.Image], box: Tuple[int, int, int, int]
) -> None:
    if image is None:
        return
    x1, y1, x2, y2 = box
    width = max(1, x2 - x1)
    height = max(1, y2 - y1)
    resized = image.resize((width, height), Image.LANCZOS)
    base.alpha_composite(resized, (x1, y1))


def _icon_path(index: int) -> str:
    return str(DANI_DIR / f"{index}.png")


def _diff_icon_path(level: Any) -> str:
    return str(DIFF_DIR / f"{_difficulty_level(level)}.png")


def _render_progress_fill(
    width: int, height: int, color: Tuple[int, int, int]
) -> Image.Image:
    image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (0, 0, image.width - 1, image.height - 1),
        radius=height // 2,
        fill=(*color, 255),
    )
    return image


def _render_metric_bar(
    base: Image.Image,
    box: Tuple[int, int, int, int],
    ratio: float,
    icon_index: int,
    text: str,
) -> None:
    x1, y1, x2, y2 = box
    draw = ImageDraw.Draw(base)
    draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=RATE_BAR_BG)
    width = x2 - x1
    progress = max(0.0, min(1.0, ratio))
    fill_w = int(round(width * progress))
    if fill_w > 0:
        fill = _render_progress_fill(fill_w, y2 - y1, _status_color(icon_index))
        base.alpha_composite(fill, (x1, y1))
    font = _load_font(20)
    _draw_text_with_stroke(
        draw, ((x1 + x2) / 2, (y1 + y2) / 2 - 1), text, font, WHITE, 2, BLACK, "mm"
    )


def _overlay_fill(
    base: Image.Image,
    fill_src: Optional[Image.Image],
    box: Tuple[int, int, int, int],
    ratio: float,
) -> None:
    if fill_src is None or ratio <= 0:
        return
    x1, y1, x2, y2 = box
    width = x2 - x1
    height = y2 - y1
    fill_w = max(1, int(round(width * min(1.0, max(0.0, ratio)))))
    resized = fill_src.resize((width, height), Image.LANCZOS).crop(
        (0, 0, fill_w, height)
    )
    base.alpha_composite(resized.convert("RGBA"), (x1, y1))


def _render_single_bar(
    base: Image.Image,
    box: Tuple[int, int, int, int],
    text: str,
    ratio: float,
    icon_index: int,
) -> None:
    bg = _load_rgba(str(DANI_DIR / "bar.png"))
    pass_fill = _load_rgba(str(DANI_DIR / "bar_4.png"))
    gold_fill = _load_rgba(str(DANI_DIR / "bar_5.png"))
    _paste_stretch(base, bg, box)
    if icon_index in {3, 5, 7}:
        _overlay_fill(base, gold_fill, box, 1.0 if ratio > 0 else 0.0)
    elif icon_index in {2, 4, 6}:
        _overlay_fill(base, pass_fill, box, 1.0 if ratio > 0 else 0.0)

    draw = ImageDraw.Draw(base)
    font = _load_font(22)
    _draw_text_with_stroke(
        draw,
        ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - 1),
        text,
        font,
        WHITE,
        3,
        BLACK,
        "mm",
    )


def _render_segmented_bar(
    base: Image.Image,
    box: Tuple[int, int, int, int],
    segment_ratios: List[float],
    segment_icons: List[int],
    text: str = "",
    segment_texts: Optional[List[str]] = None,
) -> None:
    bg = _load_rgba(str(DANI_DIR / "bar.png"))
    pass_fill = _load_rgba(str(DANI_DIR / "bar_4.png"))
    gold_fill = _load_rgba(str(DANI_DIR / "bar_5.png"))
    _paste_stretch(base, bg, box)

    x1, y1, x2, y2 = box
    total_w = x2 - x1
    gap = 6
    segment_count = max(
        1,
        len(segment_ratios),
        len(segment_icons),
        len(segment_texts or []),
    )
    seg_w = (total_w - gap * max(0, segment_count - 1)) // segment_count
    for idx in range(segment_count):
        sx1 = x1 + idx * (seg_w + gap)
        sx2 = sx1 + seg_w
        seg_box = (sx1, y1 + 6, sx2, y2 - 6)
        icon_index = segment_icons[idx] if idx < len(segment_icons) else 1
        if icon_index in {3, 5, 7}:
            _overlay_fill(base, gold_fill, seg_box, 1.0)
        elif icon_index in {2, 4, 6}:
            _overlay_fill(base, pass_fill, seg_box, 1.0)

    draw = ImageDraw.Draw(base)
    for idx in range(max(0, segment_count - 1)):
        divider_x = x1 + (idx + 1) * seg_w + idx * gap + gap // 2
        draw.line(
            (divider_x, y1 + 5, divider_x, y2 - 5), fill=(255, 245, 228, 168), width=2
        )
    if segment_texts:
        font = _load_font(20)
        for idx in range(segment_count):
            sx1 = x1 + idx * (seg_w + gap)
            sx2 = sx1 + seg_w
            label = segment_texts[idx] if idx < len(segment_texts) else ""
            if label:
                _draw_text_with_stroke(
                    draw,
                    ((sx1 + sx2) / 2, (y1 + y2) / 2 - 1),
                    label,
                    font,
                    WHITE,
                    3,
                    BLACK,
                    "mm",
                )
    elif text:
        font = _load_font(22)
        _draw_text_with_stroke(
            draw, ((x1 + x2) / 2, (y1 + y2) / 2 - 1), text, font, WHITE, 3, BLACK, "mm"
        )


def _card_row_centers(box: Tuple[int, int, int, int]) -> List[float]:
    x1, y1, x2, y2 = box
    padding_top = 18
    padding_bottom = 18
    usable = y2 - y1 - padding_top - padding_bottom
    step = usable / 7.0
    return [y1 + padding_top + step * idx + step / 2 for idx in range(7)]


def _song_order_label(index: int) -> str:
    numerals = "一二三四五六七八九十"
    if 1 <= index <= len(numerals):
        return f"曲{numerals[index - 1]}"
    return f"曲{index}"


def _draw_card(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    song_runtime: Dict[str, Any],
    grade_has_bad_target: bool,
    grade_has_drumroll_target: bool,
    box: Tuple[int, int, int, int],
) -> None:
    shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    x1, y1, x2, y2 = box
    sdraw.rounded_rectangle(
        (x1 + 10, y1 + 12, x2 + 10, y2 + 12), radius=28, fill=(0, 0, 0, 44)
    )
    base.alpha_composite(shadow)
    draw.rounded_rectangle(box, radius=28, fill=CARD_FILL, outline=CARD_STROKE, width=4)

    label_font = _load_font(26)
    song_font = _load_ddfont(24)
    score_font = _load_font(46)
    stat_font = _load_font(26)
    centers = _card_row_centers(box)
    inner_x1 = x1 + 22
    inner_x2 = x2 - 22

    _draw_text_with_stroke(
        draw,
        ((x1 + x2) / 2, centers[0]),
        _song_order_label(_safe_int(song_runtime.get("index"), 1)),
        label_font,
        (255, 141, 110),
        3,
        BLACK,
        "mm",
    )
    _paste_fit(
        base,
        _load_rgba(_diff_icon_path(song_runtime["song"]["difficulty"])),
        (inner_x1 + 84, int(centers[1] - 34), inner_x2 - 84, int(centers[1] + 34)),
    )
    title = _truncate_text(
        draw, song_runtime["song"]["title"], song_font, inner_x2 - inner_x1 - 12
    )
    _draw_text_with_stroke(
        draw, ((x1 + x2) / 2, centers[2]), title, song_font, TEXT_MAIN, 3, WHITE, "mm"
    )

    if song_runtime["entry"] is None:
        status_text = str(song_runtime.get("statusText") or "未游玩")
        _draw_text_with_stroke(
            draw,
            ((x1 + x2) / 2, centers[3]),
            status_text,
            score_font,
            (171, 174, 184),
            4,
            BLACK,
            "mm",
        )
    else:
        _draw_text_with_stroke(
            draw,
            ((x1 + x2) / 2, centers[3]),
            str(song_runtime["counts"]["score"]),
            score_font,
            WHITE,
            4,
            BLACK,
            "mm",
        )

    primary_metric = song_runtime["primaryMetric"]
    primary_has_icon = bool(primary_metric.get("comparable"))
    primary_bar_box = (
        inner_x1 + 8,
        int(centers[4] - 15),
        inner_x2 - (84 if primary_has_icon else 8),
        int(centers[4] + 15),
    )
    primary_text = _metric_display_text(
        primary_metric["kind"],
        primary_metric["current"],
        primary_metric["passTarget"],
        has_entry=song_runtime["entry"] is not None,
        estimated=bool(primary_metric.get("estimated")),
    )
    _render_metric_bar(
        base,
        primary_bar_box,
        float(primary_metric.get("ratio", 0.0)),
        primary_metric["icon"] if primary_has_icon else 0,
        primary_text,
    )
    if primary_has_icon:
        _paste_fit(
            base,
            _load_rgba(_icon_path(primary_metric["icon"])),
            (inner_x2 - 72, int(centers[4] - 28), inner_x2 - 8, int(centers[4] + 28)),
        )

    miss_has_icon = bool(grade_has_bad_target and song_runtime.get("missComparable"))
    miss_text = (
        _metric_display_text(
            "bad",
            song_runtime["counts"]["bad"],
            song_runtime["passBadTarget"],
            has_entry=song_runtime["entry"] is not None,
            estimated=bool(song_runtime.get("missEstimated")),
        )
        if miss_has_icon
        else (
            "不可 --"
            if song_runtime["entry"] is None
            else f"不可 {song_runtime['counts']['bad']}"
        )
    )
    miss_x = (x1 + x2) / 2 - 12 if miss_has_icon else (x1 + x2) / 2
    _draw_text_with_stroke(
        draw, (miss_x, centers[5]), miss_text, stat_font, TEXT_SUB, 3, WHITE, "mm"
    )
    if miss_has_icon:
        _paste_fit(
            base,
            _load_rgba(_icon_path(song_runtime["missIcon"])),
            (inner_x2 - 72, int(centers[5] - 28), inner_x2 - 8, int(centers[5] + 28)),
        )

    drumroll_has_icon = bool(
        grade_has_drumroll_target and song_runtime.get("drumrollComparable")
    )
    drumroll_text = (
        _metric_display_text(
            "drumroll",
            song_runtime["counts"]["drumroll"],
            song_runtime["passDrumrollTarget"],
            has_entry=song_runtime["entry"] is not None,
            estimated=bool(song_runtime.get("drumrollEstimated")),
        )
        if drumroll_has_icon
        else (
            "连打 --"
            if song_runtime["entry"] is None
            else f"连打 {song_runtime['counts']['drumroll']}"
        )
    )
    drumroll_x = (x1 + x2) / 2 - 12 if drumroll_has_icon else (x1 + x2) / 2
    _draw_text_with_stroke(
        draw,
        (drumroll_x, centers[6]),
        drumroll_text,
        stat_font,
        TEXT_SUB,
        3,
        WHITE,
        "mm",
    )
    if drumroll_has_icon:
        _paste_fit(
            base,
            _load_rgba(_icon_path(song_runtime["drumrollIcon"])),
            (inner_x2 - 72, int(centers[6] - 28), inner_x2 - 8, int(centers[6] + 28)),
        )


def _build_song_runtime(
    grade: Dict[str, Any], best_map: Dict[Tuple[int, int], Dict[str, Any]]
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    derived = _derive_song_targets(grade)
    pass_cond = grade["conditions"]["pass"]
    songs_runtime: List[Dict[str, Any]] = []
    totals = {
        "noteCount": 0,
        "good": 0,
        "ok": 0,
        "bad": 0,
        "drumroll": 0,
        "hit": 0,
        "score": 0,
        "soulGaugeTotal": None,
    }

    for idx, song in enumerate(grade["songs"]):
        entry = best_map.get(
            (_safe_int(song["id"]), _difficulty_level(song["difficulty"]))
        )
        counts = _entry_counts(entry)
        note_count = derived["notes"][idx]
        formula = derived["formulas"][idx]
        accuracy = _accuracy_percent(counts, note_count, formula)
        full_combo = entry is not None and _full_combo(counts)
        all_good = entry is not None and _all_good(counts, note_count)
        pass_rate = derived["pass_rate"][idx]
        gold_rate = derived["gold_rate"][idx]
        pass_bad = derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
        gold_bad = derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
        pass_drumroll = (
            derived["pass_drumroll"][idx] if idx < len(derived["pass_drumroll"]) else 0
        )
        gold_drumroll = (
            derived["gold_drumroll"][idx] if idx < len(derived["gold_drumroll"]) else 0
        )
        miss_comparable = bool(derived["has_bad_target"])
        drumroll_comparable = bool(derived["has_drumroll_target"])

        if entry is None:
            primary_metric = {
                "kind": (
                    "ok"
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        "good"
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            "hit"
                            if pass_cond.get("hitCountAtLeast") is not None
                            else "rate"
                        )
                    )
                ),
                "current": 0,
                "passTarget": (
                    derived["pass_ok"][idx]
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        derived["pass_good"][idx]
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            derived["pass_hit"][idx]
                            if pass_cond.get("hitCountAtLeast") is not None
                            else derived["pass_rate"][idx]
                        )
                    )
                ),
                "goldTarget": (
                    derived["gold_ok"][idx]
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        derived["gold_good"][idx]
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            derived["gold_hit"][idx]
                            if pass_cond.get("hitCountAtLeast") is not None
                            else derived["gold_rate"][idx]
                        )
                    )
                ),
                "icon": 1,
                "ratio": 0.0,
                "estimated": (
                    pass_cond.get("okCountLessThan") is not None
                    and not isinstance(pass_cond.get("okCountLessThan"), list)
                )
                or (
                    pass_cond.get("goodCountAtLeast") is not None
                    and not isinstance(pass_cond.get("goodCountAtLeast"), list)
                )
                or (
                    pass_cond.get("hitCountAtLeast") is not None
                    and not isinstance(pass_cond.get("hitCountAtLeast"), list)
                ),
                "comparable": True,
            }
            miss_icon = 1
            drumroll_icon = 3 if pass_drumroll <= 0 else 1
            status_text = "未收录" if _safe_int(song.get("id"), -1) <= 0 else "未游玩"
        else:
            primary_metric = _build_primary_metric(
                grade, derived, idx, counts, accuracy, full_combo, all_good
            )
            miss_icon = _best_tier(
                _metric_pass_bad(counts["bad"], pass_bad),
                _metric_pass_bad(counts["bad"], gold_bad),
                full_combo,
                all_good,
            )
            if pass_drumroll <= 0:
                drumroll_icon = 3
            else:
                drumroll_icon = _best_tier(
                    _metric_pass(counts["drumroll"], pass_drumroll),
                    _metric_pass(counts["drumroll"], gold_drumroll),
                    full_combo,
                    all_good,
                )
            status_text = ""
        runtime = {
            "index": idx + 1,
            "song": song,
            "entry": entry,
            "counts": counts,
            "noteCount": note_count,
            "formula": formula,
            "accuracyPercent": accuracy,
            "primaryMetric": primary_metric,
            "missIcon": miss_icon,
            "passRateTarget": pass_rate,
            "goldRateTarget": gold_rate,
            "passBadTarget": pass_bad,
            "goldBadTarget": gold_bad,
            "passDrumrollTarget": pass_drumroll,
            "goldDrumrollTarget": gold_drumroll,
            "drumrollIcon": drumroll_icon,
            "missComparable": miss_comparable,
            "drumrollComparable": drumroll_comparable,
            "missEstimated": not bool(derived["bad_per_song"]),
            "drumrollEstimated": not bool(derived["drumroll_per_song"]),
            "statusText": status_text,
        }
        songs_runtime.append(runtime)
        totals["noteCount"] += note_count
        totals["good"] += counts["good"]
        totals["ok"] += counts["ok"]
        totals["bad"] += counts["bad"]
        totals["drumroll"] += counts["drumroll"]
        totals["hit"] += counts["hit"]
        totals["score"] += counts["score"]

    totals["allFullCombo"] = all(
        item["entry"] is not None and _full_combo(item["counts"])
        for item in songs_runtime
    )
    totals["allAllGood"] = all(
        item["entry"] is not None and _all_good(item["counts"], item["noteCount"])
        for item in songs_runtime
    )
    totals["accuracyPercent"] = 0.0
    if totals["noteCount"] > 0:
        formulas = {item["formula"] for item in songs_runtime}
        footer_formula = FORMULA_GOOD if FORMULA_GOOD in formulas else FORMULA_OK
        totals["accuracyPercent"] = _accuracy_percent(
            {
                "good": totals["good"],
                "ok": totals["ok"],
                "bad": totals["bad"],
                "drumroll": totals["drumroll"],
                "score": totals["score"],
            },
            totals["noteCount"],
            footer_formula,
        )
        totals["formula"] = footer_formula
    else:
        totals["formula"] = FORMULA_GOOD
    totals["derived"] = derived
    return songs_runtime, totals


def _footer_rows(
    grade: Dict[str, Any], songs_runtime: List[Dict[str, Any]], totals: Dict[str, Any]
) -> List[Dict[str, Any]]:
    pass_cond = grade["conditions"]["pass"]
    gold_cond = grade["conditions"]["gold"]
    derived = totals["derived"]
    rows: List[Dict[str, Any]] = []
    full_combo = bool(totals["allFullCombo"])
    all_good = bool(totals["allAllGood"])

    def segment_value_text(
        kind: str,
        song_runtime: Dict[str, Any],
        current: float | int,
        target: float | int,
    ) -> str:
        if kind == "drumroll" and float(target) <= 0:
            return "0/0"
        if song_runtime["entry"] is None:
            if kind == "rate":
                return f"--/{float(target):.2f}%"
            if target:
                return f"--/{int(target)}"
            return "--"
        if kind == "rate":
            return f"{float(current):.2f}%/{float(target):.2f}%"
        if target:
            return f"{int(current)}/{int(target)}"
        return str(int(current))

    def build_row(
        kind: str,
        label: str,
        current: float | int,
        pass_value: float | int,
        gold_value: float | int,
        pass_ok: bool,
        gold_ok: bool,
        segmented: bool = False,
        current_segments: Optional[List[float | int]] = None,
        pass_segments: Optional[List[float | int]] = None,
        gold_segments: Optional[List[float | int]] = None,
        segment_texts: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        icon_index = _best_tier(pass_ok, gold_ok, full_combo, all_good)
        if kind in {"bad", "ok"}:
            if not pass_value:
                ratio = 0.0
            elif current <= pass_value:
                ratio = 1.0
            else:
                ratio = max(0.0, min(1.0, float(pass_value) / float(current)))
        else:
            ratio = (
                0.0
                if not pass_value
                else max(0.0, min(1.0, float(current) / float(pass_value)))
            )

        segment_ratios: List[float] = []
        segment_icons: List[int] = []
        if segmented and current_segments and pass_segments and gold_segments:
            for song_runtime, now, pval, gval in zip(
                songs_runtime, current_segments, pass_segments, gold_segments
            ):
                if kind == "drumroll" and pval <= 0:
                    seg_icon = 3
                    seg_ratio = 1.0
                elif kind in {"bad", "ok"}:
                    song_pass = pval > 0 and now < pval
                    song_gold = gval > 0 and now < gval
                    if not pval:
                        seg_ratio = 0.0
                    elif now <= pval:
                        seg_ratio = 1.0
                    else:
                        seg_ratio = max(0.0, min(1.0, float(pval) / float(now)))
                    seg_icon = _best_tier(
                        song_pass,
                        song_gold,
                        _full_combo(song_runtime["counts"]),
                        _all_good(song_runtime["counts"], song_runtime["noteCount"]),
                    )
                else:
                    song_pass = pval > 0 and now >= pval
                    song_gold = gval > 0 and now >= gval
                    seg_ratio = (
                        0.0
                        if not pval
                        else max(0.0, min(1.0, float(now) / float(pval)))
                    )
                    seg_icon = _best_tier(
                        song_pass,
                        song_gold,
                        _full_combo(song_runtime["counts"]),
                        _all_good(song_runtime["counts"], song_runtime["noteCount"]),
                    )
                segment_ratios.append(seg_ratio)
                segment_icons.append(seg_icon)

        return {
            "label": label,
            "kind": kind,
            "current": current,
            "pass": pass_value,
            "gold": gold_value,
            "ratio": ratio,
            "icon": icon_index,
            "segmented": segmented,
            "segmentRatios": segment_ratios,
            "segmentIcons": segment_icons,
            "segmentTexts": segment_texts or [],
        }

    soul_gauge = _safe_optional_int(totals.get("soulGaugeTotal"))
    if soul_gauge is not None and pass_cond.get("soulGaugePercent") is not None:
        pass_gauge = _safe_int(pass_cond.get("soulGaugePercent"))
        gold_gauge = _safe_int(gold_cond.get("soulGaugePercent"))
        rows.append(
            build_row(
                "gauge",
                "目标魂条",
                soul_gauge,
                pass_gauge,
                gold_gauge,
                _metric_pass(soul_gauge, pass_gauge),
                _metric_pass(soul_gauge, gold_gauge),
            )
        )

    use_ok_count_footer = _footer_uses_ok_count(grade)
    if use_ok_count_footer and pass_cond.get("okCountLessThan") is not None:
        ok_segmented = isinstance(pass_cond.get("okCountLessThan"), list)
        ok_current_segments = [
            song_runtime["counts"]["ok"] for song_runtime in songs_runtime
        ]
        ok_pass_value = (
            sum(derived["pass_ok"])
            if ok_segmented
            else _safe_int(pass_cond.get("okCountLessThan"))
        )
        ok_gold_value = (
            sum(derived["gold_ok"])
            if ok_segmented
            else _safe_int(gold_cond.get("okCountLessThan"))
        )
        ok_pass_status = (
            all(
                _metric_pass_bad(now, pval)
                for now, pval in zip(ok_current_segments, derived["pass_ok"])
            )
            if ok_segmented
            else _metric_pass_bad(totals["ok"], ok_pass_value)
        )
        ok_gold_status = (
            all(
                _metric_pass_bad(now, gval)
                for now, gval in zip(ok_current_segments, derived["gold_ok"])
            )
            if ok_segmented
            else _metric_pass_bad(totals["ok"], ok_gold_value)
        )
        rows.append(
            build_row(
                "ok",
                "目标可数",
                totals["ok"],
                ok_pass_value,
                ok_gold_value,
                ok_pass_status,
                ok_gold_status,
                segmented=ok_segmented,
                current_segments=ok_current_segments,
                pass_segments=derived["pass_ok"],
                gold_segments=derived["gold_ok"],
                segment_texts=(
                    [
                        segment_value_text("ok", song_runtime, current, target)
                        for song_runtime, current, target in zip(
                            songs_runtime, ok_current_segments, derived["pass_ok"]
                        )
                    ]
                    if ok_segmented
                    else None
                ),
            )
        )
    else:
        has_rate_requirement = (
            pass_cond.get("goodCountAtLeast") is not None
            or pass_cond.get("okCountLessThan") is not None
        )
        if has_rate_requirement:
            total_rate_pass = _rate_target_total(
                totals["noteCount"], pass_cond, derived["notes"]
            )
            total_rate_gold = _rate_target_total(
                totals["noteCount"], gold_cond, derived["notes"]
            )
            rate_segmented = isinstance(
                pass_cond.get("goodCountAtLeast"), list
            ) or isinstance(pass_cond.get("okCountLessThan"), list)
            current_rate = float(totals["accuracyPercent"])
            rows.append(
                build_row(
                    "rate",
                    "目标良率",
                    current_rate,
                    float(total_rate_pass),
                    float(total_rate_gold),
                    _metric_pass(current_rate, float(total_rate_pass)),
                    _metric_pass(current_rate, float(total_rate_gold)),
                    segmented=rate_segmented,
                    current_segments=[
                        float(item["accuracyPercent"]) for item in songs_runtime
                    ],
                    pass_segments=[float(item) for item in derived["pass_rate"]],
                    gold_segments=[float(item) for item in derived["gold_rate"]],
                )
            )

    if pass_cond.get("hitCountAtLeast") is not None:
        rows.append(
            build_row(
                "hit",
                "目标击打数",
                totals["hit"],
                _safe_int(pass_cond.get("hitCountAtLeast")),
                _safe_int(gold_cond.get("hitCountAtLeast")),
                _metric_pass(
                    totals["hit"], _safe_int(pass_cond.get("hitCountAtLeast"))
                ),
                _metric_pass(
                    totals["hit"], _safe_int(gold_cond.get("hitCountAtLeast"))
                ),
            )
        )

    if pass_cond.get("badCountLessThan") is not None:
        rows.append(
            build_row(
                "bad",
                "目标不可",
                totals["bad"],
                _safe_int(pass_cond.get("badCountLessThan")),
                _safe_int(gold_cond.get("badCountLessThan")),
                _metric_pass_bad(
                    totals["bad"], _safe_int(pass_cond.get("badCountLessThan"))
                ),
                _metric_pass_bad(
                    totals["bad"], _safe_int(gold_cond.get("badCountLessThan"))
                ),
            )
        )

    if pass_cond.get("drumrollCountAtLeast") is not None:
        drumroll_segmented = isinstance(pass_cond.get("drumrollCountAtLeast"), list)
        drumroll_current_segments = [
            song_runtime["counts"]["drumroll"] for song_runtime in songs_runtime
        ]
        drumroll_pass_segments = derived["pass_drumroll"]
        drumroll_gold_segments = derived["gold_drumroll"]
        rows.append(
            build_row(
                "drumroll",
                "目标连打",
                totals["drumroll"],
                (
                    sum(derived["pass_drumroll"])
                    if drumroll_segmented
                    else _safe_int(pass_cond.get("drumrollCountAtLeast"))
                ),
                (
                    sum(derived["gold_drumroll"])
                    if drumroll_segmented
                    else _safe_int(gold_cond.get("drumrollCountAtLeast"))
                ),
                _metric_pass(
                    totals["drumroll"],
                    (
                        sum(derived["pass_drumroll"])
                        if drumroll_segmented
                        else _safe_int(pass_cond.get("drumrollCountAtLeast"))
                    ),
                ),
                _metric_pass(
                    totals["drumroll"],
                    (
                        sum(derived["gold_drumroll"])
                        if drumroll_segmented
                        else _safe_int(gold_cond.get("drumrollCountAtLeast"))
                    ),
                ),
                segmented=drumroll_segmented,
                current_segments=drumroll_current_segments,
                pass_segments=drumroll_pass_segments,
                gold_segments=drumroll_gold_segments,
                segment_texts=(
                    [
                        segment_value_text("drumroll", song_runtime, current, target)
                        for song_runtime, current, target in zip(
                            songs_runtime,
                            drumroll_current_segments,
                            drumroll_pass_segments,
                        )
                    ]
                    if drumroll_segmented
                    else None
                ),
            )
        )

    return rows


def _footer_value_text(row: Dict[str, Any]) -> str:
    if row["kind"] == "rate":
        return f"{row['current']:.2f}% / {row['pass']:.2f}%"
    if row["kind"] == "gauge":
        return f"{int(row['current'])}% / {int(row['pass'])}%"
    if row["kind"] in {"bad", "ok"}:
        return f"{row['current']} / {row['pass']}"
    return f"{int(row['current'])} / {int(row['pass'])}"


def _build_dojo_counts(
    note_count: int,
    highscore: Dict[str, Any],
    odaibest: Dict[str, Any],
) -> Dict[str, int]:
    good = _safe_optional_int(highscore.get("good"))
    ok = _safe_optional_int(highscore.get("ok"))
    bad = _safe_optional_int(highscore.get("bad"))
    drumroll = _safe_optional_int(highscore.get("drumroll"))
    hit = _safe_optional_int(highscore.get("hit"))

    if good is None and (ok is not None or bad is not None):
        good = max(0, note_count - _safe_int(ok, 0) - _safe_int(bad, 0))
    if hit is None:
        hit = _safe_int(good, 0) + _safe_int(ok, 0) + _safe_int(drumroll, 0)

    score = _safe_optional_int(highscore.get("score"))
    combo = _safe_optional_int(highscore.get("combo"))

    return {
        "score": _safe_int(score, 0),
        "good": _safe_int(good, 0),
        "ok": _safe_int(ok, 0),
        "bad": _safe_int(bad, 0),
        "drumroll": _safe_int(drumroll, 0),
        "hit": _safe_int(hit, 0),
        "combo": _safe_int(combo, 0),
    }


def _build_dojo_runtime(
    grade: Dict[str, Any],
    dojo_entry: Optional[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    derived = _derive_song_targets(grade)
    pass_cond = grade["conditions"]["pass"]
    songs_runtime: List[Dict[str, Any]] = []
    totals = {
        "noteCount": 0,
        "good": 0,
        "ok": 0,
        "bad": 0,
        "drumroll": 0,
        "hit": 0,
        "score": 0,
        "levelIcon": _safe_int((dojo_entry or {}).get("level_icon"), 1),
        "soulGaugeTotal": _safe_optional_int(
            (dojo_entry or {}).get("highscore_soul_gauge_total")
        ),
    }

    arrival_song_cnt = _safe_int((dojo_entry or {}).get("arrival_song_cnt"), 0)
    dojo_songs = (dojo_entry or {}).get("songs") or []

    for idx, song in enumerate(grade["songs"]):
        note_count = derived["notes"][idx]
        formula = derived["formulas"][idx]
        song_info = (
            dojo_songs[idx]
            if idx < len(dojo_songs) and isinstance(dojo_songs[idx], dict)
            else None
        )
        reached = bool(song_info and song_info.get("reached"))
        if reached:
            highscore = song_info.get("highscore") or {}
            odaibest = song_info.get("odaibest") or {}
            counts = _build_dojo_counts(note_count, highscore, odaibest)
            accuracy = _accuracy_percent(counts, note_count, formula)
            full_combo = _full_combo(counts)
            all_good = _all_good(counts, note_count)
            pass_rate = derived["pass_rate"][idx]
            gold_rate = derived["gold_rate"][idx]
            pass_bad = derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
            gold_bad = derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
            pass_drumroll = (
                derived["pass_drumroll"][idx]
                if idx < len(derived["pass_drumroll"])
                else 0
            )
            gold_drumroll = (
                derived["gold_drumroll"][idx]
                if idx < len(derived["gold_drumroll"])
                else 0
            )
            miss_comparable = bool(derived["has_bad_target"])
            drumroll_comparable = bool(derived["has_drumroll_target"])
            primary_metric = _build_primary_metric(
                grade,
                derived,
                idx,
                counts,
                accuracy,
                full_combo,
                all_good,
            )
            miss_icon = _best_tier(
                _metric_pass_bad(counts["bad"], pass_bad),
                _metric_pass_bad(counts["bad"], gold_bad),
                full_combo,
                all_good,
            )
            if pass_drumroll <= 0:
                drumroll_icon = 3
            else:
                drumroll_icon = _best_tier(
                    _metric_pass(counts["drumroll"], pass_drumroll),
                    _metric_pass(counts["drumroll"], gold_drumroll),
                    full_combo,
                    all_good,
                )
            entry: Optional[Dict[str, Any]] = song_info
            status_text = ""
            totals["noteCount"] += note_count
            totals["good"] += counts["good"]
            totals["ok"] += counts["ok"]
            totals["bad"] += counts["bad"]
            totals["drumroll"] += counts["drumroll"]
            totals["hit"] += counts["hit"]
            totals["score"] += counts["score"]
        else:
            counts = {
                "score": 0,
                "good": 0,
                "ok": 0,
                "bad": 0,
                "drumroll": 0,
                "hit": 0,
                "combo": 0,
            }
            accuracy = 0.0
            pass_rate = derived["pass_rate"][idx]
            gold_rate = derived["gold_rate"][idx]
            pass_bad = derived["pass_bad"][idx] if idx < len(derived["pass_bad"]) else 0
            gold_bad = derived["gold_bad"][idx] if idx < len(derived["gold_bad"]) else 0
            pass_drumroll = (
                derived["pass_drumroll"][idx]
                if idx < len(derived["pass_drumroll"])
                else 0
            )
            gold_drumroll = (
                derived["gold_drumroll"][idx]
                if idx < len(derived["gold_drumroll"])
                else 0
            )
            miss_comparable = bool(derived["has_bad_target"])
            drumroll_comparable = bool(derived["has_drumroll_target"])
            primary_metric = {
                "kind": (
                    "ok"
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        "good"
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            "hit"
                            if pass_cond.get("hitCountAtLeast") is not None
                            else "rate"
                        )
                    )
                ),
                "current": 0,
                "passTarget": (
                    derived["pass_ok"][idx]
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        derived["pass_good"][idx]
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            derived["pass_hit"][idx]
                            if pass_cond.get("hitCountAtLeast") is not None
                            else derived["pass_rate"][idx]
                        )
                    )
                ),
                "goldTarget": (
                    derived["gold_ok"][idx]
                    if pass_cond.get("okCountLessThan") is not None
                    else (
                        derived["gold_good"][idx]
                        if pass_cond.get("goodCountAtLeast") is not None
                        else (
                            derived["gold_hit"][idx]
                            if pass_cond.get("hitCountAtLeast") is not None
                            else derived["gold_rate"][idx]
                        )
                    )
                ),
                "icon": 1,
                "ratio": 0.0,
                "estimated": (
                    pass_cond.get("okCountLessThan") is not None
                    and not isinstance(pass_cond.get("okCountLessThan"), list)
                )
                or (
                    pass_cond.get("goodCountAtLeast") is not None
                    and not isinstance(pass_cond.get("goodCountAtLeast"), list)
                )
                or (
                    pass_cond.get("hitCountAtLeast") is not None
                    and not isinstance(pass_cond.get("hitCountAtLeast"), list)
                ),
                "comparable": True,
            }
            miss_icon = 1
            drumroll_icon = 3 if pass_drumroll <= 0 else 1
            entry = None
            status_text = (
                "未到达"
                if arrival_song_cnt > 0 and idx + 1 > arrival_song_cnt
                else "未游玩"
            )

        songs_runtime.append(
            {
                "index": idx + 1,
                "song": song,
                "entry": entry,
                "counts": counts,
                "noteCount": note_count,
                "formula": formula,
                "accuracyPercent": accuracy,
                "primaryMetric": primary_metric,
                "missIcon": miss_icon,
                "passRateTarget": pass_rate,
                "goldRateTarget": gold_rate,
                "passBadTarget": pass_bad,
                "goldBadTarget": gold_bad,
                "passDrumrollTarget": pass_drumroll,
                "goldDrumrollTarget": gold_drumroll,
                "drumrollIcon": drumroll_icon,
                "missComparable": miss_comparable,
                "drumrollComparable": drumroll_comparable,
                "missEstimated": not bool(derived["bad_per_song"]),
                "drumrollEstimated": not bool(derived["drumroll_per_song"]),
                "statusText": status_text,
            }
        )

    totals["allFullCombo"] = all(
        item["entry"] is not None and _full_combo(item["counts"])
        for item in songs_runtime
    )
    totals["allAllGood"] = all(
        item["entry"] is not None and _all_good(item["counts"], item["noteCount"])
        for item in songs_runtime
    )
    totals["accuracyPercent"] = 0.0
    if totals["noteCount"] > 0:
        formulas = {item["formula"] for item in songs_runtime}
        footer_formula = FORMULA_GOOD if FORMULA_GOOD in formulas else FORMULA_OK
        totals["accuracyPercent"] = _accuracy_percent(
            {
                "good": totals["good"],
                "ok": totals["ok"],
                "bad": totals["bad"],
                "drumroll": totals["drumroll"],
                "score": totals["score"],
            },
            totals["noteCount"],
            footer_formula,
        )
        totals["formula"] = footer_formula
    else:
        totals["formula"] = FORMULA_GOOD
    totals["derived"] = derived
    return songs_runtime, totals


def _section_height(
    footer_rows: List[Dict[str, Any]],
    *,
    large_title_icon: bool = False,
) -> int:
    base_height = 726 + len(footer_rows) * 64
    if large_title_icon:
        return base_height + 104
    return base_height


def _draw_progress_section(
    canvas: Image.Image,
    section_top: int,
    title: str,
    grade: Dict[str, Any],
    songs_runtime: List[Dict[str, Any]],
    footer_rows: List[Dict[str, Any]],
    *,
    title_icon: Optional[int] = None,
) -> None:
    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(44)
    has_large_title_icon = bool(title_icon and title_icon > 0)
    title_y = section_top + (100 if has_large_title_icon else 46)
    if has_large_title_icon:
        icon_size = 176
        icon_gap = 30
        title_width = int(round(draw.textlength(title, font=title_font)))
        group_width = title_width + icon_gap + icon_size
        group_x1 = int(round((1280 - group_width) / 2))
        title_x = group_x1 + title_width / 2
        _draw_text_with_stroke(
            draw, (title_x, title_y), title, title_font, WHITE, 4, BLACK, "mm"
        )
        icon_left = group_x1 + title_width + icon_gap
        _paste_fit(
            canvas,
            _load_rgba(_icon_path(title_icon)),
            (
                icon_left,
                section_top + 12,
                icon_left + icon_size,
                section_top + 12 + icon_size,
            ),
        )
    else:
        _draw_text_with_stroke(
            draw, (640, title_y), title, title_font, WHITE, 4, BLACK, "mm"
        )

    main_x1 = 36
    main_x2 = 1244
    main_y1 = section_top + (202 if has_large_title_icon else 98)
    main_y2 = main_y1 + 488
    footer_x1 = 54
    footer_x2 = 1226
    footer_y1 = main_y2 + 28
    footer_y2 = (
        section_top
        + _section_height(footer_rows, large_title_icon=has_large_title_icon)
        - 28
    )

    draw.rounded_rectangle(
        (main_x1, main_y1, main_x2, main_y2),
        radius=34,
        fill=(255, 247, 238, 110),
        outline=(255, 248, 229, 176),
        width=2,
    )
    draw.rounded_rectangle(
        (footer_x1, footer_y1, footer_x2, footer_y2),
        radius=30,
        fill=FOOTER_FILL,
        outline=FOOTER_STROKE,
        width=2,
    )
    _draw_text_with_stroke(
        draw,
        (footer_x1 + 36, footer_y1 + 28),
        "总和条件",
        _load_font(28),
        (255, 191, 133),
        3,
        BLACK,
        "lm",
    )
    draw.line(
        (footer_x1 + 28, footer_y1 + 48, footer_x2 - 28, footer_y1 + 48),
        fill=(255, 228, 187, 120),
        width=2,
    )

    card_count = max(1, len(songs_runtime))
    gap = 24
    total_gap = gap * max(0, card_count - 1)
    card_w = (main_x2 - main_x1 - total_gap) // card_count
    grade_has_bad_target = (
        grade["conditions"]["pass"].get("badCountLessThan") is not None
    )
    grade_has_drumroll_target = (
        grade["conditions"]["pass"].get("drumrollCountAtLeast") is not None
    )
    for idx, runtime in enumerate(songs_runtime):
        x1 = main_x1 + idx * (card_w + gap)
        x2 = x1 + card_w
        _draw_card(
            canvas,
            draw,
            runtime,
            grade_has_bad_target,
            grade_has_drumroll_target,
            (x1, main_y1, x2, main_y2),
        )

    label_font = _load_font(24)
    row_top = footer_y1 + 66
    icon_size = 58
    for row in footer_rows:
        cy = row_top + 28
        _paste_fit(
            canvas,
            _load_rgba(_icon_path(row["icon"])),
            (
                footer_x1 + 18,
                cy - icon_size // 2,
                footer_x1 + 18 + icon_size,
                cy + icon_size // 2,
            ),
        )
        _draw_text_with_stroke(
            draw, (footer_x1 + 92, cy), row["label"], label_font, WHITE, 3, BLACK, "lm"
        )
        bar_box = (footer_x1 + 280, row_top + 2, footer_x2 - 28, row_top + 54)
        bar_text = _footer_value_text(row)
        if row["segmented"]:
            _render_segmented_bar(
                canvas,
                bar_box,
                row["segmentRatios"],
                row["segmentIcons"],
                text=bar_text,
                segment_texts=row.get("segmentTexts"),
            )
        else:
            _render_single_bar(canvas, bar_box, bar_text, row["ratio"], row["icon"])
        row_top += 64


def _render_section_background(path: Path, height: int) -> Image.Image:
    return Image.open(path).convert("RGBA").resize((1280, height), Image.LANCZOS)


def render_dani_progress_image_bytes(
    user_id: int,
    grade_name: str,
    *,
    version: str = CURRENT_DANI_VERSION,
    explicit_version: bool = False,
) -> bytes:
    version = str(version or CURRENT_DANI_VERSION)
    try:
        grade = _load_grade_index(version).get(str(grade_name).strip())
    except KeyError:
        return _render_notice("仅支持虹2020-2025段位进度。")
    if not grade:
        return _render_notice("未找到对应段位。")

    canonical = str(grade["grade"])
    user_path = USERDATA_DIR / f"{user_id}data.json"
    if not user_path.exists():
        return _render_notice(f"未找到用户 {user_id} 的成绩文件。")

    userdata = json.loads(user_path.read_text(encoding="utf-8"))
    best_map = _build_best_entry_map(userdata.get("songs", []))
    songs_runtime, totals = _build_song_runtime(grade, best_map)
    if not songs_runtime:
        return _render_notice("该段位暂无可用课题曲数据。")
    footer_rows = _footer_rows(grade, songs_runtime, totals)
    main_title = (
        f"虹{version}{canonical}进度"
        if version != CURRENT_DANI_VERSION or explicit_version
        else f"{canonical}进度"
    )
    upper_height = _section_height(footer_rows)
    if version != CURRENT_DANI_VERSION:
        canvas = Image.new("RGBA", (1280, upper_height), (0, 0, 0, 0))
        canvas.alpha_composite(
            _render_section_background(UP_TEMPLATE_PATH, upper_height),
            (0, 0),
        )
        _draw_progress_section(canvas, 0, main_title, grade, songs_runtime, footer_rows)
    else:
        dojo_payload = normalize_dojo_scores(userdata.get("dojo") or {})
        dan_id = get_dan_id_by_grade_name(canonical)
        dojo_map = build_dojo_score_map(dojo_payload)
        dojo_entry = dojo_map.get(dan_id or -1)
        if not dojo_entry and dan_id:
            history_dojo_payload = _load_history_dojo_payload_for_dan(user_id, dan_id)
            if history_dojo_payload:
                dojo_payload = history_dojo_payload
                dojo_map = build_dojo_score_map(dojo_payload)
                dojo_entry = dojo_map.get(dan_id)
        dojo_songs_runtime, dojo_totals = _build_dojo_runtime(grade, dojo_entry)
        dojo_footer_rows = _footer_rows(grade, dojo_songs_runtime, dojo_totals)

        dojo_title_icon = _safe_int((dojo_entry or {}).get("level_icon"), 0)
        if (
            dojo_title_icon <= 0
            and dan_id
            and 0 < dan_id <= len(dojo_payload.get("levelList") or [])
        ):
            dojo_title_icon = level_mark_to_icon(
                (dojo_payload.get("levelList") or [])[dan_id - 1]
            )

        lower_height = _section_height(
            dojo_footer_rows, large_title_icon=dojo_title_icon > 0
        )
        section_gap = 0
        height = upper_height + section_gap + lower_height

        canvas = Image.new("RGBA", (1280, height), (0, 0, 0, 0))
        canvas.alpha_composite(
            _render_section_background(UP_TEMPLATE_PATH, upper_height), (0, 0)
        )
        canvas.alpha_composite(
            _render_section_background(DOWN_TEMPLATE_PATH, lower_height),
            (0, upper_height + section_gap),
        )
        _draw_progress_section(canvas, 0, main_title, grade, songs_runtime, footer_rows)
        _draw_progress_section(
            canvas,
            upper_height + section_gap,
            f"{canonical}进度（段位内）",
            grade,
            dojo_songs_runtime,
            dojo_footer_rows,
            title_icon=dojo_title_icon,
        )

    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
