from __future__ import annotations
from .resources import RenderResources
import os
import math
from io import BytesIO
from pathlib import Path
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from .context import ScorePresentationContext

WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
BLUE = (38, 133, 222)
SIZE_TITLE = 27
SIZE_SCORE = 48
SIZE_STATS = 24
STROKE_TITLE = 2
STROKE_SCORE = 3
STROKE_STATS = 2
ART_POS = (95, 88)
ART_SIZE = (400, 400)
INFO_X = 755
POS_TITLE_EN = (INFO_X, 140)
POS_TITLE_JP = (INFO_X, 230)
POS_TYPE = (INFO_X, 323)
LEVEL_STEP_X = 62
POS_ID_BPM = (INFO_X - 90, 412)
ROW_Y = [585, 715, 845, 975, 1105]
OPTION_ICON_SIZE = (30, 30)
OPTION_ICON_MARGIN = 8
LEVEL_X = 165
LEVEL_Y_OFFSET = 30
SCORE_X = 190
SCORE_Y_OFFSET = -int(SIZE_SCORE / 2)
RANK_ICON_SIZE = (85, 85)
CROWN_ICON_SIZE = (85, 85)
AFTER_SCORE_GAP = 12
AFTER_RANK_GAP = 12
RANK_X_FIXED = 425
CROWN_X_FIXED = 535
STAT_COL_X_CENTER = 733
POUND_COL_X_CENTER = 955
STAT_Y_OFFSET = -35
STAT_LINE_H = 40
FONT_FILE_NAME = "DDFont.ttf"
RAW_DIM_KEYS = ["复合处理", "平均密度", "瞬间密度", "节奏处理", "BPM变化", "HS变化"]
RAW_DIM_VALUE_ALIASES = {
    "复合处理": ("复合处理",),
    "平均密度": ("平均密度",),
    "瞬间密度": ("瞬间密度",),
    "节奏处理": ("节奏处理", "叩き分け"),
    "BPM变化": ("BPM变化",),
    "HS变化": ("HS变化", "hs变化"),
}
PLAYER_DIM_KEYS = ["复合处理", "节奏处理", "精度力", "高速处理", "体力", "大歌力"]
RADAR_CARD_W = 420
RADAR_CARD_H = 1140
RADAR_CARD_GAP = 24
SIDE_PADDING = 24
RADAR_TOP_Y = 132
RADAR_RADIUS = 118
RADAR_GRID_STEPS = 5
DETAIL_PANEL_W = 500
DETAIL_PANEL_H = 550
DETAIL_PANEL_GAP = 22
DETAIL_SECTION_TOP_GAP = 28
DETAIL_PLAYER_LABEL_X = 268
DETAIL_PLAYER_VALUE_RIGHT_X = DETAIL_PANEL_W - 18
DETAIL_METRIC_MIN_GAP = 8
DETAIL_METRIC_FONT_SIZE = 20
DETAIL_METRIC_MIN_FONT_SIZE = 14
DETAIL_CONSTANT_COLUMN_CENTERS = (158, 292, 426)
TYPE_MAP = {
    "南梦宫原创音乐": "original",
    "流行音乐": "pop",
    "动漫音乐": "anime",
    "游戏音乐": "gamemusic",
    "博歌乐音乐": "vocaloid",
    "儿童音乐": "kid",
    "古典音乐": "classic",
    "综合音乐": "variety",
}


