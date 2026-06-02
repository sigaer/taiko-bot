from __future__ import annotations

import json
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
from taiko_bot.settings import get_settings

from .dojo_score import (
    build_dojo_score_map,
    level_mark_to_icon,
    normalize_dojo_scores,
)
from .snapshot_history import list_snapshot_files
from .song_visibility import is_song_id_publicly_visible, is_song_publicly_visible

ROOT_DIR = Path(__file__).resolve().parents[2]
USERDATA_DIR = get_settings().userdata_dir
ASSETS_DIR = ROOT_DIR / "assets" / "dress"
OUTPUT_DIR = ROOT_DIR / "output"
TEMPLATES_DIR = ROOT_DIR / "assets" / "templates"
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"
ICONS_DIR = ROOT_DIR / "assets" / "icons"
DANI_ICONS_DIR = ICONS_DIR / "dani"
MY_DON_BG_PATH = TEMPLATES_DIR / "progress_bg.png"

LINE_PATH = ASSETS_DIR / "common" / "line" / "line_290.png"

NAME_PLATE_DIR = ROOT_DIR / "assets" / "name_plate"
NAME_PLATE_DANI_DIR = ROOT_DIR / "assets" / "name_plate_dani"
FONT_PATH = ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"
TITLE_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"
UPDATE_LEGACY_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "FZPW_GBK.ttf"
UPDATE_LEGACY_TITLE_FONT_PATH = ROOT_DIR / "assets" / "fonts" / "FOT-RodinNTLG_Pro_DB.otf"

BASE_LAYER_RULES: List[Tuple[str, str]] = [
    ("color_limb", "common/skin/skin_290_{num}.png"),
    ("color_body", "common/body/body_290_{num}.png"),
    ("color_face", "common/face/face_290_{num}.png"),
]

PART_RULES: List[Tuple[str, str]] = [
    ("costume_4", "paint/paint_290_{num}.png"),
    ("costume_3", "body/body_290_{num}.png"),
    ("costume_2", "head/head_290_{num}.png"),
    ("costume_5", "accessories/accF_290_{num}.png"),
]

# Player info layout (same base coordinate system as draw_summary.py)
PLAYER_PLATE_XY = (78, 949)
PLAYER_PLATE_SIZE = (346, 56)
PLAYER_TITLE_BOX = (78, 949, 78 + 346, 949 + 28)
PLAYER_LOWER_BOX = (78, 949 + 28, 78 + 346, 949 + 56)
PLAYER_NAME_RATIO = 0.55
NICKNAME_Y_OFFSET_WITH_DAN = 6
NICKNAME_Y_OFFSET_NO_DAN = NICKNAME_Y_OFFSET_WITH_DAN

ACH_BOX = (81, 1182, 418, 1367)
ACH_ROW_Y_FRAC = [0.15, 0.39, 0.62, 0.87]
ACH_COL_X_FRAC = [0.23, 0.55, 0.87]
ACH_NUM_W_FRAC = 0.22
ACH_NUM_H_FRAC = 0.18
ACH_ROW1_X_FRAC = 0.87
ACH_BASE_SIZE = (353, 204)
ACH_ROW_Y_ADJUST = (2, 2, 2, 0)

MY_DON_CARD_WIDTH = 432
MY_DON_CARD_RADIUS = 24
MY_DON_CARD_BG = (255, 255, 255, 242)
MY_DON_CARD_OUTLINE = (226, 231, 239, 255)
MY_DON_CARD_GRID = (236, 240, 246, 255)
MY_DON_CARD_SUB_BG = (248, 250, 253, 255)
MY_DON_CARD_TITLE = (56, 62, 77, 255)
MY_DON_CARD_TEXT = (42, 48, 64, 255)
MY_DON_CARD_MUTED = (118, 126, 142, 255)


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


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


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


def _draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill,
    stroke_fill: Optional[Tuple[int, int, int]] = None,
    stroke_width: int = 0,
) -> None:
    x, y = xy
    draw.text(
        (x, y + _ddfont_y_offset(font)),
        text,
        font=font,
        fill=fill,
        stroke_width=stroke_width,
        stroke_fill=stroke_fill,
    )


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


def _pick_achievement_bg(count_level: int) -> Optional[Path]:
    level = max(1, min(5, int(count_level)))
    path = TEMPLATES_DIR / f"bg_level_{level}_panel.png"
    if path.exists():
        return path
    return None


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


@lru_cache(maxsize=1)
def _load_song_title_map() -> Dict[int, str]:
    title_map: Dict[int, str] = {}
    if not SONG_DATA_PATH.exists():
        return title_map
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return title_map
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            song_id = int(row.get("id"))
        except Exception:
            continue
        title = row.get("song_name") or row.get("song_name_jp") or f"ID{song_id}"
        title_map[song_id] = str(title)
    return title_map


@lru_cache(maxsize=1)
def _load_song_display_map() -> Dict[int, Dict[str, Any]]:
    song_map: Dict[int, Dict[str, Any]] = {}
    if not SONG_DATA_PATH.exists():
        return song_map
    with open(SONG_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return song_map
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            song_id = int(row.get("id"))
        except Exception:
            continue
        if not is_song_publicly_visible(row):
            continue
        title = row.get("song_name") or row.get("song_name_jp") or f"ID{song_id}"
        levels: Dict[int, float] = {}
        for level in (1, 2, 3, 4, 5):
            raw = row.get(f"level_{level}")
            if raw in (None, "", "-"):
                continue
            try:
                levels[level] = float(raw)
            except Exception:
                continue
        song_map[song_id] = {
            "title": str(title),
            "levels": levels,
            "shelf_status": _safe_int(row.get("shelf_status", 0), 0),
        }
    return song_map


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


def _is_current_playable_song(song_no: int) -> bool:
    return is_song_id_publicly_visible(song_no)


def _build_my_don_song_map(
    songs: Iterable[Dict[str, Any]],
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    return {
        key: song
        for key, song in _build_song_map(songs).items()
        if _is_current_playable_song(key[0])
    }


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
) -> Optional[Dict[Tuple[int, int], Dict[str, Any]]]:
    history_dir = USERDATA_DIR / str(user_id)
    if not history_dir.exists():
        return None
    history_files = list_snapshot_files(history_dir)
    if len(history_files) < 2:
        return None

    song_states: List[List[Dict[str, Any]]] = []
    current_songs: List[Dict[str, Any]] = []
    for history_file in history_files:
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        if _snapshot_is_full(payload) or not song_states:
            raw_songs = payload.get("songs") or []
            current_songs = [dict(song) for song in raw_songs if isinstance(song, dict)]
        else:
            song_map = _build_song_map(current_songs)
            for song in payload.get("songs") or []:
                if not isinstance(song, dict):
                    continue
                key = _song_key(song)
                if key is None:
                    continue
                song_map[key] = dict(song)
            for raw_key in payload.get("songs_removed") or []:
                key = _normalize_removed_key(raw_key)
                if key is None:
                    continue
                song_map.pop(key, None)
            current_songs = list(song_map.values())

        song_states.append([dict(song) for song in current_songs])

    if len(song_states) < 2:
        return None
    return _build_song_map(song_states[-2])


def _load_previous_dojo_state(user_id: int) -> Optional[Dict[str, Any]]:
    history_dir = USERDATA_DIR / str(user_id)
    if not history_dir.exists():
        return None
    history_files = list_snapshot_files(history_dir)
    if len(history_files) < 2:
        return None

    dojo_states: List[Dict[str, Any]] = []
    current_dojo: Optional[Dict[str, Any]] = None
    for history_file in history_files:
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        if _snapshot_is_full(payload):
            if "dojo" in payload:
                current_dojo = normalize_dojo_scores(payload.get("dojo") or {})
        elif "dojo" in payload:
            current_dojo = normalize_dojo_scores(payload.get("dojo") or {})

        if current_dojo is not None:
            dojo_states.append(json.loads(json.dumps(current_dojo, ensure_ascii=False)))

    if len(dojo_states) < 2:
        return None
    return dojo_states[-2]


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: int
) -> str:
    if max_width <= 0:
        return ""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "..."
    if draw.textlength(ellipsis, font=font) > max_width:
        return ""
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        candidate = text[:mid] + ellipsis
        if draw.textlength(candidate, font=font) <= max_width:
            left = mid + 1
        else:
            right = mid
    return text[: max(0, right - 1)] + ellipsis


