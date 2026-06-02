# -*- coding: utf-8 -*-
"""
太鼓年终总结 2025 - 坐标版模板填充器（不使用图像检测）
入口函数：render_taiko_2025_summary(user_id: int) -> bytes

依赖：
  pip install pillow matplotlib pandas numpy

要求：
  - 字体：assets/fonts/DDFont.ttf
  - 模板：assets/templates/ 下的4种模板
  - 用户数据：userdata/{user_id}data.json
  - 歌曲库：songs/song_data.json
  - 刷分库：songs/twso_cn_data.json
  - score_calculator.py：用于雷达图与best10文本（路径可改）
"""

from __future__ import annotations
import os
import json
import math
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import matplotlib

matplotlib.use("Agg")
from taiko_bot.settings import get_settings
from .draw_dress import draw_achievement_overview, draw_player_info


# =========================
# 基准画布尺寸（你的坐标系）
# =========================
BASE_W = 499
BASE_H = 5194


# =========================
# 路径配置（按你的项目修改）
# =========================
ASSETS_DIR = Path("./assets")
TEMPLATES_DIR = ASSETS_DIR / "templates"
FONTS_DIR = ASSETS_DIR / "fonts"
FONT_FZPW = FONTS_DIR / "DDFont.ttf"

NAME_PLATE_DIR = ASSETS_DIR / "name_plate"
NAME_PLATE_DANI_DIR = ASSETS_DIR / "name_plate_dani"

SONG_DB_PATH = Path("./songs/song_data.json")
TWSO_CN_PATH = Path("./songs/twso_cn_data.json")

# 你上传的 score_calculator.py 若在其它位置，请修改这里
SCORE_CALC_PATH = Path("./plugins/utils/score_calculator.py")

# score_calculator 内部会读取 rating_structured_with_ids.json（你项目若不同请改）
RATING_STRUCT_PATH = Path("./songs/rating_structured_with_ids.json")

