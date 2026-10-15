from __future__ import annotations

import json
import re
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple

from fuzzywuzzy import fuzz
from PIL import Image, ImageDraw, ImageFont

from .display_host_support.custom_title import (
    CUSTOM_PLATE_PATHS,
    list_custom_titles,
    list_custom_titles_for_song,
    normalize_custom_title_display,
)
from .display_support.draw_dress import FONT_PATH, render_nickname_title_row
from ...public.config import root
from .display_host_support.song_title_showcase import (
    ShowcaseTitle,
    _load_song_lookup,
    _song_lookup_keys,
    list_official_titles_for_song,
    load_song_title_relations,
)


SONG_TITLE_QUERY_PATTERN = re.compile(r"^/?查称号\s*(?P<query>.*?)\s*$", re.IGNORECASE)
SONG_DATA_PATH = root() / "songs" / "song_data.json"

CANVAS_WIDTH = 850
CANVAS_PADDING = 28
SECTION_GAP = 20
CELL_GAP = 14
SECTION_INSET = 14
DEFAULT_CELL_WIDTH = (
    CANVAS_WIDTH - CANVAS_PADDING * 2 - SECTION_INSET * 2 - CELL_GAP
) // 2
CELL_PADDING = 10
CONDITION_HEIGHT = 30
MAX_COLUMNS = 2
FUZZY_ACCEPT_THRESHOLD = 0.75

BACKGROUND = (239, 244, 251, 255)
CARD_BACKGROUND = (255, 255, 255, 250)
CARD_OUTLINE = (220, 228, 239, 255)
CELL_BACKGROUND = (248, 250, 253, 255)
TITLE_COLOR = (42, 48, 64, 255)
MUTED_COLOR = (112, 122, 140, 255)
OFFICIAL_COLOR = (72, 112, 184, 255)
CUSTOM_COLOR = (191, 126, 42, 255)
FONT_FALLBACK_PATHS = (
    FONT_PATH,
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
)

ACHIEVEMENT_LABELS = {
    "clear": "通关",
    "full_combo": "全连",
    "all_perfect": "全良",
}
DIFFICULTY_LABELS = {
    "easy": "简单",
    "normal": "一般",
    "hard": "困难",
    "oni": "魔王",
    "inner_oni": "里谱",
    "oni_or_inner_oni": "魔王 / 里谱",
    "unspecified": "任意难度",
}


@dataclass(frozen=True)
class TitleSongMatch:
    title_name: str
    song_id: int
    song_title: str
    source: str
    match_mode: str
    similarity: float


def parse_song_title_query(text: object) -> Optional[str]:
    match = SONG_TITLE_QUERY_PATTERN.match(str(text or "").strip())
    if not match:
        return None
    query = str(match.group("query") or "").strip()
    return query or None


def load_song_title_query_entries(
    song_id: int,
) -> Tuple[list[ShowcaseTitle], list[ShowcaseTitle]]:
    return (
        list_official_titles_for_song(song_id),
        list_custom_titles_for_song(song_id),
    )


def _normalize_title_query(value: object) -> str:
    return normalize_custom_title_display(value).casefold()


def _load_song_id_title_map() -> dict[int, str]:
    try:
        payload = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result: dict[int, str] = {}
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id"))
        except Exception:
            continue
        result[song_id] = str(
            item.get("song_name_jp") or item.get("song_name") or f"ID{song_id}"
        )
    return result


def _title_song_catalog() -> list[Tuple[str, str, Tuple[int, ...]]]:
    title_lookup, _, _, _ = _load_song_lookup()
    grouped: dict[Tuple[str, str], dict[str, object]] = {}

    for relation in load_song_title_relations():
        song_ids: set[int] = set()
        for song_name in relation.song_names:
            for lookup_key in _song_lookup_keys(song_name):
                song_ids.update(title_lookup.get(lookup_key, ()))
        if not song_ids:
            continue
        key = (_normalize_title_query(relation.title_name), "official")
        item = grouped.setdefault(
            key,
            {"title_name": relation.title_name, "song_ids": set()},
        )
        item["song_ids"].update(song_ids)

    try:
        custom_titles = list_custom_titles()
    except Exception:
        custom_titles = []
    for record in custom_titles:
        key = (_normalize_title_query(record.title_name), "custom")
        item = grouped.setdefault(
            key,
            {"title_name": record.title_name, "song_ids": set()},
        )
        item["song_ids"].add(int(record.song_id))

    result: list[Tuple[str, str, Tuple[int, ...]]] = []
    for (title_key, source), item in grouped.items():
        if not title_key:
            continue
        song_ids = tuple(sorted(int(value) for value in item["song_ids"]))
        if song_ids:
            result.append((str(item["title_name"]), source, song_ids))
    return result


