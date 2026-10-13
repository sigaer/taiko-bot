"""Alias card drawing with explicit public font input."""
from typing import List, Tuple
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

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

def render_alias_image(
    song_title: str,
    song_id: str,
    aliases: List[str],
    font_path: str,
    width: int = 980,
    padding: int = 28,
    font_size: int = 26,
    line_gap: int = 8,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(font_path, font_size)
    title_font = _load_alias_font(font_path, font_size + 4)
    tmp = Image.new("RGBA", (width, 10), (*bg_color, 255))
    draw = ImageDraw.Draw(tmp)

    lines: List[str] = []
    title_line = f"歌曲：{song_title} (id{song_id})"
    lines.extend(_wrap_text(draw, title_line, title_font, width - padding * 2))
    if not aliases:
        lines.append("别名：暂无记录")
    else:
        lines.append(f"别名（{len(aliases)}）：")
        max_w = width - padding * 2
        for idx, alias in enumerate(aliases, start=1):
            prefix = f"{idx}. "
            prefix_w = int(draw.textlength(prefix, font=font))
            chunks = _wrap_text(draw, alias, font, max(20, max_w - prefix_w))
            if chunks:
                lines.append(prefix + chunks[0])
                indent = " " * len(prefix)
                for chunk in chunks[1:]:
                    lines.append(indent + chunk)

    line_height = int(font_size * 1.4)
    title_height = int((font_size + 4) * 1.4)
    height = padding * 2 + (len(lines) * line_height) + (line_gap * (len(lines) - 1))
    height = max(height, padding * 2 + title_height + line_gap)
    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    y = padding
    for i, line in enumerate(lines):
        use_font = title_font if i == 0 else font
        draw.text((padding, y), line, fill=fg_color, font=use_font)
        y += line_height + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()
