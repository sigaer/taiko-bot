from .drawinfo import *
import json
import os
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont
from .progress_catalog import load_active_song_ids
from .twso import find_player
from .score_calculator import compute_all_from_userdata, generate_top_N_image, generate_dim_top_image
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
    userdata: Optional[Dict[str, Any]] = None,
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

    userdata = _resolve_userdata_payload(user_id, userdata)
    if userdata is None:
        return _render_simple_notice(
            f"未找到用户 {user_id} 的成绩数据。",
            1060,
            24,
            font_path,
            28,
            (245, 247, 250),
            (28, 32, 36),
        )
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
