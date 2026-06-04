# -*- coding: utf-8 -*-
"""
B30 summary image renderer based on assets/templates/b30_template.png.
"""

from __future__ import annotations

import datetime
import json
import math
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from PIL import Image, ImageDraw, ImageFont
from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata

from .b30_single import (
    _compute_rating_for_entry,
    _load_rating_resources,
    build_song_index,
    render_b30_single_card,
)
from .draw_dress import (
    TITLE_FONT_PATH,
    draw_player_info,
    _crop_with_pad,
    _get_font,
    _get_font_by_path,
    _load_previous_song_map,
    render_user_dress,
)
from .score_calculator import (
    TREND_COLORS,
    TREND_DIM_COLUMNS,
    TREND_SHORT_LABELS,
    _compute_results_from_userdata_records,
    aggregate_topN_value,
    build_daily_rating_points,
    compute_all_from_userdata,
    compute_dim_topN_means,
    get_song_chart_identity_key,
    load_rating_config,
    getUtime,
)
from .song_visibility import is_song_id_publicly_visible

ROOT_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT_DIR / "assets"
TEMPLATE_DEFAULT = ASSETS_DIR / "templates" / "b30_template.png"
SONG_DB_DEFAULT = ROOT_DIR / "songs" / "song_data.json"
RATING_JSON_DEFAULT = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

FONT_TITLE_PATH = ASSETS_DIR / "fonts" / "FZPW_GBK.ttf"
FONT_DD_PATH = ASSETS_DIR / "fonts" / "DDFont.ttf"

B30_DELTA_EPSILON = 0.001

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Template layout (1080x2982)
TOP_WHITE_BOX = (70, 332, 1010, 702)
TOP_ORANGE_BOX = (70, 238, 1010, 331)
MID_ORANGE_BOX = (70, 703, 1010, 760)

GRID_BOX = (70, 780, 1010, 2760)
FOOTER_START_Y = 2750
BODY_REPEAT_SLICE_Y = 2480
BODY_REPEAT_SLICE_H = 80

GRID_GAP_X = 30
GRID_GAP_Y = 18
CARD_PAD_X = 35
CARD_PAD_Y = 25
GRID_PAD_SIDE = 18
GRID_PAD_TOP = 32
GRID_PAD_BOTTOM = 24

TOP_PAD_X = 24
TOP_PAD_Y = 24
TOP_GAP_X = 18
TOP_CENTER_GAP_Y = 12

RATING_FONT_SIZE = 48
UPDATE_FONT_SIZE = 28
MAX_CARD_SCALE = 1.0
MAX_GRID_COLS = 4
MIN_CARD_SCALE = 0.38
SOFT_MAX_CANVAS_HEIGHT = 3600
HEIGHT_OVERFLOW_WEIGHT = 1.2
SMALL_CARD_PENALTY = 4000
LARGE_CARD_PENALTY = 600


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    text = str(hex_color or "").strip().lstrip("#")
    if len(text) != 6:
        return (78, 121, 167, alpha)
    try:
        return (
            int(text[0:2], 16),
            int(text[2:4], 16),
            int(text[4:6], 16),
            alpha,
        )
    except Exception:
        return (78, 121, 167, alpha)


def _ddfont_y_offset(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))


def _draw_text_with_stroke(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_width: int,
    stroke_fill: Tuple[int, int, int],
) -> None:
    x, y = xy
    y += _ddfont_y_offset(font)
    try:
        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
    except TypeError:
        for dx, dy in [
            (-stroke_width, 0),
            (stroke_width, 0),
            (0, -stroke_width),
            (0, stroke_width),
            (-stroke_width, -stroke_width),
            (-stroke_width, stroke_width),
            (stroke_width, -stroke_width),
            (stroke_width, stroke_width),
        ]:
            draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
        draw.text((x, y), text, font=font, fill=fill)


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    center: Tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int] | Tuple[int, int, int],
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    x = int(round(center[0] - tw / 2 - bbox[0]))
    y = int(round(center[1] - th / 2 - bbox[1]))
    y += _ddfont_y_offset(font)
    draw.text((x, y), text, font=font, fill=fill)