class ScoreInfoRenderer(RenderResources):

    def __init__(self, context: ScorePresentationContext):
        self.context = context
        self.ASSETS_DIR = Path(context.layout_assets_base or context.assets_base)
        self.FONT_TITLE_PATH = self.ASSETS_DIR / "fonts/FZPW_GBK.ttf"
        self.FONT_DD_PATH = self.ASSETS_DIR / "fonts/DDFont.ttf"
        self._ICON_CACHE = {}

    def _load_font(self, path: str, size: int) -> ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            return ImageFont.load_default()

    def _ddfont_y_offset(self, font: ImageFont.ImageFont, ratio: float = 0.1) -> int:
        font_path = str(getattr(font, "path", "") or "")
        size = int(getattr(font, "size", 0) or 0)
        if "DDFont" not in font_path or size <= 0:
            return 0
        return int(round(size * ratio))

    def _draw_text(self, draw: ImageDraw.ImageDraw, xy, text, font, fill):
        x, y = xy
        draw.text((x, y + self._ddfont_y_offset(font)), text, font=font, fill=fill)

    def _draw_text_with_stroke(
        self, draw: ImageDraw.ImageDraw, xy, text, font, fill, stroke_width, stroke_fill
    ):
        x, y = xy
        y += self._ddfont_y_offset(font)
        try:
            draw.text(
                (x, y),
                text,
                font=font,
                fill=fill,
                stroke_width=stroke_width,
                stroke_fill=stroke_fill,
            )
        except TypeError:
            for dx, dy in [
                (-stroke_width, 0),
                (stroke_width, 0),
                (0, -stroke_width),
                (0, stroke_width),
                (-stroke_width, -stroke_width),
                (-stroke_width, stroke_width),
                (stroke_width, -stroke_width),
                (stroke_width, stroke_width),
            ]:
                draw.text((x + dx, y + dy), text, font=font, fill=stroke_fill)
            draw.text((x, y), text, font=font, fill=fill)

    def _center_crop_to_square(self, im: Image.Image) -> Image.Image:
        w, h = im.size
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        return self._own(im.crop((left, top, left + side, top + side)))

    def _cover_resize_to_box(
        self, im: Image.Image, size: tuple[int, int]
    ) -> Image.Image:
        tw, th = size
        w, h = im.size
        if w <= 0 or h <= 0:
            return self._own(Image.new("RGBA", size, (242, 246, 252, 255)))
        scale = max(tw / w, th / h)
        nw = max(1, int(round(w * scale)))
        nh = max(1, int(round(h * scale)))
        resized = self._own(im.resize((nw, nh), Image.LANCZOS))
        left = (nw - tw) // 2
        top = (nh - th) // 2
        return self._own(resized.crop((left, top, left + tw, top + th)))

    def _paste_song_art(self, canvas: Image.Image, path: str, pos, size):
        if not os.path.exists(path):
            return
        art = self._own(self._own(Image.open(path)).convert("RGBA"))
        art = self._own(self._center_crop_to_square(art).resize(size, Image.LANCZOS))
        canvas.paste(art, pos, art)

    def _load_icon(self, path: Optional[str], size=None) -> Optional[Image.Image]:
        if not path or not os.path.exists(path):
            return None
        im = self._own(self._own(Image.open(path)).convert("RGBA"))
        if size:
            im = self._own(im.resize(size, Image.LANCZOS))
        return im

    def _rank_icon_path(self, assets_base: str, rank_value: int) -> str:
        return os.path.join(assets_base, "icons", "rank", f"{rank_value}.png")

    def _pick_crown_path(self, assets_base: str, entry: dict) -> Optional[str]:
        if entry.get("dondaful_combo_cnt", 0) > 0:
            return os.path.join(assets_base, "icons", "crown", "dondaful.png")
        if entry.get("full_combo_cnt", 0) > 0:
            return os.path.join(assets_base, "icons", "crown", "full.png")
        if entry.get("clear_cnt", 0) > 0:
            return os.path.join(assets_base, "icons", "crown", "clear.png")
        hiroba_crown = str(entry.get("_hiroba_crown") or "").strip().lower()
        if hiroba_crown in {"dondaful", "donderfull"}:
            return os.path.join(assets_base, "icons", "crown", "dondaful.png")
        if hiroba_crown == "gold":
            return os.path.join(assets_base, "icons", "crown", "full.png")
        if hiroba_crown == "silver":
            return os.path.join(assets_base, "icons", "crown", "clear.png")
        return None

    def _to_float(self, v) -> Optional[float]:
        try:
            return float(v)
        except Exception:
            return None

    def _available_chart_levels(self, song_data: dict) -> list[int]:

        def has_level(level: int) -> bool:
            v = song_data.get(f"level_{level}")
            return v not in (None, "", "-")

        levels = [lv for lv in (5, 4, 3) if has_level(lv)]
        return levels or [4]

    def _extract_raw_dims(self, chart_info: dict) -> Optional[list[float]]:
        if not chart_info:
            return None
        vals = []
        for k in RAW_DIM_KEYS:
            fv = None
            for key in RAW_DIM_VALUE_ALIASES.get(k, (k,)):
                fv = self._to_float(chart_info.get(key))
                if fv is not None:
                    break
            if fv is None:
                return None
            vals.append(fv)
        return vals

    def _axis_ceiling(self, values: list[float]) -> int:
        if not values:
            return 10
        vmax = max((float(v) for v in values))
        if vmax <= 0:
            return 10
        return int(math.ceil(vmax / 10.0) * 10)

    def _radar_points(self, cx: int, cy: int, radius: float):
        points = []
        for i in range(6):
            ang = math.radians(-90 + i * 60)
            x = cx + radius * math.cos(ang)
            y = cy + radius * math.sin(ang)
            points.append((x, y))
        return points

    def _draw_radar_chart(
        self,
        draw: ImageDraw.ImageDraw,
        values: list[float],
        labels: list[str],
        axis_max: int,
        center: tuple[int, int],
        radius: int,
        label_font,
        primary_fill=(57, 108, 176, 88),
        primary_outline=(49, 99, 164, 255),
        overlay_values: Optional[list[float]] = None,
        overlay_fill=(225, 144, 58, 54),
        overlay_outline=(220, 133, 42, 230),
    ):
        cx, cy = center
        spokes = self._radar_points(cx, cy, radius)
        label_gap = max(12, int(radius * 0.16))
        for step in range(1, RADAR_GRID_STEPS + 1):
            r = radius * step / RADAR_GRID_STEPS
            grid_pts = self._radar_points(cx, cy, r)
            draw.polygon(grid_pts, outline=(192, 207, 224, 255))
        for px, py in spokes:
            draw.line((cx, cy, px, py), fill=(184, 201, 220, 255), width=1)
        if overlay_values:
            overlay_pts = []
            for i, val in enumerate(overlay_values):
                p = max(0.0, min(1.0, float(val) / max(axis_max, 1)))
                px, py = spokes[i]
                overlay_pts.append((cx + (px - cx) * p, cy + (py - cy) * p))
            draw.polygon(
                overlay_pts, fill=overlay_fill, outline=overlay_outline, width=2
            )
        plot_pts = []
        for i, val in enumerate(values):
            p = max(0.0, min(1.0, float(val) / max(axis_max, 1)))
            px, py = spokes[i]
            plot_pts.append((cx + (px - cx) * p, cy + (py - cy) * p))
        draw.polygon(plot_pts, fill=primary_fill, outline=primary_outline, width=2)
        for i, label in enumerate(labels):
            px, py = spokes[i]
            tx = px
            ty = py
            if i == 0:
                ty -= label_gap + 6
            elif i in (1, 2):
                tx += label_gap
            elif i == 3:
                ty += label_gap // 2
            else:
                tx -= label_gap
            bbox = draw.textbbox((0, 0), label, font=label_font)
            tw = bbox[2] - bbox[0]
            th = bbox[3] - bbox[1]
            min_x = 12
            max_x = RADAR_CARD_W - 12 - tw
            if i in (1, 2):
                self._draw_text(
                    draw,
                    (min(max(tx, min_x), max_x), ty - th // 2),
                    label,
                    label_font,
                    (58, 75, 96, 255),
                )
            elif i in (4, 5):
                x = tx - tw
                self._draw_text(
                    draw,
                    (min(max(x, min_x), max_x), ty - th // 2),
                    label,
                    label_font,
                    (58, 75, 96, 255),
                )
            else:
                x = tx - tw // 2
                self._draw_text(
                    draw,
                    (min(max(x, min_x), max_x), ty - th // 2),
                    label,
                    label_font,
                    (58, 75, 96, 255),
                )

    def _draw_radar_card(
        self,
        level: int,
        panel_title: str,
        values: Optional[list[float]],
        labels: list[str],
        placeholder: str,
        assets_base: str,
        font_path: str,
        card_bg_path: Optional[str] = None,
        axis_max_fixed: Optional[int] = None,
        overlay_values: Optional[list[float]] = None,
        table_labels: Optional[list[str]] = None,
        table_values: Optional[list[float]] = None,
        table_max_values: Optional[list[float]] = None,
        primary_value_color=(41, 93, 167, 255),
        max_value_color=(220, 133, 42, 255),
    ) -> Image.Image:
        card = self._own(Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (0, 0, 0, 0)))
        mask = self._own(Image.new("L", (RADAR_CARD_W, RADAR_CARD_H), 0))
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle(
            (0, 0, RADAR_CARD_W - 1, RADAR_CARD_H - 1), radius=18, fill=255
        )
        if card_bg_path and os.path.exists(card_bg_path):
            src = self._own(self._own(Image.open(card_bg_path)).convert("RGBA"))
            bg = self._cover_resize_to_box(src, (RADAR_CARD_W, RADAR_CARD_H))
        else:
            bg = self._own(
                Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (242, 246, 252, 255))
            )
        bg.putalpha(mask.point(lambda a: int(a * 0.72)))
        card.alpha_composite(bg)
        overlay = self._own(
            Image.new("RGBA", (RADAR_CARD_W, RADAR_CARD_H), (244, 248, 255, 80))
        )
        overlay.putalpha(mask.point(lambda a: int(a * 0.55)))
        card.alpha_composite(overlay)
        draw = ImageDraw.Draw(card)
        draw.rounded_rectangle(
            (0, 0, RADAR_CARD_W - 1, RADAR_CARD_H - 1),
            radius=18,
            outline=(188, 203, 220, 255),
            width=2,
        )
        title_font = self._load_font(font_path, 30)
        label_font = self._load_font(font_path, 20)
        value_font = self._load_font(font_path, 28)
        diff_icon = self._load_icon(
            os.path.join(assets_base, "icons", "diff", f"{level}.png"), size=(38, 38)
        )
        title_x = 14
        title_y = 18
        if diff_icon:
            card.paste(diff_icon, (title_x, title_y), diff_icon)
            title_x += 46
        self._draw_text(
            draw, (title_x, title_y + 2), panel_title, title_font, (74, 49, 24, 255)
        )
        if not values:
            ph_bbox = draw.textbbox((0, 0), placeholder, font=title_font)
            pw = ph_bbox[2] - ph_bbox[0]
            ph = ph_bbox[3] - ph_bbox[1]
            self._draw_text(
                draw,
                ((RADAR_CARD_W - pw) // 2, (RADAR_CARD_H - ph) // 2),
                placeholder,
                title_font,
                (132, 146, 162, 255),
            )
            return card
        axis_max = axis_max_fixed if axis_max_fixed else self._axis_ceiling(values)
        self._draw_radar_chart(
            draw=draw,
            values=values,
            labels=labels,
            axis_max=axis_max,
            center=(RADAR_CARD_W // 2, RADAR_TOP_Y + RADAR_RADIUS),
            radius=RADAR_RADIUS,
            label_font=label_font,
            overlay_values=overlay_values,
        )
        table_labels = table_labels or labels
        table_values = table_values or values
        list_top = RADAR_TOP_Y + RADAR_RADIUS * 2 + 64
        row_h = 90
        for idx, (name, val) in enumerate(zip(table_labels, table_values)):
            y = list_top + idx * row_h
            draw.line(
                (12, y - 8, RADAR_CARD_W - 12, y - 8),
                fill=(206, 217, 228, 255),
                width=2,
            )
            self._draw_text(draw, (16, y), name, value_font, (45, 67, 97, 255))
            if table_max_values and idx < len(table_max_values):
                cur_txt = f"{float(val):.2f}"
                slash_txt = "/"
                max_txt = f"{float(table_max_values[idx]):.2f}"
                b1 = draw.textbbox((0, 0), cur_txt, font=value_font)
                b2 = draw.textbbox((0, 0), slash_txt, font=value_font)
                b3 = draw.textbbox((0, 0), max_txt, font=value_font)
                w1 = b1[2] - b1[0]
                w2 = b2[2] - b2[0]
                w3 = b3[2] - b3[0]
                x = RADAR_CARD_W - 16 - (w1 + w2 + w3)
                self._draw_text(draw, (x, y), cur_txt, value_font, primary_value_color)
                self._draw_text(
                    draw, (x + w1, y), slash_txt, value_font, (86, 100, 116, 255)
                )
                self._draw_text(
                    draw, (x + w1 + w2, y), max_txt, value_font, max_value_color
                )
            else:
                txt = f"{float(val):.2f}"
                bbox = draw.textbbox((0, 0), txt, font=value_font)
                tw = bbox[2] - bbox[0]
                self._draw_text(
                    draw,
                    (RADAR_CARD_W - 16 - tw, y),
                    txt,
                    value_font,
                    primary_value_color,
                )
        return card

    def _draw_compact_radar(
        self,
        draw: ImageDraw.ImageDraw,
        values: list[float],
        labels: list[str],
        center: tuple[int, int],
        radius: int,
        axis_max: int,
        label_font,
        fill,
        outline,
        overlay_values: Optional[list[float]] = None,
        overlay_fill=(225, 144, 58, 54),
        overlay_outline=(220, 133, 42, 230),
    ):
        cx, cy = center
        spokes = []
        count = len(values)
        for idx in range(count):
            angle = math.radians(-90 + idx * 360 / count)
            spokes.append(
                (cx + radius * math.cos(angle), cy + radius * math.sin(angle))
            )
        for step in range(1, 5):
            scale = step / 4
            grid = [(cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in spokes]
            draw.polygon(grid, outline=(193, 207, 224, 255))
        for px, py in spokes:
            draw.line((cx, cy, px, py), fill=(184, 201, 220, 255), width=1)
        if overlay_values:
            overlay_points = []
            for (px, py), value in zip(spokes, overlay_values):
                scale = max(0.0, min(1.0, float(value) / max(axis_max, 1)))
                overlay_points.append((cx + (px - cx) * scale, cy + (py - cy) * scale))
            if overlay_points:
                draw.polygon(
                    overlay_points, fill=overlay_fill, outline=overlay_outline, width=2
                )
        points = []
        for (px, py), value in zip(spokes, values):
            scale = max(0.0, min(1.0, float(value) / max(axis_max, 1)))
            points.append((cx + (px - cx) * scale, cy + (py - cy) * scale))
        if points:
            draw.polygon(points, fill=fill, outline=outline, width=2)
        for (px, py), label in zip(spokes, labels):
            bbox = draw.textbbox((0, 0), label, font=label_font)
            tw, th = (bbox[2] - bbox[0], bbox[3] - bbox[1])
            x = px - tw / 2
            y = py - th / 2
            if px > cx + 10:
                x = px + 5
            elif px < cx - 10:
                x = px - tw - 5
            if py < cy - radius * 0.55:
                y = py - th - 4
            elif py > cy + radius * 0.55:
                y = py + 3
            x = max(8, min(int(x), DETAIL_PANEL_W - tw - 8))
            self._draw_text(draw, (x, int(y)), label, label_font, (58, 75, 96, 255))

    def _fit_detail_metric_font(
        self,
        draw: ImageDraw.ImageDraw,
        font_path: str,
        label_text: str,
        value_parts: list[str],
    ):
        """为详情面板玩家行选择不会与维度名相撞的最大字号。"""
        available_width = DETAIL_PLAYER_VALUE_RIGHT_X - DETAIL_PLAYER_LABEL_X
        for size in range(DETAIL_METRIC_FONT_SIZE, DETAIL_METRIC_MIN_FONT_SIZE - 1, -1):
            font = self._load_font(font_path, size)
            text_width = sum(
                (
                    draw.textbbox((0, 0), text, font=font)[2]
                    for text in (label_text, *value_parts)
                )
            )
            if text_width + DETAIL_METRIC_MIN_GAP <= available_width:
                return font
        return self._load_font(font_path, DETAIL_METRIC_MIN_FONT_SIZE)

    def _draw_detail_player_metric(
        self,
        draw: ImageDraw.ImageDraw,
        *,
        y: int,
        label: str,
        current_value: float,
        max_value: Optional[float],
        font_path: str,
    ) -> None:
        current_text = f"{current_value:.2f}"
        max_text = f" / {max_value:.2f}" if max_value is not None else ""
        value_parts = [current_text]
        if max_text:
            value_parts.append(max_text)
        row_font = self._fit_detail_metric_font(draw, font_path, label, value_parts)
        self._draw_text(
            draw, (DETAIL_PLAYER_LABEL_X, y), label, row_font, (45, 67, 97, 255)
        )
        part_widths = [
            draw.textbbox((0, 0), text, font=row_font)[2] for text in value_parts
        ]
        values_x = DETAIL_PLAYER_VALUE_RIGHT_X - sum(part_widths)
        self._draw_text(draw, (values_x, y), current_text, row_font, (41, 93, 167, 255))
        if max_text:
            self._draw_text(
                draw,
                (values_x + part_widths[0], y),
                max_text,
                row_font,
                (220, 133, 42, 255),
            )

    def _draw_detail_panel(
        self,
        *,
        title: str,
        chart_values: Optional[list[float]],
        chart_labels: list[str],
        player_values: Optional[list[float]],
        player_labels: list[str],
        constants: Optional[tuple[float, float, float]],
        font_path: str,
        bg_path: Optional[str],
        accent: tuple[int, int, int],
        constant_caption: str = "定数",
        constant_labels: Optional[tuple[str, str, str]] = None,
        player_summary: Optional[tuple[str, float]] = None,
        player_max_values: Optional[list[float]] = None,
        player_max_summary: Optional[tuple[str, float]] = None,
    ) -> Image.Image:
        panel = self._own(
            Image.new("RGBA", (DETAIL_PANEL_W, DETAIL_PANEL_H), (0, 0, 0, 0))
        )
        draw = ImageDraw.Draw(panel)
        draw.rounded_rectangle(
            (0, 0, DETAIL_PANEL_W - 1, DETAIL_PANEL_H - 1),
            radius=18,
            fill=(245, 248, 252, 245),
            outline=(188, 203, 220, 255),
            width=2,
        )
        if bg_path and os.path.exists(bg_path):
            mask = self._own(Image.new("L", (DETAIL_PANEL_W, DETAIL_PANEL_H), 0))
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.rounded_rectangle(
                (0, 0, DETAIL_PANEL_W - 1, DETAIL_PANEL_H - 1), radius=18, fill=255
            )
            bg = self._cover_resize_to_box(
                self._own(self._own(Image.open(bg_path)).convert("RGBA")),
                (DETAIL_PANEL_W, DETAIL_PANEL_H),
            )
            bg.putalpha(mask.point(lambda alpha: int(alpha * 0.34)))
            panel.alpha_composite(bg)
            overlay = self._own(
                Image.new("RGBA", (DETAIL_PANEL_W, DETAIL_PANEL_H), (246, 249, 253, 92))
            )
            overlay.putalpha(mask.point(lambda alpha: int(alpha * 0.55)))
            panel.alpha_composite(overlay)
            draw = ImageDraw.Draw(panel)
            draw.rounded_rectangle(
                (0, 0, DETAIL_PANEL_W - 1, DETAIL_PANEL_H - 1),
                radius=18,
                outline=(188, 203, 220, 255),
                width=2,
            )
        title_font = self._load_font(font_path, 25)
        label_font = self._load_font(font_path, 17)
        value_font = self._load_font(font_path, 20)
        self._draw_text(draw, (18, 14), title, title_font, (74, 49, 24, 255))
        if constants:
            c1, c2, c3 = constants
            if c1 == c2 == c3:
                const_text = f"{constant_caption}  {c1:.2f}"
                self._draw_text(draw, (18, 50), const_text, value_font, accent)
            else:
                self._draw_text(draw, (18, 50), constant_caption, value_font, accent)
                labels = constant_labels or ("", "", "")
                for center_x, value, label in zip(
                    DETAIL_CONSTANT_COLUMN_CENTERS, (c1, c2, c3), labels
                ):
                    value_text = f"{value:.2f}"
                    value_bbox = draw.textbbox((0, 0), value_text, font=value_font)
                    value_x = (
                        center_x - (value_bbox[2] - value_bbox[0]) / 2 - value_bbox[0]
                    )
                    self._draw_text(draw, (value_x, 50), value_text, value_font, accent)
                    if label:
                        label_bbox = draw.textbbox((0, 0), label, font=label_font)
                        label_x = (
                            center_x
                            - (label_bbox[2] - label_bbox[0]) / 2
                            - label_bbox[0]
                        )
                        self._draw_text(
                            draw, (label_x, 75), label, label_font, (102, 116, 132, 255)
                        )
        self._draw_text(draw, (18, 102), "谱面", label_font, (58, 75, 96, 255))
        self._draw_text(draw, (268, 102), "玩家", label_font, (58, 75, 96, 255))
        if chart_values:
            self._draw_compact_radar(
                draw,
                chart_values,
                chart_labels,
                (125, 180),
                70,
                100 if max(chart_values) > 20 else 15,
                label_font,
                (57, 108, 176, 70),
                (49, 99, 164, 255),
            )
        else:
            self._draw_text(
                draw, (69, 186), "暂无谱面数据", value_font, (132, 146, 162, 255)
            )
        if player_values:
            self._draw_compact_radar(
                draw,
                player_values,
                player_labels,
                (375, 180),
                70,
                15,
                label_font,
                (57, 108, 176, 70),
                (49, 99, 164, 255),
                overlay_values=player_max_values,
            )
        else:
            self._draw_text(
                draw, (310, 186), "暂无玩家数据", value_font, (132, 146, 162, 255)
            )
        rows = max(len(chart_values or []), len(player_values or []))
        for idx in range(rows):
            y = 292 + idx * 34
            draw.line(
                (16, y - 6, DETAIL_PANEL_W - 16, y - 6),
                fill=(220, 228, 236, 255),
                width=1,
            )
            if chart_values and idx < len(chart_values):
                self._draw_text(
                    draw,
                    (18, y),
                    f"{chart_labels[idx]} {chart_values[idx]:.2f}",
                    value_font,
                    (41, 93, 167, 255),
                )
            if player_values and idx < len(player_values):
                max_value = (
                    player_max_values[idx]
                    if player_max_values and idx < len(player_max_values)
                    else None
                )
                self._draw_detail_player_metric(
                    draw,
                    y=y,
                    label=player_labels[idx],
                    current_value=player_values[idx],
                    max_value=max_value,
                    font_path=font_path,
                )
        if player_summary or player_max_summary:
            summary_y = 292 + rows * 34
            draw.line(
                (254, summary_y - 6, DETAIL_PANEL_W - 16, summary_y - 6),
                fill=(194, 208, 222, 255),
                width=2,
            )
            if player_summary:
                summary_label, summary_value = player_summary
                summary_max_value = (
                    player_max_summary[1] if player_max_summary else None
                )
                self._draw_detail_player_metric(
                    draw,
                    y=summary_y,
                    label=summary_label,
                    current_value=summary_value,
                    max_value=summary_max_value,
                    font_path=font_path,
                )
        return panel

    def _compose_with_side_radar(
        self,
        center_img: Image.Image,
        song_no: int,
        song_data: dict,
        entries: dict,
        assets_base: str,
        font_path: str,
        side_bg_path: Optional[str] = None,
    ) -> Image.Image:
        levels = self._available_chart_levels(song_data)
        section_h = 52 + DETAIL_PANEL_H + DETAIL_SECTION_TOP_GAP
        out_w = center_img.width
        out_h = center_img.height + len(levels) * section_h
        out = self._own(Image.new("RGBA", (out_w, out_h), (235, 241, 248, 255)))
        out.paste(center_img, (0, 0), center_img)
        rating_index = self.context.rating_index
        v2_map = self.context.v2_charts
        font_path = str(font_path)
        label_font = self._load_font(font_path, 24)
        for idx, level in enumerate(levels):
            top = center_img.height + idx * section_h
            draw = ImageDraw.Draw(out)
            draw.rounded_rectangle(
                (SIDE_PADDING, top + 8, out_w - SIDE_PADDING, top + section_h - 8),
                radius=18,
                fill=(244, 248, 253, 220),
                outline=(188, 203, 220, 255),
                width=2,
            )
            icon = self._load_icon(
                os.path.join(assets_base, "icons", "diff", f"{level}.png"), (32, 32)
            )
            title_x = SIDE_PADDING + 18
            if icon:
                out.paste(icon, (title_x, top + 18), icon)
                title_x += 42
            self._draw_text(
                draw, (title_x, top + 18), "难度分析", label_font, (74, 49, 24, 255)
            )
            chart_info = rating_index.get((song_no, level))
            v1_raw = self._extract_raw_dims(chart_info)
            v1_const = self._to_float(chart_info.get("score")) if chart_info else None
            v1_player_metrics = self.context.player_metrics.get(level)
            v1_player = (
                v1_player_metrics.get("current_dims") if v1_player_metrics else None
            )
            v1_summary = (
                v1_player_metrics.get("current_rating") if v1_player_metrics else None
            )
            v1_player_max = (
                v1_player_metrics.get("max_dims") if v1_player_metrics else None
            )
            v1_summary_max = (
                v1_player_metrics.get("max_rating") if v1_player_metrics else None
            )
            v2_chart = v2_map.get((song_no, level))
            v2_raw = None
            v2_constants = None
            if v2_chart:
                v2_raw = [
                    v2_chart.stamina,
                    v2_chart.handspeed,
                    v2_chart.burst,
                    v2_chart.rhythm,
                    v2_chart.complex,
                ]
                v2_constants = (
                    v2_chart.sub_constant_1,
                    v2_chart.main_constant,
                    v2_chart.sub_constant_2,
                )
            v2_player_result = self.context.v2_player_values.get(level)
            v2_player = v2_player_result[0] if v2_player_result else None
            v2_summary = v2_player_result[1] if v2_player_result else None
            v2_player_max = v2_player_result[2] if v2_player_result else None
            v2_summary_max = v2_player_result[3] if v2_player_result else None
            panel_y = top + 62
            v1_panel = self._draw_detail_panel(
                title="V1 传统定数",
                chart_values=v1_raw,
                chart_labels=RAW_DIM_KEYS,
                player_values=v1_player,
                player_labels=PLAYER_DIM_KEYS,
                constants=(
                    (v1_const, v1_const, v1_const) if v1_const is not None else None
                ),
                font_path=font_path,
                bg_path=side_bg_path,
                accent=(41, 93, 167),
                constant_caption="定数",
                player_summary=(
                    ("综合得分", float(v1_summary)) if v1_summary is not None else None
                ),
                player_max_values=v1_player_max,
                player_max_summary=(
                    ("综合得分", float(v1_summary_max))
                    if v1_summary_max is not None
                    else None
                ),
            )
            v2_panel = self._draw_detail_panel(
                title="V2 Rating",
                chart_values=v2_raw,
                chart_labels=["体力", "手速", "爆发", "节奏", "复合"],
                player_values=v2_player,
                player_labels=["体力", "手速", "爆发", "精度", "节奏", "复合"],
                constants=v2_constants,
                font_path=font_path,
                bg_path=side_bg_path,
                accent=(39, 154, 145),
                constant_labels=("75%", "95%", "99%"),
                player_summary=(
                    ("综合", float(v2_summary)) if v2_summary is not None else None
                ),
                player_max_values=v2_player_max,
                player_max_summary=(
                    ("综合", float(v2_summary_max))
                    if v2_summary_max is not None
                    else None
                ),
            )
            out.paste(v1_panel, (SIDE_PADDING, panel_y), v1_panel)
            out.paste(
                v2_panel, (out_w - SIDE_PADDING - DETAIL_PANEL_W, panel_y), v2_panel
            )
        return out

    def resolve_template(self):
        assets_base_path = self.context.assets_base
        song_data = self.context.song_info
        template_path = str(
            self.context.template_path
            or assets_base_path / "templates/info-bg-final-fix.png"
        )
        side_bg_path = None
        category = song_data.get("type", "") or ""
        if category in TYPE_MAP:
            type_key = TYPE_MAP[category]
            info_tpl = assets_base_path / "templates" / f"{type_key}-info-bg.png"
            side_tpl = assets_base_path / "templates" / f"{type_key}-bg.png"
            if info_tpl.exists():
                template_path = str(info_tpl)
            if side_tpl.exists():
                side_bg_path = str(side_tpl)
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"模板不存在: {template_path}")
        return (template_path, side_bg_path)

    def _render(self):
        song_no = self.context.song_no
        song_data = self.context.song_info
        entries = self.context.entries_by_level
        assets_base_path = self.context.assets_base
        assets_base = str(assets_base_path)
        template_path, side_bg_path = self.resolve_template()
        canvas = self._own(self._own(Image.open(template_path)).convert("RGBA"))
        W, H = canvas.size
        if (W, H) != (1060, 1220):
            print(
                f"[warn] 模板尺寸为 {W}x{H}，预期 1060x1220。坐标仍按 1060x1220 绘制。"
            )
        draw = ImageDraw.Draw(canvas)
        cover_path = os.path.join(assets_base, "cover", f"{song_no}.png")
        self._paste_song_art(canvas, cover_path, ART_POS, ART_SIZE)
        font_path = os.path.join(assets_base, "fonts", FONT_FILE_NAME)
        font_title = self._load_font(font_path, SIZE_TITLE)
        font_score = self._load_font(font_path, SIZE_SCORE)
        font_stats = self._load_font(font_path, SIZE_STATS)
        main_card_ddfont_lift = 4

        def draw_main_card_text_with_stroke(
            pos, text, font, fill, stroke_width, stroke_fill
        ):
            self._draw_text_with_stroke(
                draw,
                (pos[0], pos[1] - main_card_ddfont_lift),
                text,
                font,
                fill,
                stroke_width,
                stroke_fill,
            )

        song_name = song_data.get("song_name", "") or ""
        song_name_jp = song_data.get("song_name_jp", "") or ""
        title_en_bbox = draw.textbbox((0, 0), song_name, font=font_title)
        title_jp_bbox = draw.textbbox((0, 0), song_name_jp, font=font_title)
        pos_title_en_fix = (
            POS_TITLE_EN[0] - (title_en_bbox[2] - title_en_bbox[0]) // 2,
            POS_TITLE_EN[1],
        )
        pos_title_jp_fix = (
            POS_TITLE_JP[0] - (title_jp_bbox[2] - title_jp_bbox[0]) // 2,
            POS_TITLE_JP[1],
        )
        draw_main_card_text_with_stroke(
            pos_title_en_fix, song_name, font_title, WHITE, STROKE_TITLE, BLUE
        )
        draw_main_card_text_with_stroke(
            pos_title_jp_fix, song_name_jp, font_title, WHITE, STROKE_TITLE, BLUE
        )
        category = song_data.get("type", "") or ""
        lx, ly = POS_TYPE
        txt_bbox = draw.textbbox((0, 0), category, font=font_title)
        txt_x = lx - (txt_bbox[2] - txt_bbox[0]) // 2
        draw_main_card_text_with_stroke(
            (txt_x, ly - 3), category, font_title, WHITE, STROKE_TITLE, BLUE
        )
        id_text = f"{song_data.get('id', '')}"
        bpm_val = song_data.get("bpm", None)
        draw_main_card_text_with_stroke(
            POS_ID_BPM, id_text, font_title, WHITE, STROKE_TITLE, BLUE
        )
        if bpm_val not in (None, "", "-"):
            id_bbox = draw.textbbox(POS_ID_BPM, id_text, font=font_title)
            bpm_x = id_bbox[0] + 182
            draw_main_card_text_with_stroke(
                (bpm_x, POS_ID_BPM[1]),
                f"{bpm_val}",
                font_title,
                WHITE,
                STROKE_TITLE,
                BLUE,
            )
        for idx, row_center_y in enumerate(ROW_Y):
            level_idx = 5 - idx
            level = song_data.get(f"level_{level_idx}", "")
            txt = "☆ "
            txt += "-" if level in (None, "", "-") else str(level)
            draw_main_card_text_with_stroke(
                (LEVEL_X, row_center_y + LEVEL_Y_OFFSET),
                txt,
                font_title,
                WHITE,
                STROKE_TITLE,
                BLUE,
            )
            entry = entries.get(level_idx)
            if not entry:
                continue
            option_flags = entry.get("option_flg", [])
            icon_x = SCORE_X + OPTION_ICON_SIZE[0]
            icon_y = row_center_y - SIZE_SCORE // 2 - OPTION_ICON_SIZE[1] - 4
            if len(option_flags) >= 1:
                flag_name = str(format(option_flags[0], ".1f"))
                icon_path = os.path.join(
                    assets_base, "icons", "option", f"{flag_name}.png"
                )
                icon_img = self._load_icon(icon_path, OPTION_ICON_SIZE)
                if icon_img:
                    canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                    icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2
            if len(option_flags) >= 2:
                if option_flags[1] == 1:
                    icon_path = os.path.join(
                        assets_base, "icons", "option", "hidden.png"
                    )
                    icon_img = self._load_icon(icon_path, OPTION_ICON_SIZE)
                    if icon_img:
                        canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                        icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2
            if len(option_flags) >= 3:
                if option_flags[2] == 1:
                    icon_path = os.path.join(
                        assets_base, "icons", "option", "mirror.png"
                    )
                    icon_img = self._load_icon(icon_path, OPTION_ICON_SIZE)
                    if icon_img:
                        canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                        icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2
            if len(option_flags) >= 4:
                if option_flags[3] == "01":
                    icon_path = os.path.join(
                        assets_base, "icons", "option", "super_random.png"
                    )
                    icon_img = self._load_icon(icon_path, OPTION_ICON_SIZE)
                    if icon_img:
                        canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                        icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2
                elif option_flags[3] == "10":
                    icon_path = os.path.join(
                        assets_base, "icons", "option", "random.png"
                    )
                    icon_img = self._load_icon(icon_path, OPTION_ICON_SIZE)
                    if icon_img:
                        canvas.paste(icon_img, (icon_x, icon_y), icon_img)
                        icon_x += OPTION_ICON_SIZE[0] + OPTION_ICON_SIZE[0] // 2
            score = entry.get("high_score", 0)
            score_txt = f"{score:,}".replace(",", "")
            score_pos = (SCORE_X, row_center_y + SCORE_Y_OFFSET)
            draw_main_card_text_with_stroke(
                score_pos, score_txt, font_score, WHITE, STROKE_SCORE, BLACK
            )
            icon_y = int(row_center_y - RANK_ICON_SIZE[1] / 2)
            try:
                rank_val = int(entry.get("best_score_rank", 0))
            except Exception:
                rank_val = 0
            rank_path = self._rank_icon_path(assets_base, rank_val)
            rank_icon = self._load_icon(rank_path, RANK_ICON_SIZE)
            if rank_icon:
                canvas.paste(rank_icon, (RANK_X_FIXED + 12, icon_y), rank_icon)
            crown_path = self._pick_crown_path(assets_base, entry)
            crown_icon = self._load_icon(crown_path, CROWN_ICON_SIZE)
            if crown_icon:
                canvas.paste(crown_icon, (CROWN_X_FIXED + 4, icon_y), crown_icon)
            left_values = [
                entry.get("good_cnt", 0),
                entry.get("ok_cnt", 0),
                entry.get("ng_cnt", 0),
            ]
            right_values = [entry.get("pound_cnt", 0), entry.get("combo_cnt", 0)]
            for i, val in enumerate(left_values):
                y = row_center_y + STAT_Y_OFFSET + i * STAT_LINE_H
                val_bbox = draw.textbbox((0, 0), str(val), font=font_stats)
                val_len = val_bbox[2] - val_bbox[0]
                val_x = STAT_COL_X_CENTER + 28 - val_len
                draw_main_card_text_with_stroke(
                    (val_x, y - 20), str(val), font_stats, WHITE, STROKE_STATS, BLACK
                )
            for i, val in enumerate(right_values):
                y = row_center_y + STAT_Y_OFFSET - 5 + i * (STAT_LINE_H + 10)
                val_bbox = draw.textbbox((0, 0), str(val), font=font_stats)
                val_len = val_bbox[2] - val_bbox[0]
                val_x = POUND_COL_X_CENTER + 20 - val_len
                draw_main_card_text_with_stroke(
                    (val_x, y), str(val), font_stats, WHITE, STROKE_STATS, BLACK
                )
        canvas = self._compose_with_side_radar(
            center_img=canvas,
            song_no=song_no,
            song_data=song_data,
            entries=entries,
            assets_base=assets_base,
            font_path=font_path,
            side_bg_path=side_bg_path,
        )
        bio = BytesIO()
        canvas.save(bio, format="PNG")
        return bio.getvalue()
