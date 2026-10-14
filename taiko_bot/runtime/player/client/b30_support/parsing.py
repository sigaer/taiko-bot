from __future__ import annotations

import re

from typing import *

from io import BytesIO

from PIL import Image

DIM_ALIASES = {
    "大歌": "big_song",
    "大歌力": "big_song",
    "节奏": "rhythm",
    "节奏处理": "rhythm",
    "复合": "complex_proc",
    "复合处理": "complex_proc",
    "精度": "accuracy_power",
    "精度力": "accuracy_power",
    "体力": "stamina",
    "高速": "speed",
    "高速处理": "speed",
}

TAIKOB_V2_DIM_USAGE = "体力、手速、爆发、精度、节奏、复合"

_TAIKOB_DIM_WRAPPER_CHARS = "[]【】()（）<>《》「」『』"

def _resolve_taikob_dim_arg(args: Sequence[str]) -> Optional[str]:
    selected_dim, _ = _parse_taikob_dim_arg(args, DIM_ALIASES)
    return selected_dim

def _parse_taikob_dim_arg(
    args: Sequence[str], alias_map: Dict[str, str]
) -> Tuple[Optional[str], List[str]]:
    pending_dim_flag = False
    selected_dim: Optional[str] = None
    unknown_tokens: List[str] = []
    for raw_token in args:
        token = str(raw_token or "").strip()
        if not token or token.lower() == "-r":
            continue
        if pending_dim_flag:
            normalized = token.strip(_TAIKOB_DIM_WRAPPER_CHARS).strip()
            resolved = alias_map.get(normalized)
            if resolved is None:
                unknown_tokens.append(token)
            elif selected_dim is None:
                selected_dim = resolved
            pending_dim_flag = False
            continue
        if re.fullmatch(r"(?:-d|--dim|维度)", token, flags=re.IGNORECASE):
            pending_dim_flag = True
            continue
        if token.startswith(("--dim=", "-d=", "维度=")):
            token = token.split("=", 1)[1]
        normalized = token.strip(_TAIKOB_DIM_WRAPPER_CHARS).strip()
        if normalized in alias_map:
            if selected_dim is None:
                selected_dim = alias_map[normalized]
        else:
            unknown_tokens.append(token)
    return selected_dim, unknown_tokens

def _to_jpeg_bytes(img_buf: bytes | BytesIO, quality: int = 85) -> bytes:
    if isinstance(img_buf, BytesIO):
        data = img_buf.getvalue()
    else:
        data = img_buf
    img = Image.open(BytesIO(data))
    if img.mode in ("RGBA", "LA"):
        base = Image.new("RGB", img.size, (255, 255, 255))
        base.paste(img, mask=img.split()[-1])
        img = base
    else:
        img = img.convert("RGB")
    out = BytesIO()
    img.save(out, format="JPEG", quality=quality, optimize=True)
    return out.getvalue()
