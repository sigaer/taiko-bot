from __future__ import annotations

import io
import json
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional

from PIL import Image, ImageDraw

from .dani_progress import (
    BASE,
    BLACK,
    CARD_STROKE,
    TEXT_MAIN,
    TEXT_SUB,
    UP_TEMPLATE_PATH,
    WHITE,
    _difficulty_level,
    _diff_icon_path,
    _draw_text_with_stroke,
    _load_ddfont,
    _load_font,
    _load_grade_payload,
    _load_rgba,
    _resolved_gold_conditions,
    _paste_fit,
    _truncate_text,
)

DEFAULT_GRADE_ORDER = [
    "五級",
    "四級",
    "三級",
    "二級",
    "一級",
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
]

LANG_JA = "ja"
LANG_CN = "cn"

COPY_BY_LANG: Dict[str, Dict[str, str]] = {
    LANG_JA: {
        "title": "ニジイロ{version} 五級-達人 課題曲と赤金合格条件",
        "subtitle": "全19段位の最新課題曲・合格条件",
        "badge_subtitle": "段位条件",
        "pass_label": "赤",
        "gold_label": "金",
        "note_count": "ノーツ {count}",
        "unavailable": "未実装",
        "footer": "曲名・ノーツ数・条件は太鼓の達人 譜面とか Wiki の最新情報に準拠。",
    },
    LANG_CN: {
        "title": "虹{version} 五級-達人课题曲与赤金合格条件",
        "subtitle": "全19段位最新课题曲与合格条件",
        "badge_subtitle": "段位条件",
        "pass_label": "赤",
        "gold_label": "金",
        "note_count": "物量 {count}",
        "unavailable": "未实装",
        "footer": "曲名、物量与条件依据太鼓之达人谱面 Wiki 最新资料整理。",
    },
}


@lru_cache(maxsize=1)
def _load_song_index() -> Dict[int, Dict[str, Any]]:
    payload = json.loads((BASE / "songs" / "song_data.json").read_text(encoding="utf-8"))
    return {
        int(song["id"]): song
        for song in payload
        if isinstance(song, dict) and song.get("id") is not None
    }


def _is_song_available(song_info: Optional[Dict[str, Any]]) -> bool:
    if not song_info:
        return False
    return song_info.get("shelf_status") not in (1, "1", "已下架")


def _copy(lang: str, key: str) -> str:
    return COPY_BY_LANG.get(lang, COPY_BY_LANG[LANG_CN])[key]


def _localized_song(song: Dict[str, Any], lang: str) -> Dict[str, Any]:
    song_id = int(song.get("id") or 0)
    song_info = _load_song_index().get(song_id) if song_id > 0 else None
    if lang == LANG_JA:
        title = (
            (song_info or {}).get("song_name_jp")
            or (song_info or {}).get("song_name")
            or song.get("title")
            or "-"
        )
    else:
        title = (
            (song_info or {}).get("song_name")
            or (song_info or {}).get("song_name_jp")
            or song.get("title")
            or "-"
        )

    result = dict(song)
    result["title"] = str(title)
    result["isAvailable"] = _is_song_available(song_info)
    return result


def _section_background(height: int) -> Image.Image:
    src = Image.open(UP_TEMPLATE_PATH).convert("RGBA")
    canvas = Image.new("RGBA", (1280, height), (0, 0, 0, 0))
    y = 0
    while y < height:
        canvas.alpha_composite(src, (0, y))
        y += src.height
    return canvas


