from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Tuple

from PIL import Image, ImageFont

from taiko_bot.runtime.player.center.draw_dress import (
        ACH_BASE_SIZE,
        ACH_COL_X_FRAC,
        ACH_NUM_H_FRAC,
        ACH_NUM_W_FRAC,
        ACH_ROW1_X_FRAC,
        ACH_ROW_Y_FRAC,
    )

from taiko_bot.offline.paths import root as _runtime_root
ROOT_DIR = _runtime_root()
TEMPLATES_DIR = ROOT_DIR / "assets" / "templates"
RANK_DIR = ROOT_DIR / "assets" / "icons" / "rank"
CROWN_DIR = ROOT_DIR / "assets" / "icons" / "crown"
FONT_PATH = ROOT_DIR / "assets" / "fonts" / "DDFont.ttf"


def _resize_icon(icon: Image.Image, target_h: int) -> Image.Image:
    ow, oh = icon.size
    if ow <= 0 or oh <= 0:
        return icon
    scale = target_h / oh
    nw = max(1, int(round(ow * scale)))
    nh = max(1, int(round(oh * scale)))
    return icon.resize((nw, nh), Image.LANCZOS)


def _paste_icon(
    base: Image.Image,
    icon_path: Path,
    box_center_x: int,
    row_y: int,
    target_h: int,
    margin: int,
    text_width: int,
) -> None:
    if not icon_path.exists():
        return
    icon = Image.open(icon_path).convert("RGBA")
    icon = _resize_icon(icon, target_h)
    text_left = box_center_x - text_width // 2
    x = text_left - margin - icon.width
    y = row_y - icon.height // 2
    base.alpha_composite(icon, (x, y))


def _build_for_level(
    level: int,
    base_font_size: int = 20,
    output_suffix: str = "_panel",
) -> Path:
    src = TEMPLATES_DIR / f"bg_level_{level}.png"
    if not src.exists():
        raise FileNotFoundError(src)
    base = Image.open(src).convert("RGBA")

    target_w, target_h = base.size
    base_w, base_h = ACH_BASE_SIZE
    sx = target_w / base_w
    sy = target_h / base_h

    font_size = max(10, int(round(base_font_size * (sx + sy) / 2)))
    target_icon_h = max(8, int(round(font_size * 1.8)))
    margin = max(2, int(round(font_size * 0.15)))

    if FONT_PATH.exists():
        font = ImageFont.truetype(str(FONT_PATH), font_size)
    else:
        font = ImageFont.load_default()
    sample_text = "0000"
    bb = font.getbbox(sample_text)
    text_width = bb[2] - bb[0]

    num_w = int(round(base_w * ACH_NUM_W_FRAC * sx))
    num_h = int(round(base_h * ACH_NUM_H_FRAC * sy))

    row1_y = int(round(base_h * ACH_ROW_Y_FRAC[0] * sy))
    row2_y = int(round(base_h * ACH_ROW_Y_FRAC[1] * sy))
    row4_y = int(round(base_h * ACH_ROW_Y_FRAC[3] * sy))
    row4_y = row4_y - max(1, int(round(font_size / 2)))
    row3_y = int(round((row2_y + row4_y) / 2))

    row1_x = int(round(base_w * ACH_ROW1_X_FRAC * sx))
    col_x = [int(round(base_w * f * sx)) for f in ACH_COL_X_FRAC]

    _paste_icon(
        base,
        RANK_DIR / "8.png",
        row1_x,
        row1_y,
        min(target_icon_h, num_h),
        margin,
        text_width,
    )

    for icon_id, cx in zip((5, 6, 7), col_x):
        _paste_icon(
            base,
            RANK_DIR / f"{icon_id}.png",
            cx,
            row2_y,
            min(target_icon_h, num_h),
            margin,
            text_width,
        )

    for icon_id, cx in zip((2, 3, 4), col_x):
        _paste_icon(
            base,
            RANK_DIR / f"{icon_id}.png",
            cx,
            row3_y,
            min(target_icon_h, num_h),
            margin,
            text_width,
        )

    for icon_name, cx in zip(("clear.png", "full.png", "dondaful.png"), col_x):
        _paste_icon(
            base,
            CROWN_DIR / icon_name,
            cx,
            row4_y,
            min(target_icon_h, num_h),
            margin,
            text_width,
        )

    out_path = TEMPLATES_DIR / f"bg_level_{level}{output_suffix}.png"
    base.save(out_path)
    return out_path


def build_all(levels: Iterable[int] = range(1, 6)) -> List[Path]:
    outputs: List[Path] = []
    for level in levels:
        outputs.append(_build_for_level(level))
    return outputs


if __name__ == "__main__":
    paths = build_all()
    for p in paths:
        print(p)
