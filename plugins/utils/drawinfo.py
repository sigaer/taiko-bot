# -*- coding: utf-8 -*-
"""
Taiko 成绩卡渲染（1060x1220）
- 封装为函数 generate_score_image(song_no, user_id) -> bytes
- 仅调整位置；字号/描边/曲绘尺寸等保持既定要求
- 曲绘固定 400x400
- 依赖资源路径（可按需通过参数覆盖）：
    template_path:   assets/templates/info-bg-final-fix.png     # 背景模板 1060x1220
    db_path:         songs/song_data.json          # 曲目信息库（含 song_name, song_name_jp, level_1..5, bpm, id）
    assets_base:     assets/                       # 资源根目录
        cover/{song_no}.png                        # 曲绘（将居中裁切后缩放至 400x400）
        fonts/DDFont.ttf                 # 字体
        icons/rank/{1..10}.png                     # 段位/评分图
        icons/crown/{clear|full|dondaful}.png      # 皇冠
    userdata_dir:    userdata/                     # 用户数据目录
        {user_id}data.json                         # 成绩 JSON（含 high_score、best_score_rank、good_cnt、...）
"""

from io import BytesIO
import json
import math
import os
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from taiko_bot.settings import get_settings
from .score_calculator import (
    build_const_table,
    calc_accuracy,
    calc_y,
    compute_AD_AE_AF_AG,
    compute_AI,
    compute_P,
    compute_Q,
    compute_six_dims,
    lookup_const_score,
)

_SETTINGS = get_settings()


# ---------- 颜色与字号（保持原始要求） ----------
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (0x26, 0x85, 0xDE)  # #2685de

SIZE_TITLE = 27  # 曲名/日文名/ID/BPM/难度定数（您当前模板用 27，更贴合行距）
SIZE_SCORE = 48  # 分数
SIZE_STATS = 24  # 良/可/不可/连打/最大连击

STROKE_TITLE = 2  # 蓝描边
STROKE_SCORE = 3  # 黑描边
STROKE_STATS = 2  # 黑描边

# ---------- 版面（仅位置；尺寸保持要求） ----------
# 画布：1060x1220
# 曲绘：固定 400x400
ART_POS = (95, 88)  # 左上角
ART_SIZE = (400, 400)

# 右侧信息区（曲名 / 日文名 / 难度定数 / ID & BPM）
INFO_X = 755
POS_TITLE_EN = (INFO_X, 140)
POS_TITLE_JP = (INFO_X, 230)
POS_TYPE = (INFO_X, 323)  # 分类的起点
LEVEL_STEP_X = 62  # 相邻定数水平间距
POS_ID_BPM = (INFO_X - 90, 412)  # ID 起点（BPM 在其右边固定偏移）

# 成绩 5 行（Level5→Level1）
ROW_Y = [585, 715, 845, 975, 1105]  # 每行视觉中心

# 左侧难度图标（若需要可自行贴）
# DIFF_ICON_POS_X = 95
# DIFF_ICON_SIZE = (52, 52)
# 小图标尺寸
OPTION_ICON_SIZE = (30, 30)
OPTION_ICON_MARGIN = 8  # 横向间隔

# 定数
LEVEL_X = 165
LEVEL_Y_OFFSET = 30
# 分数
SCORE_X = 190
SCORE_Y_OFFSET = -int(SIZE_SCORE / 2)

# rank / crown 图标
RANK_ICON_SIZE = (85, 85)
CROWN_ICON_SIZE = (85, 85)
AFTER_SCORE_GAP = 12  # 分数 → rank 的间距（最终采用固定 X）
AFTER_RANK_GAP = 12  # rank → crown 的间距（最终采用固定 X）
RANK_X_FIXED = 425  # 覆盖动态计算，使用与模板对齐的固定位置
CROWN_X_FIXED = 535

# 右侧统计（两列居中数值：左列 良/可/不可；右列 连打数/最大连击数）
STAT_COL_X_CENTER = 733
POUND_COL_X_CENTER = 955
STAT_Y_OFFSET = -35
STAT_LINE_H = 40
# 资源路径
USERDATA_DIR = str(_SETTINGS.userdata_dir)
RATING_DB_PATH = str(_SETTINGS.root_dir / "songs" / "rating_structured_with_ids.json")
FONT_FILE_NAME = "DDFont.ttf"
RAW_DIM_KEYS = ["复合处理", "平均密度", "瞬间密度", "节奏处理", "BPM变化", "HS变化"]
RAW_DIM_VALUE_ALIASES = {
    "复合处理": ("复合处理",),
    "平均密度": ("平均密度",),
    "瞬间密度": ("瞬间密度",),
    "节奏处理": ("节奏处理", "叩き分け"),
    "BPM变化": ("BPM变化",),
    "HS变化": ("HS变化", "hs变化"),
}
PLAYER_DIM_KEYS = ["复合处理", "节奏处理", "精度力", "高速处理", "体力", "大歌力"]