def _draw_multiline_centered(
    draw: ImageDraw.ImageDraw,
    center: Tuple[float, float],
    lines: List[Tuple[str, ImageFont.ImageFont, Tuple[int, int, int, int]]],
    line_gap: int = 1,
    line_gaps: Optional[List[int]] = None,
) -> None:
    line_sizes = []
    total_h = 0
    for text, font, _ in lines:
        bbox = draw.textbbox((0, 0), text, font=font)
        h = bbox[3] - bbox[1]
        line_sizes.append((bbox, h))
        total_h += h
    for idx in range(max(0, len(lines) - 1)):
        gap = line_gaps[idx] if line_gaps and idx < len(line_gaps) else line_gap
        total_h += gap

    y = int(round(center[1] - total_h / 2))
    for line_idx, ((text, font, fill), (bbox, h)) in enumerate(zip(lines, line_sizes)):
        tw = bbox[2] - bbox[0]
        x = int(round(center[0] - tw / 2 - bbox[0]))
        draw.text((x, y - bbox[1] + _ddfont_y_offset(font)), text, font=font, fill=fill)
        if line_idx < len(lines) - 1:
            gap = (
                line_gaps[line_idx]
                if line_gaps and line_idx < len(line_gaps)
                else line_gap
            )
            y += h + gap


