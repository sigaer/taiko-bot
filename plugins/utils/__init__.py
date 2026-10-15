from .drawinfo import *
import json
import os
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from .progress_catalog import load_active_song_ids
from .score_calculator import compute_all_from_userdata
import io
from .draw_dress import (
    build_dress_image,
    draw_achievement_overview,
    draw_player_info,
    render_achievement_panel,
    render_update_changes_image,
    render_user_dress,
)
from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata

BASE = get_settings().root_dir
PATH_SONG_DATA = BASE / "songs" / "song_data.json"
JSON_PATH = BASE / "songs" / "taiko_goku_onis.json"
PATH_RATING_STRUCT = BASE / "songs" / "rating_structured_with_ids.json"
PROGRESS_BG_PATH = BASE / "assets" / "templates" / "progress_bg.png"




# ======= 图标路径规则 =======


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




def _resolve_userdata_payload(
    user_id: int | str,
    userdata: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    if isinstance(userdata, dict):
        return userdata
    return get_cached_userdata(str(user_id))


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












# ======= 核心函数：生成PNG字节流 =======














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
