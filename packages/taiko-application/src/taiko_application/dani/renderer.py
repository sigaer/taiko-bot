"""Pillow Dani renderer. Reads only caller-selected presentation assets."""

from __future__ import annotations

import io
from typing import Any, Dict, List, Optional, Tuple
import os
from contextlib import closing
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .models import DaniAssets, DaniProgress
from .common import (
    WHITE,
    BLACK,
    TEXT_MAIN,
    TEXT_SUB,
    CARD_FILL,
    CARD_STROKE,
    FOOTER_FILL,
    FOOTER_STROKE,
    RATE_BAR_BG,
    _difficulty_level,
    _metric_display_text,
    _safe_int,
    _status_color,
)


class DaniProgressRenderer:
    def __init__(self, assets: DaniAssets):
        self.assets = assets
        self._images = {}

    def close(self):
        for image in self._images.values():
            if image is not None:
                image.close()
        self._images.clear()

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype(str(self.assets.font), size)
        except Exception:
            return ImageFont.load_default()

    def _load_ddfont(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        try:
            return ImageFont.truetype(str(self.assets.ddfont), size)
        except Exception:
            return self._load_font(size)

    def _font_y_offset(self, font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
        font_path = str(getattr(font, "path", "") or "")
        size = int(getattr(font, "size", 0) or 0)
        if "DDFont" not in font_path or size <= 0:
            return 0
        return int(round(size * ratio))

    def _draw_text_with_stroke(
        self,
        draw: ImageDraw.ImageDraw,
        pos: Tuple[float, float],
        text: str,
        font: ImageFont.ImageFont,
        fill: Tuple[int, int, int],
        stroke_width: int = 3,
        stroke_fill: Tuple[int, int, int] = BLACK,
        anchor: Optional[str] = None,
    ) -> None:
        x, y = pos
        y += self._font_y_offset(font)
        try:
            draw.text(
                (x, y),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
                anchor=anchor,
            )
        except TypeError:
            for dx in range(-stroke_width, stroke_width + 1):
                for dy in range(-stroke_width, stroke_width + 1):
                    if dx == 0 and dy == 0:
                        continue
                    draw.text(
                        (x + dx, y + dy),
                        text,
                        font=font,
                        fill=stroke_fill,
                        anchor=anchor,
                    )
            draw.text((x, y), text, font=font, fill=fill, anchor=anchor)

    def _truncate_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_width: int,
    ) -> str:
        if draw.textlength(text, font=font) <= max_width:
            return text
        ellipsis = "…"
        if draw.textlength(ellipsis, font=font) >= max_width:
            return ellipsis
        left = 0
        right = len(text)
        while left < right:
            mid = (left + right + 1) // 2
            candidate = text[:mid] + ellipsis
            if draw.textlength(candidate, font=font) <= max_width:
                left = mid
            else:
                right = mid - 1
        return text[:left] + ellipsis

    def _render_notice(self, text: str) -> bytes:
        with Image.open(self.assets.upper) as source, closing(
            source.convert("RGBA")
        ) as base:
            with closing(Image.new("RGBA", base.size, (0, 0, 0, 0))) as overlay:
                draw = ImageDraw.Draw(overlay)
                draw.rounded_rectangle(
                    (132, 208, 1148, 512), radius=36, fill=(255, 251, 244, 240)
                )
                self._draw_text_with_stroke(
                    draw,
                    (640, 272),
                    "段位进度",
                    self._load_font(42),
                    WHITE,
                    4,
                    BLACK,
                    "mm",
                )
                self._draw_text_with_stroke(
                    draw,
                    (640, 372),
                    text,
                    self._load_font(28),
                    TEXT_MAIN,
                    3,
                    WHITE,
                    "mm",
                )
                base.alpha_composite(overlay)
            buf = io.BytesIO()
            with closing(base.convert("RGB")) as converted:
                converted.save(buf, format="PNG", optimize=True)
            return buf.getvalue()

    def _load_rgba(self, path: str) -> Optional[Image.Image]:
        if path in self._images:
            return self._images[path]
        if not path or not os.path.exists(path):
            return None
        try:
            with Image.open(path) as source:
                image = source.convert("RGBA")
        except Exception:
            return None
        # A Dani image uses fewer than 64 icons. Refuse accidental unbounded assets.
        if len(self._images) >= 64:
            image.close()
            raise ValueError("Too many Dani presentation assets")
        self._images[path] = image
        return image

    def _paste_fit(
        self,
        base: Image.Image,
        image: Optional[Image.Image],
        box: Tuple[int, int, int, int],
    ) -> None:
        if image is None:
            return
        x1, y1, x2, y2 = box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        ratio = min(width / image.width, height / image.height)
        size = (
            max(1, int(round(image.width * ratio))),
            max(1, int(round(image.height * ratio))),
        )
        resized = image.resize(size, Image.LANCZOS)
        pos = (x1 + (width - resized.width) // 2, y1 + (height - resized.height) // 2)
        base.alpha_composite(resized, pos)

    def _paste_stretch(
        self,
        base: Image.Image,
        image: Optional[Image.Image],
        box: Tuple[int, int, int, int],
    ) -> None:
        if image is None:
            return
        x1, y1, x2, y2 = box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        resized = image.resize((width, height), Image.LANCZOS)
        base.alpha_composite(resized, (x1, y1))

    def _icon_path(self, index: int) -> str:
        return str(self.assets.dani_icons / f"{index}.png")

    def _diff_icon_path(self, level: Any) -> str:
        return str(self.assets.difficulty_icons / f"{_difficulty_level(level)}.png")

    def _render_progress_fill(
        self, width: int, height: int, color: Tuple[int, int, int]
    ) -> Image.Image:
        image = Image.new("RGBA", (max(1, width), max(1, height)), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (0, 0, image.width - 1, image.height - 1),
            radius=height // 2,
            fill=(*color, 255),
        )
        return image

    def _render_metric_bar(
        self,
        base: Image.Image,
        box: Tuple[int, int, int, int],
        ratio: float,
        icon_index: int,
        text: str,
    ) -> None:
        x1, y1, x2, y2 = box
        draw = ImageDraw.Draw(base)
        draw.rounded_rectangle(box, radius=(y2 - y1) // 2, fill=RATE_BAR_BG)
        width = x2 - x1
        progress = max(0.0, min(1.0, ratio))
        fill_w = int(round(width * progress))
        if fill_w > 0:
            fill = self._render_progress_fill(
                fill_w, y2 - y1, _status_color(icon_index)
            )
            base.alpha_composite(fill, (x1, y1))
        font = self._load_font(20)
        self._draw_text_with_stroke(
            draw, ((x1 + x2) / 2, (y1 + y2) / 2 - 1), text, font, WHITE, 2, BLACK, "mm"
        )

    def _overlay_fill(
        self,
        base: Image.Image,
        fill_src: Optional[Image.Image],
        box: Tuple[int, int, int, int],
        ratio: float,
    ) -> None:
        if fill_src is None or ratio <= 0:
            return
        x1, y1, x2, y2 = box
        width = x2 - x1
        height = y2 - y1
        fill_w = max(1, int(round(width * min(1.0, max(0.0, ratio)))))
        resized = fill_src.resize((width, height), Image.LANCZOS).crop(
            (0, 0, fill_w, height)
        )
        base.alpha_composite(resized.convert("RGBA"), (x1, y1))

    def _render_single_bar(
        self,
        base: Image.Image,
        box: Tuple[int, int, int, int],
        text: str,
        ratio: float,
        icon_index: int,
    ) -> None:
        bg = self._load_rgba(str(self.assets.dani_icons / "bar.png"))
        pass_fill = self._load_rgba(str(self.assets.dani_icons / "bar_4.png"))
        gold_fill = self._load_rgba(str(self.assets.dani_icons / "bar_5.png"))
        self._paste_stretch(base, bg, box)
        if icon_index in {3, 5, 7}:
            self._overlay_fill(base, gold_fill, box, 1.0 if ratio > 0 else 0.0)
        elif icon_index in {2, 4, 6}:
            self._overlay_fill(base, pass_fill, box, 1.0 if ratio > 0 else 0.0)
        draw = ImageDraw.Draw(base)
        font = self._load_font(22)
        self._draw_text_with_stroke(
            draw,
            ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2 - 1),
            text,
            font,
            WHITE,
            3,
            BLACK,
            "mm",
        )

    def _render_segmented_bar(
        self,
        base: Image.Image,
        box: Tuple[int, int, int, int],
        segment_ratios: List[float],
        segment_icons: List[int],
        text: str = "",
        segment_texts: Optional[List[str]] = None,
    ) -> None:
        bg = self._load_rgba(str(self.assets.dani_icons / "bar.png"))
        pass_fill = self._load_rgba(str(self.assets.dani_icons / "bar_4.png"))
        gold_fill = self._load_rgba(str(self.assets.dani_icons / "bar_5.png"))
        self._paste_stretch(base, bg, box)
        x1, y1, x2, y2 = box
        total_w = x2 - x1
        gap = 6
        segment_count = max(
            1, len(segment_ratios), len(segment_icons), len(segment_texts or [])
        )
        seg_w = (total_w - gap * max(0, segment_count - 1)) // segment_count
        for idx in range(segment_count):
            sx1 = x1 + idx * (seg_w + gap)
            sx2 = sx1 + seg_w
            seg_box = (sx1, y1 + 6, sx2, y2 - 6)
            icon_index = segment_icons[idx] if idx < len(segment_icons) else 1
            if icon_index in {3, 5, 7}:
                self._overlay_fill(base, gold_fill, seg_box, 1.0)
            elif icon_index in {2, 4, 6}:
                self._overlay_fill(base, pass_fill, seg_box, 1.0)
        draw = ImageDraw.Draw(base)
        for idx in range(max(0, segment_count - 1)):
            divider_x = x1 + (idx + 1) * seg_w + idx * gap + gap // 2
            draw.line(
                (divider_x, y1 + 5, divider_x, y2 - 5),
                fill=(255, 245, 228, 168),
                width=2,
            )
        if segment_texts:
            font = self._load_font(20)
            for idx in range(segment_count):
                sx1 = x1 + idx * (seg_w + gap)
                sx2 = sx1 + seg_w
                label = segment_texts[idx] if idx < len(segment_texts) else ""
                if label:
                    self._draw_text_with_stroke(
                        draw,
                        ((sx1 + sx2) / 2, (y1 + y2) / 2 - 1),
                        label,
                        font,
                        WHITE,
                        3,
                        BLACK,
                        "mm",
                    )
        elif text:
            font = self._load_font(22)
            self._draw_text_with_stroke(
                draw,
                ((x1 + x2) / 2, (y1 + y2) / 2 - 1),
                text,
                font,
                WHITE,
                3,
                BLACK,
                "mm",
            )

    def _card_row_centers(self, box: Tuple[int, int, int, int]) -> List[float]:
        x1, y1, x2, y2 = box
        padding_top = 18
        padding_bottom = 18
        usable = y2 - y1 - padding_top - padding_bottom
        step = usable / 7.0
        return [y1 + padding_top + step * idx + step / 2 for idx in range(7)]

    def _song_order_label(self, index: int) -> str:
        numerals = "一二三四五六七八九十"
        if 1 <= index <= len(numerals):
            return f"曲{numerals[index - 1]}"
        return f"曲{index}"

    def _draw_card(
        self,
        base: Image.Image,
        draw: ImageDraw.ImageDraw,
        song_runtime: Dict[str, Any],
        grade_has_bad_target: bool,
        grade_has_drumroll_target: bool,
        box: Tuple[int, int, int, int],
    ) -> None:
        shadow = Image.new("RGBA", base.size, (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(shadow)
        x1, y1, x2, y2 = box
        sdraw.rounded_rectangle(
            (x1 + 10, y1 + 12, x2 + 10, y2 + 12), radius=28, fill=(0, 0, 0, 44)
        )
        base.alpha_composite(shadow)
        draw.rounded_rectangle(
            box, radius=28, fill=CARD_FILL, outline=CARD_STROKE, width=4
        )
        label_font = self._load_font(26)
        song_font = self._load_ddfont(24)
        score_font = self._load_font(46)
        stat_font = self._load_font(26)
        centers = self._card_row_centers(box)
        inner_x1 = x1 + 22
        inner_x2 = x2 - 22
        self._draw_text_with_stroke(
            draw,
            ((x1 + x2) / 2, centers[0]),
            self._song_order_label(_safe_int(song_runtime.get("index"), 1)),
            label_font,
            (255, 141, 110),
            3,
            BLACK,
            "mm",
        )
        diff_icon = self._load_rgba(
            self._diff_icon_path(song_runtime["song"]["difficulty"])
        )
        diff_font = label_font
        diff_text = f"★ {song_runtime['star']}"
        diff_text_width = draw.textlength(diff_text, font=diff_font)
        diff_gap = 12
        icon_max_w = 128
        icon_max_h = 68
        icon_w = 0
        icon_h = 0
        if diff_icon is not None:
            ratio = min(icon_max_w / diff_icon.width, icon_max_h / diff_icon.height)
            icon_w = max(1, int(round(diff_icon.width * ratio)))
            icon_h = max(1, int(round(diff_icon.height * ratio)))
        total_w = icon_w + (diff_gap if icon_w > 0 else 0) + diff_text_width
        group_x1 = int(round((x1 + x2) / 2 - total_w / 2))
        icon_y = int(round(centers[1] - icon_h / 2))
        if diff_icon is not None:
            base.alpha_composite(
                diff_icon.resize((icon_w, icon_h), Image.LANCZOS), (group_x1, icon_y)
            )
        text_x = group_x1 + icon_w + (diff_gap if icon_w > 0 else 0)
        self._draw_text_with_stroke(
            draw, (text_x, centers[1]), diff_text, diff_font, TEXT_MAIN, 3, WHITE, "lm"
        )
        title = self._truncate_text(
            draw, song_runtime["song"]["title"], song_font, inner_x2 - inner_x1 - 12
        )
        self._draw_text_with_stroke(
            draw,
            ((x1 + x2) / 2, centers[2]),
            title,
            song_font,
            TEXT_MAIN,
            3,
            WHITE,
            "mm",
        )
        if song_runtime["entry"] is None:
            status_text = str(song_runtime.get("statusText") or "未游玩")
            self._draw_text_with_stroke(
                draw,
                ((x1 + x2) / 2, centers[3]),
                status_text,
                score_font,
                (171, 174, 184),
                4,
                BLACK,
                "mm",
            )
        else:
            self._draw_text_with_stroke(
                draw,
                ((x1 + x2) / 2, centers[3]),
                str(song_runtime["counts"]["score"]),
                score_font,
                WHITE,
                4,
                BLACK,
                "mm",
            )
        primary_metric = song_runtime["primaryMetric"]
        primary_has_icon = bool(primary_metric.get("comparable"))
        primary_bar_box = (
            inner_x1 + 8,
            int(centers[4] - 15),
            inner_x2 - (84 if primary_has_icon else 8),
            int(centers[4] + 15),
        )
        primary_text = _metric_display_text(
            primary_metric["kind"],
            primary_metric["current"],
            primary_metric["passTarget"],
            has_entry=song_runtime["entry"] is not None,
            estimated=bool(primary_metric.get("estimated")),
        )
        self._render_metric_bar(
            base,
            primary_bar_box,
            float(primary_metric.get("ratio", 0.0)),
            primary_metric["icon"] if primary_has_icon else 0,
            primary_text,
        )
        if primary_has_icon:
            self._paste_fit(
                base,
                self._load_rgba(self._icon_path(primary_metric["icon"])),
                (
                    inner_x2 - 72,
                    int(centers[4] - 28),
                    inner_x2 - 8,
                    int(centers[4] + 28),
                ),
            )
        miss_has_icon = bool(
            grade_has_bad_target and song_runtime.get("missComparable")
        )
        miss_text = (
            _metric_display_text(
                "bad",
                song_runtime["counts"]["bad"],
                song_runtime["passBadTarget"],
                has_entry=song_runtime["entry"] is not None,
                estimated=bool(song_runtime.get("missEstimated")),
            )
            if miss_has_icon
            else (
                "不可 --"
                if song_runtime["entry"] is None
                else f"不可 {song_runtime['counts']['bad']}"
            )
        )
        miss_x = (x1 + x2) / 2 - 12 if miss_has_icon else (x1 + x2) / 2
        self._draw_text_with_stroke(
            draw, (miss_x, centers[5]), miss_text, stat_font, TEXT_SUB, 3, WHITE, "mm"
        )
        if miss_has_icon:
            self._paste_fit(
                base,
                self._load_rgba(self._icon_path(song_runtime["missIcon"])),
                (
                    inner_x2 - 72,
                    int(centers[5] - 28),
                    inner_x2 - 8,
                    int(centers[5] + 28),
                ),
            )
        drumroll_has_icon = bool(
            grade_has_drumroll_target and song_runtime.get("drumrollComparable")
        )
        drumroll_text = (
            _metric_display_text(
                "drumroll",
                song_runtime["counts"]["drumroll"],
                song_runtime["passDrumrollTarget"],
                has_entry=song_runtime["entry"] is not None,
                estimated=bool(song_runtime.get("drumrollEstimated")),
            )
            if drumroll_has_icon
            else (
                "连打 --"
                if song_runtime["entry"] is None
                else f"连打 {song_runtime['counts']['drumroll']}"
            )
        )
        drumroll_x = (x1 + x2) / 2 - 12 if drumroll_has_icon else (x1 + x2) / 2
        self._draw_text_with_stroke(
            draw,
            (drumroll_x, centers[6]),
            drumroll_text,
            stat_font,
            TEXT_SUB,
            3,
            WHITE,
            "mm",
        )
        if drumroll_has_icon:
            self._paste_fit(
                base,
                self._load_rgba(self._icon_path(song_runtime["drumrollIcon"])),
                (
                    inner_x2 - 72,
                    int(centers[6] - 28),
                    inner_x2 - 8,
                    int(centers[6] + 28),
                ),
            )

    def _footer_value_text(self, row: Dict[str, Any]) -> str:
        if row.get("unavailable"):
            return "暂无数据"
        if row["kind"] == "rate":
            return f"{row['current']:.2f}% / {row['pass']:.2f}%"
        if row["kind"] == "gauge":
            return f"{int(row['current'])}% / {int(row['pass'])}%"
        if row["kind"] in {"bad", "ok"}:
            return f"{row['current']} / {row['pass']}"
        return f"{int(row['current'])} / {int(row['pass'])}"

    def _section_height(
        self, footer_rows: List[Dict[str, Any]], *, large_title_icon: bool = False
    ) -> int:
        base_height = 726 + len(footer_rows) * 64
        if large_title_icon:
            return base_height + 104
        return base_height

    def _draw_progress_section(
        self,
        canvas: Image.Image,
        section_top: int,
        title: str,
        grade: Dict[str, Any],
        songs_runtime: List[Dict[str, Any]],
        footer_rows: List[Dict[str, Any]],
        *,
        title_icon: Optional[int] = None,
    ) -> None:
        draw = ImageDraw.Draw(canvas)
        title_font = self._load_font(44)
        has_large_title_icon = bool(title_icon and title_icon > 0)
        title_y = section_top + (100 if has_large_title_icon else 46)
        if has_large_title_icon:
            icon_size = 176
            icon_gap = 30
            title_width = int(round(draw.textlength(title, font=title_font)))
            group_width = title_width + icon_gap + icon_size
            group_x1 = int(round((1280 - group_width) / 2))
            title_x = group_x1 + title_width / 2
            self._draw_text_with_stroke(
                draw, (title_x, title_y), title, title_font, WHITE, 4, BLACK, "mm"
            )
            icon_left = group_x1 + title_width + icon_gap
            self._paste_fit(
                canvas,
                self._load_rgba(self._icon_path(title_icon)),
                (
                    icon_left,
                    section_top + 12,
                    icon_left + icon_size,
                    section_top + 12 + icon_size,
                ),
            )
        else:
            self._draw_text_with_stroke(
                draw, (640, title_y), title, title_font, WHITE, 4, BLACK, "mm"
            )
        main_x1 = 36
        main_x2 = 1244
        main_y1 = section_top + (202 if has_large_title_icon else 98)
        main_y2 = main_y1 + 488
        footer_x1 = 54
        footer_x2 = 1226
        footer_y1 = main_y2 + 28
        footer_y2 = (
            section_top
            + self._section_height(footer_rows, large_title_icon=has_large_title_icon)
            - 28
        )
        draw.rounded_rectangle(
            (main_x1, main_y1, main_x2, main_y2),
            radius=34,
            fill=(255, 247, 238, 110),
            outline=(255, 248, 229, 176),
            width=2,
        )
        draw.rounded_rectangle(
            (footer_x1, footer_y1, footer_x2, footer_y2),
            radius=30,
            fill=FOOTER_FILL,
            outline=FOOTER_STROKE,
            width=2,
        )
        self._draw_text_with_stroke(
            draw,
            (footer_x1 + 36, footer_y1 + 28),
            "总和条件",
            self._load_font(28),
            (255, 191, 133),
            3,
            BLACK,
            "lm",
        )
        draw.line(
            (footer_x1 + 28, footer_y1 + 48, footer_x2 - 28, footer_y1 + 48),
            fill=(255, 228, 187, 120),
            width=2,
        )
        card_count = max(1, len(songs_runtime))
        gap = 24
        total_gap = gap * max(0, card_count - 1)
        card_w = (main_x2 - main_x1 - total_gap) // card_count
        grade_has_bad_target = (
            grade["conditions"]["pass"].get("badCountLessThan") is not None
        )
        grade_has_drumroll_target = (
            grade["conditions"]["pass"].get("drumrollCountAtLeast") is not None
        )
        for idx, runtime in enumerate(songs_runtime):
            x1 = main_x1 + idx * (card_w + gap)
            x2 = x1 + card_w
            self._draw_card(
                canvas,
                draw,
                runtime,
                grade_has_bad_target,
                grade_has_drumroll_target,
                (x1, main_y1, x2, main_y2),
            )
        label_font = self._load_font(24)
        row_top = footer_y1 + 66
        icon_size = 58
        for row in footer_rows:
            cy = row_top + 28
            self._paste_fit(
                canvas,
                self._load_rgba(self._icon_path(row["icon"])),
                (
                    footer_x1 + 18,
                    cy - icon_size // 2,
                    footer_x1 + 18 + icon_size,
                    cy + icon_size // 2,
                ),
            )
            self._draw_text_with_stroke(
                draw,
                (footer_x1 + 92, cy),
                row["label"],
                label_font,
                WHITE,
                3,
                BLACK,
                "lm",
            )
            bar_box = (footer_x1 + 280, row_top + 2, footer_x2 - 28, row_top + 54)
            bar_text = self._footer_value_text(row)
            if row["segmented"]:
                self._render_segmented_bar(
                    canvas,
                    bar_box,
                    row["segmentRatios"],
                    row["segmentIcons"],
                    text=bar_text,
                    segment_texts=row.get("segmentTexts"),
                )
            else:
                self._render_single_bar(
                    canvas, bar_box, bar_text, row["ratio"], row["icon"]
                )
            row_top += 64

    def _render_section_background(self, path: Path, height: int) -> Image.Image:
        with Image.open(path) as source, closing(source.convert("RGBA")) as rgba:
            return rgba.resize((1280, height), Image.LANCZOS)

    def render(self, progress: DaniProgress) -> bytes:
        """Render a prepared model; owns and releases all cached icon images."""
        try:
            if progress.notice is not None:
                return self._render_notice(progress.notice)
            heights = [
                self._section_height(s.footer, large_title_icon=s.title_icon > 0)
                for s in progress.sections
            ]
            with closing(
                Image.new("RGBA", (1280, sum(heights)), (0, 0, 0, 0))
            ) as canvas:
                top = 0
                for index, (section, height) in enumerate(
                    zip(progress.sections, heights)
                ):
                    path = self.assets.upper if index == 0 else self.assets.lower
                    background = self._render_section_background(path, height)
                    try:
                        canvas.alpha_composite(background, (0, top))
                    finally:
                        background.close()
                    self._draw_progress_section(
                        canvas,
                        top,
                        section.title,
                        progress.grade,
                        section.songs,
                        section.footer,
                        title_icon=section.title_icon,
                    )
                    top += height
                buf = io.BytesIO()
                converted = canvas.convert("RGB")
                try:
                    converted.save(buf, format="PNG", optimize=True)
                finally:
                    converted.close()
                return buf.getvalue()
        finally:
            self.close()