def _load_icon_sized(path: Path, size: Tuple[int, int]) -> Optional[Image.Image]:
    if not path.exists():
        return None
    try:
        return Image.open(path).convert("RGBA").resize(size, Image.LANCZOS)
    except Exception:
        return None


def _sorted_changed_entries(
    prev_map: Dict[Tuple[int, int], Dict[str, Any]],
    curr_map: Dict[Tuple[int, int], Dict[str, Any]],
) -> List[Tuple[Tuple[int, int], Dict[str, Any], Dict[str, Any]]]:
    changed: List[Tuple[Tuple[int, int], Dict[str, Any], Dict[str, Any]]] = []
    for key, curr in curr_map.items():
        prev = prev_map.get(key)
        if prev != curr:
            changed.append((key, prev or {}, curr))
    changed.sort(key=lambda item: (-item[0][1], item[0][0]))
    return changed


def _difficulty_group(level: int) -> int:
    if level <= 0:
        return 0
    return min(level, 4)


def _song_diff_sort_key(item: Dict[str, Any]) -> Tuple[int, float, int, int]:
    level = _safe_int(item.get("level"), 0)
    star_value = float(item.get("star_value", 0.0) or 0.0)
    song_no = _safe_int(item.get("song_no"), 0)
    return (_difficulty_group(level), star_value, level, -song_no)


def _combined_low_miss_count(entry: Dict[str, Any]) -> int:
    ok_cnt = _safe_int(entry.get("ok_cnt"), 0)
    ng_cnt = _safe_int(entry.get("ng_cnt", entry.get("bad_cnt")), 0)
    return ok_cnt + ng_cnt