def _center_box(
    box: Tuple[int, int, int, int], size: Tuple[int, int]
) -> Tuple[int, int]:
    x1, y1, x2, y2 = box
    w, h = size
    x = x1 + max(0, (x2 - x1 - w) // 2)
    y = y1 + max(0, (y2 - y1 - h) // 2)
    return x, y


def _paste_scaled_center(
    base: Image.Image, overlay: Image.Image, box: Tuple[int, int, int, int]
) -> None:
    x1, y1, x2, y2 = box
    max_w = max(1, x2 - x1)
    max_h = max(1, y2 - y1)
    ow, oh = overlay.size
    scale = min(max_w / ow, max_h / oh)
    nw = max(1, int(round(ow * scale)))
    nh = max(1, int(round(oh * scale)))
    resized = overlay.resize((nw, nh), Image.LANCZOS)
    px, py = _center_box(box, resized.size)
    base.alpha_composite(resized, (px, py))


def _paste_scaled_center_zoom(
    base: Image.Image,
    overlay: Image.Image,
    box: Tuple[int, int, int, int],
    scale_multiplier: float,
) -> None:
    x1, y1, x2, y2 = box
    max_w = max(1, x2 - x1)
    max_h = max(1, y2 - y1)
    ow, oh = overlay.size
    scale = min(max_w / ow, max_h / oh) * scale_multiplier
    nw = max(1, int(round(ow * scale)))
    nh = max(1, int(round(oh * scale)))
    resized = overlay.resize((nw, nh), Image.LANCZOS)
    cx = (x1 + x2) // 2
    cy = (y1 + y2) // 2
    px = cx - nw // 2
    py = cy - nh // 2
    base.alpha_composite(resized, (px, py))


def _trend_series_value(point: Tuple[datetime.datetime, Dict[str, float], float], name: str) -> float:
    if name == "综合Rating":
        return float(point[2])
    return float(point[1].get(name, 0.0))


def _load_trend_ranges(user_id: int, N: int, max_days: int = 30) -> List[Dict[str, Any]]:
    daily_points = build_daily_rating_points(
        user_id, N=N, json_path=RATING_JSON_DEFAULT, max_days=max_days
    )
    if not daily_points:
        return []

    rows: List[Dict[str, Any]] = []
    for category in [*TREND_DIM_COLUMNS, "综合Rating"]:
        values = [_trend_series_value(point, category) for point in daily_points]
        if not values:
            continue
        vmin = min(values)
        vmax = max(values)
        rows.append(
            {
                "label": TREND_SHORT_LABELS.get(category, category),
                "delta": max(0.0, vmax - vmin),
                "latest": values[-1],
                "color": _hex_to_rgba(TREND_COLORS.get(category, "#4E79A7")),
            }
        )
    return rows


def _render_trend_image(
    user_id: int, N: int, size: Tuple[int, int]
) -> Optional[Image.Image]:
    rows = _load_trend_ranges(user_id, N, max_days=30)
    if not rows:
        return None

    width, height = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(FONT_DD_PATH, 20)
    font_sub = _load_font(FONT_DD_PATH, 14)
    font_label = _load_font(FONT_DD_PATH, 17)
    font_value = _load_font(FONT_DD_PATH, 16)

    _draw_centered_text(draw, (width / 2, 16), "近30日区间", font_title, (17, 24, 39, 255))
    _draw_centered_text(draw, (width / 2, 38), f"Top{N} 均值变化", font_sub, (75, 85, 99, 255))

    max_delta = max([row["delta"] for row in rows] + [0.01])
    top = 56
    bottom_pad = 6
    row_h = max(1.0, (height - top - bottom_pad) / len(rows))
    label_x = 8
    bar_x = 56
    value_w = 54
    bar_w = max(20, width - bar_x - value_w - 8)
    bar_h = 13

    for idx, row in enumerate(rows):
        cy = top + row_h * idx + row_h / 2
        label = str(row["label"])
        delta = float(row["delta"])
        color = row["color"]

        draw.text(
            (label_x, int(round(cy - 10)) + _ddfont_y_offset(font_label)),
            label,
            font=font_label,
            fill=(31, 41, 55, 255),
        )

        track = (
            bar_x,
            int(round(cy - bar_h / 2)),
            bar_x + bar_w,
            int(round(cy + bar_h / 2)),
        )
        draw.rectangle(track, fill=(229, 231, 235, 255))
        fill_w = int(round(bar_w * (delta / max_delta))) if max_delta > 0 else 0
        if delta > 0:
            fill_w = max(4, fill_w)
        if fill_w > 0:
            draw.rectangle(
                (track[0], track[1], track[0] + min(bar_w, fill_w), track[3]),
                fill=color,
            )

        value_text = f"+{delta:.2f}"
        value_bbox = draw.textbbox((0, 0), value_text, font=font_value)
        value_h = value_bbox[3] - value_bbox[1]
        draw.text(
            (bar_x + bar_w + 7, int(round(cy - value_h / 2 - value_bbox[1]))),
            value_text,
            font=font_value,
            fill=(17, 24, 39, 255),
        )

    return img


def _topn_entry_identity_keys(
    top_entries: List[Tuple[float, Dict[str, Any]]],
) -> Set[Tuple[str, int, int]]:
    keys: Set[Tuple[str, int, int]] = set()
    for _, entry in top_entries:
        try:
            song_no = int(entry.get("song_no", 0))
            level = int(entry.get("level", 0))
        except (TypeError, ValueError):
            continue
        keys.add(get_song_chart_identity_key(song_no, level))
    return keys


def compute_b30_update_diff(
    user_id: int,
    N: int,
    *,
    current_results: List[Any],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
    current_top_entries: List[Tuple[float, Dict[str, Any]]],
) -> Tuple[Set[Tuple[str, int, int]], Dict[str, float]]:
    prev_map = _load_previous_song_map(user_id)
    if not prev_map:
        return set(), {}

    prev_top_entries = _pick_top_entries(
        list(prev_map.values()), rating_index, const_table, N
    )
    prev_keys = _topn_entry_identity_keys(prev_top_entries)
    curr_keys = _topn_entry_identity_keys(current_top_entries)
    new_keys = curr_keys - prev_keys

    cfg = load_rating_config(RATING_JSON_DEFAULT)
    prev_results = _compute_results_from_userdata_records(
        list(prev_map.values()), cfg, const_table
    )
    if not prev_results or not current_results:
        return new_keys, {}

    prev_means = compute_dim_topN_means(prev_results, N)
    curr_means = compute_dim_topN_means(current_results, N)
    dim_deltas: Dict[str, float] = {}
    for category in TREND_DIM_COLUMNS:
        delta = float(curr_means.get(category, 0.0)) - float(prev_means.get(category, 0.0))
        if abs(delta) > B30_DELTA_EPSILON:
            dim_deltas[category] = delta
    return new_keys, dim_deltas


def _render_radar_image(
    results: List[Any],
    N: int,
    size: Tuple[int, int],
    *,
    dim_deltas: Optional[Dict[str, float]] = None,
) -> Image.Image:
    dim_means = compute_dim_topN_means(results, N)
    categories = ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"]
    labels = [TREND_SHORT_LABELS.get(category, category) for category in categories]
    values = [float(dim_means.get(category, 0.0)) for category in categories]

    width, height = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_title = _load_font(FONT_DD_PATH, 20)
    font_label = _load_font(FONT_DD_PATH, 16)
    font_value = _load_font(FONT_DD_PATH, 15)
    font_delta = _load_font(FONT_DD_PATH, 13)

    _draw_centered_text(draw, (width / 2, 16), "六维得分", font_title, (17, 24, 39, 255))

    if values:
        rmin = max(0.0, math.floor(min(values)) - 1.0)
        rmax = min(15.5, math.ceil(max(values)) + 0.2)
    else:
        rmin, rmax = 0.0, 15.5
    if rmax <= rmin:
        rmax = rmin + 1.0

    cx = width / 2
    cy = height * 0.53
    radius = min(width * 0.285, height * 0.265)
    axis_count = len(categories)
    angles = [(-math.pi / 2) + i * 2 * math.pi / axis_count for i in range(axis_count)]

    def point_for(angle: float, ratio: float) -> Tuple[float, float]:
        return (
            cx + math.cos(angle) * radius * ratio,
            cy + math.sin(angle) * radius * ratio,
        )

    grid_color = (148, 163, 184, 165)
    spoke_color = (148, 163, 184, 125)
    for step in range(1, 5):
        ratio = step / 4
        pts = [point_for(angle, ratio) for angle in angles]
        draw.line(pts + [pts[0]], fill=grid_color, width=1)
    for angle in angles:
        px, py = point_for(angle, 1.0)
        draw.line((cx, cy, px, py), fill=spoke_color, width=1)

    value_points = []
    for angle, value in zip(angles, values):
        ratio = max(0.0, min(1.0, (value - rmin) / (rmax - rmin)))
        value_points.append(point_for(angle, ratio))

    if value_points:
        draw.polygon(value_points, fill=(37, 99, 235, 54))
        draw.line(value_points + [value_points[0]], fill=(37, 99, 235, 255), width=3)
        dot_r = 3
        for px, py in value_points:
            draw.ellipse(
                (px - dot_r, py - dot_r, px + dot_r, py + dot_r),
                fill=(37, 99, 235, 255),
            )

    label_radius = radius + 36
    delta_positive = (46, 125, 50, 255)
    delta_negative = (198, 40, 40, 255)
    for angle, label, value, category in zip(angles, labels, values, categories):
        lx = cx + math.cos(angle) * label_radius
        ly = cy + math.sin(angle) * label_radius
        lx = max(28, min(width - 28, lx))
        ly = max(50, min(height - 22, ly))
        lines: List[Tuple[str, ImageFont.ImageFont, Tuple[int, int, int, int]]] = [
            (label, font_label, (17, 24, 39, 255)),
            (f"{value:.2f}", font_value, (37, 99, 235, 255)),
        ]
        line_gaps = [2]
        if dim_deltas and category in dim_deltas:
            delta = float(dim_deltas[category])
            delta_text = f"{delta:+.2f}"
            delta_color = delta_positive if delta > 0 else delta_negative
            lines.append((delta_text, font_delta, delta_color))
            line_gaps.append(5)
        _draw_multiline_centered(
            draw,
            (lx, ly),
            lines,
            line_gap=2,
            line_gaps=line_gaps,
        )

    return img


def _format_update_date(user_id: int) -> str:
    ts = getUtime(user_id)
    if not ts:
        return "更新于未知"
    try:
        dt = datetime.datetime.fromisoformat(ts)
    except Exception:
        return f"更新于{ts[:10]}"
    return f"更新于{dt.strftime('%Y-%m-%d')}"


def _build_best_entry_map(
    entries: List[Dict[str, Any]],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
) -> Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]]:
    best: Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]] = {}
    for entry in entries:
        try:
            song_no = int(entry.get("song_no", 0))
            level = int(entry.get("level", 0))
        except Exception:
            continue
        if level < 4 or not is_song_id_publicly_visible(song_no):
            continue
        rating = _compute_rating_for_entry(entry, rating_index, const_table)
        if rating is None or rating <= 0:
            continue
        key = get_song_chart_identity_key(song_no, level)
        previous = best.get(key)
        score = int(entry.get("high_score", 0) or 0)
        previous_score = (
            int(previous[1].get("high_score", 0) or 0) if previous is not None else -1
        )
        if previous is None or rating > previous[0] or (
            abs(rating - previous[0]) <= 1e-9 and score > previous_score
        ):
            best[key] = (float(rating), entry)
    return best


