from __future__ import annotations
from .paths import ROOT as _ROOT


import os

from pathlib import Path

from typing import Dict, Any, Tuple, List, Optional

from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

import io

from .draw_dress import draw_player_info

BASE = _ROOT  # 如在本地请改成你的真实路径

PROGRESS_BG_PATH = BASE / "assets" / "templates" / "progress_bg.png"

DEFAULT_PROGRESS_FONT_PATH = str(BASE / "assets" / "fonts" / "DDFont.ttf")

def _load_font(
    font_path: str | None, size: int
) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if font_path and os.path.exists(font_path):
        try:
            return ImageFont.truetype(font_path, size)
        except Exception:
            pass
    # 回退
    return ImageFont.load_default()

def _font_drop(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    _ = (font, ratio)
    return 0

def _draw_text_with_font_drop(
    draw: ImageDraw.ImageDraw,
    pos: Tuple[float, float],
    text: str,
    *,
    font: ImageFont.ImageFont,
    fill,
    **kwargs,
) -> None:
    x, y = pos
    draw.text((x, y + _font_drop(font)), text, font=font, fill=fill, **kwargs)

def _truncate_to_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    """若文本太长则末尾加省略号"""
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    if draw.textlength(ell, font=font) > max_w:
        return ""  # 太窄，直接空
    # 二分截断
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        t = text[:mid] + ell
        if draw.textlength(t, font=font) <= max_w:
            left = mid + 1
        else:
            right = mid
    return text[: right - 1] + ell if right > 0 else ell

@lru_cache(maxsize=128)
def _load_icon_cached(path: str, size: int) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        icon = Image.open(path).convert("RGBA")
        if size > 0:
            w, h = icon.size
            if h != size:
                nw = max(1, int(round(w * size / max(1, h))))
                icon = icon.resize((nw, size), Image.LANCZOS)
        return icon
    except Exception:
        return None

def _draw_target_recommend_arrow(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
) -> None:
    x1, y1, x2, y2 = box
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    shaft_len = min(58, max(26, (x2 - x1) // 2))
    shaft_h = 12
    head_w = 24
    head_h = 34
    left = cx - (shaft_len + head_w) // 2
    shaft_box = (
        left,
        cy - shaft_h // 2,
        left + shaft_len,
        cy + shaft_h // 2,
    )
    color = (44, 160, 98, 255)
    outline = (18, 96, 62, 180)
    draw.rounded_rectangle(shaft_box, radius=shaft_h // 2, fill=color)
    head = [
        (left + shaft_len - 2, cy - head_h // 2),
        (left + shaft_len + head_w, cy),
        (left + shaft_len - 2, cy + head_h // 2),
    ]
    draw.polygon(head, fill=color)
    draw.line(
        [head[0], head[1], head[2]],
        fill=outline,
        width=2,
        joint="curve",
    )

def _crop_box_with_pad(
    image: Image.Image, box: Tuple[int, int, int, int], pad: int = 4
) -> Image.Image:
    x1, y1, x2, y2 = box
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(image.width, x2 + pad)
    y2 = min(image.height, y2 + pad)
    return image.crop((x1, y1, x2, y2))

def _render_progress_profile_panel(
    userdata: Dict[str, Any],
    target_width: int,
    font_path: str | None,
) -> Image.Image:
    canvas = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(font_path, 16)
    title_font = _load_font(font_path, 16)
    box = draw_player_info(
        base=canvas,
        draw=draw,
        userdata=userdata,
        sx=1.0,
        sy=1.0,
        font=font,
        stroke_width=2,
        fill=(255, 255, 255),
        stroke_fill=(0, 0, 0),
        offset_xy=(0, 0),
        title_font=title_font,
    )
    panel = _crop_box_with_pad(canvas, box, pad=4)
    if panel.width <= 0:
        return panel
    scale = target_width / panel.width
    target_h = max(1, int(round(panel.height * scale)))
    return panel.resize((target_width, target_h), Image.LANCZOS)

def _draw_vertical_gradient(
    img: Image.Image,
    top: Tuple[int, int, int],
    mid: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> None:
    draw = ImageDraw.Draw(img)
    w, h = img.size
    mid_y = h * 0.56
    for y in range(h):
        if y <= mid_y:
            t = y / max(1, mid_y)
            c = tuple(int(top[i] * (1 - t) + mid[i] * t) for i in range(3))
        else:
            t = (y - mid_y) / max(1, h - mid_y - 1)
            c = tuple(int(mid[i] * (1 - t) + bottom[i] * t) for i in range(3))
        draw.line((0, y, w, y), fill=(*c, 255))

def render_target_recommendation_image_bytes(
    user_id: int,
    userdata: Dict[str, Any],
    target_display: str,
    rows: List[Dict[str, Any]],
    assets_base: str | Path = str(_ROOT / 'assets'),
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
) -> bytes:
    table_w = 1602
    pad = 24
    title_row_h = 74
    header_h = 58
    row_h = 56
    top_gap = 16
    bottom_pad = 24

    assets_base_path = Path(assets_base)
    profile_panel = _render_progress_profile_panel(
        userdata=userdata,
        target_width=640,
        font_path=font_path,
    )
    top_area_h = max(profile_panel.height + top_gap, 130)
    panel_h = title_row_h + header_h + len(rows) * row_h + 14
    img_w = table_w + pad * 2
    img_h = pad + top_area_h + panel_h + bottom_pad

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
    panel_y = pad + top_area_h
    panel_box = (panel_x, panel_y, panel_x + table_w, panel_y + panel_h)
    draw.rounded_rectangle(
        panel_box,
        radius=14,
        fill=(245, 250, 243, 206),
        outline=(186, 199, 176, 232),
        width=3,
    )

    if profile_panel.width > 0 and profile_panel.height > 0:
        img.alpha_composite(profile_panel, (panel_x + 8, pad))

    title_font = _load_font(font_path, 52)
    header_font = _load_font(font_path, 24)
    row_font = _load_font(font_path, 24)
    score_font = _load_font(font_path, 22)
    index_font = _load_font(font_path, 22)

    cols = [
        ("难度", 96),
        ("ID", 92),
        ("星级", 92),
        ("曲名", 490),
        ("分数", 150),
        ("", 150),
        ("目标分数", 150),
        ("差距", 190),
        ("推荐指数", 190),
    ]
    col_starts: List[int] = []
    x = panel_x + 2
    for _, cw in cols:
        col_starts.append(x)
        x += cw

    title_row_y = panel_y + 8
    draw.rounded_rectangle(
        (panel_x + 8, title_row_y, panel_x + table_w - 8, title_row_y + title_row_h - 6),
        radius=10,
        fill=(218, 226, 205, 228),
    )
    full_title = f"{target_display}目标推荐 · 共{len(rows)}首"
    title_bbox = draw.textbbox((0, 0), full_title, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    title_x = panel_x + (table_w - title_w) // 2
    title_y = title_row_y + (title_row_h - title_h) // 2 - 2
    _draw_text_with_font_drop(
        draw,
        (title_x, title_y),
        full_title,
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
        if not label:
            continue
        _draw_text_with_font_drop(
            draw,
            (cx + (cw - draw.textlength(label, font=header_font)) / 2, header_y + 12),
            label,
            font=header_font,
            fill=(53, 67, 57, 255),
        )

    for idx, row in enumerate(rows):
        row_top = panel_y + title_row_h + header_h + 8 + idx * row_h
        row_bot = row_top + row_h - 4
        fill = (244, 239, 231, 150) if idx % 2 == 0 else (246, 248, 244, 126)
        draw.rounded_rectangle(
            (panel_x + 8, row_top, panel_x + table_w - 8, row_bot),
            radius=8,
            fill=fill,
        )

        level = int(row.get("level", 4) or 4)
        diff_icon = _load_icon_cached(
            str(assets_base_path / "icons" / "diff" / f"{level}.png"),
            32,
        )
        cell_x = col_starts[0]
        if diff_icon is not None:
            ix = cell_x + (cols[0][1] - diff_icon.width) // 2
            iy = row_top + (row_h - diff_icon.height) // 2 - 2
            img.alpha_composite(diff_icon, (ix, iy))

        song_id_txt = str(row.get("song_id", "-"))
        id_x = col_starts[1]
        id_w = cols[1][1]
        id_disp = _truncate_to_width(draw, song_id_txt, score_font, id_w - 14)
        ib = draw.textbbox((0, 0), id_disp, font=score_font)
        _draw_text_with_font_drop(
            draw,
            (id_x + (id_w - (ib[2] - ib[0])) // 2, row_top + (row_h - (ib[3] - ib[1])) // 2 - 1),
            id_disp,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        star_txt = str(row.get("star", "-") or "-")
        star_x = col_starts[2]
        star_w = cols[2][1]
        star_disp = _truncate_to_width(draw, star_txt, score_font, star_w - 12)
        stb = draw.textbbox((0, 0), star_disp, font=score_font)
        _draw_text_with_font_drop(
            draw,
            (star_x + (star_w - (stb[2] - stb[0])) // 2, row_top + (row_h - (stb[3] - stb[1])) // 2 - 1),
            star_disp,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        title = str(row.get("title", ""))
        title_cell_x = col_starts[3]
        title_cell_w = cols[3][1]
        title_disp = _truncate_to_width(draw, title, row_font, title_cell_w - 24)
        tb = draw.textbbox((0, 0), title_disp, font=row_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        _draw_text_with_font_drop(
            draw,
            (title_cell_x + (title_cell_w - tw) // 2, row_top + (row_h - th) // 2 - 1),
            title_disp,
            font=row_font,
            fill=(44, 49, 53, 245),
        )

        score = row.get("score")
        score_txt = "-" if score is None else str(score)
        sx = col_starts[4]
        sw = cols[4][1]
        sb = draw.textbbox((0, 0), score_txt, font=score_font)
        _draw_text_with_font_drop(
            draw,
            (sx + (sw - (sb[2] - sb[0])) // 2, row_top + (row_h - (sb[3] - sb[1])) // 2 - 1),
            score_txt,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        px = col_starts[5]
        pw = cols[5][1]
        _draw_target_recommend_arrow(
            draw,
            (px + 14, row_top + 8, px + pw - 14, row_bot - 8),
        )

        target_txt = str(row.get("target_text", "-"))
        target_x = col_starts[6]
        target_w = cols[6][1]
        target_disp = _truncate_to_width(draw, target_txt, score_font, target_w - 16)
        tb = draw.textbbox((0, 0), target_disp, font=score_font)
        _draw_text_with_font_drop(
            draw,
            (target_x + (target_w - (tb[2] - tb[0])) // 2, row_top + (row_h - (tb[3] - tb[1])) // 2 - 1),
            target_disp,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        gap_txt = str(row.get("gap_text", "-"))
        gap_x = col_starts[7]
        gap_w = cols[7][1]
        gap_disp = _truncate_to_width(draw, gap_txt, score_font, gap_w - 16)
        gb = draw.textbbox((0, 0), gap_disp, font=score_font)
        _draw_text_with_font_drop(
            draw,
            (gap_x + (gap_w - (gb[2] - gb[0])) // 2, row_top + (row_h - (gb[3] - gb[1])) // 2 - 1),
            gap_disp,
            font=score_font,
            fill=(92, 64, 47, 248),
        )

        rec_idx = max(0.0, min(100.0, float(row.get("recommend_index", 0.0) or 0.0)))
        index_txt = f"{rec_idx:.1f}"
        ix = col_starts[8]
        iw = cols[8][1]
        ib = draw.textbbox((0, 0), index_txt, font=index_font)
        if rec_idx >= 80:
            index_color = (32, 116, 85, 255)
        elif rec_idx >= 60:
            index_color = (126, 91, 31, 255)
        else:
            index_color = (146, 67, 67, 255)
        _draw_text_with_font_drop(
            draw,
            (ix + (iw - (ib[2] - ib[0])) // 2, row_top + (row_h - (ib[3] - ib[1])) // 2 - 1),
            index_txt,
            font=index_font,
            fill=index_color,
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
