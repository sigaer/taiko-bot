# -*- coding: utf-8 -*-
"""
B30 single-song card renderer.

Template size: 595x384
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from .score_calculator import (
    PAIR_ID_GROUPS,
    PAIR_ID_MAP,
    _calc_accuracy_for_record,
    build_const_table,
    calc_y,
    compute_AD_AE_AF_AG,
    compute_AI,
    compute_P,
    compute_Q,
    load_rating_config,
    lookup_const_score,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
ASSETS_DIR = ROOT_DIR / "assets"
TEMPLATE_DEFAULT = ASSETS_DIR / "templates" / "b30_single.png"
SONG_DB_DEFAULT = ROOT_DIR / "songs" / "song_data.json"
RATING_JSON_DEFAULT = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

TYPE_MAP = {
    "南梦宫原创音乐": "original",
    "流行音乐": "pop",
    "动漫音乐": "anime",
    "游戏音乐": "gamemusic",
    "博歌乐音乐": "vocaloid",
    "儿童音乐": "kid",
    "古典音乐": "classical",
    "综合音乐": "variety",
}

FONT_TITLE_PATH = ASSETS_DIR / "fonts" / "FZPW_GBK.ttf"
FONT_SCORE_PATH = ASSETS_DIR / "fonts" / "FZPW_GBK.ttf"
FONT_STATS_PATH = ASSETS_DIR / "fonts" / "FZPW_GBK.ttf"
FONT_TITLE_FALLBACK_PATHS = [
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/SourceHanSansCN-Bold.otf"),
    Path("/usr/share/fonts/SourceHanSansCN-Medium.otf"),
    FONT_TITLE_PATH,
]

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)

# Layout tuned for assets/templates/b30_single.png (595x384)
DIFF_ICON_POS = (35, 0)
DIFF_ICON_SIZE_DEFAULT = (168, 71)
DIFF_TEXT_Y_OFFSET = 13
OPTION_ROW_POS = (262, 76)

COVER_OUTER_SIZE = 200
COVER_ART_SIZE = 190
COVER_BORDER_WIDTH = 5
COVER_ART_POS = (58, 109)
COVER_POS = (
    COVER_ART_POS[0] - COVER_BORDER_WIDTH,
    COVER_ART_POS[1] - COVER_BORDER_WIDTH,
)

TITLE_BOX = (254, 116, 545, 161)

SCORE_BOX = (265, 178, 537, 229)
SCORE_RIGHT_MARGIN = 8
SCORE_ARROW_GAP = 6

RANK_ICON_SIZE = (60, 60)
CROWN_ICON_SIZE = (60, 60)
RANK_POS = (268, 233)
CROWN_POS = (358, 233)

STATS_RIGHT_X = 531
STATS_TOP_Y = 238
STATS_LINE_GAP = 30
STATS_Y_OFFSET = -6

OPTION_ICON_SIZE = (30, 30)
OPTION_ICON_GAP = 13

NEW_ICON_PATH = ASSETS_DIR / "icons" / "other" / "new.png"
NEW_ICON_MAX_SIZE = (88, 66)
NEW_ICON_COVER_OFFSET = (2, 4)

TITLE_FONT_SIZE = 28
SCORE_FONT_SIZE = 26
STATS_FONT_SIZE = 22
DIFF_FONT_SIZE = 22

ARROW = "→"


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _load_font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


def _load_font_candidates(paths: Iterable[Path], size: int) -> ImageFont.ImageFont:
    for path in paths:
        if not path.exists():
            continue
        try:
            return ImageFont.truetype(str(path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _ddfont_y_offset(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
) -> None:
    x, y = xy
    draw.text((x, y + _ddfont_y_offset(font)), text, font=font, fill=fill)


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


def _center_crop_to_square(im: Image.Image) -> Image.Image:
    w, h = im.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    return im.crop((left, top, left + side, top + side))


def _load_icon(
    path: Path, size: Optional[Tuple[int, int]] = None
) -> Optional[Image.Image]:
    if not path.exists():
        return None
    im = Image.open(path).convert("RGBA")
    if size:
        im = im.resize(size, Image.LANCZOS)
    return im


def _load_icon_fit(
    path: Path, max_size: Tuple[int, int]
) -> Optional[Image.Image]:
    if not path.exists():
        return None
    im = Image.open(path).convert("RGBA")
    im.thumbnail(max_size, Image.LANCZOS)
    return im


def _resolve_template_path(template_path: Path, assets_base: Path) -> Path:
    if template_path.exists():
        return template_path
    fallback = assets_base / "templates" / template_path.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Template not found: {template_path}")


def _pick_b30_template(
    template_path: Path, assets_base: Path, song_type: str
) -> Path:
    category = (song_type or "").strip()
    if category in TYPE_MAP:
        typed = assets_base / "templates" / f"b30_single_{TYPE_MAP[category]}.png"
        if typed.exists():
            return typed
    return _resolve_template_path(template_path, assets_base)


def _truncate_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    if draw.textlength(ellipsis, font=font) > max_width:
        return ellipsis
    trimmed = text
    while trimmed:
        trimmed = trimmed[:-1]
        candidate = trimmed + ellipsis
        if draw.textlength(candidate, font=font) + 16 <= max_width:
            return candidate
    return ellipsis


def _draw_text_centered_in_box(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_width: int = 0,
    stroke_fill: Tuple[int, int, int] = BLACK,
    y_offset: int = 0,
) -> None:
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    # For "visual" centering, compensate for fonts whose bbox has negative top/left.
    # Pillow's text drawing uses the text origin at the top-left of the glyph bbox;
    # therefore we subtract bbox[0]/bbox[1] to keep the rendered ink centered.
    box_w = x2 - x1
    box_h = y2 - y1
    x = x1 + max(0, (box_w - text_w) // 2) - bbox[0]
    y = y1 + max(0, (box_h - text_h) // 2) - bbox[1] + y_offset
    if stroke_width > 0:
        _draw_text_with_stroke(
            draw, (x, y), text, font, fill, stroke_width, stroke_fill
        )
    else:
        _draw_text(draw, (x, y), text, font, fill)


def _center_y_text_in_box(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    y_offset: int = 0,
) -> int:
    """Return y such that the rendered text is visually centered within the y-range.

    This compensates for fonts where textbbox() has a negative top (bbox[1] < 0).
    """

    _, y1, _, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    text_h = bbox[3] - bbox[1]
    box_h = y2 - y1
    return y1 + max(0, (box_h - text_h) // 2) - bbox[1] + y_offset


def _center_y_in_box(box: Tuple[int, int, int, int], height: int) -> int:
    _, y1, _, y2 = box
    return y1 + max(0, (y2 - y1 - height) // 2)


def _center_y_with_font_offset(
    box: Tuple[int, int, int, int], text_height: int, font: ImageFont.ImageFont
) -> int:
    y = _center_y_in_box(box, text_height)
    font_size = getattr(font, "size", 0) or 0
    return y - font_size // 2


def _draw_right_aligned(
    draw: ImageDraw.ImageDraw,
    x_right: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_width: int = 0,
    stroke_fill: Tuple[int, int, int] = BLACK,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    x = x_right - text_w
    if stroke_width > 0:
        _draw_text_with_stroke(
            draw, (x, y), text, font, fill, stroke_width, stroke_fill
        )
    else:
        _draw_text(draw, (x, y), text, font, fill)


def _paste_cover(
    canvas: Image.Image, cover_path: Path, fallback_path: Path, pos: Tuple[int, int]
) -> None:
    if cover_path.exists():
        path = cover_path
    elif fallback_path.exists():
        path = fallback_path
    else:
        return
    art = Image.open(path).convert("RGBA")
    art = _center_crop_to_square(art).resize(
        (COVER_ART_SIZE, COVER_ART_SIZE), Image.LANCZOS
    )
    x, y = pos
    canvas.paste(art, (x + COVER_BORDER_WIDTH, y + COVER_BORDER_WIDTH), art)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle(
        (x, y, x + COVER_OUTER_SIZE - 1, y + COVER_OUTER_SIZE - 1),
        outline=BLACK,
        width=COVER_BORDER_WIDTH,
    )


def _pick_crown_path(assets_base: Path, entry: Dict[str, Any]) -> Optional[Path]:
    if entry.get("dondaful_combo_cnt", 0) > 0:
        return assets_base / "icons" / "crown" / "dondaful.png"
    if entry.get("full_combo_cnt", 0) > 0:
        return assets_base / "icons" / "crown" / "full.png"
    if entry.get("clear_cnt", 0) > 0:
        return assets_base / "icons" / "crown" / "clear.png"
    return None


def _rank_icon_path(assets_base: Path, rank_value: int) -> Path:
    return assets_base / "icons" / "rank" / f"{rank_value}.png"


def _format_level_value(value: Any) -> str:
    if value in (None, "", "-"):
        return "-"
    try:
        num = float(value)
    except Exception:
        return str(value)
    if num.is_integer():
        return str(int(num))
    return f"{num:.1f}".rstrip("0").rstrip(".")


_RATING_RESOURCE_CACHE: Dict[
    str, Tuple[int, Tuple[Dict[str, Any], Dict[Tuple[int, int], dict], List[tuple]]]
] = {}


def _load_rating_resources(
    path_str: str,
) -> Tuple[Dict[str, Any], Dict[Tuple[int, int], dict], List[tuple]]:
    path = Path(path_str)
    mtime_ns = path.stat().st_mtime_ns
    cached = _RATING_RESOURCE_CACHE.get(str(path))
    if cached and cached[0] == mtime_ns:
        return cached[1]

    cfg = load_rating_config(path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)
    index: Dict[Tuple[int, int], dict] = {}
    for song in cfg["songs"].values():
        try:
            key = (int(song.get("id", 0)), int(song.get("level", 0)))
        except Exception:
            continue
        index[key] = song
    result = (cfg, index, const_table)
    _RATING_RESOURCE_CACHE[str(path)] = (mtime_ns, result)
    return result


def _compute_rating_for_entry(
    entry: Dict[str, Any],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
) -> Optional[float]:
    try:
        song_no = int(entry.get("song_no", 0))
        level = int(entry.get("level", 0))
    except Exception:
        return None
    song_info = rating_index.get((song_no, level))
    if not song_info:
        pair_id = PAIR_ID_MAP.get(song_no)
        if pair_id is not None:
            for candidate_song_no in PAIR_ID_GROUPS[pair_id]:
                if candidate_song_no == song_no:
                    continue
                song_info = rating_index.get((candidate_song_no, level))
                if song_info:
                    break
    if not song_info:
        return None
    good_cnt = int(entry.get("good_cnt", 0) or 0)
    ok_cnt = int(entry.get("ok_cnt", 0) or 0)
    total_notes = int(song_info.get("combo", 0) or 0)
    dondaful_cnt = int(entry.get("dondaful_combo_cnt", 0) or 0)
    accuracy = _calc_accuracy_for_record(
        total_notes=total_notes,
        great_cnt=good_cnt,
        good_cnt=ok_cnt,
        dondaful_combo_cnt=dondaful_cnt,
        algorithm="comprehensive",
    )
    if accuracy == 0.0:
        return 0.0
    metrics = compute_AD_AE_AF_AG(song_info)
    const_value = song_info.get("score", 0)
    M = lookup_const_score(const_value, const_table)
    N = calc_y(accuracy=accuracy, normalization_factor=15.5, algorithm="comprehensive")
    P = compute_P(M, N)
    Q = compute_Q(M, N)
    return compute_AI(M, N, P, Q)


def build_song_index(song_db: Iterable[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    index: Dict[int, Dict[str, Any]] = {}
    for song in song_db:
        try:
            song_id = int(song.get("id", 0))
        except Exception:
            continue
        index[song_id] = song
    return index


def _paste_new_badge(canvas: Image.Image, assets_base: Path) -> None:
    icon_path = assets_base / "icons" / "other" / "new.png"
    if not icon_path.exists():
        icon_path = NEW_ICON_PATH
    icon = _load_icon_fit(icon_path, NEW_ICON_MAX_SIZE)
    if not icon:
        return
    cover_x2 = COVER_POS[0] + COVER_OUTER_SIZE
    cover_y1 = COVER_POS[1]
    offset_x, offset_y = NEW_ICON_COVER_OFFSET
    x = cover_x2 - icon.width + offset_x
    y = cover_y1 + offset_y
    x = max(COVER_POS[0], x)
    y = max(0, y)
    canvas.alpha_composite(icon, (x, y))


def render_b30_single_card(
    entry: Dict[str, Any],
    song_info: Dict[str, Any],
    *,
    template_path: str | Path = TEMPLATE_DEFAULT,
    assets_base: str | Path = ASSETS_DIR,
    rating_json_path: str | Path = RATING_JSON_DEFAULT,
    rating_index: Optional[Dict[Tuple[int, int], dict]] = None,
    const_table: Optional[List[tuple]] = None,
    as_png_bytes: bool = True,
    show_new: bool = False,
) -> bytes | Image.Image:
    assets_base = Path(assets_base)
    template_path = _pick_b30_template(
        Path(template_path), assets_base, song_info.get("type", "")
    )
    canvas = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)

    font_title = _load_font_candidates(FONT_TITLE_FALLBACK_PATHS, TITLE_FONT_SIZE)
    font_score = _load_font(FONT_SCORE_PATH, SCORE_FONT_SIZE)
    font_stats = _load_font(FONT_STATS_PATH, STATS_FONT_SIZE)
    font_diff = _load_font(FONT_STATS_PATH, DIFF_FONT_SIZE)

    try:
        song_no = int(entry.get("song_no", 0))
        level = int(entry.get("level", 0))
    except Exception:
        song_no = 0
        level = 0

    diff_icon_path = assets_base / "icons" / "diff" / f"icon_{level}.png"
    diff_icon = _load_icon(diff_icon_path)
    if diff_icon:
        canvas.paste(diff_icon, DIFF_ICON_POS, diff_icon)

    level_value = song_info.get(f"level_{level}")
    diff_text = f"☆ {_format_level_value(level_value)}"
    icon_w, icon_h = diff_icon.size if diff_icon else DIFF_ICON_SIZE_DEFAULT
    diff_text_box = (
        DIFF_ICON_POS[0],
        DIFF_ICON_POS[1],
        DIFF_ICON_POS[0] + icon_w,
        DIFF_ICON_POS[1] + icon_h,
    )
    _draw_text_centered_in_box(
        draw,
        diff_text_box,
        diff_text,
        font_diff,
        WHITE,
        stroke_width=2,
        stroke_fill=BLACK,
        y_offset=DIFF_TEXT_Y_OFFSET,
    )

    option_flags = entry.get("option_flg", [])
    if isinstance(option_flags, list):
        icon_x = OPTION_ROW_POS[0]
        icon_y = OPTION_ROW_POS[1]
        if len(option_flags) >= 1:
            flag_name = str(format(option_flags[0], ".1f"))
            icon_path = assets_base / "icons" / "option" / f"{flag_name}.png"
            icon = _load_icon(icon_path, OPTION_ICON_SIZE)
            if icon:
                canvas.paste(icon, (icon_x, icon_y), icon)
                icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_GAP
        if len(option_flags) >= 2 and option_flags[1] == 1:
            icon_path = assets_base / "icons" / "option" / "hidden.png"
            icon = _load_icon(icon_path, OPTION_ICON_SIZE)
            if icon:
                canvas.paste(icon, (icon_x, icon_y), icon)
                icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_GAP
        if len(option_flags) >= 3 and option_flags[2] == 1:
            icon_path = assets_base / "icons" / "option" / "mirror.png"
            icon = _load_icon(icon_path, OPTION_ICON_SIZE)
            if icon:
                canvas.paste(icon, (icon_x, icon_y), icon)
                icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_GAP
        if len(option_flags) >= 4:
            if option_flags[3] == "01":
                icon_path = assets_base / "icons" / "option" / "super_random.png"
            elif option_flags[3] == "10":
                icon_path = assets_base / "icons" / "option" / "random.png"
            else:
                icon_path = None
            if icon_path:
                icon = _load_icon(icon_path, OPTION_ICON_SIZE)
                if icon:
                    canvas.paste(icon, (icon_x, icon_y), icon)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_GAP

    cover_path = assets_base / "cover" / f"{song_no}.png"
    fallback_cover = assets_base / "cover" / "1384.png"
    _paste_cover(canvas, cover_path, fallback_cover, COVER_POS)

    song_name = (
        song_info.get("song_name")
        or song_info.get("song_name_jp")
        or song_info.get("song_name_cn")
        or f"ID{song_no}"
    )
    title_text = _truncate_text(
        draw, str(song_name), font_title, TITLE_BOX[2] - TITLE_BOX[0]
    )
    title_y = _center_y_text_in_box(draw, TITLE_BOX, title_text, font_title)
    _draw_text(draw, (TITLE_BOX[0] + 15, title_y), title_text, font_title, BLACK)

    if rating_index is None or const_table is None:
        _, rating_index, const_table = _load_rating_resources(str(rating_json_path))

    rating_value = _compute_rating_for_entry(entry, rating_index, const_table) or 0.0
    score_value = int(entry.get("high_score", 0) or 0)
    score_text = f"{score_value:,}".replace(",", "")
    rating_text = f"{rating_value:.2f}"
    score_line = f"{score_text} {ARROW} {rating_text}"
    score_y = _center_y_text_in_box(draw, SCORE_BOX, score_line, font_score)
    score_bbox = draw.textbbox((0, 0), score_text, font=font_score)
    arrow_bbox = draw.textbbox((0, 0), ARROW, font=font_score)
    rating_bbox = draw.textbbox((0, 0), rating_text, font=font_score)
    rating_x = SCORE_BOX[2] - SCORE_RIGHT_MARGIN - (rating_bbox[2] - rating_bbox[0])
    score_x = SCORE_BOX[0] + 7
    score_right = score_x + (score_bbox[2] - score_bbox[0])
    arrow_w = arrow_bbox[2] - arrow_bbox[0]
    arrow_x = int((score_right + rating_x - arrow_w) / 2)

    _draw_text_with_stroke(
        draw,
        (score_x, score_y),
        score_text,
        font_score,
        WHITE,
        stroke_width=3,
        stroke_fill=BLACK,
    )
    _draw_text_with_stroke(
        draw,
        (arrow_x, score_y),
        ARROW,
        font_score,
        WHITE,
        stroke_width=3,
        stroke_fill=BLACK,
    )
    _draw_text_with_stroke(
        draw,
        (rating_x, score_y),
        rating_text,
        font_score,
        WHITE,
        stroke_width=3,
        stroke_fill=BLACK,
    )

    try:
        rank_val = int(entry.get("best_score_rank", 0) or 0)
    except Exception:
        rank_val = 0
    rank_icon = _load_icon(_rank_icon_path(assets_base, rank_val), RANK_ICON_SIZE)
    if rank_icon:
        canvas.paste(rank_icon, RANK_POS, rank_icon)

    crown_path = _pick_crown_path(assets_base, entry)
    crown_icon = _load_icon(crown_path, CROWN_ICON_SIZE) if crown_path else None
    if crown_icon:
        canvas.paste(crown_icon, CROWN_POS, crown_icon)

    good_cnt = str(entry.get("good_cnt", 0) or 0)
    ok_cnt = str(entry.get("ok_cnt", 0) or 0)
    _draw_right_aligned(
        draw,
        STATS_RIGHT_X,
        STATS_TOP_Y + STATS_Y_OFFSET,
        good_cnt,
        font_stats,
        WHITE,
        stroke_width=2,
        stroke_fill=BLACK,
    )
    _draw_right_aligned(
        draw,
        STATS_RIGHT_X,
        STATS_TOP_Y + STATS_LINE_GAP + STATS_Y_OFFSET,
        ok_cnt,
        font_stats,
        WHITE,
        stroke_width=2,
        stroke_fill=BLACK,
    )

    if show_new:
        _paste_new_badge(canvas, assets_base)

    if as_png_bytes:
        from io import BytesIO

        bio = BytesIO()
        canvas.save(bio, format="PNG")
        return bio.getvalue()
    return canvas


def render_b30_single_cards_from_user_data(
    user_data_path: str | Path,
    *,
    song_db_path: str | Path = SONG_DB_DEFAULT,
    template_path: str | Path = TEMPLATE_DEFAULT,
    assets_base: str | Path = ASSETS_DIR,
    rating_json_path: str | Path = RATING_JSON_DEFAULT,
    limit: Optional[int] = None,
) -> List[bytes]:
    user_data = _load_json(Path(user_data_path))
    songs = user_data.get("songs", []) if isinstance(user_data, dict) else user_data
    song_db = _load_json(Path(song_db_path))
    song_index = build_song_index(song_db)
    _, rating_index, const_table = _load_rating_resources(str(rating_json_path))

    output: List[bytes] = []
    for entry in songs:
        song_no = int(entry.get("song_no", 0) or 0)
        song_info = song_index.get(song_no)
        if not song_info:
            continue
        img_bytes = render_b30_single_card(
            entry,
            song_info,
            template_path=template_path,
            assets_base=assets_base,
            rating_index=rating_index,
            const_table=const_table,
            as_png_bytes=True,
        )
        output.append(img_bytes)
        if limit and len(output) >= limit:
            break
    return output
