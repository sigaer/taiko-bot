from __future__ import annotations
from .resources import RenderResources
import io
import os
from pathlib import Path
from typing import List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from .context import ScorePresentationContext


class RecommendationRenderer(RenderResources):

    def __init__(self, context: ScorePresentationContext):
        self.context = context
        self.ASSETS_DIR = Path(context.layout_assets_base or context.assets_base)
        self.FONT_TITLE_PATH = self.ASSETS_DIR / "fonts/FZPW_GBK.ttf"
        self.FONT_DD_PATH = self.ASSETS_DIR / "fonts/DDFont.ttf"
        self.PROGRESS_BG_PATH = (
            context.background_path or self.ASSETS_DIR / "templates/progress_bg.png"
        )
        self.SONG_STAR_MAP = context.song_star_map
        self._ICON_CACHE = {}

    def _load_font(
        self, font_path: str | None, size: int
    ) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if font_path and os.path.exists(font_path):
            try:
                return ImageFont.truetype(font_path, size)
            except Exception:
                pass
        return ImageFont.load_default()

    def _draw_text_with_font_drop(
        self,
        draw: ImageDraw.ImageDraw,
        pos: Tuple[float, float],
        text: str,
        *,
        font: ImageFont.ImageFont,
        fill,
        **kwargs,
    ) -> None:
        x, y = pos
        draw.text((x, y), text, font=font, fill=fill, **kwargs)

    def _truncate_to_width(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.ImageFont,
        max_w: int,
    ) -> str:
        if draw.textlength(text, font=font) <= max_w:
            return text
        ellipsis = "…"
        if draw.textlength(ellipsis, font=font) > max_w:
            return ""
        left, right = (0, len(text))
        while left < right:
            mid = (left + right) // 2
            candidate = text[:mid] + ellipsis
            if draw.textlength(candidate, font=font) <= max_w:
                left = mid + 1
            else:
                right = mid
        return text[: right - 1] + ellipsis if right > 0 else ellipsis

    def _load_icon_cached(self, path: str, size: int) -> Optional[Image.Image]:
        if not path or not os.path.exists(path):
            return None
        try:
            icon = self._own(self._own(Image.open(path)).convert("RGBA"))
            if size > 0:
                width, height = icon.size
                if height != size:
                    new_width = max(1, int(round(width * size / max(1, height))))
                    icon = self._own(icon.resize((new_width, size), Image.LANCZOS))
            return icon
        except Exception:
            return None

    def _crop_box_with_pad(
        self, image: Image.Image, box: Tuple[int, int, int, int], pad: int = 4
    ) -> Image.Image:
        x1, y1, x2, y2 = box
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(image.width, x2 + pad)
        y2 = min(image.height, y2 + pad)
        return self._own(image.crop((x1, y1, x2, y2)))

    def _draw_vertical_gradient(
        self,
        img: Image.Image,
        top: Tuple[int, int, int],
        mid: Tuple[int, int, int],
        bottom: Tuple[int, int, int],
    ) -> None:
        width, height = img.size
        px = img.load()
        half = max(1, height // 2)
        for y in range(height):
            if y < half:
                ratio = y / max(1, half - 1)
                color = tuple(
                    (
                        int(round(top[index] + (mid[index] - top[index]) * ratio))
                        for index in range(3)
                    )
                )
            else:
                ratio = (y - half) / max(1, height - half - 1)
                color = tuple(
                    (
                        int(round(mid[index] + (bottom[index] - mid[index]) * ratio))
                        for index in range(3)
                    )
                )
            for x in range(width):
                px[x, y] = (*color, 255)

    def _draw_cell_text(
        self,
        draw: ImageDraw.ImageDraw,
        box: Tuple[int, int, int, int],
        text: str,
        *,
        font: ImageFont.ImageFont,
        fill,
        center: bool = True,
        padding_x: int = 10,
    ) -> None:
        text = str(text)
        text_box = draw.textbbox((0, 0), text, font=font)
        text_w = text_box[2] - text_box[0]
        text_h = text_box[3] - text_box[1]
        x1, y1, x2, y2 = box
        if center:
            text_x = x1 + max(0, (x2 - x1 - text_w) // 2)
        else:
            text_x = x1 + padding_x
        text_y = y1 + max(0, (y2 - y1 - text_h) // 2) - 1
        self._draw_text_with_font_drop(
            draw, (text_x, text_y), text, font=font, fill=fill
        )

    def _render(self):
        recs = self.context.recommendations
        title = self.context.title
        subtitle = self.context.subtitle
        assets_base = self.context.assets_base
        font_path = self.context.font_path or str(assets_base / "fonts/DDFont.ttf")
        title_row_h = 96 if subtitle else 74
        header_h = 58
        row_h = 56
        top_gap = 16
        bottom_pad = 24
        table_w = 1608
        pad = 24
        profile_panel = self.context.profile_panel
        if profile_panel is None:
            profile_panel = self._own(Image.new("RGBA", (0, 0)))
        top_area_h = max(
            profile_panel.height + top_gap, 130 if profile_panel.height > 0 else 48
        )
        row_count = max(1, len(recs))
        panel_h = title_row_h + header_h + row_count * row_h + 14
        img_w = table_w + pad * 2
        img_h = pad + top_area_h + panel_h + bottom_pad
        img = self._own(Image.new("RGBA", (img_w, img_h), (255, 255, 255, 255)))
        if self.PROGRESS_BG_PATH.exists():
            try:
                bg = self._own(
                    self._own(Image.open(self.PROGRESS_BG_PATH)).convert("RGBA")
                )
                bg = self._own(bg.resize((img_w, img_h), Image.LANCZOS))
                img.alpha_composite(bg, (0, 0))
            except Exception:
                self._draw_vertical_gradient(
                    img, top=(96, 214, 171), mid=(136, 212, 188), bottom=(236, 134, 145)
                )
        else:
            self._draw_vertical_gradient(
                img, top=(96, 214, 171), mid=(136, 212, 188), bottom=(236, 134, 145)
            )
        draw = ImageDraw.Draw(img)
        panel_x = pad
        panel_y = pad + top_area_h
        draw.rounded_rectangle(
            (panel_x, panel_y, panel_x + table_w, panel_y + panel_h),
            radius=14,
            fill=(245, 250, 243, 206),
            outline=(186, 199, 176, 232),
            width=3,
        )
        if profile_panel.width > 0 and profile_panel.height > 0:
            img.alpha_composite(profile_panel, (panel_x + 8, pad))
        title_font = self._load_font(font_path, 48 if subtitle else 52)
        subtitle_font = self._load_font(font_path, 22)
        header_font = self._load_font(font_path, 24)
        row_font = self._load_font(font_path, 24)
        value_font = self._load_font(font_path, 22)
        cols = [
            ("难度", 96),
            ("ID", 92),
            ("星级", 92),
            ("曲名", 440),
            ("未游玩", 112),
            ("谱面指标", 150),
            ("用户中位数", 150),
            ("指标偏差", 170),
            ("精度", 150),
            ("推荐指数", 156),
        ]
        col_starts: List[int] = []
        cursor_x = panel_x + 2
        for _, col_width in cols:
            col_starts.append(cursor_x)
            cursor_x += col_width
        title_row_y = panel_y + 8
        draw.rounded_rectangle(
            (
                panel_x + 8,
                title_row_y,
                panel_x + table_w - 8,
                title_row_y + title_row_h - 6,
            ),
            radius=10,
            fill=(218, 226, 205, 228),
        )
        full_title = f"{title} · 共{len(recs)}首" if recs else title
        title_bbox = draw.textbbox((0, 0), full_title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        title_h = title_bbox[3] - title_bbox[1]
        title_x = panel_x + (table_w - title_w) // 2
        if subtitle:
            title_y = title_row_y + 12
            subtitle_text = str(subtitle).strip()
            subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=subtitle_font)
            subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
            subtitle_x = panel_x + (table_w - subtitle_w) // 2
            subtitle_y = title_y + title_h + 4
            self._draw_text_with_font_drop(
                draw,
                (title_x, title_y),
                full_title,
                font=title_font,
                fill=(44, 69, 58, 238),
            )
            self._draw_text_with_font_drop(
                draw,
                (subtitle_x, subtitle_y),
                subtitle_text,
                font=subtitle_font,
                fill=(78, 92, 82, 240),
            )
        else:
            title_y = title_row_y + (title_row_h - title_h) // 2 - 2
            self._draw_text_with_font_drop(
                draw,
                (title_x, title_y),
                full_title,
                font=title_font,
                fill=(44, 69, 58, 238),
            )
        header_y = title_row_y + title_row_h
        draw.rounded_rectangle(
            (panel_x + 8, header_y, panel_x + table_w - 8, header_y + header_h - 6),
            radius=10,
            fill=(221, 228, 210, 220),
        )
        for (label, col_width), col_x in zip(cols, col_starts):
            if not label:
                continue
            label_x = col_x + (col_width - draw.textlength(label, font=header_font)) / 2
            self._draw_text_with_font_drop(
                draw,
                (label_x, header_y + 12),
                label,
                font=header_font,
                fill=(53, 67, 57, 255),
            )
        if not recs:
            notice_top = panel_y + title_row_h + header_h + 8
            notice_bot = notice_top + row_h - 4
            draw.rounded_rectangle(
                (panel_x + 8, notice_top, panel_x + table_w - 8, notice_bot),
                radius=8,
                fill=(246, 248, 244, 126),
            )
            self._draw_cell_text(
                draw,
                (panel_x + 40, notice_top, panel_x + table_w - 40, notice_bot),
                "暂无可推荐曲目（可能曲库匹配失败或数据不足）",
                font=row_font,
                fill=(59, 62, 66, 248),
            )
            buf = io.BytesIO()
            self._own(img.convert("RGB")).save(buf, format="PNG", optimize=True)
            buf.seek(0)
            return buf
        scores = [float(row.get("recommend_score", 0.0) or 0.0) for row in recs]
        score_min = min(scores)
        score_max = max(scores)
        score_denominator = score_max - score_min or 1.0
        for row_index, row in enumerate(recs):
            row_top = panel_y + title_row_h + header_h + 8 + row_index * row_h
            row_bot = row_top + row_h - 4
            is_unplayed = bool(row.get("is_unplayed", False))
            if is_unplayed:
                fill = (
                    (234, 243, 255, 180) if row_index % 2 == 0 else (240, 247, 255, 160)
                )
            else:
                fill = (
                    (244, 239, 231, 150) if row_index % 2 == 0 else (246, 248, 244, 126)
                )
            draw.rounded_rectangle(
                (panel_x + 8, row_top, panel_x + table_w - 8, row_bot),
                radius=8,
                fill=fill,
            )
            song_id = int(row.get("song_id", 0) or 0)
            level = int(row.get("level", 4) or 4)
            diff_icon = self._load_icon_cached(
                str(Path(assets_base) / "icons" / "diff" / f"{level}.png"), 32
            )
            if diff_icon is not None:
                icon_x = col_starts[0] + (cols[0][1] - diff_icon.width) // 2
                icon_y = row_top + (row_h - diff_icon.height) // 2 - 2
                img.alpha_composite(diff_icon, (icon_x, icon_y))
            star_text = self.SONG_STAR_MAP.get((song_id, level), "-")
            title_text = self._truncate_to_width(
                draw, str(row.get("title", "")), row_font, cols[3][1] - 20
            )
            deviation = (
                float(row.get("indicator_deviation_percent", 0.0) or 0.0) * 100.0
            )
            accuracy = float(row.get("accuracy", 0.0) or 0.0) * 100.0
            song_indicator = float(row.get("song_indicator", 0.0) or 0.0)
            reference_indicator = float(row.get("reference_indicator", 0.0) or 0.0)
            raw_score = float(row.get("recommend_score", 0.0) or 0.0)
            recommend_index = (score_max - raw_score) / score_denominator * 100.0
            cell_values = [
                str(song_id or "-"),
                str(star_text),
                title_text,
                "是" if is_unplayed else "否",
                f"{song_indicator:.2f}",
                f"{reference_indicator:.2f}",
                f"{deviation:+.2f}%",
                "-" if is_unplayed else f"{accuracy:.2f}%",
                f"{recommend_index:.1f}",
            ]
            for col_offset, value in enumerate(cell_values, start=1):
                cell_x = col_starts[col_offset]
                cell_w = cols[col_offset][1]
                box = (cell_x, row_top, cell_x + cell_w, row_bot)
                if col_offset == 3:
                    self._draw_cell_text(
                        draw, box, value, font=row_font, fill=(44, 49, 53, 245)
                    )
                    continue
                if col_offset == 6:
                    if deviation < 0:
                        fill_color = (32, 116, 85, 255)
                    elif deviation > 0:
                        fill_color = (146, 67, 67, 255)
                    else:
                        fill_color = (59, 62, 66, 248)
                elif col_offset == 8:
                    if recommend_index >= 80:
                        fill_color = (32, 116, 85, 255)
                    elif recommend_index >= 60:
                        fill_color = (126, 91, 31, 255)
                    else:
                        fill_color = (146, 67, 67, 255)
                elif col_offset == 4 and is_unplayed:
                    fill_color = (52, 92, 148, 255)
                else:
                    fill_color = (59, 62, 66, 248)
                self._draw_cell_text(
                    draw,
                    box,
                    value,
                    font=value_font if col_offset != 3 else row_font,
                    fill=fill_color,
                )
        buf = io.BytesIO()
        self._own(img.convert("RGB")).save(buf, format="PNG", optimize=True)
        buf.seek(0)
        return buf
