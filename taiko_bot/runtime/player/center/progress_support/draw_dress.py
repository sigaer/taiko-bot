from __future__ import annotations


import json

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from ..recommendation_support.font_fallback import draw_text as draw_text_with_fallback, text_bbox as fallback_text_bbox

ROOT_DIR = __import__("taiko_bot.runtime.player.center.recommendation_support.paths", fromlist=["ROOT"]).ROOT


ASSETS_DIR = ROOT_DIR / "assets" / "dress"

LINE_PATH = ASSETS_DIR / "common" / "line" / "line_290.png"

NAME_PLATE_DIR = ROOT_DIR / "assets" / "name_plate"

NAME_PLATE_DANI_DIR = ROOT_DIR / "assets" / "name_plate_dani"

PLAYER_PLATE_XY = (78, 949)

PLAYER_PLATE_SIZE = (346, 56)

PLAYER_PLATE_BASE_HEIGHT = 90

PLAYER_PLATE_LOWER_HEIGHT = 45

PLAYER_TITLE_BOX = (78, 949, 78 + 346, 949 + 28)

PLAYER_NAME_RATIO = 0.55

NICKNAME_Y_OFFSET_WITH_DAN = 6

NICKNAME_Y_OFFSET_NO_DAN = NICKNAME_Y_OFFSET_WITH_DAN

def _int_or_none(value: Any) -> Optional[int]:
    try:
        num = int(value)
    except (TypeError, ValueError):
        return None
    return num

def _num3(value: int) -> str:
    return f"{value:03d}"

def _build_path(pattern: str, num: int) -> Path:
    return ASSETS_DIR / pattern.format(num=_num3(num))

def _load_image(path: Path) -> Optional[Image.Image]:
    if not path.exists():
        return None
    return Image.open(path).convert("RGBA")

def _alpha_composite(base: Image.Image, overlay: Image.Image) -> None:
    base.alpha_composite(overlay, (0, 0))

