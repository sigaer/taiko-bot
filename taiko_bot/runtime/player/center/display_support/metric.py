from __future__ import annotations


import re, json

from io import BytesIO

from PIL import Image, ImageDraw, ImageFont

from taiko_bot.runtime.public.config import root

SONG_DATA_PATH=root()/"songs/song_data.json"

SONG_METRIC_FONT_PATH = "/usr/share/fonts/NotoSansCJKSC-Black.ttf"

SONG_METRIC_MAX_SHOW = 30

SONG_METRIC_DIFF_PRIORITY = {
    5: 0,
    4: 0,
    3: 1,
    2: 2,
    1: 3,
}

SONG_METRIC_QUERY_PATTERN = (
    r"^(太鼓|我的)\s*"
    r"(?:(?P<ng>\d{1,4})不可|(?P<ok>\d{1,4})可|(?P<single_ok>单可)|(?P<dondaful>全良))"
    r"(?:\s*(?P<order>正序|倒序|升序|降序|asc|desc))?\s*$"
)

def load_song_data():
    """读取 song_data.json（dict 列表）"""
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)

def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _low_miss_total(ok_cnt: Any, ng_cnt: Any) -> int:
    return _to_int(ok_cnt, 0) + _to_int(ng_cnt, 0)

def _build_song_title_map() -> Dict[int, Dict[str, Any]]:
    title_map: Dict[int, Dict[str, Any]] = {}
    for item in load_song_data():
        if not isinstance(item, dict):
            continue
        song_id = _to_int(item.get("id"), -1)
        if song_id < 0:
            continue
        title_jp = str(
            item.get("song_name_jp") or item.get("song_name") or f"ID{song_id}"
        )
        title_cn = str(item.get("song_name") or "").strip()
        # 获取上架状态：0=在架，1=下架
        shelf_status = item.get("shelf_status", 0)
        stars: Dict[int, str] = {}
        for lv in (1, 2, 3, 4, 5):
            star_raw = item.get(f"level_{lv}")
            if star_raw is None:
                continue
            star_text = str(star_raw).strip()
            if not star_text or star_text == "-":
                continue
            stars[lv] = star_text
        title_map[song_id] = {
            "title_jp": title_jp,
            "title_cn": title_cn,
            "stars": stars,
            "shelf_status": shelf_status,
        }
    return title_map

