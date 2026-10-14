from __future__ import annotations



from taiko_bot.history_adapter import previous_song_map

from pathlib import Path

from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

ROOT_DIR = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

ASSETS_DIR = ROOT_DIR / "assets" / "dress"

LINE_PATH = ASSETS_DIR / "common" / "line" / "line_290.png"

NAME_PLATE_DIR = ROOT_DIR / "assets" / "name_plate"

NAME_PLATE_DANI_DIR = ROOT_DIR / "assets" / "name_plate_dani"

FONT_PATH = ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"

TITLE_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"

PLAYER_PLATE_XY = (78, 949)

PLAYER_PLATE_SIZE = (346, 56)

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
    return draw.textbbox((0, 0), text, font=font)

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
    draw.text(
        (x, y),
        str(text),
        font=font,
        fill=fill,
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

def _get_font(size_px: int) -> ImageFont.ImageFont:
    if FONT_PATH.exists():
        try:
            return ImageFont.truetype(str(FONT_PATH), size_px)
        except Exception:
            pass
    return ImageFont.load_default()

def _get_font_by_path(path: Path, size_px: int) -> ImageFont.ImageFont:
    if path.exists():
        try:
            return ImageFont.truetype(str(path), size_px)
        except Exception:
            pass
    return _get_font(size_px)

def _song_key(entry: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    try:
        return int(entry.get("song_no")), int(entry.get("level"))
    except Exception:
        return None

def _build_song_map(
    songs: Iterable[Dict[str, Any]],
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    out: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for song in songs:
        if not isinstance(song, dict):
            continue
        key = _song_key(song)
        if key is None:
            continue
        out[key] = dict(song)
    return out

def _snapshot_is_full(payload: Dict[str, Any]) -> bool:
    meta = payload.get("_meta")
    if isinstance(meta, dict):
        if meta.get("full") is True:
            return True
        if meta:
            return False
    return (
        isinstance(payload.get("songs"), list)
        and "profile" in payload
        and "achievement" in payload
    )

def _normalize_removed_key(raw: Any) -> Optional[Tuple[int, int]]:
    if isinstance(raw, (list, tuple)) and len(raw) >= 2:
        try:
            return int(raw[0]), int(raw[1])
        except Exception:
            return None
    return None

def _load_previous_song_map(
    user_id: int,
    history_snapshots,
) -> Optional[Dict[Tuple[int, int], Dict[str, Any]]]:
    snapshots = history_snapshots
    return previous_song_map(snapshots, is_full=_snapshot_is_full, build_map=_build_song_map,
                             key_for=_song_key, removed_key=_normalize_removed_key)

def _crop_with_pad(
    image: Image.Image, box: Tuple[int, int, int, int], pad: int
) -> Image.Image:
    x1, y1, x2, y2 = box
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(image.width, x2 + pad)
    y2 = min(image.height, y2 + pad)
    return image.crop((x1, y1, x2, y2))





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
    is_dan = bool(gc.get("is_disp_dan_on")) and bool(
        badge_path and badge_path.exists()
    )

    plate_x, plate_y = PLAYER_PLATE_XY
    plate_w, plate_h = PLAYER_PLATE_SIZE
    plate_box = (plate_x, plate_y, plate_x + plate_w, plate_y + plate_h)
    plate_box_s = _scale_box(plate_box, sx, sy)

    plate_img = None
    plate_path = _pick_name_plate(gc, use_dan_plate=is_dan)
    if plate_path and plate_path.exists():
        plate_img = Image.open(plate_path).convert("RGBA")
        img_x, img_y = plate_img.size
        plate_img = plate_img.resize(
            (round(img_x / 1.607), round(img_y / 1.607)), Image.LANCZOS
        )
        offset = img_y - 90
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
    lower_outer_h = max(1, int(round(45 * sy)))
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

from taiko_bot.runtime.player.client.progress_support.draw_dress import build_dress_image