def _format_condition_line(
    cond: Dict[str, Any],
    *,
    reference_pass: Optional[Dict[str, Any]] = None,
    show_unknown: bool = False,
) -> List[str]:
    lines: List[str] = []
    soul = cond.get("soulGaugePercent")
    if soul is not None:
        lines.append(f"魂 {int(soul)}%+")
    elif show_unknown and reference_pass and reference_pass.get("soulGaugePercent") is not None:
        lines.append("魂 ?")

    good = cond.get("goodCountAtLeast")
    ok = cond.get("okCountLessThan")
    bad = cond.get("badCountLessThan")
    drumroll = cond.get("drumrollCountAtLeast")
    hit = cond.get("hitCountAtLeast")
    pass_good = reference_pass.get("goodCountAtLeast") if reference_pass else None
    pass_ok = reference_pass.get("okCountLessThan") if reference_pass else None
    pass_hit = reference_pass.get("hitCountAtLeast") if reference_pass else None

    if good is not None:
        if isinstance(good, list):
            lines.append("良 " + " / ".join(str(int(item)) for item in good) + "+")
        else:
            lines.append(f"良 {int(good)}+")
    elif show_unknown and pass_good is not None:
        lines.append("良 ?")
    if ok is not None:
        if isinstance(ok, list):
            lines.append("可 " + " / ".join(str(int(item)) for item in ok) + " 未满")
        else:
            lines.append(f"可 {int(ok)} 未满")
    elif show_unknown and pass_ok is not None:
        lines.append("可 ?")
    if bad is not None:
        lines.append(f"不可 {int(bad)} 未满")
    elif show_unknown and reference_pass and reference_pass.get("badCountLessThan") is not None:
        lines.append("不可 ?")
    if drumroll is not None:
        if isinstance(drumroll, list):
            lines.append(
                "连打 " + " / ".join(str(int(item)) for item in drumroll) + "+"
            )
        else:
            lines.append(f"连打 {int(drumroll)}+")
    elif show_unknown and reference_pass and reference_pass.get("drumrollCountAtLeast") is not None:
        lines.append("连打 ?")
    if hit is not None:
        if isinstance(hit, list):
            lines.append("击打 " + " / ".join(str(int(item)) for item in hit) + "+")
        else:
            lines.append(f"击打 {int(hit)}+")
    elif show_unknown and pass_hit is not None:
        lines.append("击打 ?")
    return lines


def _draw_song_chip(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    song: Dict[str, Any],
    box: tuple[int, int, int, int],
    *,
    lang: str,
) -> None:
    x1, y1, x2, y2 = box
    draw.rounded_rectangle(box, radius=20, fill=(255, 248, 240, 224), outline=(255, 235, 216, 255), width=2)

    icon_box = (x1 + 12, y1 + 12, x1 + 64, y2 - 12)
    _paste_fit(canvas, _load_rgba(_diff_icon_path(song["difficulty"])), icon_box)

    title_font = _load_ddfont(20)
    title = _truncate_text(draw, str(song.get("title") or "-"), title_font, x2 - x1 - 82)
    _draw_text_with_stroke(
        draw,
        (x1 + 70, y1 + 28),
        title,
        title_font,
        TEXT_MAIN,
        3,
        WHITE,
        "lm",
    )

    note_text = _copy(lang, "note_count").format(count=int(song.get("noteCount") or 0))
    _draw_text_with_stroke(
        draw,
        (x1 + 72, y1 + 62),
        note_text,
        _load_font(20),
        TEXT_SUB,
        2,
        WHITE,
        "lm",
    )

    if not song.get("isAvailable", int(song.get("id") or 0) > 0):
        badge_box = (x2 - 116, y1 + 14, x2 - 16, y1 + 46)
        draw.rounded_rectangle(badge_box, radius=14, fill=(255, 164, 96, 255))
        _draw_text_with_stroke(
            draw,
            ((badge_box[0] + badge_box[2]) / 2, (badge_box[1] + badge_box[3]) / 2),
            _copy(lang, "unavailable"),
            _load_font(16),
            WHITE,
            2,
            BLACK,
            "mm",
        )


def _draw_condition_pills(
    draw: ImageDraw.ImageDraw,
    lines: Iterable[str],
    *,
    label_text: str,
    start_x: int,
    start_y: int,
    max_x: int,
    label_fill: tuple[int, int, int, int],
    pill_fill: tuple[int, int, int, int],
    pill_outline: tuple[int, int, int, int],
) -> None:
    font = _load_font(20)
    label_font = _load_font(20)
    label_width = 44
    label_box = (start_x, start_y, start_x + label_width, start_y + 34)
    draw.rounded_rectangle(label_box, radius=16, fill=label_fill, outline=pill_outline, width=2)
    _draw_text_with_stroke(
        draw,
        ((label_box[0] + label_box[2]) / 2, (label_box[1] + label_box[3]) / 2),
        label_text,
        label_font,
        WHITE,
        2,
        BLACK,
        "mm",
    )

    x = start_x + label_width + 10
    y = start_y
    for text in lines:
        width = int(draw.textlength(text, font=font)) + 34
        if x + width > max_x:
            x = start_x + label_width + 10
            y += 44
        box = (x, y, x + width, y + 34)
        draw.rounded_rectangle(box, radius=16, fill=pill_fill, outline=pill_outline, width=2)
        _draw_text_with_stroke(
            draw,
            ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2),
            text,
            font,
            WHITE,
            2,
            BLACK,
            "mm",
        )
        x += width + 12


