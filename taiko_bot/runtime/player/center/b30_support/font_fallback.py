from __future__ import annotations


from functools import lru_cache

from pathlib import Path

from typing import List, Optional, Tuple

from PIL import ImageDraw, ImageFont

try:
    from fontTools.ttLib import TTFont
except ImportError:  # pragma: no cover - production image includes fontTools
    TTFont = None

FALLBACK_FONT_PATHS = (
    Path("/usr/share/fonts/truetype/unifont/unifont.ttf"),
    Path("/usr/share/fonts/truetype/unifont/unifont_sample.ttf"),
    Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
)

@lru_cache(maxsize=64)
def _font_codepoints(path: str, index: int) -> Optional[frozenset[int]]:
    if TTFont is None:
        return None
    loaded_font = None
    try:
        loaded_font = TTFont(path, fontNumber=index, lazy=True)
        return frozenset((loaded_font.getBestCmap() or {}).keys())
    except Exception:
        return None
    finally:
        if loaded_font is not None:
            loaded_font.close()

def font_supports_char(font: ImageFont.ImageFont, char: str) -> bool:
    if not char or char in "\r\n\t":
        return True
    path = str(getattr(font, "path", "") or "")
    if path:
        codepoints = _font_codepoints(path, int(getattr(font, "index", 0) or 0))
        if codepoints is not None:
            return ord(char) in codepoints
    try:
        glyph = font.getmask(char)
        missing = font.getmask("\U0010ffff")
        return (glyph.size, bytes(glyph)) != (missing.size, bytes(missing))
    except Exception:
        return True

@lru_cache(maxsize=32)
def _load_fallback_fonts(size_px: int) -> Tuple[ImageFont.ImageFont, ...]:
    fonts: List[ImageFont.ImageFont] = []
    for path in FALLBACK_FONT_PATHS:
        if not path.exists():
            continue
        try:
            fonts.append(ImageFont.truetype(str(path), size_px))
        except Exception:
            continue
    return tuple(fonts)

def font_runs(
    text: str, font: ImageFont.ImageFont
) -> List[Tuple[str, ImageFont.ImageFont]]:
    value = str(text)
    if not value or all(font_supports_char(font, char) for char in value):
        return [(value, font)]

    size_px = int(getattr(font, "size", 0) or 16)
    fallback_fonts = _load_fallback_fonts(size_px)
    runs: List[Tuple[str, ImageFont.ImageFont]] = []
    for char in value:
        selected_font = font
        if not font_supports_char(font, char):
            selected_font = next(
                (
                    candidate
                    for candidate in fallback_fonts
                    if font_supports_char(candidate, char)
                ),
                font,
            )
        if runs and runs[-1][1] is selected_font:
            runs[-1] = (runs[-1][0] + char, selected_font)
        else:
            runs.append((char, selected_font))
    return runs

def text_bbox(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    runs = font_runs(str(text), font)
    if len(runs) == 1 and runs[0][1] is font:
        return draw.textbbox((0, 0), str(text), font=font)
    cursor = 0.0
    bounds: List[Tuple[int, int, int, int]] = []
    for run_text, run_font in runs:
        bounds.append(draw.textbbox((cursor, 0), run_text, font=run_font))
        cursor += float(draw.textlength(run_text, font=run_font))
    if not bounds:
        return (0, 0, 0, 0)
    return (
        min(item[0] for item in bounds),
        min(item[1] for item in bounds),
        max(item[2] for item in bounds),
        max(item[3] for item in bounds),
    )

def draw_text(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float],
    text: str,
    font: ImageFont.ImageFont,
    fill,
    *,
    stroke_fill=None,
    stroke_width: int = 0,
) -> None:
    cursor, y = xy
    for run_text, run_font in font_runs(str(text), font):
        draw.text(
            (cursor, y),
            run_text,
            font=run_font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )
        cursor += float(draw.textlength(run_text, font=run_font))