def _pick_top_entries(
    entries: List[Dict[str, Any]],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
    N: int,
) -> List[Tuple[float, Dict[str, Any]]]:
    best_map = _build_best_entry_map(entries, rating_index, const_table)
    rated = list(best_map.values())
    rated.sort(key=lambda x: x[0], reverse=True)
    return rated[:N]


def _grid_gaps_for_cols(cols: int) -> Tuple[int, int]:
    if cols >= 4:
        return 24, 16
    return GRID_GAP_X, GRID_GAP_Y


def _compute_body_height(rows: int, card_h_vis: int, gap_y: int) -> int:
    if rows <= 0:
        return GRID_PAD_TOP + GRID_PAD_BOTTOM
    return (
        GRID_PAD_TOP
        + GRID_PAD_BOTTOM
        + rows * card_h_vis
        + (rows - 1) * gap_y
    )


def _choose_grid_layout(
    total_count: int,
    *,
    grid_w: int,
    card_w0: int,
    card_h0: int,
    target_canvas_height: int,
    footer_height: int,
) -> Dict[str, int | float]:
    if total_count <= 0:
        return {
            "cols": 3,
            "rows": 0,
            "scale": 0.0,
            "gap_x": GRID_GAP_X,
            "gap_y": GRID_GAP_Y,
            "card_w": 0,
            "card_h": 0,
            "card_w_vis": 0,
            "card_h_vis": 0,
            "pad_x": 0,
            "pad_y": 0,
            "body_height": GRID_PAD_TOP + GRID_PAD_BOTTOM,
            "canvas_height": GRID_BOX[1] + GRID_PAD_TOP + GRID_PAD_BOTTOM + footer_height,
        }

    card_w0_vis = max(1, card_w0 - CARD_PAD_X * 2)
    card_h0_vis = max(1, card_h0 - CARD_PAD_Y * 2)

    min_cols = 1 if total_count == 1 else 2
    max_cols = min(MAX_GRID_COLS, total_count)
    best_layout: Optional[Dict[str, int | float]] = None
    best_key: Optional[Tuple[float, float, int]] = None

    for cols in range(min_cols, max_cols + 1):
        gap_x, gap_y = _grid_gaps_for_cols(cols)
        available_w = grid_w - GRID_PAD_SIDE * 2 - (cols - 1) * gap_x
        if available_w <= 0:
            continue

        scale = min(MAX_CARD_SCALE, available_w / (cols * card_w0_vis))
        card_w = max(1, int(round(card_w0 * scale)))
        card_h = max(1, int(round(card_h0 * scale)))
        pad_x = max(0, int(round(CARD_PAD_X * scale)))
        pad_y = max(0, int(round(CARD_PAD_Y * scale)))
        card_w_vis = max(1, card_w - pad_x * 2)
        card_h_vis = max(1, card_h - pad_y * 2)
        rows = math.ceil(total_count / cols)
        body_height = _compute_body_height(rows, card_h_vis, gap_y)
        canvas_height = GRID_BOX[1] + body_height + footer_height

        score = abs(canvas_height - target_canvas_height)
        if canvas_height > SOFT_MAX_CANVAS_HEIGHT:
            score += (canvas_height - SOFT_MAX_CANVAS_HEIGHT) * HEIGHT_OVERFLOW_WEIGHT
        if scale < MIN_CARD_SCALE:
            score += (MIN_CARD_SCALE - scale) * SMALL_CARD_PENALTY
        if scale > 0.95:
            score += (scale - 0.95) * LARGE_CARD_PENALTY

        key = (score, -scale, cols)
        if best_key is None or key < best_key:
            best_key = key
            best_layout = {
                "cols": cols,
                "rows": rows,
                "scale": scale,
                "gap_x": gap_x,
                "gap_y": gap_y,
                "card_w": card_w,
                "card_h": card_h,
                "card_w_vis": card_w_vis,
                "card_h_vis": card_h_vis,
                "pad_x": pad_x,
                "pad_y": pad_y,
                "body_height": body_height,
                "canvas_height": canvas_height,
            }

    if best_layout is None:
        raise ValueError("failed to choose grid layout")
    return best_layout