def render_dani_overview_image_bytes(
    version: str = "2026",
    grade_order: Optional[List[str]] = None,
    lang: str = LANG_CN,
) -> bytes:
    payload = _load_grade_payload(version)
    grade_map = {
        str(item.get("grade")).strip(): item
        for item in (payload.get("grades") or [])
        if isinstance(item, dict)
    }
    ordered_names = grade_order or DEFAULT_GRADE_ORDER
    grades = [grade_map[name] for name in ordered_names if name in grade_map]
    if not grades:
        raise ValueError(f"未找到虹{version}段位数据")

    row_height = 228
    header_height = 176
    footer_height = 66
    height = header_height + len(grades) * row_height + footer_height
    canvas = _section_background(height)
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    _draw_text_with_stroke(
        draw,
        (640, 56),
        _copy(lang, "title").format(version=version),
        _load_font(40),
        WHITE,
        4,
        BLACK,
        "mm",
    )
    _draw_text_with_stroke(
        draw,
        (640, 108),
        _copy(lang, "subtitle"),
        _load_font(24),
        (255, 213, 161),
        3,
        BLACK,
        "mm",
    )

    row_top = header_height - 8
    badge_font = _load_font(42)
    sub_font = _load_font(18)
    for grade in grades:
        x1, x2 = 36, 1244
        y1, y2 = row_top, row_top + row_height - 24
        draw.rounded_rectangle(
            (x1, y1, x2, y2),
            radius=28,
            fill=(255, 246, 236, 188),
            outline=CARD_STROKE,
            width=3,
        )

        badge_box = (x1 + 18, y1 + 18, x1 + 156, y2 - 18)
        draw.rounded_rectangle(
            badge_box,
            radius=24,
            fill=(44, 34, 34, 216),
            outline=(255, 226, 186, 180),
            width=2,
        )
        _draw_text_with_stroke(
            draw,
            ((badge_box[0] + badge_box[2]) / 2, badge_box[1] + 48),
            str(grade["grade"]),
            badge_font,
            WHITE,
            4,
            BLACK,
            "mm",
        )
        _draw_text_with_stroke(
            draw,
            ((badge_box[0] + badge_box[2]) / 2, badge_box[1] + 92),
            _copy(lang, "badge_subtitle"),
            sub_font,
            (255, 213, 161),
            2,
            BLACK,
            "mm",
        )

        chip_y1 = y1 + 20
        chip_y2 = chip_y1 + 80
        gap = 8
        chip_x1 = x1 + 174
        chip_w = (x2 - chip_x1 - 24 - gap * 2) // 3
        songs = grade.get("songs") or []
        for idx, song in enumerate(songs[:3]):
            sx1 = chip_x1 + idx * (chip_w + gap)
            sx2 = sx1 + chip_w
            _draw_song_chip(
                overlay,
                draw,
                _localized_song(song, lang),
                (sx1, chip_y1, sx2, chip_y2),
                lang=lang,
            )

        pass_cond = (grade.get("conditions") or {}).get("pass") or {}
        gold_cond = _resolved_gold_conditions(grade)

        _draw_condition_pills(
            draw,
            _format_condition_line(pass_cond),
            start_x=chip_x1,
            start_y=y1 + 114,
            max_x=x2 - 24,
            label_text=_copy(lang, "pass_label"),
            label_fill=(210, 74, 46, 240),
            pill_fill=(36, 28, 28, 188),
            pill_outline=(255, 226, 186, 160),
        )
        _draw_condition_pills(
            draw,
            _format_condition_line(gold_cond, reference_pass=pass_cond, show_unknown=True),
            start_x=chip_x1,
            start_y=y1 + 156,
            max_x=x2 - 24,
            label_text=_copy(lang, "gold_label"),
            label_fill=(216, 162, 44, 240),
            pill_fill=(68, 46, 22, 198),
            pill_outline=(255, 233, 160, 188),
        )

        row_top += row_height

    _draw_text_with_stroke(
        draw,
        (640, height - 28),
        _copy(lang, "footer"),
        _load_font(18),
        (255, 222, 196),
        2,
        BLACK,
        "mm",
    )

    canvas.alpha_composite(overlay)
    buf = io.BytesIO()
    canvas.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
