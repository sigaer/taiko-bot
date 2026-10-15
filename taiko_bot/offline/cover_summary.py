import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw, ImageFont


# ---------------------------
# 配置区
# ---------------------------

SONG_DB_PATH = "songs/song_data.json"
COVER_DIR = "assets/cover"
# FONT_PATH = "assets/fonts/DDFont.ttf"
FONT_PATH = "assets/fonts/DDFont.ttf"
OUT_PATH = "assets/cover_progress.png"

# 8 类及颜色（RGB）
TYPE_COLOR: Dict[str, Tuple[int, int, int]] = {
    "南梦宫原创音乐": (255, 153, 0),  # 橙
    "流行音乐": (0, 122, 204),  # 蓝
    "儿童音乐": (255, 204, 0),  # 金
    "古典音乐": (184, 134, 11),  # 棕黄
    "综合音乐": (46, 204, 113),  # 绿
    "游戏音乐": (155, 89, 182),  # 紫
    "博歌乐音乐": (128, 128, 128),  # 灰
    "动漫音乐": (255, 105, 180),  # 粉
}

TYPE_ORDER = [
    "南梦宫原创音乐",
    "流行音乐",
    "儿童音乐",
    "古典音乐",
    "综合音乐",
    "游戏音乐",
    "博歌乐音乐",
    "动漫音乐",
]

# 你项目里歌曲名字段可能不同，这里给一组“常见候选字段”，按顺序取第一个非空
TITLE_FIELDS_CANDIDATES = [
    "song_name_cn",
    "song_name_zh",
    "song_name",
    "song_name_jp",
    "name",
    "title",
]


@dataclass
class SongEntry:
    song_id: str
    song_type: str
    title: str
    has_cover: bool


# ---------------------------
# 工具函数
# ---------------------------


def _safe_str(x: Any) -> str:
    if x is None:
        return ""
    return str(x)


def _pick_title(item: Dict[str, Any]) -> str:
    for k in TITLE_FIELDS_CANDIDATES:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    # 有些结构可能把名字放在更深层
    # 兜底：把 item 中所有可能的名字字段都试一下
    for k, v in item.items():
        if "name" in k.lower() and isinstance(v, str) and v.strip():
            return v.strip()
    return "(未命名)"


def _cover_path(song_id: str) -> str:
    return os.path.join(COVER_DIR, f"{song_id}.png")


def _file_exists(path: str) -> bool:
    return os.path.isfile(path)


