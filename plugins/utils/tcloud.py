from __future__ import annotations

import json
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Dict

from PIL import Image
from wordcloud import WordCloud

from .draw_dress import render_my_don_image

ROOT_DIR = Path(__file__).resolve().parents[2]
USERDATA_DIR = ROOT_DIR / "userdata"
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

_FONT_CANDIDATES = [
    "assets/fonts/DDFont.ttf",
    str(ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"),
    str(ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"),
]


def _resolve_font_path() -> str | None:
    for path in _FONT_CANDIDATES:
        if Path(path).exists():
            return path
    return None


@lru_cache(maxsize=1)
def _load_song_name_map() -> Dict[int, str]:
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    name_map: Dict[int, str] = {}
    if not isinstance(data, list):
        return name_map
    for entry in data:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("id")
        try:
            song_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        name = entry.get("song_name") or entry.get("song_name_jp") or f"ID{song_id}"
        name_map[song_id] = name
    return name_map


def _load_user_play_counts(user_id: int) -> Dict[int, int]:
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")
    with userdata_path.open("r", encoding="utf-8") as f:
        userdata = json.load(f)
    songs = userdata.get("songs", [])
    if not isinstance(songs, list):
        return {}
    counts: Dict[int, int] = {}
    for entry in songs:
        if not isinstance(entry, dict):
            continue
        raw_id = entry.get("song_no")
        try:
            song_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        raw_count = (
            entry.get("stage_cnt")
            if entry.get("stage_cnt") is not None
            else entry.get("play_cnt")
        )
        if raw_count is None:
            raw_count = entry.get("play_count")
        try:
            count = int(raw_count or 0)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        counts[song_id] = counts.get(song_id, 0) + count
    return counts


def _build_word_frequencies(user_id: int) -> Dict[str, int]:
    counts = _load_user_play_counts(user_id)
    if not counts:
        return {}
    name_map = _load_song_name_map()
    freqs: Dict[str, int] = {}
    for song_id, count in counts.items():
        name = name_map.get(song_id, f"ID{song_id}")
        freqs[name] = freqs.get(name, 0) + count
    return freqs


def _render_wordcloud_image(
    user_id: int, width: int, height: int
) -> Image.Image:
    freqs = _build_word_frequencies(user_id)
    if not freqs:
        raise ValueError("no_play_data")
    font_path = _resolve_font_path()
    wc = WordCloud(
        width=width,
        height=height,
        background_color="white",
        font_path=font_path,
        max_words=220,
        prefer_horizontal=0.9,
        colormap="tab20",
        random_state=42,
        min_font_size=10,
        max_font_size=90,
    ).generate_from_frequencies(freqs)
    return wc.to_image().convert("RGBA")


def render_tcloud_image(user_id: int, gap: int = 16) -> bytes:
    left_img = Image.open(BytesIO(render_my_don_image(user_id))).convert("RGBA")
    height = left_img.height
    width = max(left_img.width, height)
    right_img = _render_wordcloud_image(user_id, width=width, height=height)

    total_width = left_img.width + gap + right_img.width
    total_height = max(left_img.height, right_img.height)
    canvas = Image.new("RGBA", (total_width, total_height), (255, 255, 255, 255))

    left_y = (total_height - left_img.height) // 2
    right_y = (total_height - right_img.height) // 2
    canvas.alpha_composite(left_img, (0, left_y))
    canvas.alpha_composite(right_img, (left_img.width + gap, right_y))

    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()