def _compose_resizable_template(
    template: Image.Image,
    *,
    body_height: int,
) -> Image.Image:
    width, height = template.size
    body_top = GRID_BOX[1]
    footer_start = FOOTER_START_Y
    body_height = max(1, int(body_height))

    top_part = template.crop((0, 0, width, body_top))
    body_part = template.crop((0, body_top, width, footer_start))
    footer_part = template.crop((0, footer_start, width, height))

    if body_height <= body_part.height:
        body = body_part.crop((0, 0, width, body_height))
    else:
        body = Image.new("RGBA", (width, body_height), (0, 0, 0, 0))
        body.alpha_composite(body_part, (0, 0))

        slice_y1 = BODY_REPEAT_SLICE_Y
        slice_y2 = BODY_REPEAT_SLICE_Y + BODY_REPEAT_SLICE_H
        repeat_slice = template.crop((0, slice_y1, width, slice_y2))
        y = body_part.height
        while y < body_height:
            chunk_h = min(repeat_slice.height, body_height - y)
            if chunk_h == repeat_slice.height:
                chunk = repeat_slice
            else:
                chunk = repeat_slice.crop((0, 0, width, chunk_h))
            body.alpha_composite(chunk, (0, y))
            y += chunk_h

    canvas = Image.new(
        "RGBA",
        (width, body_top + body_height + footer_part.height),
        (0, 0, 0, 0),
    )
    canvas.alpha_composite(top_part, (0, 0))
    canvas.alpha_composite(body, (0, body_top))
    canvas.alpha_composite(footer_part, (0, body_top + body_height))
    return canvas