OUTPUT_DIR = Path("./output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 四种模板： (has_twso, has_random_or_speed) -> template_path
TEMPLATE_MAP = {
    (True, True): TEMPLATES_DIR / "太鼓年终总结2025-白色描边-有刷分有随机.png",
    (True, False): TEMPLATES_DIR / "太鼓年终总结2025-白色描边-有刷分无随机.png",
    (False, True): TEMPLATES_DIR / "太鼓年终总结2025-白色描边-无刷分有随机.png",
    (False, False): TEMPLATES_DIR / "太鼓年终总结2025-白色描边-无刷分无随机.png",
}


# =========================
# 固定坐标（基于 499x5194）
# =========================

# 1) 玩家信息区（你确认：左上角 (78,949)，name_plate 要 346*56）
PLAYER_PLATE_XY = (78, 949)
PLAYER_PLATE_SIZE = (346, 56)  # 必须与原图一致
# 上半：称号；下半：名称/段位
PLAYER_TITLE_BOX = (78, 949, 78 + 346, 949 + 28)
PLAYER_LOWER_BOX = (78, 949 + 28, 78 + 346, 949 + 56)
# 下半分割（显示段位时：左名称 55% / 右段位 45%）
PLAYER_NAME_RATIO = 0.55

# 2) 成绩展示区（紫色区域，基于你模板推导的稳定坐标；若你想微调就改这里）
ACH_BOX = (81, 1182, 418, 1367)
# 4行中心 y（相对 ACH_BOX 高度）
ACH_ROW_Y_FRAC = [0.15, 0.39, 0.62, 0.87]
# 3列中心 x（相对 ACH_BOX 宽度）
ACH_COL_X_FRAC = [0.23, 0.55, 0.87]
# 行内数字框大小（相对 ACH_BOX）
ACH_NUM_W_FRAC = 0.22
ACH_NUM_H_FRAC = 0.18
# 第一行“极”数值：只用最右列
ACH_ROW1_X_FRAC = 0.87

# 3~7) 五块牌匾大框（推导得到，稳定）
PLAQUE_TOTAL_BOX = (225, 1554, 476, 1729)  # 总歌曲数
PLAQUE_MOSTPLAYED_BOX = (31, 1870, 476, 2022)  # 游玩次数最多
PLAQUE_HIGHSCORE_BOX = (31, 2169, 476, 2317)  # 分数最高
PLAQUE_TWSO_BOX = (101, 2448, 479, 2626)  # 刷分赛
PLAQUE_RANDOM_BOX = (201, 2757, 476, 2926)  # 随机/倍速

# 8) 底部纸张区域（关键词+雷达+Top10）
PAPER_BOX = (48, 3046, 456, 5141)

# 关键词文本框（放“最大维度名”）
KEYWORD_TEXT_BOX = (130, 3147, 379, 3236)

# 雷达图放置区域（底色 #fde2bb）
RADAR_BOX = (95, 3410, 409, 3665)

# “最好的10首歌”文本区域（紧跟标题下方）
BEST10_TEXT_BOX = (90, 3780, 414, 4920)


# =========================
# 基础工具函数
# =========================


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def safe_int(x, default=0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def get_font(size_px: int) -> ImageFont.FreeTypeFont:
    if not FONT_FZPW.exists():
        raise FileNotFoundError(f"字体不存在：{FONT_FZPW}")
    return ImageFont.truetype(str(FONT_FZPW), size_px)


def scale_box(
    box: Tuple[int, int, int, int], sx: float, sy: float
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )


def scale_xy(xy: Tuple[int, int], sx: float, sy: float) -> Tuple[int, int]:
    x, y = xy
    return (int(round(x * sx)), int(round(y * sy)))


def offset_box(
    box: Tuple[int, int, int, int], dx: int, dy: int
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)


def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    return draw.textbbox((0, 0), text, font=font)


def wrap_text_by_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> List[str]:
    """按像素宽度自动换行（不截断、不省略），中文友好。"""
    lines: List[str] = []
    cur = ""
    for ch in str(text):
        if ch == "\n":  # 强制换行
            lines.append(cur)
            cur = ""
            continue
        nxt = cur + ch
        bb = draw.textbbox((0, 0), nxt, font=font)
        if (bb[2] - bb[0]) <= max_w or not cur:
            cur = nxt
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def draw_wrapped_items_in_box(
    base: Image.Image,
    box: Tuple[int, int, int, int],
    items: List[str],
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_fill: Tuple[int, int, int],
    stroke_width: int,
    wrap_gap: int,  # 条目内部换行行距（小）
    item_gap: int,  # 条目之间间距（大）
    align: str = "left",  # "left" or "center"
    valign: str = "top",  # "top" or "center"（center 会整体居中，通常 best10 不建议）
) -> None:
    draw = ImageDraw.Draw(base)
    x1, y1, x2, y2 = box
    max_w = x2 - x1

    # 预展开：把每个条目拆成若干行（条目内换行），并记录每个条目高度
    expanded: List[List[str]] = []
    item_heights: List[int] = []

    for it in items:
        # 一个条目允许本身带 \n（例如“歌名行\n成绩行”），我们对每个 para 再 wrap
        lines: List[str] = []
        for para in str(it).split("\n"):
            lines.extend(wrap_text_by_width(draw, para, font, max_w))

        heights = []
        for ln in lines:
            bb = draw.textbbox((0, 0), ln, font=font)
            heights.append(bb[3] - bb[1])
        h = sum(heights) + wrap_gap * max(0, len(lines) - 1)

        expanded.append(lines)
        item_heights.append(h)

    total_h = sum(item_heights) + item_gap * max(0, len(items) - 1)

    if valign == "center":
        y = y1 + max(0, (y2 - y1 - total_h) // 2)
    else:
        y = y1

    # 绘制
    for lines, h_item in zip(expanded, item_heights):
        if y >= y2:
            break

        for idx, ln in enumerate(lines):
            bb = draw.textbbox((0, 0), ln, font=font)
            lw = bb[2] - bb[0]
            lh = bb[3] - bb[1]
            if y + lh > y2:
                return

            if align == "center":
                x = x1 + max(0, (max_w - lw) // 2)
            else:
                x = x1

            draw.text(
                (x, y),
                ln,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )

            y += lh
            if idx != len(lines) - 1:
                y += wrap_gap

        # 条目结束，加条目间距
        y += item_gap


def draw_text_center(
    draw: ImageDraw.ImageDraw, box, text, font, fill, stroke_fill, stroke_width
):
    x1, y1, x2, y2 = box
    bb = text_bbox(draw, str(text), font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    x = x1 + (x2 - x1 - tw) // 2
    y = y1 + (y2 - y1 - th) // 2 - 4
    draw.text(
        (x, y),
        str(text),
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


def draw_player_and_achievement(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    userdata: Dict[str, Any],
    sx: float,
    sy: float,
    font16: ImageFont.ImageFont,
    font20: ImageFont.ImageFont,
    stroke2: int,
    WHITE: Tuple[int, int, int],
    BLACK: Tuple[int, int, int],
    offset_xy: Tuple[int, int] = (0, 0),
) -> Tuple[int, int, int, int]:
    plate_box_bounds = draw_player_info(
        base=base,
        draw=draw,
        userdata=userdata,
        sx=sx,
        sy=sy,
        font=font16,
        stroke_width=stroke2,
        fill=WHITE,
        stroke_fill=BLACK,
        offset_xy=offset_xy,
    )
    ach_box_s = draw_achievement_overview(
        base=base,
        draw=draw,
        userdata=userdata,
        sx=sx,
        sy=sy,
        font=font20,
        stroke_width=stroke2,
        fill=WHITE,
        stroke_fill=BLACK,
        offset_xy=offset_xy,
    )
    min_x = min(plate_box_bounds[0], ach_box_s[0])
    min_y = min(plate_box_bounds[1], ach_box_s[1])
    max_x = max(plate_box_bounds[2], ach_box_s[2])
    max_y = max(plate_box_bounds[3], ach_box_s[3])
    return (min_x, min_y, max_x, max_y)


def compute_player_achievement_bounds(
    userdata: Dict[str, Any], sx: float, sy: float
) -> Tuple[int, int, int, int]:
    prof = userdata.get("profile") or {}
    gc = prof.get("gameCostume") or {}

    plate_x, plate_y = PLAYER_PLATE_XY
    plate_w, plate_h = PLAYER_PLATE_SIZE
    plate_box = (plate_x, plate_y, plate_x + plate_w, plate_y + plate_h)
    plate_box_s = scale_box(plate_box, sx, sy)

    plate_path = pick_name_plate(gc)
    if plate_path and plate_path.exists():
        plate_img = Image.open(plate_path).convert("RGBA")
        img_x, img_y = plate_img.size
        offset = img_y - 90
        plate_box_s = list(plate_box_s)
        plate_box_s[1] = round(plate_box_s[1] - offset / 1.607)
        plate_box_s = tuple(plate_box_s)

    ach_box_s = scale_box(ACH_BOX, sx, sy)

    min_x = min(plate_box_s[0], ach_box_s[0])
    min_y = min(plate_box_s[1], ach_box_s[1])
    max_x = max(plate_box_s[2], ach_box_s[2])
    max_y = max(plate_box_s[3], ach_box_s[3])
    return (min_x, min_y, max_x, max_y)


def fit_text_in_box(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: Path,
    max_w: int,
    start_size: int,
    min_size: int = 10,
):
    """若歌名过长：自动降字号；降到 min_size 仍超宽则截断加省略号"""
    size = start_size
    while size >= min_size:
        font = ImageFont.truetype(str(font_path), size)
        bb = draw.textbbox((0, 0), text, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return text, font
        size -= 1
    # 仍超宽：截断
    font = ImageFont.truetype(str(font_path), min_size)
    t = text
    while t:
        cand = t + "…"
        bb = draw.textbbox((0, 0), cand, font=font)
        if (bb[2] - bb[0]) <= max_w:
            return cand, font
        t = t[:-1]
    return "", font


def paste_resize(
    base: Image.Image, overlay: Image.Image, box: Tuple[int, int, int, int]
):
    """拉伸贴入（用于 name_plate 必须 346x56 的要求，最终仍按 box 尺寸）"""
    x1, y1, x2, y2 = box
    ov = overlay.convert("RGBA").resize((x2 - x1, y2 - y1), Image.LANCZOS)
    base.alpha_composite(ov, (x1, y1))


def paste_contain(
    base: Image.Image,
    overlay: Image.Image,
    box: Tuple[int, int, int, int],
    pad: int = 0,
):
    """等比缩放（不拉伸）贴入 box（用于段位 badge、雷达图）"""
    x1, y1, x2, y2 = box
    x1 += pad
    y1 += pad
    x2 -= pad
    y2 -= pad
    bw, bh = (x2 - x1), (y2 - y1)
    ov = overlay.convert("RGBA")
    ow, oh = ov.size
    if ow <= 0 or oh <= 0 or bw <= 0 or bh <= 0:
        return
    s = min(bw / ow, bh / oh)
    nw, nh = max(1, int(ow * s)), max(1, int(oh * s))
    ov2 = ov.resize((nw, nh), Image.LANCZOS)
    ox = x1 + (bw - nw) // 2
    oy = y1 + (bh - nh) // 2
    base.alpha_composite(ov2, (ox, oy))


# =========================
# 数据读取与业务计算
# =========================


def load_userdata(user_id: int) -> Dict[str, Any]:
    p = get_settings().userdata_dir / f"{user_id}data.json"
    if p.exists():
        return load_json(p)
    # 兼容：有些人直接放在当前目录
    p2 = Path(f"./{user_id}data.json")
    if p2.exists():
        return load_json(p2)
    raise FileNotFoundError(f"找不到用户数据：{p} 或 {p2}")


def load_song_db() -> Dict[int, Dict[str, Any]]:
    if not SONG_DB_PATH.exists():
        return {}
    data = load_json(SONG_DB_PATH)
    if isinstance(data, list):
        return {safe_int(x.get("id")): x for x in data}
    if isinstance(data, dict) and isinstance(data.get("songs"), list):
        return {safe_int(x.get("id")): x for x in data["songs"]}
    return {}


def find_twso_record(user_id: int) -> Optional[Dict[str, Any]]:
    if not TWSO_CN_PATH.exists():
        return None
    data = load_json(TWSO_CN_PATH)
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    if not isinstance(data, list):
        return None
    for x in data:
        if safe_int(x.get("taiko_no")) == safe_int(user_id):
            return x
    return None


def count_random_speed(songs: List[Dict[str, Any]]) -> Tuple[int, int]:
    random_cnt = 0
    speed_cnt = 0
    for s in songs:
        opt = s.get("option_flg")
        v0 = v3 = None
        try:
            v0 = opt[0]
            v3 = opt[3]
        except Exception:
            pass
        # 倍速：option_flg[0] != 1
        if v0 is not None and str(v0) != "1":
            speed_cnt += 1
        # 随机：option_flg[3] != "00"
        if v3 is not None and str(v3) != "00":
            random_cnt += 1
    return random_cnt, speed_cnt


def compute_total_song_stats(songs: List[Dict[str, Any]]) -> Tuple[int, int, int]:
    total_stage = sum(safe_int(x.get("stage_cnt", 0)) for x in songs)
    v2 = int(round(total_stage / 388.0)) if total_stage else 0
    v3 = int(round(total_stage / 248.0)) if total_stage else 0
    return total_stage, v2, v3


def most_played_song(
    songs: List[Dict[str, Any]],
    song_db: Dict[int, Dict[str, Any]],
) -> Tuple[str, int, int, float]:
    grp: Dict[int, int] = {}
    for s in songs:
        sid = safe_int(s.get("song_no"))
        grp[sid] = grp.get(sid, 0) + safe_int(s.get("stage_cnt", 0))
    if not grp:
        return ("", 0, 0, 0.0)
    top_song_no = max(grp.items(), key=lambda kv: kv[1])[0]
    top_stage = grp[top_song_no]

    candidates = [s for s in songs if safe_int(s.get("song_no")) == top_song_no]
    candidates.sort(key=lambda x: safe_int(x.get("level", 0)), reverse=True)
    best_high = safe_int(candidates[0].get("high_score", 0)) if candidates else 0

    rec = song_db.get(top_song_no, {})
    song_name = (
        rec.get("song_name")
        or rec.get("song_name_jp")
        or rec.get("name")
        or str(top_song_no)
    )

    weekly = round(top_stage * 2 / 108.0, 1) if top_stage else 0.0
    return (str(song_name), best_high, top_stage, weekly)


def highest_score_song(
    songs: List[Dict[str, Any]],
    song_db: Dict[int, Dict[str, Any]],
) -> Tuple[str, str, int]:
    if not songs:
        return ("", "", 0)
    top = max(songs, key=lambda x: safe_int(x.get("high_score", 0)))
    song_no = safe_int(top.get("song_no"))
    high_score = safe_int(top.get("high_score", 0))
    level = safe_int(top.get("level", 0))

    rec = song_db.get(song_no, {})
    song_name = (
        rec.get("song_name")
        or rec.get("song_name_jp")
        or rec.get("name")
        or str(song_no)
    )

    diff_val = rec.get(f"level_{level}")
    if diff_val is not None:
        diff_map = {1: "梅", 2: "竹", 3: "松", 4: "鬼", 5: "里"}
        diff_val = f"{diff_map.get(level, '难度')}{diff_val}"
    return (str(song_name), str(diff_val), high_score)


def pick_name_plate(game_costume: Dict[str, Any]) -> Optional[Path]:
    titleplate_id = game_costume.get("titleplate_id")
    is_dan = bool(game_costume.get("is_disp_dan_on"))
    if titleplate_id is None:
        return None
    if is_dan:
        dan_path = NAME_PLATE_DIR / f"name_plate_dani_{titleplate_id}.png"
        if dan_path.exists():
            return dan_path
    return NAME_PLATE_DIR / f"name_plate_{titleplate_id}.png"


def pick_dan_badge(dan_name: Dict[str, Any]) -> Optional[Path]:
    if not isinstance(dan_name, dict):
        return None
    grade = str(dan_name.get("grade", "")).zfill(2)
    level = str(dan_name.get("level", "")).zfill(2)
    if grade == "00" and level == "00":
        return None
    return NAME_PLATE_DANI_DIR / f"name_plate_dani_{grade}_{level}.png"


def choose_template(has_twso: bool, has_random_or_speed: bool) -> Path:
    p = TEMPLATE_MAP.get((has_twso, has_random_or_speed))
    if p and p.exists():
        return p
    # 兜底：任选存在的
    for _, tp in TEMPLATE_MAP.items():
        if tp.exists():
            return tp
    raise FileNotFoundError(
        f"找不到模板图：{TEMPLATES_DIR}，请检查 TEMPLATE_MAP 文件名。"
    )


# =========================
# score_calculator 动态导入 + 雷达图/Best10文本
# =========================


def import_score_calculator():
    from . import score_calculator as module

    return module


def generate_radar_only(
    score_calc, results, bg_hex: str = "#fde2bb"
) -> Tuple[Image.Image, str]:
    dim_means = score_calc.compute_dim_topN_means(results, 20)
    categories = ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"]
    values = [(k, float(dim_means.get(k, 0.0))) for k in categories]
    max_dim = max(values, key=lambda kv: kv[1])[0] if values else "大歌力"

    # fig, ax = score_calc.plot_radar_from_values(
    #     dim_means,
    #     title="",
    #     font_path=str(FONT_FZPW),
    #     dynamic_origin=False,
    # )
    fig, ax = score_calc.plot_radar_from_values(
        dim_means,
        title="",
        font_path=str(FONT_FZPW),
        dynamic_origin=True,
    )

    bg = tuple(int(bg_hex[i : i + 2], 16) for i in (1, 3, 5))
    fig.patch.set_facecolor(tuple([c / 255 for c in bg]))
    try:
        ax.set_facecolor(tuple([c / 255 for c in bg]))
    except Exception:
        pass

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor=fig.get_facecolor())
    buf.seek(0)
    score_calc.plt.close(fig)
    radar = Image.open(buf).convert("RGBA")
    return radar, max_dim


def build_best10_text(score_calc, results) -> str:
    df = score_calc.get_topN_by_rating(results, 20)
    lines = []
    for i, row in enumerate(df.itertuples(index=False)):
        if i >= 10:
            break
        song_name = getattr(row, "song_name", "")
        const_value = getattr(row, "const_value", 0.0)
        accuracy = getattr(row, "accuracy", 0.0)
        ai_rating = getattr(row, "AI_rating", 0.0)
        lines.append(
            f"{i+1:2d}. {song_name} {const_value:.1f}*{round(accuracy*100,2)}% => {ai_rating:.2f}"
        )
    return "\n".join(lines)


# =========================
# 主入口：只收 user_id
# =========================


def render_player_and_achievement(user_id: int) -> bytes:
    userdata = load_userdata(user_id)
    sx = 1.0
    sy = 1.0

    # 字体与描边（按缩放比例）
    font_size_16 = max(10, int(round(16 * (sx + sy) / 2)))
    font_size_20 = max(10, int(round(20 * (sx + sy) / 2)))
    stroke2 = max(1, int(round(2 * (sx + sy) / 2)))

    font16 = get_font(font_size_16)
    font20 = get_font(font_size_20)

    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)

    min_x, min_y, max_x, max_y = compute_player_achievement_bounds(userdata, sx, sy)
    pad = max(2, stroke2 * 2)
    base_w = max_x - min_x + pad * 2
    base_h = max_y - min_y + pad * 2
    base = Image.new("RGBA", (base_w, base_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(base)
    offset_xy = (-min_x + pad, -min_y + pad)

    draw_player_and_achievement(
        base=base,
        draw=draw,
        userdata=userdata,
        sx=sx,
        sy=sy,
        font16=font16,
        font20=font20,
        stroke2=stroke2,
        WHITE=WHITE,
        BLACK=BLACK,
        offset_xy=offset_xy,
    )

    bio = BytesIO()
    base.save(bio, format="PNG")
    # 测试
    # base.save("./output/test.png", format="PNG")
    return bio.getvalue()


def render_taiko_2025_summary(user_id: int) -> bytes:
    out_path = OUTPUT_DIR / f"{user_id}_taiko_2025_summary.png"
    if os.path.exists(out_path):
        img = Image.open(out_path)
        imgBytes = BytesIO()
        img.save(imgBytes, format="png")
        return imgBytes.getvalue()
    userdata = load_userdata(user_id)
    songs: List[Dict[str, Any]] = userdata.get("songs", []) or []
    song_db = load_song_db()

    # 分歧点：刷分赛/随机倍速
    twso_rec = find_twso_record(user_id)
    has_twso = twso_rec is not None

    random_cnt, speed_cnt = count_random_speed(songs)
    has_random_or_speed = (random_cnt > 0) or (speed_cnt > 0)

    template_path = choose_template(has_twso, has_random_or_speed)
    base = Image.open(template_path).convert("RGBA")

    # 坐标缩放（若模板不是 499x5194，也能用）
    sx = base.width / BASE_W
    sy = base.height / BASE_H

    draw = ImageDraw.Draw(base)

    # 字体与描边（按缩放比例）
    font_size_16 = max(10, int(round(16 * (sx + sy) / 2)))
    font_size_20 = max(10, int(round(20 * (sx + sy) / 2)))
    font_size_24 = max(10, int(round(24 * (sx + sy) / 2)))
    font_size_28 = max(10, int(round(28 * (sx + sy) / 2)))
    font_size_32 = max(10, int(round(32 * (sx + sy) / 2)))
    font_size_38 = max(10, int(round(38 * (sx + sy) / 2)))
    stroke2 = max(1, int(round(2 * (sx + sy) / 2)))
    stroke3 = max(1, int(round(3 * (sx + sy) / 2)))

    font16 = get_font(font_size_16)
    font20 = get_font(font_size_20)
    font24 = get_font(font_size_24)
    font28 = get_font(font_size_28)
    font32 = get_font(font_size_32)
    font38 = get_font(font_size_38)
    font14 = get_font(max(10, int(font_size_16 * 0.85)))

    WHITE = (255, 255, 255)
    BLACK = (0, 0, 0)
    RED = (0xDF, 0x2C, 0x28)

    draw_player_and_achievement(
        base=base,
        draw=draw,
        userdata=userdata,
        sx=sx,
        sy=sy,
        font16=font16,
        font20=font20,
        stroke2=stroke2,
        WHITE=WHITE,
        BLACK=BLACK,
    )

    # =========================
    # 后续字体：#df2c28 + 3px白描边
    # =========================

    def plaque_line_boxes(
        plq_box_base: Tuple[int, int, int, int], n_lines: int
    ) -> List[Tuple[int, int, int, int]]:
        """把一块牌匾按行切分（不检测，固定比例）"""
        b = scale_box(plq_box_base, sx, sy)
        x1, y1, x2, y2 = b
        h = y2 - y1
        top_pad = int(h * 0.20)
        bot_pad = int(h * 0.12)
        usable = h - top_pad - bot_pad
        lines = []
        for i in range(n_lines):
            ly1 = y1 + top_pad + int(usable * (i / n_lines))
            ly2 = y1 + top_pad + int(usable * ((i + 1) / n_lines))
            # 左右留边
            padx = int((x2 - x1) * 0.08)
            lines.append((x1 + padx, ly1, x2 - padx, ly2))
        return lines

    def right_blank(line_box: Tuple[int, int, int, int], right_frac: float = 0.42):
        """取一行右侧空位区域（数值）"""
        x1, y1, x2, y2 = line_box
        w = x2 - x1
        return (x1 + int(w * (1 - right_frac)), y1, x2, y2)

    def two_blanks(line_box: Tuple[int, int, int, int], left_frac: float = 0.55):
        """一行两个空位：左/右"""
        x1, y1, x2, y2 = line_box
        w = x2 - x1
        mid = x1 + int(w * left_frac)
        return (x1, y1, mid, y2), (mid, y1, x2, y2)

    # 3) 总歌曲数
    total_stage, v2, v3 = compute_total_song_stats(songs)
    lines = plaque_line_boxes(PLAQUE_TOTAL_BOX, 3)
    for i in range(len(lines)):
        if i == 0:
            t = list(lines[i])
            t[0] -= 580
            t[1] -= 20
            lines[i] = tuple(t)
        else:
            t = list(lines[i])
            t[0] -= 740
            if i == 1:
                t[1] -= 16
            else:
                t[1] -= 20
            lines[i] = tuple(t)
    for i, val in enumerate([total_stage, v2, v3]):
        if i == 0:
            draw_text_center(
                draw, right_blank(lines[i]), str(val), font24, RED, WHITE, stroke3
            )
        else:
            draw_text_center(
                draw, right_blank(lines[i]), str(val), font20, RED, WHITE, stroke3
            )

    # 4) 游玩次数最多歌曲
    mp_name, mp_best_high, mp_stage_sum, mp_weekly = most_played_song(songs, song_db)
    lines = plaque_line_boxes(PLAQUE_MOSTPLAYED_BOX, 3)
    # 第1行歌名：自动缩放/截断
    maxw = lines[0][2] - lines[0][0]
    mp_name2, mp_font = fit_text_in_box(
        draw,
        mp_name,
        FONT_FZPW,
        maxw,
        font_size_20,
        min_size=max(10, int(font_size_20 * 0.7)),
    )
    lines[0] = list(lines[0])
    lines[0][1] += 24
    lines[0] = tuple(lines[0])
    draw_text_center(draw, lines[0], mp_name2, mp_font, RED, WHITE, stroke3)
    # 第2行：最高分 / 总次数
    lbox, rbox = two_blanks(lines[1], left_frac=0.58)
    lbox = list(lbox)
    lbox[0] += 200
    lbox[1] += 11
    lbox = tuple(lbox)
    rbox = list(rbox)
    rbox[0] += 120
    rbox[1] += 11
    rbox = tuple(rbox)
    draw_text_center(draw, lbox, str(mp_best_high), font20, RED, WHITE, stroke3)
    draw_text_center(draw, rbox, str(mp_stage_sum), font20, RED, WHITE, stroke3)
    # 第3行：折算值
    lines[2] = list(lines[2])
    lines[2][0] -= 700
    lines[2][1] += 1
    lines[2] = tuple(lines[2])
    draw_text_center(
        draw, right_blank(lines[2]), f"{mp_weekly:.1f}", font20, RED, WHITE, stroke3
    )

    # 5) 分数最高的歌曲
    hs_name, hs_diff, hs_score = highest_score_song(songs, song_db)
    lines = plaque_line_boxes(PLAQUE_HIGHSCORE_BOX, 2)
    maxw = lines[0][2] - lines[0][0]
    if len(hs_name) < 20:
        hs_name2, hs_font = fit_text_in_box(
            draw,
            hs_name,
            FONT_FZPW,
            maxw,
            font_size_20,
            min_size=max(10, int(font_size_24 * 0.7)),
        )
    else:
        hs_name2, hs_font = fit_text_in_box(
            draw,
            hs_name,
            FONT_FZPW,
            maxw,
            font_size_16,
            min_size=max(10, int(font_size_24 * 0.7)),
        )
    if len(hs_name2) < 20:
        lines[0] = list(lines[0])
        lines[0][0] += 30
        lines[0][1] += 10
        lines[0] = tuple(lines[0])
        draw_text_center(draw, lines[0], hs_name2, hs_font, RED, WHITE, stroke3)
    else:
        lines[0] = list(lines[0])
        lines[0][0] += 30
        lines[0][1] += 12
        lines[0] = tuple(lines[0])
        draw_text_center(draw, lines[0], hs_name2, hs_font, RED, WHITE, stroke3)
    lines[1] = list(lines[1])
    lines[1][0] += 115
    lines[1][1] -= 33
    lines[1] = tuple(lines[1])
    draw_text_center(
        draw, lines[1], f"{hs_diff}  {hs_score}", font20, RED, WHITE, stroke3
    )

    # 6) 参与刷分赛（有刷分模板才会走到这里；无则跳过）
    if has_twso and twso_rec:
        twso_total = safe_int(twso_rec.get("total_score"))
        twso_rank = safe_int(twso_rec.get("rank"))
        twso_cn_rank = safe_int(twso_rec.get("cn_rank"))
        lines = plaque_line_boxes(PLAQUE_TWSO_BOX, 2)
        # 第1行
        lines[0] = list(lines[0])
        lines[0][0] -= 560
        lines[0][1] += 18
        lines[0] = tuple(lines[0])
        draw_text_center(
            draw, right_blank(lines[0]), str(twso_total), font20, RED, WHITE, stroke3
        )
        # 第2行
        lbox, rbox = two_blanks(lines[1], left_frac=0.58)
        lbox = list(lbox)
        lbox[0] -= 40
        lbox[1] -= 45
        lbox = tuple(lbox)
        rbox = list(rbox)
        rbox[0] += 30
        rbox[1] -= 45
        rbox = tuple(rbox)
        draw_text_center(draw, lbox, str(twso_rank), font20, RED, WHITE, stroke3)
        draw_text_center(draw, rbox, str(twso_cn_rank), font20, RED, WHITE, stroke3)

    # 7) 随机/倍速（有随机模板才会走到这里；无则跳过）
    if has_random_or_speed:
        if random_cnt == speed_cnt and random_cnt > 0:
            pref = "随机&倍速"
        else:
            pref = "随机" if random_cnt >= speed_cnt else "倍速"

        lines = plaque_line_boxes(PLAQUE_RANDOM_BOX, 3)
        lines[0] = list(lines[0])
        lines[0][0] -= 450
        lines[0][1] += 28
        lines[0] = tuple(lines[0])
        draw_text_center(
            draw, right_blank(lines[0]), str(random_cnt), font20, RED, WHITE, stroke3
        )
        lines[1] = list(lines[1])
        lines[1][0] -= 440
        lines[1][1] += 10
        lines[1] = tuple(lines[1])
        draw_text_center(
            draw, right_blank(lines[1]), str(speed_cnt), font20, RED, WHITE, stroke3
        )
        lines[2] = list(lines[2])
        lines[2][0] -= 550
        lines[2][1] -= 10
        lines[2] = tuple(lines[2])
        draw_text_center(draw, right_blank(lines[2]), pref, font16, RED, WHITE, stroke3)

    # =========================
    # 8) 年度关键词：雷达图 + 最大维度名 + best10 文本
    # =========================
    score_calc = import_score_calculator()
    results = score_calc.compute_all_from_userdata(
        user_id=user_id, json_path=RATING_STRUCT_PATH
    )
    if results:
        radar_img, max_dim = generate_radar_only(score_calc, results, bg_hex="#fde2bb")
        best10_text = build_best10_text(score_calc, results)
        best10_items = best10_text.split("\n")  # 每行当一个条目（不建议长期用）

        # 关键词
        keyword_box_s = scale_box(KEYWORD_TEXT_BOX, sx, sy)
        # 微调
        keyword_box_s = list(keyword_box_s)
        keyword_box_s[1] += 41
        keyword_box_s = tuple(keyword_box_s)
        draw_text_center(draw, keyword_box_s, max_dim, font38, RED, WHITE, stroke3)

        # 雷达图底色 + 雷达图
        radar_box_s = scale_box(RADAR_BOX, sx, sy)
        radar_box_s = list(radar_box_s)
        radar_box_s[1] -= 130
        radar_box_s = tuple(radar_box_s)
        rx1, ry1, rx2, ry2 = radar_box_s
        bg = Image.new("RGBA", (rx2 - rx1, ry2 - ry1), (0xFD, 0xE2, 0xBB, 255))
        base.alpha_composite(bg, (rx1, ry1))
        paste_contain(base, radar_img, radar_box_s, pad=max(2, int(6 * sx)))

        # best10 文本
        best_box_s = scale_box(BEST10_TEXT_BOX, sx, sy)

        draw_wrapped_items_in_box(
            base=base,
            box=best_box_s,
            items=best10_items,  # List[str]，每项代表一首歌，可含 \n
            font=font24,
            fill=RED,
            stroke_fill=WHITE,
            stroke_width=stroke3,
            wrap_gap=max(5, int(round(10 * sy))),  # 条目内换行：小
            item_gap=max(20, int(round(34 * sy))),  # 歌与歌之间：大
            align="left",
            valign="top",
        )
    else:
        # 关键词
        keyword_box_s = scale_box(KEYWORD_TEXT_BOX, sx, sy)
        # 微调
        keyword_box_s = list(keyword_box_s)
        keyword_box_s[1] += 41
        keyword_box_s = tuple(keyword_box_s)
        draw_text_center(draw, keyword_box_s, "太鼓新秀", font38, RED, WHITE, stroke3)
        # best10 文本
        best_box_s = scale_box(BEST10_TEXT_BOX, sx, sy)
        draw_wrapped_items_in_box(
            base=base,
            box=best_box_s,
            items=[
                "这里需要游玩鬼难度才能解锁哦~\n期待你未来的出色表现！"
            ],  # List[str]，每项代表一首歌，可含 \n
            font=font20,
            fill=RED,
            stroke_fill=WHITE,
            stroke_width=stroke3,
            wrap_gap=max(5, int(round(10 * sy))),  # 条目内换行：小
            item_gap=max(20, int(round(34 * sy))),  # 歌与歌之间：大
            align="left",
            valign="top",
        )

    base.save(out_path)
    bio = BytesIO()
    base.save(bio, format="PNG")
    return bio.getvalue()
    # return out_path


# if __name__ == "__main__":
#     # 示例：你上传的样例 user_id
#     p = render_taiko_2025_summary(87099565)
#     print("OK:", p)
# render_player_and_achievement(2258735)
# render_taiko_2025_summary(2258735)