def find_songs_by_title(query: object) -> list[TitleSongMatch]:
    query_key = _normalize_title_query(query)
    if not query_key:
        return []
    catalog = _title_song_catalog()
    exact = [item for item in catalog if _normalize_title_query(item[0]) == query_key]
    if exact:
        selected = [(item, "exact", 1.0) for item in exact]
    else:
        partial = [
            item for item in catalog if query_key in _normalize_title_query(item[0])
        ]
        if partial:
            selected = [
                (
                    item,
                    "partial",
                    fuzz.ratio(query_key, _normalize_title_query(item[0])) / 100.0,
                )
                for item in partial
            ]
        else:
            scored = [
                (
                    item,
                    fuzz.ratio(query_key, _normalize_title_query(item[0])) / 100.0,
                )
                for item in catalog
            ]
            best_similarity = max((score for _, score in scored), default=-1.0)
            selected = [
                (item, "fuzzy", score)
                for item, score in scored
                if score == best_similarity
            ]

    song_titles = _load_song_id_title_map()
    result: list[TitleSongMatch] = []
    seen: set[Tuple[str, int]] = set()
    for (title_name, source, song_ids), match_mode, similarity in selected:
        for song_id in song_ids:
            identity = (source, song_id)
            if identity in seen:
                continue
            seen.add(identity)
            result.append(
                TitleSongMatch(
                    title_name=title_name,
                    song_id=song_id,
                    song_title=song_titles.get(song_id, f"ID{song_id}"),
                    source=source,
                    match_mode=match_mode,
                    similarity=similarity,
                )
            )
    return sorted(
        result,
        key=lambda item: (-item.similarity, item.title_name.casefold(), item.song_id),
    )


def is_accepted_similarity(
    similarity: object,
    threshold: float = FUZZY_ACCEPT_THRESHOLD,
) -> bool:
    try:
        value = float(similarity)
    except (TypeError, ValueError):
        return False
    if value > 1.0:
        value /= 100.0
    return value >= float(threshold)


def is_fuzzy_song_result(results: Sequence[Sequence[object]]) -> bool:
    return (
        len(results) == 1
        and len(results[0]) >= 3
        and isinstance(results[0][2], (int, float))
    )


def collect_accepted_song_matches(
    song_results: Sequence[Sequence[object]],
    title_results: Sequence[TitleSongMatch],
    *,
    threshold: float = FUZZY_ACCEPT_THRESHOLD,
) -> dict[int, str]:
    accepted: dict[int, str] = {}
    song_is_fuzzy = is_fuzzy_song_result(song_results)
    if song_results and (
        not song_is_fuzzy or is_accepted_similarity(song_results[0][2], threshold)
    ):
        for row in song_results:
            if len(row) < 2:
                continue
            accepted[int(row[0])] = str(row[1])

    for item in title_results:
        if item.match_mode != "fuzzy" or is_accepted_similarity(
            item.similarity, threshold
        ):
            accepted[item.song_id] = item.song_title
    return accepted


def build_rejected_match_suggestions(
    song_results: Sequence[Sequence[object]],
    title_results: Sequence[TitleSongMatch],
    *,
    threshold: float = FUZZY_ACCEPT_THRESHOLD,
) -> list[str]:
    suggestions: list[str] = []
    if is_fuzzy_song_result(song_results) and not is_accepted_similarity(
        song_results[0][2], threshold
    ):
        suggestions.append(
            f"歌曲：{song_results[0][1]}"
            f"（匹配度 {float(song_results[0][2]) / 100.0:.2f}）"
        )
    fuzzy_titles = [item for item in title_results if item.match_mode == "fuzzy"]
    if fuzzy_titles and not is_accepted_similarity(
        fuzzy_titles[0].similarity, threshold
    ):
        best_title = fuzzy_titles[0]
        suggestions.append(
            f"称号：{best_title.title_name}（匹配度 {best_title.similarity:.2f}）"
        )
    return suggestions


