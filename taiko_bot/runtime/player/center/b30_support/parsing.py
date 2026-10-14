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

def _extract_rating_version(arg_text: str) -> Tuple[str, str]:
    """Extract an optional standalone v1/v2 token without treating its digit as N."""
    normalized = str(arg_text or "").strip()
    tokens = re.split(r"\s+", normalized) if normalized else []
    versions = [token.lower() for token in tokens if token.lower() in {"v1", "v2"}]
    if len(set(versions)) > 1:
        raise ValueError("不能同时指定 v1 和 v2")
    version = versions[0] if versions else "v2"
    remaining = " ".join(
        token for token in tokens if token.lower() not in {"v1", "v2"}
    )
    return version, remaining

_TAIKOB_DIM_WRAPPER_CHARS = "[]【】()（）<>《》「」『』"

def _parse_taikob_dim_arg(
    args: Sequence[str], aliases: Dict[str, str]
) -> Tuple[Optional[str], List[str]]:
    dim: Optional[str] = None
    unknown_tokens: List[str] = []
    idx = 0
    while idx < len(args):
        raw_token = args[idx]
        token = str(raw_token or "").strip()
        if not token or token.lower() in {"-r", "v2"}:
            idx += 1
            continue
        if re.fullmatch(r"(?:-d|--dim|维度)", token, flags=re.IGNORECASE):
            idx += 1
            if idx >= len(args):
                unknown_tokens.append(token)
                break
            value_token = str(args[idx] or "").strip()
            normalized = value_token.strip(_TAIKOB_DIM_WRAPPER_CHARS).strip()
            resolved = aliases.get(normalized)
            if resolved:
                dim = dim or resolved
            else:
                unknown_tokens.extend([token, value_token])
            idx += 1
            continue
        if token.startswith(("--dim=", "-d=", "维度=")):
            token = token.split("=", 1)[1]
        normalized = token.strip(_TAIKOB_DIM_WRAPPER_CHARS).strip()
        resolved = aliases.get(normalized)
        if resolved:
            dim = dim or resolved
        else:
            unknown_tokens.append(token)
        idx += 1
    return dim, unknown_tokens

def _resolve_taikob_dim_arg(
    args: Sequence[str], aliases: Optional[Dict[str, str]] = None
) -> Optional[str]:
    dim, _ = _parse_taikob_dim_arg(args, aliases or DIM_ALIASES)
    return dim

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
