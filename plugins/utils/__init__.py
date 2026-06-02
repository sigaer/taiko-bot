from .drawinfo import *
import json
import os
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from .twso import find_player
from .score_calculator import (
    compute_all_from_userdata,
    generate_top_N_image,
    compute_recommendations_for_user,
    generate_dim_top_image,
    generate_recommend_image,
)
import io
from .draw_summary import render_taiko_2025_summary
from .draw_dress import (
    build_dress_image,
    draw_achievement_overview,
    draw_player_info,
    render_achievement_panel,
    render_update_changes_image,
    render_my_don_image,
    render_user_dress,
)
from .tcloud import render_tcloud_image
from .b30_render import render_b30_image
from .progress_catalog import (
    load_active_song_ids,
    query_progress_items_by_const,
    query_progress_items_by_pass_const,
    query_progress_items_by_star,
)
from .progress_star import StarProgressSummary, build_star_progress_summary
from taiko_bot.settings import get_settings

BASE = get_settings().root_dir
PATH_SONG_DATA = BASE / "songs" / "song_data.json"
JSON_PATH = BASE / "songs" / "taiko_goku_onis.json"
PATH_RATING_STRUCT = BASE / "songs" / "rating_structured_with_ids.json"
PROGRESS_BG_PATH = BASE / "assets" / "templates" / "progress_bg.png"
DEFAULT_PROGRESS_FONT_PATH = str(BASE / "assets" / "fonts" / "DDFont.ttf")