def extract_player_nickname(userdata: object, fallback: str = "鼓手") -> str:
    if not isinstance(userdata, dict):
        return fallback
    profile = userdata.get("profile")
    if not isinstance(profile, dict):
        return fallback
    costume = profile.get("gameCostume")
    if not isinstance(costume, dict):
        costume = {}
    nickname = str(
        costume.get("mydon_name") or profile.get("mydon_name") or ""
    ).strip()
    return nickname or fallback




def _load_font(size: int) -> ImageFont.ImageFont:
    for font_path in FONT_FALLBACK_PATHS:
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            continue
    return ImageFont.load_default()


def _truncate_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    value = str(text or "")
    if draw.textbbox((0, 0), value, font=font)[2] <= max_width:
        return value
    suffix = "…"
    while value:
        value = value[:-1]
        candidate = value + suffix
        if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
            return candidate
    return suffix


def _condition_label(item: ShowcaseTitle) -> str:
    difficulty = DIFFICULTY_LABELS.get(item.difficulty_scope, "任意难度")
    achievement = ACHIEVEMENT_LABELS.get(item.requirement_type, item.requirement_type)
    multi_song = f" · {len(item.song_names)} 曲条件" if item.is_multi_song else ""
    return f"{difficulty} · {achievement}{multi_song}"


def _prepare_rows(
    titles: Iterable[ShowcaseTitle],
    *,
    nickname: str,
) -> list[Tuple[ShowcaseTitle, Image.Image]]:
    rows: list[Tuple[ShowcaseTitle, Image.Image]] = []
    for item in titles:
        plate_id = int(
            item.showcase_bg_plate_id
            if item.showcase_bg_plate_id is not None
            else item.plate_id
        )
        plate_path = (
            CUSTOM_PLATE_PATHS.get(str(item.plate_style or ""))
            if item.source == "custom"
            else None
        )
        rows.append(
            (
                item,
                render_nickname_title_row(
                    nickname,
                    item.title_name,
                    plate_id,
                    plate_path_override=plate_path,
                ),
            )
        )
    return rows


def _section_height(
    rows: Sequence[Tuple[ShowcaseTitle, Image.Image]], columns: int
) -> int:
    if not rows:
        return 106
    row_heights = []
    for index in range(0, len(rows), columns):
        pair = rows[index : index + columns]
        row_heights.append(
            max(image.height for _, image in pair) + CELL_PADDING * 2 + CONDITION_HEIGHT
        )
    return 52 + sum(row_heights) + CELL_GAP * max(0, len(row_heights) - 1) + 18


def _layout_metrics(
    *sections: Sequence[Tuple[ShowcaseTitle, Image.Image]],
) -> Tuple[int, int, int]:
    largest_section = max((len(rows) for rows in sections), default=0)
    columns = max(1, min(MAX_COLUMNS, largest_section))
    preview_width = max(
        (preview.width for rows in sections for _, preview in rows),
        default=0,
    )
    cell_width = max(DEFAULT_CELL_WIDTH, preview_width + CELL_PADDING * 2)
    canvas_width = (
        CANVAS_PADDING * 2
        + SECTION_INSET * 2
        + cell_width * columns
        + CELL_GAP * (columns - 1)
    )
    return canvas_width, cell_width, columns


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    box: Tuple[int, int, int, int],
    text: str,
    font: ImageFont.ImageFont,
    fill: Tuple[int, int, int, int],
) -> None:
    bounds = draw.textbbox((0, 0), text, font=font)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = box[0] + (box[2] - box[0] - width) // 2 - bounds[0]
    y = box[1] + (box[3] - box[1] - height) // 2 - bounds[1]
    draw.text((x, y), text, font=font, fill=fill)