def _scale_box(
    box: Tuple[int, int, int, int], sx: float, sy: float
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (
        int(round(x1 * sx)),
        int(round(y1 * sy)),
        int(round(x2 * sx)),
        int(round(y2 * sy)),
    )

def _offset_box(
    box: Tuple[int, int, int, int], dx: int, dy: int
) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = box
    return (x1 + dx, y1 + dy, x2 + dx, y2 + dy)

def _text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    return fallback_text_bbox(draw, text, font)

def _ddfont_y_offset(font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
    font_path = str(getattr(font, "path", "") or "")
    size = int(getattr(font, "size", 0) or 0)
    if "DDFont" not in font_path or size <= 0:
        return 0
    return int(round(size * ratio))

def _draw_text_center(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int],
    stroke_fill: Tuple[int, int, int],
    stroke_width: int,
    y_offset: int = -4,
    use_font_metrics: bool = False,
) -> None:
    x1, y1, x2, y2 = box
    bb = _text_bbox(draw, str(text), font)
    tw, th = bb[2] - bb[0], bb[3] - bb[1]
    if use_font_metrics:
        try:
            ascent, descent = font.getmetrics()
            th = ascent + descent
        except Exception:
            pass
    x = x1 + (x2 - x1 - tw) // 2
    y = y1 + (y2 - y1 - th) // 2 + y_offset + _ddfont_y_offset(font)
    draw_text_with_fallback(
        draw,
        (x, y),
        str(text),
        font,
        fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )

def _paste_resize(
    base: Image.Image, overlay: Image.Image, box: Tuple[int, int, int, int]
) -> None:
    x1, y1, x2, y2 = box
    ov = overlay.convert("RGBA").resize((x2 - x1, y2 - y1), Image.LANCZOS)
    base.alpha_composite(ov, (x1, y1))

def _paste_contain(
    base: Image.Image,
    overlay: Image.Image,
    box: Tuple[int, int, int, int],
    pad: int = 0,
) -> None:
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

def _pick_name_plate(
    game_costume: Dict[str, Any], use_dan_plate: bool = False
) -> Optional[Path]:
    titleplate_id = game_costume.get("titleplate_id")
    if titleplate_id is None:
        return None
    if use_dan_plate:
        dan_path = NAME_PLATE_DIR / f"name_plate_dani_{titleplate_id}.png"
        if dan_path.exists():
            return dan_path
    return NAME_PLATE_DIR / f"name_plate_{titleplate_id}.png"

def _pick_dan_badge(dan_name: Dict[str, Any]) -> Optional[Path]:
    if not isinstance(dan_name, dict):
        return None
    grade = str(dan_name.get("grade", "")).zfill(2)
    level = str(dan_name.get("level", "")).zfill(2)
    if grade == "00" and level == "00":
        return None
    return NAME_PLATE_DANI_DIR / f"name_plate_dani_{grade}_{level}.png"

def _collect_layers(
    game_costume: Dict[str, Any],
    rules: Iterable[Tuple[str, str]],
    allow_zero_keys: Optional[Iterable[str]] = None,
) -> Tuple[List[Image.Image], List[Path]]:
    layers: List[Image.Image] = []
    missing: List[Path] = []
    allow_zero = set(allow_zero_keys or [])
    for key, pattern in rules:
        value = _int_or_none(game_costume.get(key))
        if value is None:
            continue
        if value == 0 and key not in allow_zero:
            continue
        path = _build_path(pattern, value)
        img = _load_image(path)
        if img is None:
            missing.append(path)
        else:
            layers.append(img)
    return layers, missing

def _load_line() -> Tuple[Optional[Image.Image], Optional[Path]]:
    img = _load_image(LINE_PATH)
    if img is None:
        return None, LINE_PATH
    return img, None

def _resolve_base_size(
    layers: Iterable[Image.Image], line_img: Optional[Image.Image]
) -> Tuple[int, int]:
    for img in layers:
        return img.size
    if line_img is not None:
        return line_img.size
    raise FileNotFoundError("No base layers or line image found.")

def build_dress_image(userdata) -> Image.Image:
    profile = userdata.get("profile") or {}
    game_costume = profile.get("gameCostume") or {}

    base_rules = [
        ("color_limb", "common/skin/skin_290_{num}.png"),
        ("color_body", "common/body/body_290_{num}.png"),
    ]
    face_rules = [("color_face", "common/face/face_290_{num}.png")]
    paint_rules = [("costume_4", "paint/paint_290_{num}.png")]

    base_layers, missing = _collect_layers(
        game_costume, base_rules, allow_zero_keys=["color_limb", "color_body"]
    )
    line_img, line_missing = _load_line()
    if line_missing:
        missing.append(line_missing)
    face_layers, face_missing = _collect_layers(
        game_costume, face_rules, allow_zero_keys=["color_face"]
    )
    missing.extend(face_missing)
    paint_layers, paint_missing = _collect_layers(
        game_costume, paint_rules, allow_zero_keys=["costume_4"]
    )
    missing.extend(paint_missing)

    base_size = _resolve_base_size(base_layers, line_img)
    base = Image.new("RGBA", base_size, (0, 0, 0, 0))

    for layer in base_layers:
        _alpha_composite(base, layer)
    if line_img is not None:
        _alpha_composite(base, line_img)
    for layer in face_layers:
        _alpha_composite(base, layer)
    for layer in paint_layers:
        _alpha_composite(base, layer)

    costume_1 = _int_or_none(game_costume.get("costume_1"))
    if costume_1:
        if costume_1 == 36:
            got_dan_max = _int_or_none(game_costume.get("got_dan_max")) or 0
            filename = f"cos/cos_290_036_{got_dan_max + 6}.png"
            path = ASSETS_DIR / filename
        else:
            path = _build_path("cos/cos_290_{num}.png", costume_1)
        img = _load_image(path)
        if img is None:
            missing.append(path)
        else:
            _alpha_composite(base, img)
    else:
        part_rules = [
            ("costume_3", "body/body_290_{num}.png"),
            ("costume_2", "head/head_290_{num}.png"),
            ("costume_5", "accessories/accF_290_{num}.png"),
        ]
        part_layers, part_missing = _collect_layers(game_costume, part_rules)
        missing.extend(part_missing)
        for layer in part_layers:
            _alpha_composite(base, layer)

    if missing:
        print("missing assets:")
        for path in missing:
            print(f"  - {path}")

    return base

def draw_player_info(
    base: Image.Image,
    draw: ImageDraw.ImageDraw,
    userdata: Dict[str, Any],
    sx: float,
    sy: float,
    font: ImageFont.ImageFont,
    stroke_width: int,
    fill: Tuple[int, int, int],
    stroke_fill: Tuple[int, int, int],
    offset_xy: Tuple[int, int] = (0, 0),
    title_font: Optional[ImageFont.ImageFont] = None,
    force_no_dan: bool = False,
    plate_path_override: Optional[Path] = None,
) -> Tuple[int, int, int, int]:
    ox, oy = offset_xy
    prof = userdata.get("profile") or {}
    gc = prof.get("gameCostume") or {}

    mydon_name = str(gc.get("mydon_name", ""))
    title = str(gc.get("title", ""))
    upper_text = title or mydon_name
    lower_text = mydon_name or title
    dan_name = gc.get("dan_name", {})
    badge_path = _pick_dan_badge(dan_name)
    is_dan = not force_no_dan and bool(gc.get("is_disp_dan_on")) and bool(
        badge_path and badge_path.exists()
    )

    plate_x, plate_y = PLAYER_PLATE_XY
    plate_w, plate_h = PLAYER_PLATE_SIZE
    plate_box = (plate_x, plate_y, plate_x + plate_w, plate_y + plate_h)
    plate_box_s = _scale_box(plate_box, sx, sy)

    plate_img = None
    plate_path = plate_path_override or _pick_name_plate(gc, use_dan_plate=is_dan)
    if plate_path and plate_path.exists():
        plate_img = Image.open(plate_path).convert("RGBA")
        img_x, img_y = plate_img.size
        plate_img = plate_img.resize(
            (round(img_x / 1.607), round(img_y / 1.607)), Image.LANCZOS
        )
        offset = img_y - PLAYER_PLATE_BASE_HEIGHT
        plate_box_s = list(plate_box_s)
        plate_box_s[1] = round(plate_box_s[1] - offset / 1.607)
        plate_box_s = tuple(plate_box_s)
    plate_box_s = _offset_box(plate_box_s, ox, oy)
    if plate_img is not None:
        _paste_resize(base, plate_img, plate_box_s)
    plate_box_bounds = plate_box_s

    title_box_s = _offset_box(_scale_box(PLAYER_TITLE_BOX, sx, sy), ox, oy)
    title_font = title_font or font
    _draw_text_center(
        draw,
        title_box_s,
        upper_text,
        title_font,
        fill,
        stroke_fill,
        stroke_width,
        y_offset=0,
        use_font_metrics=True,
    )

    px1, py1, px2, py2 = plate_box_bounds
    lower_outer_h = max(1, int(round(PLAYER_PLATE_LOWER_HEIGHT * sy)))
    lower_pad = max(1, int(round(1 * sy)))
    lower_outer = (px1, py2 - lower_outer_h, px2, py2)
    lower_box_s = (
        lower_outer[0],
        lower_outer[1] + lower_pad,
        lower_outer[2],
        lower_outer[3] - lower_pad,
    )
    if lower_box_s[3] <= lower_box_s[1]:
        lower_box_s = lower_outer

    # Compose lower row first in a fixed logical canvas, then scale once.
    # This keeps text/badge layout stable and prevents visual overflow.
    row_base_w = PLAYER_PLATE_SIZE[0]
    row_base_h = 43
    row_canvas = Image.new("RGBA", (row_base_w, row_base_h), (0, 0, 0, 0))
    row_draw = ImageDraw.Draw(row_canvas)

    if is_dan:
        split_base = int(row_base_w * PLAYER_NAME_RATIO)
        name_box_base = (0, 0, split_base, row_base_h)
        dan_box_base = (split_base, 0, row_base_w, row_base_h)

        _draw_text_center(
            row_draw,
            name_box_base,
            lower_text,
            font,
            fill,
            stroke_fill,
            stroke_width,
            y_offset=NICKNAME_Y_OFFSET_WITH_DAN,
            use_font_metrics=False,
        )

        if badge_path and badge_path.exists():
            badge = Image.open(badge_path).convert("RGBA")
            badge_h = min(28, row_base_h)
            badge_y = min(row_base_h - badge_h, ((row_base_h - badge_h) // 2) + 9)
            badge_box = (split_base, badge_y, row_base_w, badge_y + badge_h)
            _paste_contain(row_canvas, badge, badge_box, pad=1)
    else:
        _draw_text_center(
            row_draw,
            (0, 0, row_base_w, row_base_h),
            lower_text,
            font,
            fill,
            stroke_fill,
            stroke_width,
            y_offset=NICKNAME_Y_OFFSET_NO_DAN,
            use_font_metrics=False,
        )

    lx1, ly1, lx2, ly2 = lower_box_s
    target_w = max(1, lx2 - lx1)
    target_h = max(1, ly2 - ly1)
    row_scaled = row_canvas.resize((target_w, target_h), Image.LANCZOS)
    base.alpha_composite(row_scaled, (lx1, ly1))

    return plate_box_bounds
