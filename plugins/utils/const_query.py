"""按定数查询曲库并渲染分页表格图片。"""

from __future__ import annotations

import io
import json
import math
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from taiko_bot.settings import get_settings

from .song_visibility import is_song_publicly_visible

BASE = get_settings().root_dir
RATING_PATH = BASE / "songs" / "rating_structured_with_ids.json"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
FONT_PATH = BASE / "assets" / "fonts" / "DDFont.ttf"
PROGRESS_BG_PATH = BASE / "assets" / "templates" / "progress_bg.png"

LEVEL_LABELS = {
    1: "简单",
    2: "一般",
    3: "困难",
    4: "鬼",
    5: "里",
}

LEVEL_STAR_FIELD = {
    1: "level_1",
    2: "level_2",
    3: "level_3",
    4: "level_4",
    5: "level_5",
}

DEFAULT_PAGE_SIZE = 25
BPM_COL_MIN_CHARS = 15


@dataclass(frozen=True)
class ConstChartRow:
    song_id: int
    level: int
    const_value: float
    title_cn: str
    title_jp: str
    diff_label: str
    star: str
    bpm: str
    combo: int
    density: str
    stamina: str
    average: str
    song_type: str
    shelf_status: int


def _to_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "" or value == "-":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value: Any, digits: int = 1) -> str:
    num = _to_float(value)
    if num is None:
        return "-"
    if digits <= 0:
        return str(int(round(num)))
    return f"{num:.{digits}f}"


@lru_cache(maxsize=1)
def _load_song_index() -> Dict[int, Dict[str, Any]]:
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        songs = json.load(f)
    return {int(s["id"]): s for s in songs if s.get("id") is not None}