def _collect_song_metric_matches(
    records,
    mode: str,
    target_value: Optional[int] = None,
    order_mode: str = "default",
) -> List[Dict[str, Any]]:
    title_map = _build_song_title_map()
    matched: List[Dict[str, Any]] = []
    for record in records:
        song_no = _to_int(record.get("song_no"), -1)
        level = _to_int(record.get("level"), -1)
        if song_no < 0 or level not in (1, 2, 3, 4, 5):
            continue

        ok_cnt = _to_int(record.get("ok_cnt"), 0)
        ng_cnt = _to_int(record.get("ng_cnt", record.get("bad_cnt")), 0)
        dondaful_cnt = _to_int(record.get("dondaful_combo_cnt"), 0)
        full_combo_cnt = _to_int(record.get("full_combo_cnt"), 0)

        # 过滤规则：
        # - xx可：仅过滤全良（保留全连）
        # - 单可：仅过滤全良（保留全连）
        # - xx不可：过滤全连与全良
        if mode in ("ok", "single_ok") and dondaful_cnt > 0:
            continue
        if mode == "ng" and (full_combo_cnt > 0 or dondaful_cnt > 0):
            continue

        if mode == "ok":
            if target_value == 1:
                if _low_miss_total(ok_cnt, ng_cnt) != 1:
                    continue
            elif target_value is None or ok_cnt != target_value:
                continue
        elif mode == "single_ok":
            if _low_miss_total(ok_cnt, ng_cnt) >= 10:
                continue
        elif mode == "ng":
            if target_value is None or ng_cnt != target_value:
                continue
        elif mode == "dondaful":
            if dondaful_cnt <= 0:
                continue
        else:
            continue

        song_meta = title_map.get(song_no, {})
        # 过滤已下架歌曲（shelf_status=1 表示已下架）
        if isinstance(song_meta, dict) and song_meta.get("shelf_status") == 1:
            continue
        stars = song_meta.get("stars") if isinstance(song_meta, dict) else {}
        star = "-"
        if isinstance(stars, dict):
            star = str(stars.get(level, "-"))

        matched.append(
            {
                "song_no": song_no,
                "level": level,
                "title": (
                    str(song_meta.get("title_jp"))
                    if isinstance(song_meta, dict) and song_meta.get("title_jp")
                    else f"ID{song_no}"
                ),
                "title_cn": (
                    str(song_meta.get("title_cn", ""))
                    if isinstance(song_meta, dict)
                    else ""
                ),
                "star": star,
                "ok_cnt": ok_cnt,
                "ng_cnt": ng_cnt,
                "dondaful_combo_cnt": dondaful_cnt,
                "full_combo_cnt": full_combo_cnt,
            }
        )

    if order_mode == "asc":
        matched.sort(
            key=lambda item: (
                _get_song_metric_level_bucket(item["level"]),
                *_build_song_metric_star_sort_key(item.get("star"), descending=False),
                item["song_no"],
            )
        )
    elif order_mode == "desc":
        matched.sort(
            key=lambda item: (
                -_get_song_metric_level_bucket(item["level"]),
                *_build_song_metric_star_sort_key(item.get("star"), descending=True),
                item["song_no"],
            )
        )
    else:
        matched.sort(
            key=lambda item: (
                SONG_METRIC_DIFF_PRIORITY.get(item["level"], 99),
                *_build_song_metric_star_sort_key(item.get("star"), descending=True),
                item["song_no"],
            )
        )
    return matched

def _parse_song_metric_order(order_token: Optional[str]) -> str:
    if not order_token:
        return "default"
    token = order_token.strip().lower()
    if token in ("正序", "升序", "asc"):
        return "asc"
    if token in ("倒序", "降序", "desc"):
        return "desc"
    return "default"

def _get_song_metric_level_bucket(level: int) -> int:
    return 4 if level in (4, 5) else level

