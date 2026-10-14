from __future__ import annotations
from .paths import ROOT as _ROOT


import io

import json

from pathlib import Path

from typing import Any, Dict, List, Tuple

from PIL import Image, ImageDraw

from .draw_dress import draw_player_info

BASE = _ROOT

PATH_SONG_DATA = BASE / "songs" / "song_data.json"

PROGRESS_BG_PATH = BASE / "assets" / "templates" / "progress_bg.png"

DEFAULT_PROGRESS_FONT_PATH = str(BASE / "assets" / "fonts" / "DDFont.ttf")

from taiko_application.score import ScorePresentationContext, RecommendationRenderer

def _load_song_star_map() -> Dict[Tuple[int, int], str]:
    try:
        payload = json.loads(PATH_SONG_DATA.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, list):
        return {}

    mapping: Dict[Tuple[int, int], str] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id", -1))
        except Exception:
            continue
        if song_id < 0:
            continue
        for level in (4, 5):
            raw_value = item.get(f"level_{level}")
            if raw_value is None:
                continue
            if isinstance(raw_value, str):
                text = raw_value.strip()
                if not text or text == "-":
                    continue
                mapping[(song_id, level)] = text
                continue
            try:
                numeric = float(raw_value)
            except Exception:
                mapping[(song_id, level)] = str(raw_value)
                continue
            mapping[(song_id, level)] = (
                str(int(numeric)) if numeric.is_integer() else str(numeric)
            )
    return mapping


def _render_progress_profile_panel(
    userdata: Dict[str, Any],
    target_width: int,
    font_path: str | None,
) -> Image.Image:
    if not userdata:
        return Image.new("RGBA", (0, 0), (0, 0, 0, 0))
    canvas = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(font_path, 16)
    title_font = _load_font(font_path, 16)
    box = draw_player_info(
        base=canvas,
        draw=draw,
        userdata=userdata,
        sx=1.0,
        sy=1.0,
        font=font,
        stroke_width=2,
        fill=(255, 255, 255),
        stroke_fill=(0, 0, 0),
        offset_xy=(0, 0),
        title_font=title_font,
    )
    panel = _crop_box_with_pad(canvas, box, pad=4)
    if panel.width <= 0:
        return panel
    scale = target_width / panel.width
    target_h = max(1, int(round(panel.height * scale)))
    return panel.resize((target_width, target_h), Image.LANCZOS)

SONG_STAR_MAP = _load_song_star_map()

def render_recommend_image_bytes(
    recs: List[Dict[str, Any]],
    *,
    title: str = "Taiko 推荐歌曲",
    subtitle: str | None = None,
    user_id: int | None = None,
    userdata: Dict[str, Any] | None = None,
    assets_base: str | Path = BASE / "assets",
    font_path: str | None = DEFAULT_PROGRESS_FONT_PATH,
) -> io.BytesIO:
    font_path = font_path or DEFAULT_PROGRESS_FONT_PATH
    userdata = userdata or {}
    profile_panel = _render_progress_profile_panel(userdata, 640, font_path)
    try:
        context = ScorePresentationContext(
            assets_base=Path(assets_base),
            background_path=PROGRESS_BG_PATH,
            font_path=font_path,
            profile_panel=profile_panel,
            recommendations=recs,
            song_star_map=SONG_STAR_MAP,
            title=title,
            subtitle=subtitle,
        )
        return RecommendationRenderer(context).render()
    finally:
        profile_panel.close()

def _load_font(font_path, size):
    return RecommendationRenderer(ScorePresentationContext(BASE / "assets"))._load_font(
        font_path, size
    )

def _crop_box_with_pad(image, box, pad=4):
    return RecommendationRenderer(
        ScorePresentationContext(BASE / "assets")
    )._crop_box_with_pad(image, box, pad)