@lru_cache(maxsize=1)
def _load_rating_entries() -> List[Dict[str, Any]]:
    with open(RATING_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    songs = payload.get("songs") or {}
    if isinstance(songs, dict):
        return list(songs.values())
    if isinstance(songs, list):
        return songs
    return []


def _pick_title(song: Optional[Dict[str, Any]], chart: Dict[str, Any]) -> Tuple[str, str]:
    cn = (
        (chart.get("song_name_cn") or "").strip()
        or (song or {}).get("song_name", "")
        or (song or {}).get("song_name_jp", "")
        or chart.get("曲名", "")
        or f"ID{chart.get('id')}"
    )
    jp = (
        (song or {}).get("song_name_jp", "")
        or chart.get("曲名", "")
        or cn
    )
    return str(cn), str(jp)


def query_charts_by_const(
    const_value: float,
    *,
    include_shelf_status: bool = False,
) -> List[ConstChartRow]:
    song_index = _load_song_index()
    rows: List[ConstChartRow] = []
    for chart in _load_rating_entries():
        score = _to_float(chart.get("score"))
        if score is None or abs(score - const_value) >= 1e-6:
            continue
        try:
            song_id = int(chart.get("id"))
            level = int(chart.get("level"))
        except (TypeError, ValueError):
            continue
        song = song_index.get(song_id)
        if not include_shelf_status and not is_song_publicly_visible(song, song_id=song_id):
            continue
        title_cn, title_jp = _pick_title(song, chart)
        star_field = LEVEL_STAR_FIELD.get(level, "level_4")
        star_raw = (song or {}).get(star_field, "-")
        star = "-" if star_raw in (None, "", "-") else str(star_raw)
        rows.append(
            ConstChartRow(
                song_id=song_id,
                level=level,
                const_value=const_value,
                title_cn=title_cn,
                title_jp=title_jp,
                diff_label=LEVEL_LABELS.get(level, f"L{level}"),
                star=star,
                bpm=str(chart.get("bpm") or "-"),
                combo=int(chart.get("combo") or 0),
                density=_fmt_num(chart.get("平均密度")),
                stamina=_fmt_num(chart.get("体力")),
                average=_fmt_num(chart.get("平均")),
                song_type=str((song or {}).get("type") or "-"),
                shelf_status=int((song or {}).get("shelf_status", 0) or 0),
            )
        )
    rows.sort(key=lambda r: (r.song_id, r.level))
    return rows


def paginate_rows(
    rows: List[ConstChartRow], *, page: int, page_size: int = DEFAULT_PAGE_SIZE
) -> Tuple[List[ConstChartRow], int, int]:
    total = len(rows)
    if total == 0:
        return [], 1, 1
    total_pages = max(1, math.ceil(total / page_size))
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return rows[start:end], page, total_pages


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = str(FONT_PATH)
    if os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


def _font_drop(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    _ = (font, ratio)
    return 0


def _draw_text(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill,
) -> None:
    x, y = pos
    draw.text((x, y + _font_drop(font)), text, font=font, fill=fill)


def _col_width_for_chars(
    draw: ImageDraw.ImageDraw,
    font: ImageFont.ImageFont,
    chars: int,
    *,
    padding: int = 20,
) -> int:
    sample = "0" * max(1, chars)
    return int(draw.textlength(sample, font=font)) + padding


def _draw_centered_in_cell(
    draw: ImageDraw.ImageDraw,
    *,
    text: str,
    font: ImageFont.ImageFont,
    cell_x: int,
    cell_w: int,
    row_top: int,
    row_h: int,
    fill,
    max_width: Optional[int] = None,
) -> Tuple[int, int, int, int]:
    """在单元格内水平垂直居中绘制，返回 textbbox (x0,y0,x1,y1)。"""
    limit = cell_w - 16 if max_width is None else min(max_width, cell_w - 16)
    display = _truncate_to_width(draw, text, font, max(0, limit))
    tb = draw.textbbox((0, 0), display, font=font)
    tw = tb[2] - tb[0]
    th = tb[3] - tb[1]
    tx = cell_x + (cell_w - tw) // 2
    ty = row_top + (row_h - th) // 2 - 1
    _draw_text(draw, (tx, ty), display, font=font, fill=fill)
    return (tx, ty, tx + tw, ty + th)


def _truncate_to_width(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if max_width <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ell = "…"
    if draw.textlength(ell, font=font) > max_width:
        return ""
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ell
        if draw.textlength(candidate, font=font) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo] + ell if lo > 0 else ell


def _draw_vertical_gradient(
    img: Image.Image,
    *,
    top: Tuple[int, int, int],
    mid: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> None:
    w, h = img.size
    draw = ImageDraw.Draw(img)
    mid_y = h // 2
    for y in range(h):
        if y <= mid_y:
            t = y / max(1, mid_y)
            c = tuple(int(top[i] * (1 - t) + mid[i] * t) for i in range(3))
        else:
            t = (y - mid_y) / max(1, h - mid_y - 1)
            c = tuple(int(mid[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, w, y), fill=(*c, 255))


def _load_icon_cached(path: str, size: int) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        icon = Image.open(path).convert("RGBA")
        if icon.width != size or icon.height != size:
            icon = icon.resize((size, size), Image.LANCZOS)
        return icon
    except Exception:
        return None


def render_const_query_notice(message: str, *, width: int = 1060) -> bytes:
    font = _load_font(28)
    pad = 24
    img = Image.new("RGBA", (width, pad * 2 + 80), (245, 247, 250, 255))
    draw = ImageDraw.Draw(img)
    _draw_text(draw, (pad, pad), message, font=font, fill=(28, 32, 36, 255))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_const_query_image(
    const_value: float,
    rows: List[ConstChartRow],
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    global_offset: int = 0,
    total_count: Optional[int] = None,
    total_pages: Optional[int] = None,
    show_shelf_status: bool = False,
) -> bytes:
    if not rows:
        return render_const_query_notice(f"未找到定数 {const_value:g} 的曲目。")

    total = total_count if total_count is not None else len(rows)
    pages = total_pages if total_pages is not None else 1
    pad = 24
    title_row_h = 74
    header_h = 58
    row_h = 56
    footer_h = 44 if pages > 1 else 0

    title_font = _load_font(46)
    header_font = _load_font(22)
    row_font = _load_font(22)
    small_font = _load_font(18)
    footer_font = _load_font(20)

    tmp_draw = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    bpm_col_w = _col_width_for_chars(
        tmp_draw, row_font, BPM_COL_MIN_CHARS, padding=24
    )
    cols = [
        ("#", 68),
        ("难度", 92),
        ("曲名", 520),
        ("ID", 116),
        ("★", 68),
        ("BPM", bpm_col_w),
        ("连打", 92),
        ("密度", 92),
        ("体力", 92),
        ("综合", 92),
        ("分类", 156),
    ]
    table_w = sum(cw for _, cw in cols) + 8
    panel_h = title_row_h + header_h + len(rows) * row_h + 14 + footer_h
    img_w = table_w + pad * 2
    img_h = pad + panel_h + pad

    img = Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255))
    if PROGRESS_BG_PATH.exists():
        try:
            bg = Image.open(PROGRESS_BG_PATH).convert("RGBA")
            bg = bg.resize((img_w, img_h), Image.LANCZOS)
            img.alpha_composite(bg, (0, 0))
        except Exception:
            _draw_vertical_gradient(
                img,
                top=(96, 214, 171),
                mid=(136, 212, 188),
                bottom=(236, 134, 145),
            )
    else:
        _draw_vertical_gradient(
            img,
            top=(96, 214, 171),
            mid=(136, 212, 188),
            bottom=(236, 134, 145),
        )
    draw = ImageDraw.Draw(img)

    panel_x = pad
    panel_y = pad
    panel_box = (panel_x, panel_y, panel_x + table_w, panel_y + panel_h)
    draw.rounded_rectangle(
        panel_box,
        radius=14,
        fill=(245, 250, 243, 206),
        outline=(186, 199, 176, 232),
        width=3,
    )

    col_starts: List[int] = []
    x = panel_x + 2
    for _, cw in cols:
        col_starts.append(x)
        x += cw

    title_text = f"定数 {const_value:g} · 共{total}首 · 第{page}/{pages}页"
    title_row_y = panel_y + 8
    draw.rounded_rectangle(
        (panel_x + 8, title_row_y, panel_x + table_w - 8, title_row_y + title_row_h - 6),
        radius=10,
        fill=(218, 226, 205, 228),
    )
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    title_x = panel_x + (table_w - title_w) // 2
    title_y = title_row_y + (title_row_h - title_h) // 2 - 2
    _draw_text(
        draw,
        (title_x, title_y),
        title_text,
        font=title_font,
        fill=(44, 69, 58, 238),
    )

    header_y = title_row_y + title_row_h
    draw.rounded_rectangle(
        (panel_x + 8, header_y, panel_x + table_w - 8, header_y + header_h - 6),
        radius=10,
        fill=(221, 228, 210, 220),
    )
    for (label, cw), cx in zip(cols, col_starts):
        _draw_text(
            draw,
            (cx + (cw - draw.textlength(label, font=header_font)) / 2, header_y + 12),
            label,
            font=header_font,
            fill=(53, 67, 57, 255),
        )

    assets_base = BASE / "assets"
    for idx, row in enumerate(rows):
        row_top = panel_y + title_row_h + header_h + 8 + idx * row_h
        row_bot = row_top + row_h - 4
        fill = (244, 239, 231, 150) if idx % 2 == 0 else (246, 248, 244, 126)
        draw.rounded_rectangle(
            (panel_x + 8, row_top, panel_x + table_w - 8, row_bot),
            radius=8,
            fill=fill,
        )

        seq = global_offset + idx + 1
        values = [
            f"{seq:>2}",
            row.diff_label,
            row.title_cn,
            f"id{row.song_id}",
            row.star,
            row.bpm,
            str(row.combo),
            row.density,
            row.stamina,
            row.average,
            row.song_type,
        ]

        diff_icon = _load_icon_cached(
            str(assets_base / "icons" / "diff" / f"{row.level}.png"), 30
        )
        if diff_icon is not None:
            cell_x = col_starts[1]
            cell_w = cols[1][1]
            ix = cell_x + (cell_w - diff_icon.width) // 2
            iy = row_top + (row_h - diff_icon.height) // 2 - 2
            img.alpha_composite(diff_icon, (ix, iy))
            values[1] = ""

        for col_idx, (text, cw) in enumerate(zip(values, (c[1] for c in cols))):
            if col_idx == 1 and diff_icon is not None:
                continue
            cx = col_starts[col_idx]
            _, ty, _, ty2 = _draw_centered_in_cell(
                draw,
                text=text,
                font=row_font,
                cell_x=cx,
                cell_w=cw,
                row_top=row_top,
                row_h=row_h,
                fill=(44, 49, 53, 245),
            )
            if col_idx == 2 and row.title_jp and row.title_jp != row.title_cn:
                sub = _truncate_to_width(draw, row.title_jp, small_font, cw - 16)
                if sub:
                    sb = draw.textbbox((0, 0), sub, font=small_font)
                    sw = sb[2] - sb[0]
                    _draw_text(
                        draw,
                        (cx + (cw - sw) // 2, ty2 + 1),
                        sub,
                        font=small_font,
                        fill=(96, 104, 108, 210),
                    )

        if show_shelf_status and row.shelf_status == 1:
            badge = "下架"
            bx = panel_x + table_w - 58
            by = row_top + 8
            draw.rounded_rectangle(
                (bx, by, bx + 46, by + 22),
                radius=6,
                fill=(220, 120, 120, 200),
            )
            _draw_text(
                draw,
                (bx + 7, by + 1),
                badge,
                font=small_font,
                fill=(255, 255, 255, 255),
            )

    if pages > 1:
        footer_y = panel_y + panel_h - footer_h + 6
        hint = f"发送「查定数{const_value:g} {page + 1}」查看下一页" if page < pages else ""
        if page > 1 and page < pages:
            hint = f"查定数{const_value:g} 1-{pages} 翻页 · 当前第{page}页"
        elif page >= pages and pages > 1:
            hint = f"查定数{const_value:g} 1-{pages} 可翻页查看"
        if hint:
            _draw_text(
                draw,
                (panel_x + 16, footer_y),
                hint,
                font=footer_font,
                fill=(56, 72, 62, 230),
            )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