def _parse_song_metric_star_value(star: Any) -> Optional[float]:
    text = str(star or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    value = float(match.group())
    if "+" in text:
        value += 0.5
    return value

def _build_song_metric_star_sort_key(
    star: Any, *, descending: bool = False
) -> Tuple[bool, float]:
    value = _parse_song_metric_star_value(star)
    if value is None:
        return True, float("inf")
    return False, (-value if descending else value)

def _render_song_metric_list_image(
    metric_label: str,
    songs: List[Dict[str, Any]],
    total_count: int,
) -> bytes:
    width = 1120
    padding = 24
    line_gap = 8
    icon_size = 24
    num_w = 54
    icon_gap = 10

    bg_color = (245, 247, 250, 255)
    fg_color = (28, 32, 36, 255)

    font = _load_alias_font(SONG_METRIC_FONT_PATH, 24)
    title_font = _load_alias_font(SONG_METRIC_FONT_PATH, 30)
    sub_font = _load_alias_font(SONG_METRIC_FONT_PATH, 22)
    tmp = Image.new("RGBA", (width, 10), bg_color)
    draw = ImageDraw.Draw(tmp)

    title_line = f"{metric_label}曲目"
    sub_line = f"共 {total_count} 首，展示前 {len(songs)} 首"
    title_lines = _wrap_text(draw, title_line, title_font, width - padding * 2)
    sub_lines = _wrap_text(draw, sub_line, sub_font, width - padding * 2)

    title_h = int(30 * 1.4)
    sub_h = int(22 * 1.35)
    row_h = 36

    if songs:
        rows_h = len(songs) * (row_h + line_gap)
    else:
        rows_h = row_h

    content_h = (
        len(title_lines) * (title_h + 4) + len(sub_lines) * (sub_h + 4) + 10 + rows_h
    )
    height = max(240, padding * 2 + content_h)

    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    y = padding
    for line in title_lines:
        draw.text((padding, y), line, fill=fg_color, font=title_font)
        y += title_h + 4
    for line in sub_lines:
        draw.text((padding, y), line, fill=fg_color, font=sub_font)
        y += sub_h + 4
    y += 8

    if not songs:
        draw.text((padding, y), "暂无符合条件的曲目", fill=fg_color, font=font)
    else:
        star_font = _load_alias_font(SONG_METRIC_FONT_PATH, 22)
        icon_x = padding + num_w + icon_gap
        star_x = icon_x + icon_size + 8
        star_block_w = 56
        title_x = star_x + star_block_w + 10
        title_max_w = width - padding - title_x
        for idx, item in enumerate(songs, start=1):
            number_text = f"{idx:02d}."
            draw.text((padding, y + 4), number_text, fill=fg_color, font=font)

            level = _to_int(item.get("level"), 0)
            icon_path = (root()/"assets/icons/diff") / f"{level}.png"
            if icon_path.exists():
                try:
                    icon = (
                        Image.open(icon_path)
                        .convert("RGBA")
                        .resize((icon_size, icon_size), Image.LANCZOS)
                    )
                    icon_y = (
                        y
                        + max(0, (row_h - icon_size) // 2)
                        + int(round(icon_size * 0.25))
                    )
                    img.alpha_composite(icon, (icon_x, icon_y))
                except Exception:
                    pass

            star_raw = str(item.get("star") or "-").strip()
            star_text = f"★{star_raw}" if star_raw and star_raw != "-" else "★-"
            star_bbox = draw.textbbox((0, 0), star_text, font=star_font)
            star_h = max(1, star_bbox[3] - star_bbox[1])
            star_y = y + max(0, (row_h - star_h) // 2)
            draw.text((star_x, star_y), star_text, fill=fg_color, font=star_font)

            title_jp = str(item.get("title") or f"ID{item.get('song_no')}")
            title_cn = str(item.get("title_cn") or "").strip()
            if title_cn and title_cn != title_jp:
                display_title = f"{title_jp}（{title_cn}）"
            else:
                display_title = title_jp
            title = _truncate_text(draw, display_title, font, title_max_w)
            text_bbox = draw.textbbox((0, 0), title, font=font)
            text_h = max(1, text_bbox[3] - text_bbox[1])
            text_y = y + max(0, (row_h - text_h) // 2)
            draw.text((title_x, text_y), title, fill=fg_color, font=font)
            y += row_h + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()

def _compose_song_metric_result_image(my_don_img: bytes, list_img: bytes) -> bytes:
    left = Image.open(BytesIO(my_don_img)).convert("RGBA")
    right = Image.open(BytesIO(list_img)).convert("RGBA")
    gap = 16
    pad = 10
    canvas_w = left.width + right.width + gap + pad * 2
    canvas_h = max(left.height, right.height) + pad * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 0))
    canvas.alpha_composite(left, (pad, pad))
    canvas.alpha_composite(right, (pad + left.width + gap, pad))
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()

def _load_alias_font(font_path: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(font_path, size)
    except Exception:
        return ImageFont.load_default()

def _wrap_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> List[str]:
    if "\n" in text:
        wrapped_lines: List[str] = []
        for raw_line in text.splitlines():
            if raw_line == "":
                wrapped_lines.append("")
                continue
            wrapped_lines.extend(_wrap_text(draw, raw_line, font, max_w))
        return wrapped_lines if wrapped_lines else [""]

    if draw.textlength(text, font=font) <= max_w:
        return [text]
    lines: List[str] = []
    current = ""
    for ch in text:
        if ch == "\n":
            if current:
                lines.append(current)
                current = ""
            continue
        test = current + ch
        if draw.textlength(test, font=font) <= max_w or not current:
            current = test
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines

def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    if draw.textlength(ell, font=font) > max_w:
        return ""
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        t = text[:mid] + ell
        if draw.textlength(t, font=font) <= max_w:
            left = mid + 1
        else:
            right = mid
    return text[: right - 1] + ell if right > 0 else ell