@lru_cache(maxsize=1)
def _load_dojo_grade_display_map() -> Dict[int, Dict[str, Any]]:
    payload = json.loads(
        (ROOT_DIR / "songs" / "grade_dojo_nijiiro_2025_simple.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        idx + 1: grade
        for idx, grade in enumerate(payload.get("grades") or [])
        if isinstance(grade, dict)
    }


def _collect_change_sections(
    prev_map: Dict[Tuple[int, int], Dict[str, Any]],
    curr_map: Dict[Tuple[int, int], Dict[str, Any]],
    item_limit: Optional[int] = 5,
    include_score_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    song_map = _load_song_display_map()
    changed = _sorted_changed_entries(prev_map, curr_map)

    def make_item(song_no: int, level: int) -> Dict[str, Any]:
        song_meta = song_map.get(song_no, {})
        return {
            "song_no": song_no,
            "level": level,
            "title": song_meta.get("title", f"ID{song_no}"),
            "star_value": float((song_meta.get("levels") or {}).get(level, 0.0) or 0.0),
        }

    def has_dondaful(prev: Dict[str, Any], curr: Dict[str, Any]) -> bool:
        return (
            _to_int(prev.get("dondaful_combo_cnt", 0), 0) > 0
            or _to_int(curr.get("dondaful_combo_cnt", 0), 0) > 0
        )

    def has_fc_or_dondaful(prev: Dict[str, Any], curr: Dict[str, Any]) -> bool:
        return (
            _to_int(prev.get("full_combo_cnt", 0), 0) > 0
            or _to_int(curr.get("full_combo_cnt", 0), 0) > 0
            or has_dondaful(prev, curr)
        )

    one_ok_keys = {
        key
        for key, prev, curr in changed
        if _combined_low_miss_count(curr) == 1
        and _combined_low_miss_count(prev) != 1
        and not has_dondaful(prev, curr)
    }
    # 优先级：全良 > 全连 > 1可 > 单可 > 1不可/过关。
    # 全良命中后不再重复进入其后分类；1不可与过关同优先级。
    dondaful_keys = {
        key
        for key, prev, curr in changed
        if _to_int(prev.get("dondaful_combo_cnt", 0)) == 0
        and _to_int(curr.get("dondaful_combo_cnt", 0)) >= 1
    }
    full_combo_keys = {
        key
        for key, prev, curr in changed
        if key not in dondaful_keys
        and _to_int(prev.get("full_combo_cnt", 0)) == 0
        and _to_int(curr.get("full_combo_cnt", 0)) >= 1
    }
    clear_keys = {
        key
        for key, prev, curr in changed
        if key not in dondaful_keys
        and key not in full_combo_keys
        and _to_int(prev.get("clear_cnt", 0)) == 0
        and _to_int(curr.get("clear_cnt", 0)) >= 1
    }

    left_rules = [
        (
            "全良(0->1)",
            ICONS_DIR / "crown" / "dondaful.png",
            lambda key, prev, curr: key in dondaful_keys,
        ),
        (
            "全连(0->1)",
            ICONS_DIR / "crown" / "full.png",
            lambda key, prev, curr: key in full_combo_keys,
        ),
        (
            "1可",
            ICONS_DIR / "crown" / "clear.png",
            lambda key, prev, curr: key in one_ok_keys,
        ),
        (
            "单可",
            ICONS_DIR / "crown" / "clear.png",
            lambda key, prev, curr: key not in dondaful_keys
            and not has_dondaful(prev, curr)
            and key not in one_ok_keys
            and _combined_low_miss_count(curr) < 10
            and _combined_low_miss_count(prev) >= 10,
        ),
        (
            "过关(0->1)",
            ICONS_DIR / "crown" / "clear.png",
            lambda key, prev, curr: key in clear_keys,
        ),
        (
            "刷新最高分",
            None,
            lambda key, prev, curr: include_score_refresh
            and key not in dondaful_keys
            and key not in full_combo_keys
            and key not in clear_keys
            and _to_int(curr.get("high_score", 0)) > _to_int(prev.get("high_score", 0)),
        ),
        (
            "1不可",
            ICONS_DIR / "crown" / "clear.png",
            lambda key, prev, curr: key not in dondaful_keys
            and not has_fc_or_dondaful(prev, curr)
            and key not in one_ok_keys
            and not (
                _combined_low_miss_count(curr) < 10
                and _combined_low_miss_count(prev) >= 10
            )
            and _to_int(curr.get("ng_cnt", curr.get("bad_cnt", -1)), -1) == 1
            and _to_int(prev.get("ng_cnt", prev.get("bad_cnt", -1)), -1) != 1,
        ),
    ]

    left_sections: List[Dict[str, Any]] = []
    for label, icon_path, rule in left_rules:
        items: List[Dict[str, Any]] = []
        for key, prev, curr in changed:
            if not rule(key, prev, curr):
                continue
            song_no, level = key
            items.append(make_item(song_no, level))
        if items:
            items.sort(key=_song_diff_sort_key, reverse=True)
            limited_items = items if item_limit is None else items[:item_limit]
            left_sections.append(
                {"label": label, "icon_path": icon_path, "items": limited_items}
            )

    rank_map = {8: "取得极", 7: "取得紫雅", 6: "取得粉雅", 5: "取得金雅"}
    right_sections: List[Dict[str, Any]] = []
    for rank_value in (8, 7, 6, 5):
        items: List[Dict[str, Any]] = []
        for key, prev, curr in changed:
            prev_rank = _to_int(prev.get("best_score_rank", 0))
            curr_rank = _to_int(curr.get("best_score_rank", 0))
            if curr_rank == rank_value and curr_rank > prev_rank:
                song_no, level = key
                items.append(make_item(song_no, level))
        if items:
            items.sort(key=_song_diff_sort_key, reverse=True)
            limited_items = items if item_limit is None else items[:item_limit]
            right_sections.append(
                {
                    "label": rank_map[rank_value],
                    "icon_path": ICONS_DIR / "rank" / f"{rank_value}.png",
                    "items": limited_items,
                }
            )

    return left_sections, right_sections


def _dojo_item_sort_key(item: Dict[str, Any]) -> Tuple[int, int]:
    return (_to_int(item.get("sort_dan_id"), 0), _to_int(item.get("sort_song_index"), 0))


def _collect_dojo_change_sections(
    previous_dojo: Dict[str, Any],
    current_dojo: Dict[str, Any],
    item_limit: Optional[int] = 5,
    include_score_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    prev_map = build_dojo_score_map(previous_dojo)
    curr_map = build_dojo_score_map(current_dojo)
    grade_display_map = _load_dojo_grade_display_map()

    def make_grade_item(dan_id: int, level_mark: int, grade_name: str) -> Dict[str, Any]:
        return {
            "title": grade_name,
            "line_icon_path": DANI_ICONS_DIR / f"{level_mark_to_icon(level_mark)}.png",
            "sort_dan_id": dan_id,
            "sort_song_index": 0,
        }

    def make_song_item(dan_id: int, song_index: int, grade_name: str) -> Dict[str, Any]:
        grade_meta = grade_display_map.get(dan_id) or {}
        songs = grade_meta.get("songs") or []
        song_meta = songs[song_index - 1] if song_index - 1 < len(songs) else {}
        title = str(song_meta.get("title") or f"第{song_index}曲")
        difficulty = _to_int(song_meta.get("difficulty"), 0)
        item = {
            "title": f"{grade_name} 第{song_index}曲·{title}",
            "sort_dan_id": dan_id,
            "sort_song_index": song_index,
        }
        if difficulty > 0:
            item["line_icon_path"] = ICONS_DIR / "diff" / f"{difficulty}.png"
        return item

    mark_sections = [
        (6, "取得全良金合格"),
        (5, "取得全连金合格"),
        (4, "取得金合格"),
        (3, "取得全良赤合格"),
        (2, "取得全连赤合格"),
        (1, "取得赤合格"),
    ]
    left_sections: List[Dict[str, Any]] = []
    for target_mark, label in mark_sections:
        items: List[Dict[str, Any]] = []
        for dan_id, curr in curr_map.items():
            prev = prev_map.get(dan_id) or {}
            curr_mark = _to_int(curr.get("level_mark"), -1)
            prev_mark = _to_int(prev.get("level_mark"), -1)
            if curr_mark == target_mark and curr_mark > prev_mark:
                items.append(make_grade_item(dan_id, target_mark, str(curr.get("grade") or f"段位{dan_id}")))
        if items:
            items.sort(key=_dojo_item_sort_key, reverse=True)
            limited_items = items if item_limit is None else items[:item_limit]
            left_sections.append(
                {
                    "label": label,
                    "icon_path": DANI_ICONS_DIR / f"{level_mark_to_icon(target_mark)}.png",
                    "items": limited_items,
                }
            )

    reached_items: List[Dict[str, Any]] = []
    for dan_id, curr in curr_map.items():
        prev = prev_map.get(dan_id) or {}
        prev_songs = prev.get("songs") or []
        curr_songs = curr.get("songs") or []
        grade_name = str(curr.get("grade") or f"段位{dan_id}")
        for song_index, curr_song in enumerate(curr_songs, start=1):
            prev_song = prev_songs[song_index - 1] if song_index - 1 < len(prev_songs) else {}
            prev_reached = bool(isinstance(prev_song, dict) and prev_song.get("reached"))
            curr_reached = bool(curr_song.get("reached"))
            if curr_reached and not prev_reached:
                reached_items.append(make_song_item(dan_id, song_index, grade_name))
    if reached_items:
        reached_items.sort(key=_dojo_item_sort_key, reverse=True)
        limited_items = reached_items if item_limit is None else reached_items[:item_limit]
        left_sections.append(
            {
                "label": "到达新曲",
                "icon_path": None,
                "items": limited_items,
            }
        )

    right_sections: List[Dict[str, Any]] = []
    if include_score_refresh:
        refreshed_items: List[Dict[str, Any]] = []
        for dan_id, curr in curr_map.items():
            prev = prev_map.get(dan_id) or {}
            prev_songs = prev.get("songs") or []
            curr_songs = curr.get("songs") or []
            grade_name = str(curr.get("grade") or f"段位{dan_id}")
            for song_index, curr_song in enumerate(curr_songs, start=1):
                prev_song = prev_songs[song_index - 1] if song_index - 1 < len(prev_songs) else {}
                curr_score = _to_int(
                    ((curr_song.get("highscore") or {}).get("score")),
                    0,
                )
                prev_score = _to_int(
                    (((prev_song or {}).get("highscore") or {}).get("score")),
                    0,
                )
                if curr_score > prev_score:
                    refreshed_items.append(make_song_item(dan_id, song_index, grade_name))
        if refreshed_items:
            refreshed_items.sort(key=_dojo_item_sort_key, reverse=True)
            limited_items = refreshed_items if item_limit is None else refreshed_items[:item_limit]
            right_sections.append(
                {
                    "label": "段位内刷新最高分",
                    "icon_path": None,
                    "items": limited_items,
                }
            )

    return left_sections, right_sections


def _render_change_column(
    title: str,
    sections: List[Dict[str, Any]],
    empty_text: str,
    width: int = 540,
    font_path: Optional[Path] = None,
) -> Image.Image:
    pad = 16
    title_h = 42
    section_h = 32
    row_h = 30
    row_gap = 4
    block_gap = 8

    height = pad * 2 + title_h
    if not sections:
        height += 44
    else:
        for section in sections:
            height += (
                section_h
                + len(section.get("items", [])) * (row_h + row_gap)
                + block_gap
            )
        height -= block_gap

    panel = Image.new("RGBA", (width, max(height, 120)), (255, 255, 255, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(
        (0, 0, width - 1, panel.height - 1),
        radius=14,
        fill=(248, 248, 248, 235),
        outline=(218, 218, 218, 255),
        width=2,
    )

    use_font_path = font_path or FONT_PATH
    title_font = _get_font_by_path(use_font_path, 24)
    section_font = _get_font_by_path(use_font_path, 19)
    item_font = _get_font_by_path(use_font_path, 18)
    _draw_text(draw, (pad, pad), title, title_font, (25, 25, 25, 255))

    y = pad + title_h
    if not sections:
        _draw_text(draw, (pad, y), empty_text, section_font, (80, 80, 80, 255))
        return panel

    for section in sections:
        icon_path = section.get("icon_path")
        icon = (
            _load_icon_sized(icon_path, (24, 24))
            if isinstance(icon_path, Path)
            else None
        )
        if icon is not None:
            panel.alpha_composite(icon, (pad, y + 2))
            label_x = pad + 30
        else:
            label_x = pad + 4
        _draw_text(
            draw,
            (label_x, y + 1),
            section["label"],
            section_font,
            (40, 40, 40, 255),
        )
        y += section_h

        for item in section.get("items", []):
            line_icon_path = item.get("line_icon_path")
            if isinstance(line_icon_path, Path):
                diff_icon = _load_icon_sized(line_icon_path, (20, 20))
            else:
                level = _to_int(item.get("level"), 0)
                diff_icon = _load_icon_sized(ICONS_DIR / "diff" / f"{level}.png", (20, 20))
            if diff_icon is not None:
                panel.alpha_composite(diff_icon, (pad + 4, y + 4))
            text_x = pad + 30
            max_text_w = width - text_x - pad
            title_text = _truncate_text(
                draw, str(item.get("title", "")), item_font, max_text_w
            )
            _draw_text(draw, (text_x, y + 2), title_text, item_font, (35, 35, 35, 255))
            y += row_h + row_gap

        y += block_gap

    return panel


def _compose_columns(
    columns: List[Image.Image], gap: int = 16, pad: int = 10
) -> Image.Image:
    total_width = sum(col.width for col in columns) + gap * (len(columns) - 1) + pad * 2
    total_height = max(col.height for col in columns) + pad * 2
    canvas = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    x = pad
    for col in columns:
        y = pad
        canvas.alpha_composite(col, (x, y))
        x += col.width + gap
    return canvas


def _render_my_don_base_panel(
    user_id: int,
    userdata: Dict[str, Any],
    font_path: Optional[Path] = None,
    title_font_path: Optional[Path] = None,
) -> Image.Image:
    info_canvas = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    info_draw = ImageDraw.Draw(info_canvas)

    use_font_path = font_path or FONT_PATH
    use_title_font_path = title_font_path or TITLE_FONT_PATH
    font_title = _get_font_by_path(use_font_path, 16)
    title_font = _get_font_by_path(use_title_font_path, 16)
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

    achievement_grid_img = _render_my_don_achievement_grid_panel(
        userdata=userdata,
        font_path=use_font_path,
    )
    rank_summary_img = _render_my_don_rank_summary_panel(
        userdata=userdata,
        font_path=use_font_path,
    )

    target_title_w = int(achievement_grid_img.width * 0.94)
    if title_img.width > 0 and title_img.width < target_title_w:
        scale = target_title_w / title_img.width
        title_img = title_img.resize(
            (target_title_w, max(1, int(title_img.height * scale))),
            Image.LANCZOS,
        )

    dress_img = build_dress_image(user_id)

    parts = [title_img, dress_img, achievement_grid_img, rank_summary_img]
    width = max(img.width for img in parts)
    gap = 12
    pad = 8
    height = sum(img.height for img in parts) + gap * (len(parts) - 1) + pad * 2
    content_img = Image.new("RGBA", (width + pad * 2, height), (255, 255, 255, 0))

    y = pad
    for img in parts:
        x = (content_img.width - img.width) // 2
        content_img.alpha_composite(img, (x, y))
        y += img.height + gap

    bg_pad = 24
    final_w = content_img.width + bg_pad * 2
    final_h = content_img.height + bg_pad * 2
    final_img = Image.new("RGBA", (final_w, final_h), (255, 255, 255, 255))
    if MY_DON_BG_PATH.exists():
        try:
            bg = Image.open(MY_DON_BG_PATH).convert("RGBA")
            bg = bg.resize((final_w, final_h), Image.LANCZOS)
            final_img.alpha_composite(bg, (0, 0))
        except Exception:
            pass
    final_img.alpha_composite(content_img, (bg_pad, bg_pad))
    return final_img


def _crop_with_pad(
    image: Image.Image, box: Tuple[int, int, int, int], pad: int
) -> Image.Image:
    x1, y1, x2, y2 = box
    x1 = max(0, x1 - pad)
    y1 = max(0, y1 - pad)
    x2 = min(image.width, x2 + pad)
    y2 = min(image.height, y2 + pad)
    return image.crop((x1, y1, x2, y2))


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


def build_dress_image(user_id: int) -> Image.Image:
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")

    with open(userdata_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)

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


def draw_achievement_overview(
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
) -> Tuple[int, int, int, int]:
    ox, oy = offset_xy
    ach = userdata.get("achievement", {}) or {}
    ary_rank = ach.get("ary_score_rank_count", [0] * 7) or [0] * 7
    ary_crown = ach.get("ary_crown_count", [0] * 3) or [0] * 3
    count_level = _safe_int(ach.get("count_level", 1), 1)

    ach_box_s = _offset_box(_scale_box(ACH_BOX, sx, sy), ox, oy)
    ax1, ay1, ax2, ay2 = ach_box_s
    aw, ah = (ax2 - ax1), (ay2 - ay1)

    bg_path = _pick_achievement_bg(count_level)
    if bg_path:
        bg = Image.open(bg_path).convert("RGBA")
        bg = bg.resize((aw, ah), Image.LANCZOS)
        base.alpha_composite(bg, (ax1, ay1))

    num_w = int(aw * ACH_NUM_W_FRAC)
    num_h = int(ah * ACH_NUM_H_FRAC)

    y = ay1 + int(ah * ACH_ROW_Y_FRAC[0])
    x = ax1 + int(aw * ACH_ROW1_X_FRAC)
    box = (x - num_w // 2, y - num_h // 2, x + num_w // 2, y + num_h // 2)
    _draw_text_center(
        draw, box, str(_safe_int(ary_rank[6])), font, fill, stroke_fill, stroke_width
    )

    y = ay1 + int(ah * ACH_ROW_Y_FRAC[1])
    for i, v in enumerate(ary_rank[3:6]):
        cx = ax1 + int(aw * ACH_COL_X_FRAC[i])
        box = (cx - num_w // 2, y - num_h // 2, cx + num_w // 2, y + num_h // 2)
        _draw_text_center(
            draw, box, str(_safe_int(v)), font, fill, stroke_fill, stroke_width
        )

    y = ay1 + int(ah * ACH_ROW_Y_FRAC[2])
    for i, v in enumerate(ary_rank[0:3]):
        cx = ax1 + int(aw * ACH_COL_X_FRAC[i])
        box = (cx - num_w // 2, y - num_h // 2, cx + num_w // 2, y + num_h // 2)
        _draw_text_center(
            draw, box, str(_safe_int(v)), font, fill, stroke_fill, stroke_width
        )

    y = ay1 + int(ah * ACH_ROW_Y_FRAC[3])
    for i, v in enumerate(ary_crown[0:3]):
        cx = ax1 + int(aw * ACH_COL_X_FRAC[i])
        box = (cx - num_w // 2, y - num_h // 2, cx + num_w // 2, y + num_h // 2)
        _draw_text_center(
            draw, box, str(_safe_int(v)), font, fill, stroke_fill, stroke_width
        )

    return ach_box_s


def render_achievement_panel(
    userdata: Dict[str, Any],
    base_font_size: int = 20,
    base_stroke_width: int = 2,
    fill: Tuple[int, int, int] = (255, 255, 255),
    stroke_fill: Tuple[int, int, int] = (0, 0, 0),
    font_path: Optional[Path] = None,
) -> Image.Image:
    ach = userdata.get("achievement", {}) or {}
    ary_rank = ach.get("ary_score_rank_count", [0] * 7) or [0] * 7
    ary_crown = ach.get("ary_crown_count", [0] * 3) or [0] * 3
    count_level = _safe_int(ach.get("count_level", 1), 1)

    bg_path = _pick_achievement_bg(count_level)
    if bg_path:
        panel = Image.open(bg_path).convert("RGBA")
    else:
        panel = Image.new("RGBA", ACH_BASE_SIZE, (0, 0, 0, 0))

    target_w, target_h = panel.size
    base_w, base_h = ACH_BASE_SIZE
    sx = target_w / base_w
    sy = target_h / base_h

    font_size = max(10, int(round(base_font_size * (sx + sy) / 2)))
    stroke_width = max(1, int(round(base_stroke_width * (sx + sy) / 2)))
    font = _get_font_by_path(font_path or FONT_PATH, font_size)
    draw = ImageDraw.Draw(panel)

    base_num_w = base_w * ACH_NUM_W_FRAC
    base_num_h = base_h * ACH_NUM_H_FRAC
    num_w = int(round(base_num_w * sx))
    num_h = int(round(base_num_h * sy))

    row1_y = int(round(base_h * ACH_ROW_Y_FRAC[0] * sy)) - 5 + ACH_ROW_Y_ADJUST[0]
    row2_y = int(round(base_h * ACH_ROW_Y_FRAC[1] * sy)) - 5 + ACH_ROW_Y_ADJUST[1]
    row3_y = int(round(base_h * ACH_ROW_Y_FRAC[2] * sy)) + ACH_ROW_Y_ADJUST[2]
    row4_y = int(round(base_h * ACH_ROW_Y_FRAC[3] * sy)) + ACH_ROW_Y_ADJUST[3]

    row1_x = int(round(base_w * ACH_ROW1_X_FRAC * sx))
    col_x = [int(round(base_w * f * sx)) for f in ACH_COL_X_FRAC]

    box = (
        row1_x - num_w // 2,
        row1_y - num_h // 2,
        row1_x + num_w // 2,
        row1_y + num_h // 2,
    )
    _draw_text_center(
        draw,
        box,
        str(_safe_int(ary_rank[6])),
        font,
        fill,
        stroke_fill,
        stroke_width,
    )

    for i, v in enumerate(ary_rank[3:6]):
        cx = col_x[i]
        box = (
            cx - num_w // 2,
            row2_y - num_h // 2,
            cx + num_w // 2,
            row2_y + num_h // 2,
        )
        _draw_text_center(
            draw,
            box,
            str(_safe_int(v)),
            font,
            fill,
            stroke_fill,
            stroke_width,
        )

    row4_y = row4_y - max(1, int(round(font_size / 2)))
    row3_y = int(round((row2_y + row4_y) / 2))
    for i, v in enumerate(ary_rank[0:3]):
        cx = col_x[i]
        box = (
            cx - num_w // 2,
            row3_y - num_h // 2,
            cx + num_w // 2,
            row3_y + num_h // 2,
        )
        _draw_text_center(
            draw,
            box,
            str(_safe_int(v)),
            font,
            fill,
            stroke_fill,
            stroke_width,
        )

    for i, v in enumerate(ary_crown[0:3]):
        cx = col_x[i]
        box = (
            cx - num_w // 2,
            row4_y - num_h // 2,
            cx + num_w // 2,
            row4_y + num_h // 2,
        )
        _draw_text_center(
            draw,
            box,
            str(_safe_int(v)),
            font,
            fill,
            stroke_fill,
            stroke_width,
        )

    return panel


def _wrap_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int = 2,
) -> List[str]:
    if max_width <= 0 or max_lines <= 0:
        return []

    source = str(text or "").replace("\r", "")
    if not source:
        return [""]

    lines: List[str] = []
    for raw_line in source.split("\n") or [""]:
        rest = raw_line
        if not rest:
            lines.append("")
            if len(lines) >= max_lines:
                break
            continue

        while rest:
            if draw.textlength(rest, font=font) <= max_width:
                lines.append(rest)
                break

            cut = 1
            for idx in range(1, len(rest) + 1):
                if draw.textlength(rest[:idx], font=font) > max_width:
                    cut = max(1, idx - 1)
                    break
            current = rest[:cut]
            rest = rest[cut:]

            if len(lines) >= max_lines - 1:
                lines.append(_truncate_text(draw, current + rest, font, max_width))
                return lines[:max_lines]
            lines.append(current)

        if len(lines) >= max_lines:
            break

    return lines[:max_lines] or [""]


def _draw_text_lines_center(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    lines: List[str],
    font: ImageFont.ImageFont,
    fill,
    stroke_fill: Optional[Tuple[int, int, int]] = None,
    stroke_width: int = 0,
    line_gap: int = 4,
) -> None:
    if not lines:
        return

    x1, y1, x2, y2 = box
    metrics: List[Tuple[str, int, int]] = []
    for line in lines:
        bb = _text_bbox(draw, line or " ", font)
        metrics.append((line, bb[2] - bb[0], bb[3] - bb[1]))

    total_h = sum(item[2] for item in metrics) + line_gap * max(0, len(metrics) - 1)
    y = y1 + max(0, (y2 - y1 - total_h) // 2)
    for line, width, height in metrics:
        x = x1 + max(0, (x2 - x1 - width) // 2)
        _draw_text(
            draw,
            (x, y),
            line,
            font,
            fill,
            stroke_fill=stroke_fill,
            stroke_width=stroke_width,
        )
        y += height + line_gap


def _render_my_don_card(width: int, height: int) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    panel = Image.new("RGBA", (width, height), (255, 255, 255, 0))
    draw = ImageDraw.Draw(panel)
    draw.rounded_rectangle(
        (0, 0, width - 1, height - 1),
        radius=MY_DON_CARD_RADIUS,
        fill=MY_DON_CARD_BG,
        outline=MY_DON_CARD_OUTLINE,
        width=2,
    )
    return panel, draw


def _resolve_my_don_panel_level(
    userdata: Dict[str, Any], songs: Iterable[Dict[str, Any]]
) -> int:
    ach = userdata.get("achievement") or {}
    count_level = _safe_int(ach.get("count_level", 0), 0)
    if 1 <= count_level <= 5:
        return count_level

    available_levels = [
        _to_int(song.get("level", 0))
        for song in songs
        if (
            isinstance(song, dict)
            and 1 <= _to_int(song.get("level", 0)) <= 5
            and _is_current_playable_song(_to_int(song.get("song_no", 0), 0))
        )
    ]
    if available_levels:
        return max(available_levels)
    return 5


def _new_my_don_level_stats() -> Dict[str, Any]:
    return {
        "played": 0,
        "clear": 0,
        "full": 0,
        "dondaful": 0,
        "blank": 0,
        "ranks": {rank_value: 0 for rank_value in range(2, 9)},
    }


def _merge_my_don_level_stats(*level_stats: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    merged = _new_my_don_level_stats()
    for item in level_stats:
        if not isinstance(item, dict):
            continue
        for key in ("played", "clear", "full", "dondaful", "blank"):
            merged[key] += _safe_int(item.get(key, 0), 0)
        ranks = item.get("ranks") or {}
        if not isinstance(ranks, dict):
            continue
        for rank_value in range(2, 9):
            merged["ranks"][rank_value] += _safe_int(ranks.get(rank_value, 0), 0)
    return merged


def _resolve_my_don_rank_counts(
    userdata: Dict[str, Any],
    panel_level: int,
    panel_stats: Dict[str, Any],
) -> Dict[str, Any]:
    _ = (userdata, panel_level)
    ranks = {
        rank_value: _safe_int((panel_stats.get("ranks") or {}).get(rank_value, 0), 0)
        for rank_value in range(2, 9)
    }
    blank = max(0, _safe_int(panel_stats.get("played", 0), 0) - sum(ranks.values()))
    return {"blank": blank, "ranks": ranks}


def _collect_my_don_song_stats(
    songs: Iterable[Dict[str, Any]],
) -> Dict[int, Dict[str, Any]]:
    stats: Dict[int, Dict[str, Any]] = {
        level: _new_my_don_level_stats()
        for level in range(1, 6)
    }

    best_song_map = _build_my_don_song_map(songs)
    for song in best_song_map.values():
        level = _to_int(song.get("level", 0))
        if level not in stats:
            continue

        level_stats = stats[level]
        level_stats["played"] += 1

        has_dondaful = _to_int(song.get("dondaful_combo_cnt", 0)) > 0
        has_full = _to_int(song.get("full_combo_cnt", 0)) > 0
        has_clear = _to_int(song.get("clear_cnt", 0)) > 0

        if has_dondaful:
            level_stats["dondaful"] += 1
        elif has_full:
            level_stats["full"] += 1
        elif has_clear:
            level_stats["clear"] += 1

        rank_value = _to_int(song.get("best_score_rank", 0))
        if 2 <= rank_value <= 8:
            level_stats["ranks"][rank_value] += 1
        else:
            level_stats["blank"] += 1

    return stats


def _resolve_my_don_title_levels(panel_level: int) -> Tuple[int, ...]:
    if panel_level == 5:
        return (4, 5)
    return (panel_level,)


def _paste_my_don_title_icons(
    panel: Image.Image,
    panel_level: int,
    title_icon_box: Tuple[int, int, int, int],
) -> int:
    title_levels = _resolve_my_don_title_levels(panel_level)
    x1, y1, x2, y2 = title_icon_box
    icon_w = x2 - x1
    step = max(1, icon_w - 8)
    right_edge = x2

    for index, level in enumerate(title_levels):
        diff_icon = _load_image(ICONS_DIR / "diff" / f"{level}.png")
        if diff_icon is None:
            continue
        icon_x = x1 + index * step
        icon_box = (icon_x, y1, icon_x + icon_w, y2)
        _paste_contain(panel, diff_icon, icon_box, pad=2)
        right_edge = max(right_edge, icon_box[2])

    return right_edge


def _sum_my_don_total_stage_count(songs: Iterable[Dict[str, Any]]) -> int:
    return sum(
        _to_int(song.get("stage_cnt", 0))
        for song in songs
        if isinstance(song, dict)
    )


def _pick_highest_rating_song_name(songs: Iterable[Dict[str, Any]]) -> Optional[str]:
    best_song_map = _build_my_don_song_map(songs)
    records = list(best_song_map.values())
    if not records:
        return None

    try:
        from .score_calculator import compute_all_from_userdata_records

        results = compute_all_from_userdata_records(records)
    except Exception:
        results = []

    if results:
        top = max(results, key=lambda item: float(getattr(item, "AI_rating", 0.0) or 0.0))
        song_name = str(getattr(top, "song_name", "") or "").strip()
        if song_name:
            return song_name

    best_record = max(records, key=lambda song: _to_int(song.get("high_score", 0)))
    title_map = _load_song_title_map()
    return title_map.get(_to_int(best_record.get("song_no", 0)))


def _render_my_don_achievement_grid_panel(
    userdata: Dict[str, Any],
    font_path: Optional[Path] = None,
) -> Image.Image:
    width = MY_DON_CARD_WIDTH
    pad = 18
    title_h = 32
    header_h = 42
    row_h = 46
    row_gap = 8
    left_w = 54
    col_gap = 8
    cell_w = (width - pad * 2 - left_w - col_gap * 4) // 5
    value_cell_expand = 3
    grid_h = header_h + row_h * 3 + row_gap * 2
    height = pad * 2 + title_h + 10 + grid_h

    panel, draw = _render_my_don_card(width, height)
    title_font = _get_font_by_path(font_path or FONT_PATH, 22)
    value_font = _get_font_by_path(font_path or FONT_PATH, 24)

    _draw_text(
        draw,
        (pad, pad - 2),
        "曲目成就取得情况",
        title_font,
        MY_DON_CARD_TITLE,
    )

    stats = _collect_my_don_song_stats(userdata.get("songs") or [])
    header_y = pad + title_h + 10
    body_y = header_y + header_h
    crown_rows = [
        ("clear", ICONS_DIR / "crown" / "clear.png", (241, 248, 249, 255)),
        ("full", ICONS_DIR / "crown" / "full.png", (252, 247, 232, 255)),
        ("dondaful", ICONS_DIR / "crown" / "dondaful.png", (252, 245, 229, 255)),
    ]

    header_box = (pad + left_w, header_y, width - pad, header_y + header_h)
    draw.rounded_rectangle(
        header_box,
        radius=16,
        fill=MY_DON_CARD_SUB_BG,
        outline=MY_DON_CARD_GRID,
        width=1,
    )

    for idx, level in enumerate(range(1, 6)):
        cell_x = pad + left_w + idx * (cell_w + col_gap)
        icon_box = (cell_x, header_y + 4, cell_x + cell_w, header_y + header_h - 4)
        diff_icon = _load_image(ICONS_DIR / "diff" / f"{level}.png")
        if diff_icon is not None:
            _paste_contain(panel, diff_icon, icon_box, pad=3)

    for row_idx, (metric_key, icon_path, fill_color) in enumerate(crown_rows):
        y = body_y + row_idx * (row_h + row_gap)
        icon_box = (pad, y + 2, pad + left_w - 6, y + row_h - 2)
        row_bg_box = (pad + left_w, y, width - pad, y + row_h)
        draw.rounded_rectangle(
            row_bg_box,
            radius=16,
            fill=fill_color,
            outline=MY_DON_CARD_GRID,
            width=1,
        )

        crown_icon = _load_image(icon_path)
        if crown_icon is not None:
            _paste_contain(panel, crown_icon, icon_box, pad=2)

        for col_idx, level in enumerate(range(1, 6)):
            cell_x = pad + left_w + col_idx * (cell_w + col_gap)
            cell_box = (
                max(pad + left_w, cell_x - value_cell_expand),
                y,
                min(width - pad, cell_x + cell_w + value_cell_expand),
                y + row_h,
            )
            draw.rounded_rectangle(
                cell_box,
                radius=14,
                fill=(255, 255, 255, 210),
                outline=MY_DON_CARD_GRID,
                width=1,
            )
            _draw_text_center(
                draw,
                cell_box,
                str(stats[level][metric_key]),
                value_font,
                MY_DON_CARD_TEXT,
                MY_DON_CARD_BG[:3],
                0,
                y_offset=-1,
                use_font_metrics=True,
            )

    return panel


def _render_my_don_rank_summary_panel(
    userdata: Dict[str, Any],
    font_path: Optional[Path] = None,
) -> Image.Image:
    songs = userdata.get("songs") or []
    stats = _collect_my_don_song_stats(songs)
    panel_level = _resolve_my_don_panel_level(userdata, songs)
    if panel_level == 5:
        panel_stats = _merge_my_don_level_stats(stats.get(4), stats.get(5))
    else:
        panel_stats = stats.get(panel_level) or _new_my_don_level_stats()
    rank_counts = _resolve_my_don_rank_counts(userdata, panel_level, panel_stats)
    highest_rating_song = _pick_highest_rating_song_name(songs) or "暂无可评曲目"
    total_stage = _sum_my_don_total_stage_count(songs)

    width = MY_DON_CARD_WIDTH
    pad = 18
    title_h = 34
    row_h = 40
    row_gap = 8
    left_area_w = 228
    col_gap = 10
    rank_col_w = (left_area_w - col_gap) // 2
    info_gap = 12
    info_x = pad + left_area_w + info_gap
    info_w = width - pad - info_x
    rows_h = row_h * 4 + row_gap * 3
    height = pad * 2 + title_h + 10 + rows_h

    panel, draw = _render_my_don_card(width, height)
    title_font = _get_font_by_path(font_path or FONT_PATH, 22)
    label_font = _get_font_by_path(font_path or FONT_PATH, 13)
    value_font = _get_font_by_path(font_path or FONT_PATH, 22)
    song_font = _get_font_by_path(font_path or FONT_PATH, 16)

    title_icon_box = (pad, pad - 1, pad + 42, pad + title_h + 4)
    title_text_x = _paste_my_don_title_icons(panel, panel_level, title_icon_box)
    _draw_text(
        draw,
        (title_text_x + 4, pad - 1),
        "当前面板难度评价",
        title_font,
        MY_DON_CARD_TITLE,
    )

    body_y = pad + title_h + 10
    left_rows = [
        (8, ICONS_DIR / "rank" / "8.png"),
        (7, ICONS_DIR / "rank" / "7.png"),
        (6, ICONS_DIR / "rank" / "6.png"),
        (5, ICONS_DIR / "rank" / "5.png"),
    ]
    right_rows = [
        (4, ICONS_DIR / "rank" / "4.png"),
        (3, ICONS_DIR / "rank" / "3.png"),
        (2, ICONS_DIR / "rank" / "2.png"),
        (None, None),
    ]

    for column_index, rows in enumerate((left_rows, right_rows)):
        col_x = pad + column_index * (rank_col_w + col_gap)
        for row_index, (rank_value, icon_path) in enumerate(rows):
            y = body_y + row_index * (row_h + row_gap)
            box = (col_x, y, col_x + rank_col_w, y + row_h)
            draw.rounded_rectangle(
                box,
                radius=16,
                fill=MY_DON_CARD_SUB_BG,
                outline=MY_DON_CARD_GRID,
                width=1,
            )

            icon_box = (col_x + 8, y + 4, col_x + 52, y + row_h - 4)
            if icon_path is not None:
                rank_icon = _load_image(icon_path)
                if rank_icon is not None:
                    _paste_contain(panel, rank_icon, icon_box, pad=1)
            else:
                _draw_text_center(
                    draw,
                    icon_box,
                    "空",
                    label_font,
                    MY_DON_CARD_MUTED,
                    MY_DON_CARD_BG[:3],
                    0,
                    y_offset=0,
                    use_font_metrics=True,
                )

            value = (
                rank_counts["blank"]
                if rank_value is None
                else rank_counts["ranks"].get(rank_value, 0)
            )
            value_box = (col_x + 58, y, col_x + rank_col_w - 10, y + row_h)
            _draw_text_center(
                draw,
                value_box,
                str(value),
                value_font,
                MY_DON_CARD_TEXT,
                MY_DON_CARD_BG[:3],
                0,
                y_offset=-1,
                use_font_metrics=True,
            )

    info_top_h = 78
    info_top_box = (info_x, body_y, info_x + info_w, body_y + info_top_h)
    info_bottom_box = (
        info_x,
        body_y + info_top_h + 10,
        info_x + info_w,
        body_y + rows_h,
    )
    for box in (info_top_box, info_bottom_box):
        draw.rounded_rectangle(
            box,
            radius=18,
            fill=MY_DON_CARD_SUB_BG,
            outline=MY_DON_CARD_GRID,
            width=1,
        )

    _draw_text(
        draw,
        (info_top_box[0] + 14, info_top_box[1] + 10),
        "总游玩曲数",
        label_font,
        MY_DON_CARD_MUTED,
    )
    _draw_text_center(
        draw,
        (info_top_box[0] + 8, info_top_box[1] + 22, info_top_box[2] - 8, info_top_box[3] - 8),
        str(total_stage),
        value_font,
        MY_DON_CARD_TEXT,
        MY_DON_CARD_BG[:3],
        0,
        y_offset=-1,
        use_font_metrics=True,
    )

    _draw_text(
        draw,
        (info_bottom_box[0] + 14, info_bottom_box[1] + 10),
        "最高评价曲目",
        label_font,
        MY_DON_CARD_MUTED,
    )
    lines = _wrap_text_lines(
        draw,
        highest_rating_song,
        song_font,
        info_w - 28,
        max_lines=3,
    )
    _draw_text_lines_center(
        draw,
        (
            info_bottom_box[0] + 10,
            info_bottom_box[1] + 26,
            info_bottom_box[2] - 10,
            info_bottom_box[3] - 10,
        ),
        lines,
        song_font,
        MY_DON_CARD_TEXT,
    )

    return panel


def render_my_don_image(user_id: int, save_path: Optional[Path | str] = None) -> bytes:
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")

    with open(userdata_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)

    final_img = _render_my_don_base_panel(user_id, userdata)

    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        final_img.save(save_path)

    buf = BytesIO()
    final_img.save(buf, format="PNG")
    return buf.getvalue()


def render_update_changes_image(
    user_id: int,
    save_path: Optional[Path | str] = None,
    show_all: bool = False,
) -> bytes:
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")

    with open(userdata_path, "r", encoding="utf-8") as f:
        userdata = json.load(f)

    left_sections: List[Dict[str, Any]] = []
    right_sections: List[Dict[str, Any]] = []
    previous_map = _load_previous_song_map(user_id)
    previous_dojo = _load_previous_dojo_state(user_id)
    songs = userdata.get("songs") or []
    if previous_map is not None and isinstance(songs, list):
        current_map = _build_song_map(
            [song for song in songs if isinstance(song, dict)]
        )
        left_sections, right_sections = _collect_change_sections(
            previous_map,
            current_map,
            item_limit=None if show_all else 5,
            include_score_refresh=show_all,
        )

    current_dojo = normalize_dojo_scores(userdata.get("dojo") or {})
    if previous_dojo is not None:
        dojo_left_sections, dojo_right_sections = _collect_dojo_change_sections(
            previous_dojo,
            current_dojo,
            item_limit=None if show_all else 5,
            include_score_refresh=show_all,
        )
        left_sections.extend(dojo_left_sections)
        right_sections.extend(dojo_right_sections)

    left_col = _render_my_don_base_panel(
        user_id,
        userdata,
        font_path=UPDATE_LEGACY_FONT_PATH,
        title_font_path=UPDATE_LEGACY_TITLE_FONT_PATH,
    )
    mid_col = _render_change_column(
        title="本次更新变化 - 成就",
        sections=left_sections,
        empty_text="和上一次相比，无符合条件变化",
        font_path=UPDATE_LEGACY_FONT_PATH,
    )
    right_col = _render_change_column(
        title="本次更新变化 - 评价",
        sections=right_sections,
        empty_text="和上一次相比，无符合条件变化",
        font_path=UPDATE_LEGACY_FONT_PATH,
    )
    final_img = _compose_columns([left_col, mid_col, right_col], gap=16, pad=10)

    if save_path is not None:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        final_img.save(save_path)

    buf = BytesIO()
    final_img.save(buf, format="PNG")
    return buf.getvalue()


def render_user_dress(user_id: int, save_path: Optional[Path | str] = None) -> Path:
    image = build_dress_image(user_id)
    if save_path is None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        save_path = OUTPUT_DIR / f"dress_{user_id}.png"
    else:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(save_path)
    return save_path


# if __name__ == "__main__":
# import sys

# if len(sys.argv) < 2:
#     print("usage: python -m plugins.utils.draw_dress <user_id> [save_path]")
#     raise SystemExit(1)
# uid = int(sys.argv[1])
# out = sys.argv[2] if len(sys.argv) > 2 else None
# result = render_user_dress(2258735)
# print(f"saved: {result}")
