from __future__ import annotations

import io
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata

from .draw_dress import draw_player_info

BASE = get_settings().root_dir
PATH_SONG_DATA = BASE / "songs" / "song_data.json"
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
    return ImageFont.load_default()


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
    draw.text((x, y), text, font=font, fill=fill, **kwargs)


def _truncate_to_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ellipsis = "…"
    if draw.textlength(ellipsis, font=font) > max_w:
        return ""
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        candidate = text[:mid] + ellipsis
        if draw.textlength(candidate, font=font) <= max_w:
            left = mid + 1
        else:
            right = mid
    return text[: right - 1] + ellipsis if right > 0 else ellipsis


@lru_cache(maxsize=128)
def _load_icon_cached(path: str, size: int) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    try:
        icon = Image.open(path).convert("RGBA")
        if size > 0:
            width, height = icon.size
            if height != size:
                new_width = max(1, int(round(width * size / max(1, height))))
                icon = icon.resize((new_width, size), Image.LANCZOS)
        return icon
    except Exception:
        return None


def _crop_box_with_pad(
    image: Image.Image, box: Tuple[int, int, int, int], pad: int = 4
) -> Image.Image:
    x1, y1, x2, y2 = box
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(image.width, x2 + pad)
    y2 = min(image.height, y2 + pad)
    return image.crop((x1, y1, x2, y2))


def _draw_vertical_gradient(
    img: Image.Image,
    top: Tuple[int, int, int],
    mid: Tuple[int, int, int],
    bottom: Tuple[int, int, int],
) -> None:
    width, height = img.size
    pixels = img.load()
    half = max(1, height // 2)
    for y in range(height):
        if y < half:
            ratio = y / max(1, half - 1)
            color = tuple(
                int(round(top[index] + (mid[index] - top[index]) * ratio))
                for index in range(3)
            )
        else:
            ratio = (y - half) / max(1, height - half - 1)
            color = tuple(
                int(round(mid[index] + (bottom[index] - mid[index]) * ratio))
                for index in range(3)
            )
        for x in range(width):
            pixels[x, y] = (*color, 255)


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


def render_target_recommendation_image_bytes(
    user_id: int | str,
    userdata: Dict[str, Any],
    target_display: str,
    rows: List[Dict[str, Any]],
    assets_base: str | Path = BASE / "assets",
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
) -> bytes:
    if userdata is None:
        cached = get_cached_userdata(str(user_id))
        userdata = cached if isinstance(cached, dict) else {}

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
    for _, width in cols:
        col_starts.append(x)
        x += width

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
    for (label, width), col_x in zip(cols, col_starts):
        if not label:
            continue
        _draw_text_with_font_drop(
            draw,
            (col_x + (width - draw.textlength(label, font=header_font)) / 2, header_y + 12),
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
            icon_x = cell_x + (cols[0][1] - diff_icon.width) // 2
            icon_y = row_top + (row_h - diff_icon.height) // 2 - 2
            img.alpha_composite(diff_icon, (icon_x, icon_y))

        def _draw_center_text(col_idx: int, value: str, font_obj: ImageFont.ImageFont, fill_color) -> None:
            box_x = col_starts[col_idx]
            box_w = cols[col_idx][1]
            display = _truncate_to_width(draw, value, font_obj, box_w - 16)
            text_box = draw.textbbox((0, 0), display, font=font_obj)
            text_w = text_box[2] - text_box[0]
            text_h = text_box[3] - text_box[1]
            _draw_text_with_font_drop(
                draw,
                (box_x + (box_w - text_w) // 2, row_top + (row_h - text_h) // 2 - 1),
                display,
                font=font_obj,
                fill=fill_color,
            )

        _draw_center_text(1, str(row.get("song_id", "-")), score_font, (59, 62, 66, 248))
        _draw_center_text(2, str(row.get("star", "-") or "-"), score_font, (59, 62, 66, 248))

        title = str(row.get("title", ""))
        title_cell_x = col_starts[3]
        title_cell_w = cols[3][1]
        title_disp = _truncate_to_width(draw, title, row_font, title_cell_w - 24)
        title_box = draw.textbbox((0, 0), title_disp, font=row_font)
        title_w = title_box[2] - title_box[0]
        title_h = title_box[3] - title_box[1]
        _draw_text_with_font_drop(
            draw,
            (title_cell_x + (title_cell_w - title_w) // 2, row_top + (row_h - title_h) // 2 - 1),
            title_disp,
            font=row_font,
            fill=(44, 49, 53, 245),
        )

        score_value = row.get("score")
        _draw_center_text(4, "-" if score_value is None else str(score_value), score_font, (59, 62, 66, 248))
        _draw_target_recommend_arrow(
            draw,
            (col_starts[5] + 14, row_top + 8, col_starts[5] + cols[5][1] - 14, row_bot - 8),
        )
        _draw_center_text(6, str(row.get("target_text", "-")), score_font, (59, 62, 66, 248))
        _draw_center_text(7, str(row.get("gap_text", "-")), score_font, (92, 64, 47, 248))

        recommend_index = max(0.0, min(100.0, float(row.get("recommend_index", 0.0) or 0.0)))
        if recommend_index >= 80:
            index_color = (32, 116, 85, 255)
        elif recommend_index >= 60:
            index_color = (126, 91, 31, 255)
        else:
            index_color = (146, 67, 67, 255)
        _draw_center_text(8, f"{recommend_index:.1f}", index_font, index_color)

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