# 雷达卡尺寸/布局（加大：接近主图高度，减少拥挤）
RADAR_CARD_W = 420
RADAR_CARD_H = 1140
RADAR_CARD_GAP = 24
SIDE_PADDING = 24
RADAR_TOP_Y = 132
RADAR_RADIUS = 118
RADAR_GRID_STEPS = 5

TYPE_MAP = {
    "南梦宫原创音乐": "original",
    "流行音乐": "pop",
    "动漫音乐": "anime",
    "游戏音乐": "gamemusic",
    "博歌乐音乐": "vocaloid",
    "儿童音乐": "kid",
    "古典音乐": "classic",
    "综合音乐": "variety",
}

_RATING_INDEX_CACHE = {"mtime": None, "index": {}, "const_table": []}
ROOT_DIR = Path(__file__).resolve().parents[2]


# ---------- 基础工具 ----------
def _load_font(path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _ddfont_y_offset(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy,
    text,
    font,
    fill,
):
    x, y = xy
    draw.text((x, y + _ddfont_y_offset(font)), text, font=font, fill=fill)


def _draw_text_with_stroke(
    draw: ImageDraw.ImageDraw, xy, text, font, fill, stroke_width, stroke_fill
):
    x, y = xy
    y += _ddfont_y_offset(font)
    # Pillow 8.2+ 支持 stroke_*；降级兼容 8 邻域描边
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


def _center_crop_to_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def _cover_resize_to_box(im: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    w, h = im.size
    if w <= 0 or h <= 0:
        return Image.new("RGBA", size, (242, 246, 252, 255))
    scale = max(tw / w, th / h)
    nw = max(1, int(round(w * scale)))
    nh = max(1, int(round(h * scale)))
    resized = im.resize((nw, nh), Image.LANCZOS)
    left = (nw - tw) // 2
    top = (nh - th) // 2
    return resized.crop((left, top, left + tw, top + th))


def _paste_song_art(canvas: Image.Image, path: str, pos, size):
    if not os.path.exists(path):
        return
    art = Image.open(path).convert("RGBA")
    art = _center_crop_to_square(art).resize(size, Image.LANCZOS)
    canvas.paste(art, pos, art)


def _load_icon(path: Optional[str], size=None) -> Optional[Image.Image]:
    if not path or not os.path.exists(path):
        return None
    im = Image.open(path).convert("RGBA")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return im


def _rank_icon_path(assets_base: str, rank_value: int) -> str:
    return os.path.join(assets_base, "icons", "rank", f"{rank_value}.png")


def _pick_crown_path(assets_base: str, entry: dict) -> Optional[str]:
    # 优先级：dondaful > full > clear
    if entry.get("dondaful_combo_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "dondaful.png")
    if entry.get("full_combo_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "full.png")
    if entry.get("clear_cnt", 0) > 0:
        return os.path.join(assets_base, "icons", "crown", "clear.png")
    return None


def _collect_entries_for_song(data: list, song_no: int) -> dict:
    """将同一 song_no 的记录按 level 聚合：dict[level] = entry（level: 1..5）"""
    out = {}
    for e in data:
        if e.get("song_no") == song_no:
            try:
                lvl = int(e.get("level", 0))
            except Exception:
                continue
            out[lvl] = e
    return out


def _to_float(v) -> Optional[float]:
    try:
        return float(v)
    except Exception:
        return None


def _load_rating_song_index(path: str = RATING_DB_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        mtime = None
    cached = _RATING_INDEX_CACHE
    if cached.get("mtime") == mtime and cached.get("index"):
        return cached["index"]

    payload = json.load(open(path, "r", encoding="utf-8"))
    songs = payload.get("songs", {})
    const_map = (payload.get("const_table") or {}).get("const_to_score") or {}
    index = {}
    items = songs.values() if isinstance(songs, dict) else songs
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            sid = int(item.get("id"))
            lvl = int(item.get("level"))
        except Exception:
            continue
        index[(sid, lvl)] = item

    _RATING_INDEX_CACHE["mtime"] = mtime
    _RATING_INDEX_CACHE["index"] = index
    try:
        _RATING_INDEX_CACHE["const_table"] = build_const_table(const_map)
    except Exception:
        _RATING_INDEX_CACHE["const_table"] = []
    return index


def _load_rating_const_table(path: str = RATING_DB_PATH) -> list[tuple]:
    _load_rating_song_index(path)
    return _RATING_INDEX_CACHE.get("const_table", [])


def _available_chart_levels(song_data: dict) -> list[int]:
    def has_level(level: int) -> bool:
        v = song_data.get(f"level_{level}")
        return v not in (None, "", "-")

    has_4 = has_level(4)
    has_5 = has_level(5)
    if has_4 and has_5:
        return [4, 5]
    if has_5:
        return [5]
    if has_4:
        return [4]
    return [4]


def _extract_raw_dims(chart_info: dict) -> Optional[list[float]]:
    if not chart_info:
        return None
    vals = []
    for k in RAW_DIM_KEYS:
        fv = None
        for key in RAW_DIM_VALUE_ALIASES.get(k, (k,)):
            fv = _to_float(chart_info.get(key))
            if fv is not None:
                break
        if fv is None:
            return None
        vals.append(fv)
    return vals


def _build_player_metrics(
    chart_info: Optional[dict],
    entry: Optional[dict],
    const_table: list[tuple],
):
    if not chart_info or not entry or not const_table:
        return None
    try:
        total_notes = int(_to_float(chart_info.get("combo")) or 0)
        const_value = _to_float(chart_info.get("score"))
        if total_notes <= 0 or const_value is None:
            return None

        M = lookup_const_score(const_value, const_table)

        max_accuracy = 1.0
        N_max = calc_y(
            accuracy=max_accuracy,
            normalization_factor=15.5,
            algorithm="comprehensive",
        )
        P_max = compute_P(M, N_max)
        Q_max = compute_Q(M, N_max)
        AI_max = compute_AI(M, N_max, P_max, Q_max)
        metrics = compute_AD_AE_AF_AG(chart_info)
        six_max = compute_six_dims(AI_max, M, N_max, metrics)

        great_cnt = int(entry.get("good_cnt", 0) or 0)
        good_cnt = int(entry.get("ok_cnt", 0) or 0)
        dondaful_cnt = int(entry.get("dondaful_combo_cnt", 0) or 0)
        if dondaful_cnt > 0:
            accuracy = 1.0
        else:
            accuracy = calc_accuracy(
                total_notes=total_notes,
                great_cnt=great_cnt,
                good_cnt=good_cnt,
                algorithm="comprehensive",
            )

        if accuracy == 0.0:
            AI_cur = 0.0
            cur_dims = [0.0] * 6
        else:
            N_cur = calc_y(
                accuracy=accuracy,
                normalization_factor=15.5,
                algorithm="comprehensive",
            )
            P_cur = compute_P(M, N_cur)
            Q_cur = compute_Q(M, N_cur)
            AI_cur = compute_AI(M, N_cur, P_cur, Q_cur)
            six_cur = compute_six_dims(AI_cur, M, N_cur, metrics)
            cur_dims = [
                round(float(six_cur["复合处理"]), 2),
                round(float(six_cur["节奏处理"]), 2),
                round(float(six_cur["精度力"]), 2),
                round(float(six_cur["高速处理"]), 2),
                round(float(six_cur["体力"]), 2),
                round(float(six_cur["大歌力"]), 2),
            ]

        max_dims = [
            round(float(six_max["复合处理"]), 2),
            round(float(six_max["节奏处理"]), 2),
            round(float(six_max["精度力"]), 2),
            round(float(six_max["高速处理"]), 2),
            round(float(six_max["体力"]), 2),
            round(float(six_max["大歌力"]), 2),
        ]
        return {
            "current_dims": cur_dims,
            "max_dims": max_dims,
            "current_rating": round(float(AI_cur), 2),
            "max_rating": round(float(AI_max), 2),
        }
    except Exception:
        return None


def _axis_ceiling(values: list[float]) -> int:
    if not values:
        return 10
    vmax = max(float(v) for v in values)
    if vmax <= 0:
        return 10
    return int(math.ceil(vmax / 10.0) * 10)


def _radar_points(cx: int, cy: int, radius: float):
    points = []
    for i in range(6):
        ang = math.radians(-90 + i * 60)
        x = cx + radius * math.cos(ang)
        y = cy + radius * math.sin(ang)
        points.append((x, y))
    return points


def _draw_radar_chart(
    draw: ImageDraw.ImageDraw,
    values: list[float],
    labels: list[str],
    axis_max: int,
    center: tuple[int, int],
    radius: int,
    label_font,
    primary_fill=(57, 108, 176, 88),
    primary_outline=(49, 99, 164, 255),
    overlay_values: Optional[list[float]] = None,
    overlay_fill=(225, 144, 58, 54),
    overlay_outline=(220, 133, 42, 230),
):
    cx, cy = center
    spokes = _radar_points(cx, cy, radius)
    label_gap = max(12, int(radius * 0.16))

    # 网格
    for step in range(1, RADAR_GRID_STEPS + 1):
        r = radius * step / RADAR_GRID_STEPS
        grid_pts = _radar_points(cx, cy, r)
        draw.polygon(grid_pts, outline=(192, 207, 224, 255))
    for px, py in spokes:
        draw.line((cx, cy, px, py), fill=(184, 201, 220, 255), width=1)

    # 叠加理论上限（先画）
    if overlay_values:
        overlay_pts = []
        for i, val in enumerate(overlay_values):
            p = max(0.0, min(1.0, float(val) / max(axis_max, 1)))
            px, py = spokes[i]
            overlay_pts.append((cx + (px - cx) * p, cy + (py - cy) * p))
        draw.polygon(
            overlay_pts,
            fill=overlay_fill,
            outline=overlay_outline,
            width=2,
        )

    # 当前数据
    plot_pts = []
    for i, val in enumerate(values):
        p = max(0.0, min(1.0, float(val) / max(axis_max, 1)))
        px, py = spokes[i]
        plot_pts.append((cx + (px - cx) * p, cy + (py - cy) * p))
    draw.polygon(plot_pts, fill=primary_fill, outline=primary_outline, width=2)

    # 标签
    for i, label in enumerate(labels):
        px, py = spokes[i]
        tx = px
        ty = py
        if i == 0:
            ty -= label_gap + 6
        elif i in (1, 2):
            tx += label_gap
        elif i == 3:
            ty += label_gap // 2
        else:
            tx -= label_gap
        bbox = draw.textbbox((0, 0), label, font=label_font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        min_x = 12
        max_x = RADAR_CARD_W - 12 - tw
        if i in (1, 2):
            _draw_text(
                draw,
                (min(max(tx, min_x), max_x), ty - th // 2),
                label,
                label_font,
                (58, 75, 96, 255),
            )
        elif i in (4, 5):
            x = tx - tw
            _draw_text(
                draw,
                (min(max(x, min_x), max_x), ty - th // 2),
                label,
                label_font,
                (58, 75, 96, 255),
            )
        else:
            x = tx - tw // 2
            _draw_text(
                draw,
                (min(max(x, min_x), max_x), ty - th // 2),
                label,
                label_font,
                (58, 75, 96, 255),
            )


def _draw_radar_card(
    level: int,
    panel_title: str,
    values: Optional[list[float]],
    labels: list[str],
    placeholder: str,
    assets_base: str,
    font_path: str,
    card_bg_path: Optional[str] = None,
    axis_max_fixed: Optional[int] = None,
    overlay_values: Optional[list[float]] = None,
    table_labels: Optional[list[str]] = None,
    table_values: Optional[list[float]] = None,
    table_max_values: Optional[list[float]] = None,
    primary_value_color=(41, 93, 167, 255),
    max_value_color=(220, 133, 42, 255),
) -> Image.Image:
    card = Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (0, 0, 0, 0))
    mask = Image.new("L", (RADAR_CARD_W, RADAR_CARD_H), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle(
        (0, 0, RADAR_CARD_W - 1, RADAR_CARD_H - 1),
        radius=18,
        fill=255,
    )
    if card_bg_path and os.path.exists(card_bg_path):
        src = Image.open(card_bg_path).convert("RGBA")
        bg = _cover_resize_to_box(src, (RADAR_CARD_W, RADAR_CARD_H))
    else:
        bg = Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (242, 246, 252, 255))
    # 背景保留纹理，同时整体半透明
    bg.putalpha(mask.point(lambda a: int(a * 0.72)))
    card.alpha_composite(bg)
    # 轻微提亮以保证文字可读
    overlay = Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (244, 248, 255, 80))
    overlay.putalpha(mask.point(lambda a: int(a * 0.55)))
    card.alpha_composite(overlay)

    draw = ImageDraw.Draw(card)
    draw.rounded_rectangle(
        (0, 0, RADAR_CARD_W - 1, RADAR_CARD_H - 1),
        radius=18,
        outline=(188, 203, 220, 255),
        width=2,
    )

    title_font = _load_font(font_path, 30)
    label_font = _load_font(font_path, 20)
    value_font = _load_font(font_path, 28)

    diff_icon = _load_icon(
        os.path.join(assets_base, "icons", "diff", f"{level}.png"),
        size=(38, 38),
    )
    title_x = 14
    title_y = 18
    if diff_icon:
        card.paste(diff_icon, (title_x, title_y), diff_icon)
        title_x += 46
    _draw_text(draw, (title_x, title_y + 2), panel_title, title_font, (74, 49, 24, 255))

    if not values:
        ph_bbox = draw.textbbox((0, 0), placeholder, font=title_font)
        pw = ph_bbox[2] - ph_bbox[0]
        ph = ph_bbox[3] - ph_bbox[1]
        _draw_text(
            draw,
            ((RADAR_CARD_W - pw) // 2, (RADAR_CARD_H - ph) // 2),
            placeholder,
            title_font,
            (132, 146, 162, 255),
        )
        return card

    axis_max = axis_max_fixed if axis_max_fixed else _axis_ceiling(values)
    _draw_radar_chart(
        draw=draw,
        values=values,
        labels=labels,
        axis_max=axis_max,
        center=(RADAR_CARD_W // 2, RADAR_TOP_Y + RADAR_RADIUS),
        radius=RADAR_RADIUS,
        label_font=label_font,
        overlay_values=overlay_values,
    )

    table_labels = table_labels or labels
    table_values = table_values or values

    list_top = RADAR_TOP_Y + RADAR_RADIUS * 2 + 64
    row_h = 90
    for idx, (name, val) in enumerate(zip(table_labels, table_values)):
        y = list_top + idx * row_h
        draw.line(
            (12, y - 8, RADAR_CARD_W - 12, y - 8),
            fill=(206, 217, 228, 255),
            width=2,
        )
        _draw_text(draw, (16, y), name, value_font, (45, 67, 97, 255))
        if table_max_values and idx < len(table_max_values):
            cur_txt = f"{float(val):.2f}"
            slash_txt = "/"
            max_txt = f"{float(table_max_values[idx]):.2f}"
            b1 = draw.textbbox((0, 0), cur_txt, font=value_font)
            b2 = draw.textbbox((0, 0), slash_txt, font=value_font)
            b3 = draw.textbbox((0, 0), max_txt, font=value_font)
            w1 = b1[2] - b1[0]
            w2 = b2[2] - b2[0]
            w3 = b3[2] - b3[0]
            x = RADAR_CARD_W - 16 - (w1 + w2 + w3)
            _draw_text(draw, (x, y), cur_txt, value_font, primary_value_color)
            _draw_text(draw, (x + w1, y), slash_txt, value_font, (86, 100, 116, 255))
            _draw_text(draw, (x + w1 + w2, y), max_txt, value_font, max_value_color)
        else:
            txt = f"{float(val):.2f}"
            bbox = draw.textbbox((0, 0), txt, font=value_font)
            tw = bbox[2] - bbox[0]
            _draw_text(
                draw,
                (RADAR_CARD_W - 16 - tw, y),
                txt,
                value_font,
                primary_value_color,
            )

    return card


def _compose_with_side_radar(
    center_img: Image.Image,
    song_no: int,
    song_data: dict,
    entries: dict,
    assets_base: str,
    font_path: str,
    side_bg_path: Optional[str] = None,
) -> Image.Image:
    levels = _available_chart_levels(song_data)
    col_count = len(levels)
    side_w = SIDE_PADDING * 2 + col_count * RADAR_CARD_W + (col_count - 1) * RADAR_CARD_GAP
    out_w = center_img.width + side_w * 2
    out_h = max(center_img.height, RADAR_CARD_H + 40)
    out = Image.new("RGBA", (out_w, out_h), (235, 241, 248, 255))

    center_y = (out_h - center_img.height) // 2
    out.paste(center_img, (side_w, center_y), center_img)

    rating_index = _load_rating_song_index()
    const_table = _load_rating_const_table()
    card_y = (out_h - RADAR_CARD_H) // 2

    for idx, level in enumerate(levels):
        card_offset = SIDE_PADDING + idx * (RADAR_CARD_W + RADAR_CARD_GAP)
        chart_info = rating_index.get((song_no, level))
        raw_dims = _extract_raw_dims(chart_info)
        player_metrics = _build_player_metrics(chart_info, entries.get(level), const_table)
        player_dims = None
        player_max_dims = None
        player_rating = None
        player_max_rating = None
        if player_metrics:
            player_dims = player_metrics.get("current_dims")
            player_max_dims = player_metrics.get("max_dims")
            player_rating = player_metrics.get("current_rating")
            player_max_rating = player_metrics.get("max_rating")

        raw_table_labels = None
        raw_table_values = None
        if raw_dims and chart_info:
            const_value = _to_float(chart_info.get("score"))
            if const_value is not None:
                raw_table_labels = RAW_DIM_KEYS + ["综合定数"]
                raw_table_values = list(raw_dims) + [const_value]

        raw_card = _draw_radar_card(
            level=level,
            panel_title="谱面六维数据",
            values=raw_dims,
            labels=RAW_DIM_KEYS,
            placeholder="暂无谱面六维数据",
            assets_base=assets_base,
            font_path=font_path,
            card_bg_path=side_bg_path,
            axis_max_fixed=100,
            table_labels=raw_table_labels,
            table_values=raw_table_values,
        )

        player_table_labels = None
        player_table_values = None
        player_table_max_values = None
        if player_dims and player_max_dims and player_rating is not None and player_max_rating is not None:
            player_table_labels = PLAYER_DIM_KEYS + ["综合得分"]
            player_table_values = list(player_dims) + [float(player_rating)]
            player_table_max_values = list(player_max_dims) + [float(player_max_rating)]

        player_card = _draw_radar_card(
            level=level,
            panel_title="玩家六维得分",
            values=player_dims,
            labels=PLAYER_DIM_KEYS,
            placeholder="未游玩或暂无数据",
            assets_base=assets_base,
            font_path=font_path,
            card_bg_path=side_bg_path,
            axis_max_fixed=15,
            overlay_values=player_max_dims,
            table_labels=player_table_labels,
            table_values=player_table_values,
            table_max_values=player_table_max_values,
            primary_value_color=(41, 93, 167, 255),
            max_value_color=(220, 133, 42, 255),
        )

        out.paste(raw_card, (card_offset, card_y), raw_card)
        out.paste(player_card, (side_w + center_img.width + card_offset, card_y), player_card)

    return out


def get_score_by_id_and_level(song_no, user_id, level):
    user_json_path = os.path.join(USERDATA_DIR, f"{user_id}data.json")
    with open(user_json_path, "r", encoding="utf-8") as f:
        user_data = json.load(f)["songs"]

    # 聚合该曲成绩
    entries = _collect_entries_for_song(user_data, song_no)
    target_level_data = entries.get(level)
    if not target_level_data:
        return None
    else:
        return target_level_data


# ---------- 对外函数 ----------
def generate_score_image(
    song_no: int,
    user_id: int,
    *,
    template_path: str = "assets/templates/info-bg-final-fix.png",
    db_path: str = "songs/song_data.json",
    assets_base: str = "assets",
    as_png_bytes: bool = True,
) -> bytes:
    """
    渲染成绩卡并返回 PNG 字节流。

    Args:
        song_no:   曲目编号（决定曲绘与筛选该曲成绩）
        user_id:   用户 ID，用于读取 userdata/{user_id}data.json
        template_path, db_path, assets_base, userdata_dir: 路径可覆盖
        as_png_bytes: 恒为 True，返回 PNG 字节流

    Returns:
        PNG 图像的 bytes
    """

    assets_base_path = Path(assets_base)
    if not assets_base_path.is_absolute():
        assets_base_path = ROOT_DIR / assets_base_path
    assets_base = str(assets_base_path)

    db_path_obj = Path(db_path)
    if not db_path_obj.is_absolute():
        db_path_obj = ROOT_DIR / db_path_obj

    template_path_obj = Path(template_path)
    if not template_path_obj.is_absolute():
        template_path_obj = ROOT_DIR / template_path_obj
    template_path = str(template_path_obj)

    # --- 载入用户成绩 JSON ---
    user_json_path = os.path.join(USERDATA_DIR, f"{user_id}data.json")
    with open(user_json_path, "r", encoding="utf-8") as f:
        user_data = json.load(f)["songs"]

    # --- 载入歌曲数据库（曲名/定数/BPM等）---
    with open(db_path_obj, "r", encoding="utf-8") as f:
        db_data = json.load(f)

    # 聚合该曲成绩
    entries = _collect_entries_for_song(user_data, song_no)

    # 找该曲的静态信息
    song_data = {}
    for song in db_data:
        if song.get("id") == song_no:
            song_data = song
            break
    if not song_data:
        raise RuntimeError(
            f"发生错误：曲库中找不到 id={song_no} 的曲目信息（{db_path}）"
        )
    # --- 载入模板 ---
    side_bg_path = None
    category = song_data.get("type", "") or ""
    if category in TYPE_MAP:
        type_key = TYPE_MAP[category]
        info_tpl = assets_base_path / "templates" / f"{type_key}-info-bg.png"
        side_tpl = assets_base_path / "templates" / f"{type_key}-bg.png"
        if info_tpl.exists():
            template_path = str(info_tpl)
        if side_tpl.exists():
            side_bg_path = str(side_tpl)
    if not os.path.exists(template_path):
        raise FileNotFoundError(f"模板不存在: {template_path}")
    canvas = Image.open(template_path).convert("RGBA")
    W, H = canvas.size
    if (W, H) != (1060, 1220):
        # 非强制，仅提示
        print(f"[warn] 模板尺寸为 {W}x{H}，预期 1060x1220。坐标仍按 1060x1220 绘制。")
    draw = ImageDraw.Draw(canvas)
    # --- 曲绘 ---
    cover_path = os.path.join(assets_base, "cover", f"{song_no}.png")
    _paste_song_art(canvas, cover_path, ART_POS, ART_SIZE)

    # --- 字体 ---
    font_path = os.path.join(assets_base, "fonts", FONT_FILE_NAME)
    font_title = _load_font(font_path, SIZE_TITLE)
    font_score = _load_font(font_path, SIZE_SCORE)
    font_stats = _load_font(font_path, SIZE_STATS)
    main_card_ddfont_lift = 4

    def draw_main_card_text_with_stroke(pos, text, font, fill, stroke_width, stroke_fill):
        _draw_text_with_stroke(
            draw,
            (pos[0], pos[1] - main_card_ddfont_lift),
            text,
            font,
            fill,
            stroke_width,
            stroke_fill,
        )

    # --- 右侧：曲名 / 日文名（居中对齐） ---
    song_name = song_data.get("song_name", "") or ""
    song_name_jp = song_data.get("song_name_jp", "") or ""

    title_en_bbox = draw.textbbox((0, 0), song_name, font=font_title)
    title_jp_bbox = draw.textbbox((0, 0), song_name_jp, font=font_title)
    pos_title_en_fix = (
        POS_TITLE_EN[0] - (title_en_bbox[2] - title_en_bbox[0]) // 2,
        POS_TITLE_EN[1],
    )
    pos_title_jp_fix = (
        POS_TITLE_JP[0] - (title_jp_bbox[2] - title_jp_bbox[0]) // 2,
        POS_TITLE_JP[1],
    )

    draw_main_card_text_with_stroke(
        pos_title_en_fix, song_name, font_title, WHITE, STROKE_TITLE, BLUE
    )
    draw_main_card_text_with_stroke(
        pos_title_jp_fix, song_name_jp, font_title, WHITE, STROKE_TITLE, BLUE
    )

    # --- 右侧：难度定数（从 level_1 → level_5 左到右，按您当前模板的视觉顺序）---
    # levels = [song_data.get(f"level_{i}", "") for i in range(1, 6)]
    # lx, ly = POS_LEVELS
    # for i, val in enumerate(levels):
    #     txt = "-" if val in (None, "", "-") else str(val)
    #     txt_bbox = draw.textbbox((0, 0), txt, font=font_title)
    #     txt_x = lx + i * LEVEL_STEP_X - (txt_bbox[2] - txt_bbox[0]) // 2  # 居中落位
    #     _draw_text_with_stroke(
    #         draw, (txt_x, ly), txt, font_title, WHITE, STROKE_TITLE, BLUE
    #     )
    # 这里改成放分类
    category = song_data.get("type", "") or ""
    lx, ly = POS_TYPE
    txt_bbox = draw.textbbox((0, 0), category, font=font_title)
    txt_x = lx - (txt_bbox[2] - txt_bbox[0]) // 2  # 居中落位
    draw_main_card_text_with_stroke((txt_x, ly - 3), category, font_title, WHITE, STROKE_TITLE, BLUE)
    # --- 右侧：ID / BPM（若 BPM 缺失则只显示 ID 数字）---
    id_text = f"{song_data.get('id', '')}"
    bpm_val = song_data.get("bpm", None)

    draw_main_card_text_with_stroke(POS_ID_BPM, id_text, font_title, WHITE, STROKE_TITLE, BLUE)
    if bpm_val not in (None, "", "-"):
        id_bbox = draw.textbbox(POS_ID_BPM, id_text, font=font_title)
        bpm_x = id_bbox[0] + 182  # 与您的模板对齐的固定偏移
        draw_main_card_text_with_stroke(
            (bpm_x, POS_ID_BPM[1]),
            f"{bpm_val}",
            font_title,
            WHITE,
            STROKE_TITLE,
            BLUE,
        )

    # --- 成绩区（Level5→Level1）---
    for idx, row_center_y in enumerate(ROW_Y):
        level_idx = 5 - idx  # 5,4,3,2,1
        # 先画难度等级
        level = song_data.get(f"level_{level_idx}", "")
        txt = "☆ "
        txt += "-" if level in (None, "", "-") else str(level)
        draw_main_card_text_with_stroke(
            (LEVEL_X, row_center_y + LEVEL_Y_OFFSET),
            txt,
            font_title,
            WHITE,
            STROKE_TITLE,
            BLUE,
        )
        entry = entries.get(level_idx)
        if not entry:
            continue
        # 在这里实现放小图标，即"option_flg"
        option_flags = entry.get("option_flg", [])
        # 4个标志，分别代表：加速、隐藏、镜像、随机，类型为int、int、int、str
        # 第1个图标文件名为对应的值
        # 第2个图标文件名为hidden.png，若值为1则显示
        # 第3个图标文件名为mirror.png，若值为1则显示
        # 第4个图标文件名当值为"01"时显示super_random.png，为"10"时显示random.png
        # 放置在分数上方，横向排列，间距为图标大小的一半
        icon_x = SCORE_X + OPTION_ICON_SIZE[0]
        icon_y = row_center_y - SIZE_SCORE // 2 - OPTION_ICON_SIZE[1] - 4
        if len(option_flags) >= 1:
            flag_name = str(format(option_flags[0], ".1f"))
            icon_path = os.path.join(assets_base, "icons", "option", f"{flag_name}.png")
            icon_img = _load_icon(icon_path, OPTION_ICON_SIZE)
            if icon_img:
                canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2  # 右移
        if len(option_flags) >= 2:
            if option_flags[1] == 1:
                icon_path = os.path.join(assets_base, "icons", "option", "hidden.png")
                icon_img = _load_icon(icon_path, OPTION_ICON_SIZE)
                if icon_img:
                    canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2  # 右移
        if len(option_flags) >= 3:
            if option_flags[2] == 1:
                icon_path = os.path.join(assets_base, "icons", "option", "mirror.png")
                icon_img = _load_icon(icon_path, OPTION_ICON_SIZE)
                if icon_img:
                    canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2  # 右移
        if len(option_flags) >= 4:
            if option_flags[3] == "01":
                icon_path = os.path.join(
                    assets_base, "icons", "option", "super_random.png"
                )
                icon_img = _load_icon(icon_path, OPTION_ICON_SIZE)
                if icon_img:
                    canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2  # 右移
            elif option_flags[3] == "10":
                icon_path = os.path.join(assets_base, "icons", "option", "random.png")
                icon_img = _load_icon(icon_path, OPTION_ICON_SIZE)
                if icon_img:
                    canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2  # 右移

        # 图标位于assets/icons/options/{flag_name}.png

        # 分数
        score = entry.get("high_score", 0)
        score_txt = f"{score:,}".replace(",", "")
        score_pos = (SCORE_X, row_center_y + SCORE_Y_OFFSET)
        draw_main_card_text_with_stroke(
            score_pos, score_txt, font_score, WHITE, STROKE_SCORE, BLACK
        )

        # rank 与 crown（使用与模板一致的固定 X 坐标）
        icon_y = int(row_center_y - RANK_ICON_SIZE[1] / 2)

        try:
            rank_val = int(entry.get("best_score_rank", 0))
        except Exception:
            rank_val = 0
        rank_path = _rank_icon_path(assets_base, rank_val)
        rank_icon = _load_icon(rank_path, RANK_ICON_SIZE)
        if rank_icon:
            canvas.paste(rank_icon, (RANK_X_FIXED + 12, icon_y), rank_icon)

        crown_path = _pick_crown_path(assets_base, entry)
        crown_icon = _load_icon(crown_path, CROWN_ICON_SIZE)
        if crown_icon:
            canvas.paste(crown_icon, (CROWN_X_FIXED + 4, icon_y), crown_icon)

        # 右侧统计（两列数值，均水平居中到各自列中心）
        # update: 不居中，统一左对齐
        left_values = [
            entry.get("good_cnt", 0),
            entry.get("ok_cnt", 0),
            entry.get("ng_cnt", 0),
        ]
        right_values = [entry.get("pound_cnt", 0), entry.get("combo_cnt", 0)]
        for i, val in enumerate(left_values):
            y = row_center_y + STAT_Y_OFFSET + i * STAT_LINE_H
            val_bbox = draw.textbbox((0, 0), str(val), font=font_stats)
            val_len = val_bbox[2] - val_bbox[0]
            val_x = STAT_COL_X_CENTER + 28 - val_len
            draw_main_card_text_with_stroke(
                (val_x, y - 20), str(val), font_stats, WHITE, STROKE_STATS, BLACK
            )

        for i, val in enumerate(right_values):
            y = row_center_y + STAT_Y_OFFSET - 5 + i * (STAT_LINE_H + 10)
            val_bbox = draw.textbbox((0, 0), str(val), font=font_stats)
            val_len = val_bbox[2] - val_bbox[0]
            val_x = POUND_COL_X_CENTER + 20 - val_len
            draw_main_card_text_with_stroke(
                (val_x, y), str(val), font_stats, WHITE, STROKE_STATS, BLACK
            )

    # --- 左右扩展：附加谱面六维/玩家六维雷达图 ---
    canvas = _compose_with_side_radar(
        center_img=canvas,
        song_no=song_no,
        song_data=song_data,
        entries=entries,
        assets_base=assets_base,
        font_path=font_path,
        side_bg_path=side_bg_path,
    )

    # --- 输出为 PNG 字节流 ---
    bio = BytesIO()
    canvas.save(bio, format="PNG")
    return bio.getvalue()