def render_b30_image(
    user_id: int,
    N: int = 30,
    *,
    template_path: str | Path = TEMPLATE_DEFAULT,
    song_db_path: str | Path = SONG_DB_DEFAULT,
    assets_base: str | Path = ASSETS_DIR,
    rating_json_path: str | Path = RATING_JSON_DEFAULT,
    userdata: Optional[Dict[str, Any]] = None,
) -> bytes:
    assets_base = Path(assets_base)
    template_path = Path(template_path)
    template = Image.open(template_path).convert("RGBA")

    userdata = userdata if isinstance(userdata, dict) else get_cached_userdata(str(user_id))
    if userdata is None:
        userdata_path = get_settings().userdata_dir / f"{user_id}data.json"
        if not userdata_path.exists():
            raise FileNotFoundError(f"userdata not found: {userdata_path}")
        userdata = _load_json(userdata_path)
    entries = userdata.get("songs", []) if isinstance(userdata, dict) else []

    song_db = _load_json(Path(song_db_path))
    song_index = build_song_index(song_db)

    _, rating_index, const_table = _load_rating_resources(str(rating_json_path))
    top_entries = _pick_top_entries(entries, rating_index, const_table, N)

    results = compute_all_from_userdata(user_id)
    overall = aggregate_topN_value(results, "AI_rating", N)
    new_keys, dim_deltas = compute_b30_update_diff(
        user_id,
        N,
        current_results=results,
        rating_index=rating_index,
        const_table=const_table,
        current_top_entries=top_entries,
    )

    grid_x1, grid_y1, grid_x2, _ = GRID_BOX
    grid_w = grid_x2 - grid_x1
    footer_height = template.height - FOOTER_START_Y
    with Image.open(ASSETS_DIR / "templates" / "b30_single.png") as card_sample:
        card_w0, card_h0 = card_sample.size

    layout = _choose_grid_layout(
        min(len(top_entries), N),
        grid_w=grid_w,
        card_w0=card_w0,
        card_h0=card_h0,
        target_canvas_height=template.height,
        footer_height=footer_height,
    )
    canvas = _compose_resizable_template(template, body_height=int(layout["body_height"]))
    draw = ImageDraw.Draw(canvas)

    rating_font = _load_font(FONT_TITLE_PATH, RATING_FONT_SIZE)
    update_font = _load_font(FONT_TITLE_PATH, UPDATE_FONT_SIZE)

    rating_text = f"Rating b{N}: {overall:.2f}"
    rating_bbox = draw.textbbox((0, 0), rating_text, font=rating_font, stroke_width=2)
    rating_w = rating_bbox[2] - rating_bbox[0]
    rating_h = rating_bbox[3] - rating_bbox[1]
    rating_x, rating_y = _center_box(TOP_ORANGE_BOX, (rating_w, rating_h))
    _draw_text_with_stroke(
        draw,
        (rating_x, rating_y),
        rating_text,
        rating_font,
        WHITE,
        stroke_width=2,
        stroke_fill=BLACK,
    )

    update_text = _format_update_date(user_id)
    update_bbox = draw.textbbox((0, 0), update_text, font=update_font, stroke_width=2)
    update_w = update_bbox[2] - update_bbox[0]
    update_h = update_bbox[3] - update_bbox[1]
    update_x, update_y = _center_box(MID_ORANGE_BOX, (update_w, update_h))
    _draw_text_with_stroke(
        draw,
        (update_x, update_y),
        update_text,
        update_font,
        WHITE,
        stroke_width=2,
        stroke_fill=BLACK,
    )

    top_x1, top_y1, top_x2, top_y2 = TOP_WHITE_BOX
    top_w = top_x2 - top_x1
    top_h = top_y2 - top_y1
    col_w = int((top_w - 2 * TOP_PAD_X - 2 * TOP_GAP_X) / 3)
    col_h = top_h - 2 * TOP_PAD_Y
    left_box = (
        top_x1 + TOP_PAD_X,
        top_y1 + TOP_PAD_Y,
        top_x1 + TOP_PAD_X + col_w,
        top_y2 - TOP_PAD_Y,
    )
    center_box = (
        left_box[2] + TOP_GAP_X,
        left_box[1],
        left_box[2] + TOP_GAP_X + col_w,
        left_box[3],
    )
    right_box = (
        center_box[2] + TOP_GAP_X,
        left_box[1],
        center_box[2] + TOP_GAP_X + col_w,
        left_box[3],
    )

    trend_img = _render_trend_image(
        user_id, N, (left_box[2] - left_box[0], left_box[3] - left_box[1])
    )
    if trend_img is not None:
        _paste_scaled_center(canvas, trend_img, left_box)

    dress_path = render_user_dress(user_id)
    dress_img = Image.open(dress_path).convert("RGBA")

    info_canvas = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    info_draw = ImageDraw.Draw(info_canvas)
    font_title = _get_font(16)
    title_font = _get_font_by_path(TITLE_FONT_PATH, 16)
    stroke2 = 2
    white = (255, 255, 255)
    black = (0, 0, 0)
    plate_box = draw_player_info(
        base=info_canvas,
        draw=info_draw,
        userdata=userdata,
        sx=1.0,
        sy=1.0,
        font=font_title,
        stroke_width=stroke2,
        fill=white,
        stroke_fill=black,
        offset_xy=(0, 0),
        title_font=title_font,
    )
    title_img = _crop_with_pad(info_canvas, plate_box, pad=4)

    center_mid = (center_box[1] + center_box[3]) // 2
    upper_box = (
        center_box[0],
        center_box[1],
        center_box[2],
        center_mid - TOP_CENTER_GAP_Y // 2,
    )
    lower_box = (
        center_box[0],
        center_mid + TOP_CENTER_GAP_Y // 2,
        center_box[2],
        center_box[3],
    )
    _paste_scaled_center_zoom(canvas, dress_img, upper_box, scale_multiplier=1.5)
    _paste_scaled_center(canvas, title_img, lower_box)

    if results:
        radar_img = _render_radar_image(
            results,
            N,
            (right_box[2] - right_box[0], right_box[3] - right_box[1]),
            dim_deltas=dim_deltas or None,
        )
        _paste_scaled_center(canvas, radar_img, right_box)

    total_count = min(len(top_entries), N)
    grid_cols = int(layout["cols"])
    gap_x = int(layout["gap_x"])
    gap_y = int(layout["gap_y"])
    card_w = int(layout["card_w"])
    card_h = int(layout["card_h"])
    card_w_vis = int(layout["card_w_vis"])
    card_h_vis = int(layout["card_h_vis"])
    pad_x = int(layout["pad_x"])
    pad_y = int(layout["pad_y"])
    start_y = grid_y1 + GRID_PAD_TOP
    inner_grid_w = grid_w - GRID_PAD_SIDE * 2

    for idx, (_, entry) in enumerate(top_entries[:total_count]):
        song_no = int(entry.get("song_no", 0) or 0)
        level = int(entry.get("level", 0) or 0)
        song_info = song_index.get(song_no)
        if not song_info:
            continue
        card_bytes = render_b30_single_card(
            entry,
            song_info,
            assets_base=assets_base,
            as_png_bytes=True,
            show_new=get_song_chart_identity_key(song_no, level) in new_keys,
        )
        card_img = Image.open(BytesIO(card_bytes)).convert("RGBA")
        card_img = card_img.resize((card_w, card_h), Image.LANCZOS)
        row = idx // grid_cols
        col = idx % grid_cols
        row_start = row * grid_cols
        row_count = min(grid_cols, total_count - row_start)
        row_total_w = row_count * card_w_vis + max(0, row_count - 1) * gap_x
        row_start_x = grid_x1 + GRID_PAD_SIDE + max(0, (inner_grid_w - row_total_w) // 2)
        x_vis = row_start_x + col * (card_w_vis + gap_x)
        y_vis = start_y + row * (card_h_vis + gap_y)
        x = x_vis - pad_x
        y = y_vis - pad_y
        canvas.alpha_composite(card_img, (x, y))

    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
