from __future__ import annotations


import re

from taiko_bot.runtime.player.center.b30_support.parsing import _to_jpeg_bytes

from taiko_bot.runtime.player.center.b30_support.parsing import TAIKOB_V2_DIM_USAGE

TREND_DIM_ALIASES = {
    "rating": "综合Rating",
    "综合": "综合Rating",
    "总合": "综合Rating",
    "综合rating": "综合Rating",
    "ra": "综合Rating",
    "大歌": "大歌力",
    "大歌力": "大歌力",
    "big_song": "大歌力",
    "daigouryoku": "大歌力",
    "体力": "体力",
    "stamina": "体力",
    "高速": "高速处理",
    "高速处理": "高速处理",
    "speed": "高速处理",
    "精度": "精度力",
    "准度": "精度力",
    "良率": "精度力",
    "精度力": "精度力",
    "accuracy": "精度力",
    "accuracy_power": "精度力",
    "节奏": "节奏处理",
    "节奏处理": "节奏处理",
    "rhythm": "节奏处理",
    "复合": "复合处理",
    "复合处理": "复合处理",
    "complex": "复合处理",
    "complex_proc": "复合处理",
}

TREND_USAGE_MESSAGE = (
    "参数错误。示例：taikotrend 20 30 / taikotrend 体力 / "
    "taikotrend --dim 精度 20 / taikotrend v2 / taikotrend -a / taikotrend -b"
)

PLAYTREND_USAGE_MESSAGE = (
    "参数错误。示例：taikoplaytrend 20 80 / taikoplaytrend 体力 / "
    "taikoplaytrend --dim 精度 20 / taikoplaytrend v2 / taikoplaytrend -a / taikoplaytrend -b"
)

TREND_DEFAULT_NOTE_MESSAGE = (
    "备注：不指定参数时默认展示最近30天内的 Top20 综合 Rating 走势。\n"
    "参考：taikotrend 20 30 / taikotrend 体力 / taikotrend --dim 精度 20"
)

TREND_V2_DEFAULT_NOTE_MESSAGE = (
    "备注：当前展示 Rating v2 最近30天内的 Top20 综合走势。\n"
    "参考：taikotrend v2 20 30 / taikotrend v2 手速 / taikotrend v2 --dim 爆发"
)

def _normalize_trend_dim_token(token: str) -> str:
    return re.sub(r"\s+", "", str(token or "").strip().lower())

def _resolve_trend_dim(
    token: str, aliases: Optional[Dict[str, str]] = None
) -> Optional[str]:
    return (aliases or TREND_DIM_ALIASES).get(_normalize_trend_dim_token(token))

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

def _parse_trend_args(
    arg_text: str, *, dim_aliases: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    arg_text = (arg_text or "").strip()
    bar_mode = bool(
        re.search(r"(?:-b|--bar|bar|柱状图|柱状)", arg_text, flags=re.IGNORECASE)
    )
    show_all = bool(re.search(r"(?:-a|--all)", arg_text, flags=re.IGNORECASE))

    selected_dim: Optional[str] = None
    dim_flag_match = re.search(
        r"(?:^|\s)(?:-d|--dim|维度)(?:\s+|=)(\S+)",
        arg_text,
        flags=re.IGNORECASE,
    )
    if dim_flag_match:
        selected_dim = _resolve_trend_dim(dim_flag_match.group(1), dim_aliases)
        if not selected_dim:
            raise ValueError(
                "维度不支持。可用："
                + (
                    f"综合、{TAIKOB_V2_DIM_USAGE}"
                    if dim_aliases
                    else "综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理"
                )
            )

    tokens = re.split(r"\s+", arg_text) if arg_text else []
    unknown_tokens: List[str] = []
    for token in tokens:
        if re.fullmatch(r"\d+", token):
            continue
        if re.fullmatch(
            r"(?:-a|--all|-b|--bar|bar|柱状图|柱状)",
            token,
            flags=re.IGNORECASE,
        ):
            continue
        if re.fullmatch(r"(?:-d|--dim|维度)", token, flags=re.IGNORECASE):
            continue
        if token.startswith(("--dim=", "-d=", "维度=")):
            continue

        resolved_dim = _resolve_trend_dim(token, dim_aliases)
        if resolved_dim:
            if selected_dim is None:
                selected_dim = resolved_dim
            continue
        unknown_tokens.append(token)

    if unknown_tokens:
        raise ValueError(TREND_USAGE_MESSAGE)

    nums = [int(x) for x in re.findall(r"\d+", arg_text)]
    N = nums[0] if len(nums) > 0 else 20
    max_days = nums[1] if len(nums) > 1 else 30
    if N < 1 or N > 50:
        raise ValueError("N范围为 1-50")
    if max_days < 1 or max_days > 365:
        raise ValueError("天数范围为 1-365")

    return {
        "N": N,
        "max_days": max_days,
        "bar_mode": bar_mode,
        "show_all": show_all,
        "selected_dim": selected_dim,
    }

def _parse_playtrend_args(
    arg_text: str, *, dim_aliases: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    arg_text = (arg_text or "").strip()
    bar_mode = bool(
        re.search(r"(?:-b|--bar|bar|柱状图|柱状)", arg_text, flags=re.IGNORECASE)
    )
    show_all = bool(re.search(r"(?:-a|--all)", arg_text, flags=re.IGNORECASE))

    selected_dim: Optional[str] = None
    dim_flag_match = re.search(
        r"(?:^|\s)(?:-d|--dim|维度)(?:\s+|=)(\S+)",
        arg_text,
        flags=re.IGNORECASE,
    )
    if dim_flag_match:
        selected_dim = _resolve_trend_dim(dim_flag_match.group(1), dim_aliases)
        if not selected_dim:
            raise ValueError(
                "维度不支持。可用："
                + (
                    f"综合、{TAIKOB_V2_DIM_USAGE}"
                    if dim_aliases
                    else "综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理"
                )
            )

    tokens = re.split(r"\s+", arg_text) if arg_text else []
    unknown_tokens: List[str] = []
    for token in tokens:
        if re.fullmatch(r"\d+", token):
            continue
        if re.fullmatch(
            r"(?:-a|--all|-b|--bar|bar|柱状图|柱状)",
            token,
            flags=re.IGNORECASE,
        ):
            continue
        if re.fullmatch(r"(?:-d|--dim|维度)", token, flags=re.IGNORECASE):
            continue
        if token.startswith(("--dim=", "-d=", "维度=")):
            continue

        resolved_dim = _resolve_trend_dim(token, dim_aliases)
        if resolved_dim:
            if selected_dim is None:
                selected_dim = resolved_dim
            continue
        unknown_tokens.append(token)

    if unknown_tokens:
        raise ValueError(PLAYTREND_USAGE_MESSAGE)

    nums = [int(x) for x in re.findall(r"\d+", arg_text)]
    N = nums[0] if len(nums) > 0 else 20
    max_points = nums[1] if len(nums) > 1 else 80
    if N < 1 or N > 50:
        raise ValueError("N范围为 1-50")
    if max_points < 1 or max_points > 500:
        raise ValueError("曲数点数范围为 1-500")

    return {
        "N": N,
        "max_points": max_points,
        "bar_mode": bar_mode,
        "show_all": show_all,
        "selected_dim": selected_dim,
    }

from .taikob_v2 import V2_TREND_DIM_ALIASES