def _load_songs() -> List[SongEntry]:
    if not os.path.isfile(SONG_DB_PATH):
        raise FileNotFoundError(f"未找到数据库文件：{SONG_DB_PATH}")

    with open(SONG_DB_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("song_data.json 期望为 json list")

    songs: List[SongEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        raw_id = item.get("id")
        if raw_id is None:
            continue
        song_id = _safe_str(raw_id)

        song_type = _safe_str(item.get("type")).strip() or "未知"
        title = _pick_title(item)

        has_cover = _file_exists(_cover_path(song_id))

        songs.append(
            SongEntry(
                song_id=song_id, song_type=song_type, title=title, has_cover=has_cover
            )
        )

    return songs


def _ensure_font(size: int) -> ImageFont.FreeTypeFont:
    if not os.path.isfile(FONT_PATH):
        raise FileNotFoundError(f"未找到字体文件：{FONT_PATH}")
    return ImageFont.truetype(FONT_PATH, size=size)


def _ddfont_y_offset(font: ImageFont.FreeTypeFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill,
) -> None:
    x, y = xy
    draw.text((x, y + _ddfont_y_offset(font)), text, fill=fill, font=font)


def _text_bbox(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> Tuple[int, int]:
    # 返回 (w, h)
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int
) -> List[str]:
    """
    按像素宽度自动换行（中文/英文混排兼容）。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines: List[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue

        buf = ""
        for ch in paragraph:
            trial = buf + ch
            w, _ = _text_bbox(draw, trial, font)
            if w <= max_width or not buf:
                buf = trial
            else:
                lines.append(buf)
                buf = ch
        if buf:
            lines.append(buf)
    return lines


# ---------------------------
# 画图主逻辑
# ---------------------------


def generate_cover_progress_image(
    out_path: str = OUT_PATH,
    width: int = 1600,
    margin: int = 60,
    header_h_gap: int = 18,
    row_gap: int = 18,
    wrap_line_gap: int = 8,  # 同一条目内换行行距（更紧凑）
    item_gap: int = 16,  # 歌与歌之间行距（更舒展）
    max_list_width_ratio: float = 0.88,
) -> str:
    songs = _load_songs()

    # 按类型聚合
    by_type: Dict[str, List[SongEntry]] = {}
    for s in songs:
        by_type.setdefault(s.song_type, []).append(s)

    # 统一把未知类型放最后
    ordered_types = [t for t in TYPE_ORDER if t in by_type]
    for t in by_type.keys():
        if t not in ordered_types:
            ordered_types.append(t)

    # 统计
    stats = []
    total_all = len(songs)
    covered_all = sum(1 for s in songs if s.has_cover)
    missing_all = total_all - covered_all

    for t in ordered_types:
        lst = by_type.get(t, [])
        total = len(lst)
        covered = sum(1 for s in lst if s.has_cover)
        stats.append((t, covered, total))

    # 字体
    font_title = _ensure_font(44)
    font_sub = _ensure_font(26)
    font_row = _ensure_font(28)
    font_small = _ensure_font(22)

    # 先用临时画布测量高度
    tmp = Image.new("RGB", (width, 2000), (255, 255, 255))
    draw = ImageDraw.Draw(tmp)

    y = margin
    # 标题区
    title = "太鼓曲绘收集进度"
    w_title, h_title = _text_bbox(draw, title, font_title)
    y += h_title + header_h_gap

    summary = f"总曲数：{total_all}    已收集：{covered_all}    缺失：{missing_all}    覆盖率：{(covered_all / total_all * 100.0) if total_all else 0.0:.2f}%"
    w_sum, h_sum = _text_bbox(draw, summary, font_sub)
    y += h_sum + 30

    # 类型进度条区
    row_h = 64
    progress_bar_w = int(width * 0.55)
    for _ in stats:
        y += row_h + row_gap

    y += 20

    # 缺失列表区标题
    miss_title = "缺失曲绘列表（按类型颜色标记）"
    w_mt, h_mt = _text_bbox(draw, miss_title, font_sub)
    y += h_mt + 16

    # 缺失列表内容（按类型分组）
    list_left = margin
    list_right = width - margin
    max_list_width = int((list_right - list_left) * max_list_width_ratio)

    for t in ordered_types:
        missing = [s for s in by_type.get(t, []) if not s.has_cover]
        if not missing:
            continue

        # 分组标题
        group_title = f"{t}（缺失 {len(missing)} / {len(by_type.get(t, []))}）"
        _, gh = _text_bbox(draw, group_title, font_row)
        y += gh + 10

        # 列表条目
        for s in missing:
            entry = f"{s.song_id}：{s.title}"
            wrapped = _wrap_text(draw, entry, font_small, max_list_width)
            # 每行高度
            _, lh = _text_bbox(draw, "测", font_small)
            y += len(wrapped) * lh + (len(wrapped) - 1) * wrap_line_gap
            y += item_gap

        y += 10

    height = y + margin
    # 防止极端超高导致部分查看器不适配；你可按需调整
    height = max(height, 900)

    # 正式画布
    img = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = margin

    # 标题
    _draw_text(draw, (margin, y), title, font_title, (0, 0, 0))
    y += h_title + header_h_gap

    # 总览
    _draw_text(draw, (margin, y), summary, font_sub, (60, 60, 60))
    y += h_sum + 30

    # 类型进度条
    # 进度条：底灰 + 前景色
    bar_h = 18
    bar_radius = 9

    def rounded_rect(x0, y0, x1, y1, r, fill):
        draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill)

    for t, covered, total in stats:
        color = TYPE_COLOR.get(t, (0, 0, 0))
        pct = (covered / total * 100.0) if total else 0.0

        # 左侧类型名
        _draw_text(draw, (margin, y + 14), t, font_row, color)

        # 中间进度条
        bar_x0 = margin + 360
        bar_y0 = y + 24
        bar_x1 = bar_x0 + progress_bar_w
        bar_y1 = bar_y0 + bar_h

        # 底
        rounded_rect(bar_x0, bar_y0, bar_x1, bar_y1, bar_radius, fill=(230, 230, 230))
        # 前景
        fg_w = int(progress_bar_w * (covered / total)) if total else 0
        if fg_w > 0:
            rounded_rect(bar_x0, bar_y0, bar_x0 + fg_w, bar_y1, bar_radius, fill=color)

        # 右侧数字
        text_right = f"{covered}/{total}  {pct:.2f}%"
        _draw_text(draw, (bar_x1 + 20, y + 14), text_right, font_row, (0, 0, 0))

        y += row_h + row_gap

    y += 20

    # 缺失列表
    _draw_text(draw, (margin, y), miss_title, font_sub, (0, 0, 0))
    y += h_mt + 16

    list_left = margin
    list_right = width - margin
    max_list_width = int((list_right - list_left) * max_list_width_ratio)

    for t in ordered_types:
        missing = [s for s in by_type.get(t, []) if not s.has_cover]
        if not missing:
            continue

        color = TYPE_COLOR.get(t, (0, 0, 0))
        group_title = f"{t}（缺失 {len(missing)} / {len(by_type.get(t, []))}）"
        _draw_text(draw, (list_left, y), group_title, font_row, color)
        _, gh = _text_bbox(draw, group_title, font_row)
        y += gh + 10

        for s in missing:
            entry = f"{s.song_id}：{s.title}"
            wrapped = _wrap_text(draw, entry, font_small, max_list_width)

            _, lh = _text_bbox(draw, "测", font_small)
            # 第一行前加一个小方块做颜色标记
            bullet_size = 10
            bullet_y = y + int((lh - bullet_size) / 2)
            draw.rectangle(
                [list_left, bullet_y, list_left + bullet_size, bullet_y + bullet_size],
                fill=color,
            )

            text_x = list_left + bullet_size + 10
            for i, line in enumerate(wrapped):
                _draw_text(draw, (text_x, y), line, font_small, (30, 30, 30))
                y += lh
                if i != len(wrapped) - 1:
                    y += wrap_line_gap

            y += item_gap

        y += 10

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    img.save(out_path)
    return out_path


if __name__ == "__main__":
    out = generate_cover_progress_image()
    print(f"已生成：{out}")