@lru_cache(maxsize=1)
def _load_song_data() -> List[Dict[str, Any]]:
    if not PATH_SONG_DATA.exists():
        return []
    try:
        with open(PATH_SONG_DATA, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return []
    return payload if isinstance(payload, list) else []


# ======= 图标路径规则 =======
def _crown_icon_path(assets_base: Path, entry: Dict[str, Any]) -> str | None:
    # 优先级：dondaful > full > clear
    if entry.get("dondaful_combo_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "dondaful.png")
    if entry.get("full_combo_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "full.png")
    if entry.get("clear_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "clear.png")
    return None


def _rank_icon_path(assets_base: Path, rank_value: int) -> str:
    return os.path.join(assets_base, "icons", "rank", f"{rank_value}.png")


# ======= 选取“最佳成绩记录”的帮助函数（以最高 high_score 为准） =======
def _build_best_entry_map(
    user_scores: List[Dict[str, Any]],
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    """
    返回 (song_no, level) -> entry（该组合下分数最高的那条记录）。
    已下架曲目成绩不计入进度统计。
    """
    active_song_ids = load_active_song_ids()
    best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for r in user_scores:
        try:
            song_no = int(r["song_no"])
            level = int(r["level"])
            hs = int(r.get("high_score", 0) or 0)
        except Exception:
            continue
        if song_no not in active_song_ids:
            continue
        key = (song_no, level)
        if key not in best or hs > int(best[key].get("high_score", 0) or 0):
            best[key] = r
    return best


# ======= 文本测量与截断 =======
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


def _load_note_count_map() -> Dict[Tuple[int, int], int]:
    cache = getattr(_load_note_count_map, "_cache", None)
    mapping: Dict[Tuple[int, int], int] = {}
    if not PATH_RATING_STRUCT.exists():
        return mapping
    mtime_ns = PATH_RATING_STRUCT.stat().st_mtime_ns
    if cache and cache.get("mtime_ns") == mtime_ns:
        return cache["mapping"]
    with PATH_RATING_STRUCT.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    songs = payload.get("songs", {})
    items = songs.values() if isinstance(songs, dict) else songs
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id"))
            level = int(item.get("level"))
            combo = int(float(item.get("combo") or 0))
        except Exception:
            continue
        if combo <= 0:
            continue
        key = (song_id, level)
        if combo > mapping.get(key, 0):
            mapping[key] = combo
    for song in _load_song_data():
        try:
            song_id = int(song.get("id"))
        except Exception:
            continue
        combos = song.get("max_combo") or []
        if not isinstance(combos, list):
            continue
        for level, value in enumerate(combos, start=1):
            if value in (None, "-", ""):
                continue
            try:
                combo = int(value)
            except Exception:
                continue
            if combo <= 0:
                continue
            key = (song_id, level)
            if combo > mapping.get(key, 0):
                mapping[key] = combo
    _load_note_count_map._cache = {"mtime_ns": mtime_ns, "mapping": mapping}
    return mapping


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


def _draw_text_centered(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill,
    *,
    y_offset: int = 0,
) -> None:
    x1, y1, x2, y2 = box
    tb = draw.textbbox((0, 0), text, font=font)
    text_w = tb[2] - tb[0]
    text_h = tb[3] - tb[1]
    text_x = x1 + (x2 - x1 - text_w) // 2
    text_y = y1 + (y2 - y1 - text_h) // 2 + y_offset
    _draw_text_with_font_drop(
        draw,
        (text_x, text_y),
        text,
        font=font,
        fill=fill,
    )


def _alpha_composite_center(
    base: Image.Image,
    overlay: Optional[Image.Image],
    box: Tuple[int, int, int, int],
) -> None:
    if overlay is None:
        return
    x1, y1, x2, y2 = box
    x = x1 + max(0, (x2 - x1 - overlay.width) // 2)
    y = y1 + max(0, (y2 - y1 - overlay.height) // 2)
    base.alpha_composite(overlay, (x, y))


def _completion_rate(entry: Optional[Dict[str, Any]], total_notes: int) -> float:
    if not entry:
        return 0.0
    if total_notes <= 0:
        total_notes = (
            int(entry.get("good_cnt", 0) or 0)
            + int(entry.get("ok_cnt", 0) or 0)
            + int(entry.get("ng_cnt", entry.get("bad_cnt", 0)) or 0)
        )
    if total_notes <= 0:
        return 0.0
    if int(entry.get("dondaful_combo_cnt", 0) or 0) > 0:
        return 100.0
    good = int(entry.get("good_cnt", 0) or 0)
    ok = int(entry.get("ok_cnt", 0) or 0)
    rate = (good + ok * 0.5) / total_notes * 100.0
    return max(0.0, min(100.0, rate))


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


def _crop_transparent_panel(image: Image.Image, pad: int = 0) -> Image.Image:
    bbox = image.getbbox()
    if bbox is None:
        return image
    return _crop_box_with_pad(image, bbox, pad=pad)


def _render_star_progress_profile_panel(
    user_id: int,
    userdata: Dict[str, Any],
    target_width: int,
    target_height: int,
    font_path: str | None,
) -> Image.Image:
    profile_panel = _render_progress_profile_panel(
        userdata=userdata,
        target_width=target_width,
        font_path=font_path,
    )
    panel_h = max(profile_panel.height, target_height)
    panel = Image.new("RGBA", (target_width, panel_h), (0, 0, 0, 0))
    if profile_panel.width > 0 and profile_panel.height > 0:
        panel.alpha_composite(profile_panel, (0, 0))

    available_top = profile_panel.height + 10
    available_bottom = panel_h - 12
    available_h = available_bottom - available_top
    if available_h <= 0:
        return panel

    try:
        dress_img = _crop_transparent_panel(build_dress_image(user_id), pad=4)
    except Exception:
        return panel
    if dress_img.width <= 0 or dress_img.height <= 0:
        return panel

    max_w = min(target_width - 36, int(target_width * 0.72))
    scale = min(max_w / dress_img.width, available_h / dress_img.height, 1.25)
    if scale <= 0:
        return panel
    dress_w = max(1, int(round(dress_img.width * scale)))
    dress_h = max(1, int(round(dress_img.height * scale)))
    dress_img = dress_img.resize((dress_w, dress_h), Image.LANCZOS)
    dress_x = (target_width - dress_w) // 2
    dress_y = available_top + max(0, (available_h - dress_h) // 2)
    panel.alpha_composite(dress_img, (dress_x, dress_y))
    return panel


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


def _mix_rgb(
    left: Tuple[int, int, int], right: Tuple[int, int, int], t: float
) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(round(left[i] * (1 - t) + right[i] * t)) for i in range(3))


def _sample_gradient_stops(
    stops: List[Tuple[float, Tuple[int, int, int]]], t: float
) -> Tuple[int, int, int]:
    if not stops:
        return (255, 255, 255)
    if t <= stops[0][0]:
        return stops[0][1]
    for idx in range(1, len(stops)):
        prev_t, prev_color = stops[idx - 1]
        curr_t, curr_color = stops[idx]
        if t <= curr_t:
            local_t = (t - prev_t) / max(1e-6, curr_t - prev_t)
            return _mix_rgb(prev_color, curr_color, local_t)
    return stops[-1][1]


def _progress_marker_thresholds() -> Tuple[float, ...]:
    return (0.50, 0.60, 0.70, 0.80, 0.90, 0.95)


def _progress_fill_stops(rate: float) -> List[Tuple[float, Tuple[int, int, int]]]:
    if rate >= 100:
        return [
            (0.00, (255, 96, 116)),
            (0.18, (255, 170, 83)),
            (0.36, (255, 231, 99)),
            (0.54, (120, 228, 121)),
            (0.72, (92, 191, 255)),
            (0.88, (177, 121, 255)),
            (1.00, (255, 121, 228)),
        ]
    if rate >= 95:
        base = (154, 98, 243)
    elif rate >= 90:
        base = (246, 132, 192)
    elif rate >= 80:
        base = (238, 196, 68)
    elif rate >= 70:
        base = (192, 198, 208)
    elif rate >= 60:
        base = (186, 125, 78)
    elif rate >= 50:
        base = (241, 232, 213)
    else:
        return [(0.0, (255, 255, 255)), (1.0, (255, 255, 255))]
    light = _mix_rgb(base, (255, 255, 255), 0.42)
    deep = _mix_rgb(base, (72, 56, 66), 0.24)
    return [(0.0, light), (0.55, base), (1.0, deep)]


def _build_progress_fill_image(width: int, height: int, rate: float) -> Image.Image:
    fill_img = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
    if rate < 50:
        draw = ImageDraw.Draw(fill_img)
        draw.rounded_rectangle(
            (0, 0, fill_img.width - 1, fill_img.height - 1),
            radius=max(2, min(8, fill_img.height // 2)),
            fill=(255, 255, 255, 255),
        )
        return fill_img
    gradient = Image.new("RGBA", fill_img.size, (0, 0, 0, 0))
    grad_draw = ImageDraw.Draw(gradient)
    stops = _progress_fill_stops(rate)
    grad_w, grad_h = gradient.size

    for x in range(grad_w):
        t = x / max(1, grad_w - 1)
        t = 1.0 - t
        color = _sample_gradient_stops(stops, t)
        grad_draw.line((x, 0, x, grad_h), fill=(*color, 255))

    highlight = Image.new("RGBA", fill_img.size, (0, 0, 0, 0))
    hi_draw = ImageDraw.Draw(highlight)
    for y in range(grad_h):
        if y <= grad_h * 0.48:
            alpha = int(round(72 * (1 - y / max(1, grad_h * 0.48))))
            hi_draw.line((0, y, grad_w, y), fill=(255, 255, 255, alpha))
        else:
            alpha = int(round(24 * ((y - grad_h * 0.48) / max(1, grad_h * 0.52))))
            hi_draw.line((0, y, grad_w, y), fill=(28, 22, 32, alpha))
    gradient.alpha_composite(highlight)

    mask = Image.new("L", fill_img.size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        (0, 0, grad_w - 1, grad_h - 1),
        radius=max(2, min(8, grad_h // 2)),
        fill=255,
    )
    fill_img.paste(gradient, (0, 0), mask)
    return fill_img


def _build_progress_rows(
    items: List[Tuple[int, int, str]],
    best_map: Dict[Tuple[int, int], Dict[str, Any]],
    assets_base: Path,
) -> List[Dict[str, Any]]:
    note_map = _load_note_count_map()
    active_song_ids = load_active_song_ids()
    rows: List[Dict[str, Any]] = []
    for song_id, level, title in items:
        if song_id not in active_song_ids:
            continue
        entry = best_map.get((song_id, level))
        score = int(entry.get("high_score", 0) or 0) if entry else None
        crown_path = _crown_icon_path(assets_base, entry) if entry else None
        try:
            rank_val = int(entry.get("best_score_rank", 0) or 0) if entry else 0
        except Exception:
            rank_val = 0
        rank_path = _rank_icon_path(assets_base, rank_val) if rank_val > 0 else None
        total_notes = int(note_map.get((song_id, level), 0))
        rows.append(
            {
                "song_id": song_id,
                "level": level,
                "title": title,
                "score": score,
                "progress": _completion_rate(entry, total_notes),
                "crown_path": crown_path,
                "rank_path": rank_path,
            }
        )
    rows.sort(key=lambda r: (r["score"] is None, -(r["score"] or 0), r["title"]))
    return rows


DEFAULT_PROGRESS_PAGE_SIZE = 60


def _paginate_progress_rows(
    rows: List[Dict[str, Any]],
    page: int,
    page_size: int,
) -> Tuple[List[Dict[str, Any]], int, int]:
    total = len(rows)
    if total == 0:
        return [], 1, 1
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = max(1, min(page, total_pages))
    start = (page - 1) * page_size
    end = start + page_size
    return rows[start:end], page, total_pages


def _render_star_progress_summary_panel(
    star_value: int,
    summary: StarProgressSummary,
    assets_base: Path,
    font_path: str | None,
) -> Image.Image:
    width = 892
    height = 408
    pad = 20
    title_h = 38
    section_gap = 16
    stats_h = 76
    grid_top = pad + title_h + 16 + stats_h + section_gap
    grid_h = height - grid_top - pad

    panel = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=24,
        fill=(255, 255, 255, 240),
        outline=(226, 231, 239, 255),
        width=2,
    )

    title_font = _load_font(font_path, 24)
    value_font = _load_font(font_path, 26)
    count_font = _load_font(font_path, 24)
    label_font = _load_font(font_path, 14)
    section_font = _load_font(font_path, 18)

    title_icons = [
        _load_icon_cached(str(assets_base / "icons" / "diff" / "4.png"), 24),
        _load_icon_cached(str(assets_base / "icons" / "diff" / "5.png"), 24),
    ]
    title_x = pad
    for icon in title_icons:
        if icon is None:
            continue
        panel.alpha_composite(icon, (title_x, pad + 3))
        title_x += icon.width + 6

    title = f"我的小咚 · {star_value}星魔王/里魔王"
    _draw_text_with_font_drop(
        draw,
        (title_x, pad - 1),
        title,
        font=title_font,
        fill=(56, 62, 77, 255),
    )
    _draw_text_with_font_drop(
        draw,
        (pad, pad + 29),
        "仅统计当前星级范围内的鬼谱与里谱曲数",
        font=label_font,
        fill=(118, 126, 142, 255),
    )

    stat_gap = 12
    stat_w = (width - pad * 2 - stat_gap * 2) // 3
    stat_y = pad + title_h + 16
    stat_specs = [
        ("总曲数", summary.total_count, (255, 247, 229, 255)),
        ("已游玩", summary.played_count, (238, 250, 243, 255)),
        ("未游玩", summary.unplayed_count, (243, 246, 252, 255)),
    ]
    for idx, (label, value, fill_color) in enumerate(stat_specs):
        x1 = pad + idx * (stat_w + stat_gap)
        box = (x1, stat_y, x1 + stat_w, stat_y + stats_h)
        draw.rounded_rectangle(
            box,
            radius=18,
            fill=fill_color,
            outline=(236, 240, 246, 255),
            width=1,
        )
        _draw_text_with_font_drop(
            draw,
            (box[0] + 14, box[1] + 11),
            label,
            font=label_font,
            fill=(118, 126, 142, 255),
        )
        _draw_text_centered(
            draw,
            (box[0] + 8, box[1] + 24, box[2] - 8, box[3] - 8),
            str(value),
            value_font,
            (42, 48, 64, 255),
            y_offset=-1,
        )

    crown_w = 320
    crown_x = pad
    rank_x = crown_x + crown_w + 16
    rank_w = width - pad - rank_x
    crown_box = (crown_x, grid_top, crown_x + crown_w, grid_top + grid_h)
    rank_box = (rank_x, grid_top, rank_x + rank_w, grid_top + grid_h)
    for box in (crown_box, rank_box):
        draw.rounded_rectangle(
            box,
            radius=22,
            fill=(248, 250, 253, 255),
            outline=(236, 240, 246, 255),
            width=1,
        )

    _draw_text_with_font_drop(
        draw,
        (crown_box[0] + 16, crown_box[1] + 10),
        "皇冠数",
        font=section_font,
        fill=(56, 62, 77, 255),
    )
    _draw_text_with_font_drop(
        draw,
        (rank_box[0] + 16, rank_box[1] + 10),
        "歌曲评价",
        font=section_font,
        fill=(56, 62, 77, 255),
    )

    crown_items = [
        ("clear", summary.clear_count),
        ("full", summary.full_count),
        ("dondaful", summary.dondaful_count),
    ]
    crown_cell_gap = 10
    crown_cell_w = (crown_w - 32 - crown_cell_gap * 2) // 3
    crown_cell_y1 = crown_box[1] + 44
    crown_cell_y2 = crown_box[3] - 16
    for idx, (name, value) in enumerate(crown_items):
        x1 = crown_box[0] + 16 + idx * (crown_cell_w + crown_cell_gap)
        cell_box = (x1, crown_cell_y1, x1 + crown_cell_w, crown_cell_y2)
        cell_radius = max(10, min(18, (cell_box[3] - cell_box[1]) // 2 - 2))
        draw.rounded_rectangle(
            cell_box,
            radius=cell_radius,
            fill=(255, 255, 255, 225),
            outline=(236, 240, 246, 255),
            width=1,
        )
        icon = _load_icon_cached(str(assets_base / "icons" / "crown" / f"{name}.png"), 38)
        _alpha_composite_center(
            panel,
            icon,
            (cell_box[0], cell_box[1] + 12, cell_box[2], cell_box[1] + 64),
        )
        _draw_text_centered(
            draw,
            (cell_box[0] + 8, cell_box[1] + 72, cell_box[2] - 8, cell_box[3] - 10),
            str(value),
            count_font,
            (42, 48, 64, 255),
            y_offset=-2,
        )

    rank_items: List[int | None] = [8, 7, 6, 5, 4, 3, 2, None]
    rank_cell_gap = 8
    rank_cols = 4
    rank_rows = 2
    rank_cell_w = (rank_w - 32 - rank_cell_gap * (rank_cols - 1)) // rank_cols
    rank_cell_h = (grid_h - 60 - rank_cell_gap * (rank_rows - 1)) // rank_rows
    for idx, rank_value in enumerate(rank_items):
        row_idx = idx // rank_cols
        col_idx = idx % rank_cols
        x1 = rank_box[0] + 16 + col_idx * (rank_cell_w + rank_cell_gap)
        y1 = rank_box[1] + 46 + row_idx * (rank_cell_h + rank_cell_gap)
        cell_box = (x1, y1, x1 + rank_cell_w, y1 + rank_cell_h)
        cell_radius = max(10, min(18, (cell_box[3] - cell_box[1]) // 2 - 2))
        draw.rounded_rectangle(
            cell_box,
            radius=cell_radius,
            fill=(255, 255, 255, 225),
            outline=(236, 240, 246, 255),
            width=1,
        )
        if rank_value is None:
            _draw_text_centered(
                draw,
                (cell_box[0] + 8, cell_box[1] + 8, cell_box[2] - 8, cell_box[1] + 40),
                "空位",
                label_font,
                (118, 126, 142, 255),
                y_offset=-1,
            )
            value = summary.blank_rank_count
        else:
            icon = _load_icon_cached(
                str(assets_base / "icons" / "rank" / f"{rank_value}.png"),
                34,
            )
            _alpha_composite_center(
                panel,
                icon,
                (cell_box[0], cell_box[1] + 10, cell_box[2], cell_box[1] + 52),
            )
            value = summary.rank_counts.get(rank_value, 0)
        _draw_text_centered(
            draw,
            (cell_box[0] + 8, cell_box[1] + 56, cell_box[2] - 8, cell_box[3] - 10),
            str(value),
            count_font,
            (42, 48, 64, 255),
            y_offset=-1,
        )

    return panel


def _render_progress_table_image(
    user_id: int,
    userdata: Dict[str, Any],
    title_text: str,
    rows: List[Dict[str, Any]],
    assets_base: Path,
    font_path: str | None,
    page: int = 1,
    total_pages: int = 1,
    total_count: int | None = None,
    page_hint_base: str | None = None,
    top_summary_panel: Optional[Image.Image] = None,
    profile_panel_override: Optional[Image.Image] = None,
) -> bytes:
    table_w = 1580
    pad = 24
    title_row_h = 74
    header_h = 58
    row_h = 56
    top_gap = 16
    bottom_pad = 24
    footer_h = 44 if total_pages > 1 else 0

    profile_panel = profile_panel_override
    if profile_panel is None:
        profile_panel = _render_progress_profile_panel(
            userdata=userdata,
            target_width=640,
            font_path=font_path,
        )
    top_content_h = profile_panel.height
    if top_summary_panel is not None:
        top_content_h = max(top_content_h, top_summary_panel.height)
    top_area_h = max(top_content_h + top_gap, 130)
    panel_h = title_row_h + header_h + len(rows) * row_h + 14 + footer_h
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
    if top_summary_panel is not None:
        summary_x = panel_x + table_w - top_summary_panel.width - 8
        summary_y = pad + max(0, (top_content_h - top_summary_panel.height) // 2)
        img.alpha_composite(top_summary_panel, (summary_x, summary_y))

    title_font = _load_font(font_path, 52)

    header_font = _load_font(font_path, 24)
    row_font = _load_font(font_path, 24)
    score_font = _load_font(font_path, 23)
    progress_font = _load_font(font_path, 20)
    footer_font = _load_font(font_path, 20)

    cols = [
        ("难度", 96),
        ("曲名", 584),
        ("分数", 190),
        ("达成进度", 486),
        ("成就", 110),
        ("评价", 110),
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
    title_suffix = ""
    if total_count is not None:
        title_suffix = f" · 共{total_count}首"
        if total_pages > 1:
            title_suffix += f" · 第{page}/{total_pages}页"
    full_title = f"{title_text}{title_suffix}"
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
        diff_icon = _load_icon_cached(str(assets_base / "icons" / "diff" / f"{level}.png"), 32)
        cell_x = col_starts[0]
        if diff_icon is not None:
            ix = cell_x + (cols[0][1] - diff_icon.width) // 2
            iy = row_top + (row_h - diff_icon.height) // 2 - 2
            img.alpha_composite(diff_icon, (ix, iy))

        title = str(row.get("title", ""))
        title_cell_x = col_starts[1]
        title_cell_w = cols[1][1]
        title_max = title_cell_w - 24
        title_disp = _truncate_to_width(draw, title, row_font, title_max)
        tb = draw.textbbox((0, 0), title_disp, font=row_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        tx = title_cell_x + (title_cell_w - tw) // 2
        ty = row_top + (row_h - th) // 2 - 1
        _draw_text_with_font_drop(
            draw,
            (tx, ty),
            title_disp,
            font=row_font,
            fill=(44, 49, 53, 245),
        )

        score = row.get("score")
        score_txt = "-" if score is None else str(score)
        sx = col_starts[2]
        sw = cols[2][1]
        sb = draw.textbbox((0, 0), score_txt, font=score_font)
        stw = sb[2] - sb[0]
        sth = sb[3] - sb[1]
        _draw_text_with_font_drop(
            draw,
            (sx + (sw - stw) // 2, row_top + (row_h - sth) // 2 - 1),
            score_txt,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        rate = float(row.get("progress", 0.0) or 0.0)
        px = col_starts[3]
        pw = cols[3][1]
        bar_x = px + 14
        bar_y = row_top + (row_h - 16) // 2
        bar_w = pw - 86
        bar_h = 16
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
            radius=8,
            fill=(129, 133, 132, 175),
        )
        prog_w = max(0, min(bar_w, int(round(bar_w * rate / 100.0))))
        if prog_w > 0:
            fill_img = _build_progress_fill_image(prog_w, bar_h, rate)
            img.alpha_composite(fill_img, (bar_x, bar_y))
        for t in _progress_marker_thresholds():
            tx2 = bar_x + int(bar_w * t)
            draw.line((tx2, bar_y + 2, tx2, bar_y + bar_h - 2), fill=(97, 98, 99, 120), width=1)
        pct = f"{rate:.1f}%"
        _draw_text_with_font_drop(
            draw,
            (bar_x + bar_w + 10, bar_y - 3),
            pct,
            font=progress_font,
            fill=(56, 65, 66, 240),
        )

        crown_icon = _load_icon_cached(str(row.get("crown_path") or ""), 34)
        cx = col_starts[4]
        cw = cols[4][1]
        if crown_icon is not None:
            img.alpha_composite(
                crown_icon,
                (cx + (cw - crown_icon.width) // 2, row_top + (row_h - crown_icon.height) // 2 - 1),
            )
        else:
            _draw_text_with_font_drop(
                draw,
                (cx + cw // 2 - 5, row_top + 13),
                "-",
                font=row_font,
                fill=(96, 104, 108, 220),
            )

        rank_icon = _load_icon_cached(str(row.get("rank_path") or ""), 34)
        rx = col_starts[5]
        rw = cols[5][1]
        if rank_icon is not None:
            img.alpha_composite(
                rank_icon,
                (rx + (rw - rank_icon.width) // 2, row_top + (row_h - rank_icon.height) // 2 - 1),
            )
        else:
            _draw_text_with_font_drop(
                draw,
                (rx + rw // 2 - 5, row_top + 13),
                "-",
                font=row_font,
                fill=(96, 104, 108, 220),
            )

    if total_pages > 1 and page_hint_base:
        footer_y = panel_y + panel_h - footer_h + 6
        hint = (
            f"发送「{page_hint_base} {page + 1}」查看下一页"
            if page < total_pages
            else f"发送「{page_hint_base} 1-{total_pages}」翻页查看"
        )
        _draw_text_with_font_drop(
            draw,
            (panel_x + 16, footer_y),
            hint,
            font=footer_font,
            fill=(56, 72, 62, 230),
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ======= 核心函数：生成PNG字节流 =======
def render_pass_progress_image_bytes(
    user_id: int,
    decimal: str,
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
    font_size: int = 28,
    line_gap: int = 10,
    padding: int = 24,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
    width: int = 1060,
    page: int = 1,
    page_size: int = DEFAULT_PROGRESS_PAGE_SIZE,
) -> bytes:
    _ = (font_size, line_gap, padding, bg_color, fg_color, width)
    user_path = BASE / "userdata" / f"{user_id}data.json"
    if not user_path.exists():
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩文件。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    with open(user_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)
    user_scores = userdata.get("songs", [])
    best_map = _build_best_entry_map(user_scores)
    diff_key = f"{decimal}"
    items = query_progress_items_by_pass_const(diff_key)
    if not items:
        return _render_simple_notice(
            f"未找到定数 {diff_key} 的过关难度曲目列表。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    progress_items = [(item.song_id, item.level, item.title) for item in items]
    rows = _build_progress_rows(progress_items, best_map, BASE / "assets")
    if not rows:
        return _render_simple_notice(
            f"定数 {diff_key} 暂无未下架过关难度曲目。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    total_count = len(rows)
    page_rows, page, total_pages = _paginate_progress_rows(rows, page, page_size)
    return _render_progress_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"{diff_key}过关进度（过关难度）",
        rows=page_rows,
        assets_base=BASE / "assets",
        font_path=font_path,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        page_hint_base=f"{diff_key}过关进度",
    )


def render_progress_image_bytes(
    user_id: int,
    decimal: str,
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
    font_size: int = 28,
    line_gap: int = 10,
    padding: int = 24,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
    width: int = 1060,
    page: int = 1,
    page_size: int = DEFAULT_PROGRESS_PAGE_SIZE,
) -> bytes:
    _ = (font_size, line_gap, padding, bg_color, fg_color, width)
    user_path = BASE / "userdata" / f"{user_id}data.json"
    if not user_path.exists():
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩文件。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    with open(user_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)
    user_scores = userdata.get("songs", [])
    best_map = _build_best_entry_map(user_scores)
    diff_key = f"{decimal}"
    items = query_progress_items_by_const(float(diff_key))
    if not items:
        return _render_simple_notice(
            f"未找到定数 {diff_key} 的曲目列表。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    progress_items = [(item.song_id, item.level, item.title) for item in items]
    rows = _build_progress_rows(progress_items, best_map, BASE / "assets")
    if not rows:
        return _render_simple_notice(
            f"定数 {diff_key} 暂无未下架曲目。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    total_count = len(rows)
    page_rows, page, total_pages = _paginate_progress_rows(rows, page, page_size)
    return _render_progress_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"{diff_key}综合进度（综合难度）",
        rows=page_rows,
        assets_base=BASE / "assets",
        font_path=font_path,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        page_hint_base=f"{diff_key}综合进度",
    )


def render_progress_image_bytes_by_list(
    user_id: int,
    progress_name: str,  # 例如 "SS" / "地力S" / "個人差A+"
    assets_base: str = str(BASE / "assets"),
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
    font_size: int = 28,
    line_gap: int = 16,
    padding: int = 24,
    width: int = 1060,
    page: int = 1,
    page_size: int = DEFAULT_PROGRESS_PAGE_SIZE,
) -> bytes:
    _ = (font_size, line_gap, padding, width)
    assets_base_path = Path(assets_base)
    PATH_PROGRESS_LIST = BASE / "songs" / "music_donda_list.json"
    if not PATH_PROGRESS_LIST.exists():
        return _render_simple_notice(
            f"未找到进度列表文件：{PATH_PROGRESS_LIST}",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    with open(PATH_PROGRESS_LIST, "r", encoding="utf-8") as f:
        prog_map = json.load(f)

    if progress_name not in prog_map:
        return _render_simple_notice(
            f"未找到进度名：{progress_name}",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    raw_items: List[Dict[str, Any]] = prog_map[progress_name]

    items: List[Tuple[int, int, str]] = []
    for it in raw_items:
        sid = it.get("id", None)
        if sid is None:
            continue
        try:
            sid = int(sid)
        except Exception:
            continue
        if sid not in load_active_song_ids():
            continue

        name = str(it.get("song_name", "") or "")
        is_ura = "（裏）" in name or "(裏)" in name
        level = 5 if is_ura else 4
        items.append((sid, level, name))

    if not items:
        return _render_simple_notice(
            f"{progress_name}：列表为空（或全部为null）",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    user_path = BASE / "userdata" / f"{user_id}data.json"
    if not user_path.exists():
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩文件。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    with open(user_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)
    user_scores = userdata.get("songs", [])
    best_map = _build_best_entry_map(user_scores)
    rows = _build_progress_rows(items, best_map, assets_base_path)
    if not rows:
        return _render_simple_notice(
            f"{progress_name}：暂无未下架曲目",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    total_count = len(rows)
    page_rows, page, total_pages = _paginate_progress_rows(rows, page, page_size)
    return _render_progress_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"{progress_name}进度（全良难度）",
        rows=page_rows,
        assets_base=assets_base_path,
        font_path=font_path,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        page_hint_base=f"{progress_name}进度",
    )


def render_star_progress_image_bytes(
    user_id: int,
    star_value: int,
    assets_base: str = str(BASE / "assets"),
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
    page: int = 1,
    page_size: int = DEFAULT_PROGRESS_PAGE_SIZE,
) -> bytes:
    user_path = BASE / "userdata" / f"{user_id}data.json"
    if not user_path.exists():
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩文件。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    items = query_progress_items_by_star(star_value)
    if not items:
        return _render_simple_notice(
            f"未找到 {star_value} 星的未下架鬼/里谱。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    with open(user_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)
    user_scores = userdata.get("songs", [])
    best_map = _build_best_entry_map(user_scores)
    assets_base_path = Path(assets_base)
    progress_items = [(item.song_id, item.level, item.title) for item in items]
    rows = _build_progress_rows(progress_items, best_map, assets_base_path)
    if not rows:
        return _render_simple_notice(
            f"{star_value} 星：暂无未下架鬼/里谱。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
    star_summary = build_star_progress_summary(progress_items, best_map)
    top_summary_panel = _render_star_progress_summary_panel(
        star_value=star_value,
        summary=star_summary,
        assets_base=assets_base_path,
        font_path=font_path,
    )
    top_profile_panel = _render_star_progress_profile_panel(
        user_id=user_id,
        userdata=userdata,
        target_width=640,
        target_height=top_summary_panel.height,
        font_path=font_path,
    )
    total_count = len(rows)
    page_rows, page, total_pages = _paginate_progress_rows(rows, page, page_size)
    return _render_progress_table_image(
        user_id=user_id,
        userdata=userdata,
        title_text=f"{star_value}星进度",
        rows=page_rows,
        assets_base=assets_base_path,
        font_path=font_path,
        page=page,
        total_pages=total_pages,
        total_count=total_count,
        page_hint_base=f"{star_value}星进度",
        top_summary_panel=top_summary_panel,
        profile_panel_override=top_profile_panel,
    )


_DIM_LABEL_MAP: Dict[str, str] = {
    "big_song": "大歌力",
    "stamina": "体力",
    "speed": "高速处理",
    "accuracy_power": "精度力",
    "rhythm": "节奏处理",
    "complex_proc": "复合处理",
}


def _render_dimension_table_image(
    user_id: int,
    userdata: Dict[str, Any],
    title_text: str,
    rows: List[Dict[str, Any]],
    assets_base: Path,
    font_path: str | None,
    dim_label: str,
) -> bytes:
    table_w = 1580
    pad = 24
    title_row_h = 74
    header_h = 58
    row_h = 56
    top_gap = 16
    bottom_pad = 24

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
    header_font = _load_font(font_path, 22)
    row_font = _load_font(font_path, 24)
    score_font = _load_font(font_path, 22)
    progress_font = _load_font(font_path, 20)

    cols = [
        ("难度", 96),
        ("曲名", 560),
        ("分数", 170),
        ("良率", 604),
        (f"{dim_label}得点", 150),
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
    title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
    title_w = title_bbox[2] - title_bbox[0]
    title_h = title_bbox[3] - title_bbox[1]
    title_x = panel_x + (table_w - title_w) // 2
    title_y = title_row_y + (title_row_h - title_h) // 2 - 2
    _draw_text_with_font_drop(
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
        _draw_text_with_font_drop(
            draw,
            (cx + (cw - draw.textlength(label, font=header_font)) / 2, header_y + 13),
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
        diff_icon = _load_icon_cached(str(assets_base / "icons" / "diff" / f"{level}.png"), 32)
        cell_x = col_starts[0]
        if diff_icon is not None:
            ix = cell_x + (cols[0][1] - diff_icon.width) // 2
            iy = row_top + (row_h - diff_icon.height) // 2 - 2
            img.alpha_composite(diff_icon, (ix, iy))

        title = str(row.get("title", ""))
        title_cell_x = col_starts[1]
        title_cell_w = cols[1][1]
        title_disp = _truncate_to_width(draw, title, row_font, title_cell_w - 24)
        tb = draw.textbbox((0, 0), title_disp, font=row_font)
        tw = tb[2] - tb[0]
        th = tb[3] - tb[1]
        tx = title_cell_x + (title_cell_w - tw) // 2
        ty = row_top + (row_h - th) // 2 - 1
        _draw_text_with_font_drop(
            draw,
            (tx, ty),
            title_disp,
            font=row_font,
            fill=(44, 49, 53, 245),
        )

        score_txt = str(int(row.get("score", 0) or 0))
        sx = col_starts[2]
        sw = cols[2][1]
        sb = draw.textbbox((0, 0), score_txt, font=score_font)
        stw = sb[2] - sb[0]
        sth = sb[3] - sb[1]
        _draw_text_with_font_drop(
            draw,
            (sx + (sw - stw) // 2, row_top + (row_h - sth) // 2 - 1),
            score_txt,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

        rate = float(row.get("accuracy_rate", 0.0) or 0.0)
        px = col_starts[3]
        pw = cols[3][1]
        bar_x = px + 14
        bar_y = row_top + (row_h - 16) // 2
        bar_w = pw - 86
        bar_h = 16
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
            radius=8,
            fill=(129, 133, 132, 175),
        )
        prog_w = max(0, min(bar_w, int(round(bar_w * rate / 100.0))))
        if prog_w > 0:
            fill_img = _build_progress_fill_image(prog_w, bar_h, rate)
            img.alpha_composite(fill_img, (bar_x, bar_y))
        for t in _progress_marker_thresholds():
            tx2 = bar_x + int(bar_w * t)
            draw.line((tx2, bar_y + 2, tx2, bar_y + bar_h - 2), fill=(97, 98, 99, 120), width=1)
        pct = f"{rate:.2f}%"
        _draw_text_with_font_drop(
            draw,
            (bar_x + bar_w + 10, bar_y - 3),
            pct,
            font=progress_font,
            fill=(56, 65, 66, 240),
        )

        dim_score_txt = f"{float(row.get('dim_score', 0.0) or 0.0):.2f}"
        rx = col_starts[4]
        rw = cols[4][1]
        rb = draw.textbbox((0, 0), dim_score_txt, font=score_font)
        rtw = rb[2] - rb[0]
        rth = rb[3] - rb[1]
        _draw_text_with_font_drop(
            draw,
            (rx + (rw - rtw) // 2, row_top + (row_h - rth) // 2 - 1),
            dim_score_txt,
            font=score_font,
            fill=(59, 62, 66, 248),
        )

    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_dim_top_image(
    results,
    N: int,
    dim: str,
    user_id=None,
    font_path: str | None = "assets/fonts/DDFont.ttf",
) -> bytes:
    dim_label = _DIM_LABEL_MAP.get(dim)
    if not dim_label:
        return _render_simple_notice(
            f"不支持的维度：{dim}",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    user_path = BASE / "userdata" / f"{user_id}data.json"
    if not user_path.exists():
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩文件。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    with open(user_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)

    normalized_rows: List[Dict[str, Any]] = []
    for item in results:
        row = item if isinstance(item, dict) else item.__dict__
        if dim not in row:
            continue
        score = float(row.get(dim, 0.0) or 0.0)
        normalized_rows.append(
            {
                "song_id": int(row.get("song_id", 0) or 0),
                "level": int(row.get("level", 4) or 4),
                "title": str(row.get("song_name", "") or ""),
                "score": int(row.get("high_score", 0) or 0),
                "accuracy_rate": float(row.get("accuracy", 0.0) or 0.0) * 100.0,
                "dim_score": score,
            }
        )

    normalized_rows.sort(key=lambda r: (-r["dim_score"], -r["score"], r["title"]))
    top_rows = normalized_rows[: max(1, int(N))]
    if not top_rows:
        return _render_simple_notice(
            f"{dim_label}暂无可展示的数据。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )

    return _render_dimension_table_image(
        user_id=int(user_id or 0),
        userdata=userdata,
        title_text=f"{dim_label} best{len(top_rows)}",
        rows=top_rows,
        assets_base=BASE / "assets",
        font_path=font_path,
        dim_label=dim_label,
    )


# 简单提示图（当找不到数据等情况）
def _render_simple_notice(
    msg: str,
    width: int,
    padding: int,
    font_path: str | None,
    font_size: int,
    bg_color,
    fg_color,
) -> bytes:
    font = _load_font(font_path, font_size)
    img = Image.new("RGBA", (width, padding * 2 + font_size * 2), (*bg_color, 255))
    draw = ImageDraw.Draw(img)
    _draw_text_with_font_drop(
        draw,
        (padding, padding),
        msg,
        font=font,
        fill=fg_color,
    )
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ========== 数据读取与计算逻辑 ==========
@lru_cache(maxsize=1)
def _load_score_json() -> Dict[str, Any]:
    """
    读取并缓存统一后的 taiko_goku_onis.json。
    期望结构：列表，每项至少包含 id / level / initial_points。
    """
    from .score_line import ROLL_PATH, SCORE_PATH, SONG_DATA_PATH, rebuild_scoreline_dataset

    source_mtime = max(
        SCORE_PATH.stat().st_mtime,
        ROLL_PATH.stat().st_mtime,
        SONG_DATA_PATH.stat().st_mtime,
    )
    if not JSON_PATH.exists() or JSON_PATH.stat().st_mtime < source_mtime:
        rebuild_scoreline_dataset(JSON_PATH)
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"未找到分值配置文件: {JSON_PATH}")
    with JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data


def find_by_volume(
    data: Dict[str, Dict[str, Dict[str, int]]],
    target: int | Tuple[int, int],
    stat_key: str = "total",
) -> List[Tuple[str, str]]:
    """
    按物量查找歌曲与难度。

    参数:
      - data: 由 load_note_counts 读出的字典
      - target: 目标物量。可以是整数(精确匹配)或 (lo, hi) 区间(闭区间)
      - stat_key: 统计项，默认 'total'；也可用 '1'/'2'/'3'/'4' 之一

    返回:
      - [(title, "Course|Level"), ...]，已按标题、难度名排序
    """
    if stat_key not in {"1", "2", "3", "4", "total"}:
        raise ValueError("stat_key 必须是 '1','2','3','4' 或 'total'")
    courseMap = {
        "Edit": "里谱",
        "Oni": "魔王",
        "Hard": "困难",
        "Normal": "一般",
        "Easy": "简单",
    }
    is_range = isinstance(target, tuple)
    lo, hi = target if is_range else (target, target)

    hits: List[Tuple[str, str]] = []
    for title, courses in data.items():
        for course_level, counts in courses.items():
            course_level = courseMap.get(course_level.split("|")[0])
            val = int(counts.get(stat_key, None))
            if val is None:
                continue
            if lo <= val <= hi:
                hits.append((title, course_level))

    # 按曲名、难度字符串排序，便于展示稳定
    hits.sort(key=lambda x: (x[0], x[1]))
    return hits


def _get_initial_points(song_id: int, level: int) -> int:
    """
    在列表型 JSON 中，遍历查找 id==song_id 且 level==level 的项，返回 initial_points（良的基础分值）。
    若存在多条匹配，取第一条；若不存在匹配则报错。
    """
    data_list = _load_score_json()

    for item in data_list:
        # 允许 id 为字符串/数字，做一次安全解析
        try:
            item_id = int(item.get("id"))
        except Exception:
            continue
        item_level = item.get("level")

        if item_id == song_id and item_level == level:
            if "initial_points" not in item:
                raise KeyError(
                    f"id={song_id}, level={level} 的记录缺少 'initial_points'"
                )
            ip = item["initial_points"]
            return ip

    raise KeyError(f"未在 {JSON_PATH} 中找到 id={song_id}, level={level} 的分值记录。")


def compute_score(
    song_id: int, good: int, ok: int, drumroll: int = 0, level: int = 4
) -> int:
    """
    计算总分（支持里/表对应 level）：
      - 良基础分值 = initial_points
      - 可基础分值 = (initial_points // 2) 再“舍去个位” => ((initial_points // 2) // 10) * 10
      - 连打分 = drumroll * 100
    """
    initial_points = _get_initial_points(song_id, level=level)
    good_base = initial_points
    # “除以2后舍去个位”（例如 390 -> 190, 391 -> 190）
    ok_base = (initial_points // 2) // 10 * 10
    total = good * good_base + ok * ok_base + drumroll * 100
    return int(total)