def _draw_section(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    *,
    top: int,
    label: str,
    accent: Tuple[int, int, int, int],
    rows: Sequence[Tuple[ShowcaseTitle, Image.Image]],
    canvas_width: int,
    cell_width: int,
    columns: int,
) -> int:
    section_height = _section_height(rows, columns)
    left = CANVAS_PADDING
    right = canvas_width - CANVAS_PADDING
    bottom = top + section_height
    draw.rounded_rectangle(
        (left, top, right, bottom),
        radius=22,
        fill=CARD_BACKGROUND,
        outline=CARD_OUTLINE,
        width=1,
    )
    section_font = _load_font(23)
    count_font = _load_font(17)
    draw.text((left + 20, top + 15), label, font=section_font, fill=accent)
    count_text = f"{len(rows)} 个"
    count_width = draw.textbbox((0, 0), count_text, font=count_font)[2]
    draw.text((right - 20 - count_width, top + 19), count_text, font=count_font, fill=MUTED_COLOR)

    if not rows:
        _draw_centered_text(
            draw,
            (left + 16, top + 51, right - 16, bottom - 12),
            "暂无相关称号",
            _load_font(18),
            MUTED_COLOR,
        )
        return bottom

    condition_font = _load_font(16)
    row_top = top + 52
    for index in range(0, len(rows), columns):
        pair = rows[index : index + columns]
        row_height = max(preview.height for _, preview in pair) + CELL_PADDING * 2 + CONDITION_HEIGHT
        for column, (item, preview) in enumerate(pair):
            cell_left = left + SECTION_INSET + column * (cell_width + CELL_GAP)
            cell_right = cell_left + cell_width
            cell_bottom = row_top + row_height
            draw.rounded_rectangle(
                (cell_left, row_top, cell_right, cell_bottom),
                radius=16,
                fill=CELL_BACKGROUND,
                outline=CARD_OUTLINE,
                width=1,
            )
            preview_x = cell_left + (cell_width - preview.width) // 2
            preview_y = row_top + CELL_PADDING
            image.alpha_composite(preview, (preview_x, preview_y))
            condition = _truncate_text(
                draw,
                _condition_label(item),
                condition_font,
                cell_width - CELL_PADDING * 2,
            )
            _draw_centered_text(
                draw,
                (
                    cell_left + CELL_PADDING,
                    cell_bottom - CONDITION_HEIGHT - 2,
                    cell_right - CELL_PADDING,
                    cell_bottom - 2,
                ),
                condition,
                condition_font,
                MUTED_COLOR,
            )
        row_top += row_height + CELL_GAP
    return bottom


def render_song_title_query(
    song_title: str,
    song_id: int,
    nickname: str,
    official_titles: Sequence[ShowcaseTitle],
    custom_titles: Sequence[ShowcaseTitle],
) -> BytesIO:
    official_rows = _prepare_rows(official_titles, nickname=nickname)
    custom_rows = _prepare_rows(custom_titles, nickname=nickname)
    canvas_width, cell_width, columns = _layout_metrics(
        official_rows,
        custom_rows,
    )
    header_height = 112
    total_height = (
        header_height
        + _section_height(official_rows, columns)
        + SECTION_GAP
        + _section_height(custom_rows, columns)
        + CANVAS_PADDING
    )
    image = Image.new("RGBA", (canvas_width, total_height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = _load_font(31)
    subtitle_font = _load_font(17)
    display_title = _truncate_text(
        draw,
        f"《{song_title}》相关称号",
        title_font,
        canvas_width - CANVAS_PADDING * 2,
    )
    draw.text((CANVAS_PADDING, 24), display_title, font=title_font, fill=TITLE_COLOR)
    draw.text(
        (CANVAS_PADDING, 70),
        f"歌曲 ID {int(song_id)} · 共 {len(official_rows) + len(custom_rows)} 个",
        font=subtitle_font,
        fill=MUTED_COLOR,
    )

    section_top = header_height
    section_top = _draw_section(
        image,
        draw,
        top=section_top,
        label="原有称号",
        accent=OFFICIAL_COLOR,
        rows=official_rows,
        canvas_width=canvas_width,
        cell_width=cell_width,
        columns=columns,
    )
    _draw_section(
        image,
        draw,
        top=section_top + SECTION_GAP,
        label="自定义称号",
        accent=CUSTOM_COLOR,
        rows=custom_rows,
        canvas_width=canvas_width,
        cell_width=cell_width,
        columns=columns,
    )

    output = BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output
