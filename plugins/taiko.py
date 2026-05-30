from .utils.update_user import getUserData
from .utils.hiroba.sync import sync_hiroba_userdata
from .utils.hiroba.sync import sync_multiple_hiroba_userdatas
from .utils.hiroba.cooldown import peek_hiroba_sync_cooldown
from .utils.hiroba.credentials import (
    delete_hiroba_credentials,
    ensure_hiroba_credentials_table,
    has_hiroba_credentials,
    load_hiroba_credentials,
    save_hiroba_credentials,
)
from .utils.public_score_token import (
    PublicScoreTokenError,
    get_taiko_db_connection,
    issue_public_score_token_for_taiko_id,
)
from .utils.merged_bind import (
    MergedBindError,
    MergedBindMissingUserdataError,
    materialize_merged_bind_userdata,
)
from .utils.drawinfo import generate_score_image, get_score_by_id_and_level
from .utils import (
    render_pass_progress_image_bytes,
    render_progress_image_bytes_by_list,
    find_by_volume,
    compute_score,
    render_progress_image_bytes,
    render_star_progress_image_bytes,
    compute_recommendations_for_user,
    generate_recommend_image,
    generate_dim_top_image,
    render_my_don_image,
    render_update_changes_image,
    render_b30_image,
    render_tcloud_image,
)
from .utils.draw_summary import render_taiko_2025_summary
from .utils.progress_catalog import (
    available_const_progress_keys,
    available_pass_progress_keys,
    available_star_progress_values,
)
from .utils.dani_progress import (
    parse_dani_progress_request,
    render_dani_progress_image_bytes,
)
from .utils.score_line import (
    available_levels_for_song,
    compute_scoreline_result,
    format_scoreline_message,
    get_scoreline_entry,
    parse_scoreline_request,
)
from .utils.twso import find_player
from .utils.song_position import format_position_reply, get_song_position_by_id
from .utils.arcade_map import (
    CityShopQueryResult,
    build_tencent_map_location_json,
    format_city_shop_forward_nickname,
    format_taiko_city_shop_entry,
    format_taiko_city_shop_reply,
    format_taiko_city_shop_summary,
    query_taiko_shops_by_city,
)
from .utils.const_query import (
    DEFAULT_PAGE_SIZE,
    paginate_rows,
    query_charts_by_const,
    render_const_query_image,
    render_const_query_notice,
)
from .utils.score_calculator import (
    compute_all_from_userdata,
    generate_top_N_image,
    getUtime,
    generate_rating_trend_image,
    generate_rating_playcount_image,
)
import random
import re
import asyncio
import subprocess
import threading
import time
import os
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from datetime import datetime
import httpx
from PIL import Image, ImageDraw, ImageFont
import json
from fuzzywuzzy import fuzz
from nonebot import logger
from nonebot.adapters import Bot, Event
from nonebot.exception import MatcherException
from nonebot.plugin import on_regex, on_fullmatch, on_command, on_message
from nonebot.params import RegexMatched, RegexGroup, CommandArg
from nonebot.permission import SUPERUSER
from nonebot.rule import Rule
from nonebot.adapters.onebot.v11.permission import GROUP_ADMIN, GROUP_OWNER
from nonebot.matcher import Matcher
from typing import Dict, Any, Tuple, List, Optional, Set
from taiko_bot.settings import get_settings

_SETTINGS = get_settings()
ROOT_DIR = _SETTINGS.root_dir
ASSETS_DIR = ROOT_DIR / "assets"
SONGS_DIR = ROOT_DIR / "songs"
_AGENT_DEBUG_LOG_PATH = str(ROOT_DIR / ".cursor" / "debug-open-source.log")
_AGENT_DEBUG_SESSION_ID = "6cd261"


def _agent_debug_log(
    location: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
    *,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    # region agent log
    payload = {
        "sessionId": _AGENT_DEBUG_SESSION_ID,
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    try:
        with open(_AGENT_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion


from nonebot.adapters.onebot.v11 import (
    Message,
    MessageSegment,
    GroupMessageEvent,
    PrivateMessageEvent,
)
from feature_handler.feature_handler import feature_on, apply_switch
from taiko_runtime.platform_adapter import (
    ONEBOT_V11_PLATFORM,
    build_identity_key,
    extract_plain_text as extract_platform_plain_text,
    get_group_key,
    get_identity_key,
    is_onebot_message_targeting_other_account,
    is_qq_official_event,
    is_qq_official_group_event,
    is_qq_official_private_event,
    parse_identity_key,
    resolve_target_identity_key,
    send_image_reply,
    send_onebot_forward_messages,
    send_text_reply,
)

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule
tsearch_rule = feature_on("tsearch")
draw_guess_rule = feature_on("taiko_draw_guess")
SONG_DATA_PATH = SONGS_DIR / "song_data.json"
COVER_DIR = ASSETS_DIR / "cover"
OSS_COVER_PREFIX = "oss://sigaer/cover"
FONT_PATH = "assets/fonts/DDFont.ttf"
SONG_RANK_FONT_PATH = "/usr/share/fonts/NotoSansCJKSC-Black.ttf"
SONG_METRIC_FONT_PATH = "/usr/share/fonts/NotoSansCJKSC-Black.ttf"
TAIKOB_FONT_PATH = FONT_PATH
FUMENS_DIR = Path("assets") / "fumens_renamed"
ALIAS_LOG_PATH = ROOT_DIR / "logs" / "alias_action_log.json"
REGION_MAP_PATH = SONGS_DIR / "region_map.json"
CONFIG_PATH = ROOT_DIR / "config.json"
TAIKO_FORUM_BASE_URL = os.getenv("TAIKO_VIEWER_BASE_URL", "https://viewer.sakura-bot.cn").rstrip("/")
DEVELOPER_QQ_EXPORT_DIR = ROOT_DIR / "output" / "developer_userdata_exports"
BIND_VERIFY_TIMEOUT_SECONDS = 600
BIND_VERIFY_BYPASS_IDS = {"2258735"}
BIND_VERIFY_SESSIONS: Dict[str, Dict[str, Any]] = {}
BIND_DELETE_CONFIRM_TIMEOUT_SECONDS = 300
BIND_DELETE_CONFIRM_SESSIONS: Dict[str, Dict[str, Any]] = {}
TAIKO_MULTI_BIND_PATH = ROOT_DIR / "data" / "taiko_multi_bind.json"
DIM_MAP = {
    "rating": "rating",
    "综合": "rating",
    "总合": "rating",
    "daigouryoku": "daigouryoku",
    "大歌力": "daigouryoku",
    "大歌": "daigouryoku",
    "stamina": "stamina",
    "体力": "stamina",
    "speed": "speed",
    "高速": "speed",
    "高速处理": "speed",
    "accuracy_power": "accuracy_power",
    "精度": "accuracy_power",
    "准度": "accuracy_power",
    "良率": "accuracy_power",
    "精度力": "accuracy_power",
    "rhythm": "rhythm",
    "节奏": "rhythm",
    "节奏处理": "rhythm",
    "complex": "complex",
    "复合": "complex",
    "复合处理": "complex",
}
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
    "taikotrend --dim 精度 20 / taikotrend -a / taikotrend -b"
)
PLAYTREND_USAGE_MESSAGE = (
    "参数错误。示例：taikoplaytrend 20 80 / taikoplaytrend 体力 / "
    "taikoplaytrend --dim 精度 20 / taikoplaytrend -a / taikoplaytrend -b"
)
DIFF_MAP = {
    "里": "InnerOni",
    "鬼": "Oni",
    "表": "Oni",
    "魔王": "Oni",
    "松": "Muzukashii",
    "困难": "Muzukashii",
    "竹": "Futsuu",
    "一般": "Futsuu",
    "梅": "Kantan",
    "简单": "Kantan",
}
ALIAS_QUERY_REGEX = re.compile(r"^(?P<q>.+?)有什么别名[？?]?$")
WHAT_SONG_REGEX = re.compile(r"^(?P<q>.+?)是什么歌[？?]?$")
SONG_WHERE_REGEX = re.compile(r"^(?P<q>.+?)歌在哪[？?]?$")
SONG_POSITION_REGEX = re.compile(r"^(?P<q>.+?)在什么位置[？?]?$")
SONG_POS_BY_ID_REGEX = re.compile(r"^位置\s*(?:id)?\s*(?P<id>\d+)\s*[？?]?$")
DIFF_BY_ID_REGEX = re.compile(
    r"^(?P<diff>里|鬼|表|松|竹|梅|简单|一般|困难|魔王)\s*(?:id)?\s*(?P<id>\d+)\s*[？?]?$"
)
CITY_ARCADE_QUERY_REGEX = re.compile(r"^(?P<city>.+?)(?:哪有鼓|哪里有鼓)\s*[？?]?$")
PROGRESS_WITH_PAGE_REGEX = re.compile(r"^(?P<body>.+进度)(?:\s+(?P<page>\d+))?$")
UPDATE_COMMAND_PATTERN = re.compile(
    r"^(?:taikoupdate|更新广场)(?:(?:\s+|)(?P<show_all>all|全部|全量|-a|--all))?\s*$",
    flags=re.IGNORECASE,
)
TCLOUD_COMMAND_PATTERN = re.compile(
    r"^(?:tcloud|太鼓词云|词云)\s*$",
    flags=re.IGNORECASE,
)
UPDATE_TYPO_TARGET = "taikoupdate"
UPDATE_TYPO_ALPHABET = "abcdefghijklmnopqrstuvwxyz"


def _build_single_edit_variants(target: str) -> Set[str]:
    variants: Set[str] = set()
    for idx in range(len(target)):
        variants.add(target[:idx] + target[idx + 1 :])
    for idx, original in enumerate(target):
        prefix = target[:idx]
        suffix = target[idx + 1 :]
        for ch in UPDATE_TYPO_ALPHABET:
            if ch != original:
                variants.add(prefix + ch + suffix)
    for idx in range(len(target) + 1):
        prefix = target[:idx]
        suffix = target[idx:]
        for ch in UPDATE_TYPO_ALPHABET:
            variants.add(prefix + ch + suffix)
    variants.discard(target)
    return variants


UPDATE_TYPO_VARIANTS = _build_single_edit_variants(UPDATE_TYPO_TARGET)


def _normalize_update_command_text(text: str) -> str:
    normalized = str(text or "").lstrip().lower()
    return normalized[1:] if normalized.startswith("/") else normalized


def _normalize_slash_command_text(text: str) -> str:
    normalized = str(text or "").strip()
    return normalized[1:].lstrip() if normalized.startswith("/") else normalized


def _should_trigger_tcloud_command(text: str) -> bool:
    normalized = _normalize_slash_command_text(text)
    return bool(TCLOUD_COMMAND_PATTERN.match(normalized))


def _parse_update_command(text: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_update_command_text(text)
    match = UPDATE_COMMAND_PATTERN.fullmatch(normalized)
    if not match:
        return None
    return {"show_all": bool(match.group("show_all"))}


def _should_trigger_update_command(text: str) -> bool:
    return _parse_update_command(text) is not None


def _is_update_typo_candidate_text(text: str) -> bool:
    normalized = _normalize_update_command_text(str(text or "").strip())
    return len(normalized) in (10, 11, 12)


def _normalize_trend_dim_token(token: str) -> str:
    return re.sub(r"\s+", "", str(token or "").strip().lower())


def _resolve_trend_dim(token: str) -> Optional[str]:
    return TREND_DIM_ALIASES.get(_normalize_trend_dim_token(token))


def _parse_trend_args(arg_text: str) -> Dict[str, Any]:
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
        selected_dim = _resolve_trend_dim(dim_flag_match.group(1))
        if not selected_dim:
            raise ValueError(
                "维度不支持。可用：综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理"
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

        resolved_dim = _resolve_trend_dim(token)
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


def _parse_playtrend_args(arg_text: str) -> Dict[str, Any]:
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
        selected_dim = _resolve_trend_dim(dim_flag_match.group(1))
        if not selected_dim:
            raise ValueError(
                "维度不支持。可用：综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理"
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

        resolved_dim = _resolve_trend_dim(token)
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


DIFF_MAP_REVERSE = {
    "InnerOni": "里谱",
    "Oni": "魔王",
    "Muzukashii": "困难",
    "Futsuu": "普通",
    "Kantan": "简单",
}
RANK_DIFF_INPUT_MAP = {
    "简单": 1,
    "梅": 1,
    "一般": 2,
    "竹": 2,
    "困难": 3,
    "松": 3,
    "魔王": 4,
    "鬼": 4,
    "里魔王": 5,
    "里谱": 5,
    "里": 5,
}
RANK_DIFF_LABEL_MAP = {
    1: "简单",
    2: "一般",
    3: "困难",
    4: "魔王",
    5: "里魔王",
}
RANK_DIFF_EN_MAP = {
    "easy": 1,
    "normal": 2,
    "hard": 3,
    "oni": 4,
    "ura": 5,
    "inner": 5,
    "inneroni": 5,
}
REGION_SUFFIXES = [
    "省",
    "市",
    "自治区",
    "壮族自治区",
    "回族自治区",
    "维吾尔自治区",
    "特别行政区",
]
DRAW_GUESS_DATA_DIR = ROOT_DIR / "data" / "draw_guess"
DRAW_GUESS_IMAGE_DIR = DRAW_GUESS_DATA_DIR / "images"
DRAW_GUESS_DB_PATH = DRAW_GUESS_DATA_DIR / "records.json"
DRAW_GUESS_TEMPLATE_PATH = ASSETS_DIR / "templates" / "太鼓你画我猜.png"
DRAW_GUESS_TIMEOUT_SECONDS = 600
DRAW_GUESS_MAX_TRIES = 5
DRAW_GUESS_REPORT_DELETE_THRESHOLD = 5
DRAW_GUESS_DB_LOCK = asyncio.Lock()
DRAW_GUESS_MAKE_SESSIONS: Dict[str, Dict[str, Any]] = {}
DRAW_GUESS_GROUP_SESSIONS: Dict[str, Dict[str, Any]] = {}
USERDATA_DIR = ROOT_DIR / "userdata"
SONG_METRIC_MAX_SHOW = 30
SONG_METRIC_DIFF_PRIORITY = {
    5: 0,
    4: 0,
    3: 1,
    2: 2,
    1: 3,
}
SONG_METRIC_QUERY_PATTERN = (
    r"^(太鼓|我的)\s*"
    r"(?:(?P<ng>\d{1,4})不可|(?P<ok>\d{1,4})可|(?P<single_ok>单可)|(?P<dondaful>全良))"
    r"(?:\s*(?P<order>正序|倒序|升序|降序|asc|desc))?\s*$"
)


def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段
    """
    return extract_platform_plain_text(event)


QQ_OFFICIAL_UNSUPPORTED_MESSAGE = (
    "该功能暂未支持 QQ 官方机器人，当前仅支持太鼓核心查询链路。"
)
QQ_OFFICIAL_UNSUPPORTED_PATTERNS = [
    re.compile(r"^(?:开发者数据|taikodevdata)\b", re.IGNORECASE),
    re.compile(r"^(?:网页成绩token|成绩token|scoretoken|获取token)\b", re.IGNORECASE),
    re.compile(r"^taiko2025$", re.IGNORECASE),
    re.compile(r"^cover\s*\d+", re.IGNORECASE),
    re.compile(r"^(开启|关闭)(pjsk|taiko|mai)功能$"),
    re.compile(r"^tsearch\s*(on|off)$", re.IGNORECASE),
    re.compile(r"^(开启|关闭)太鼓你画我猜功能$"),
    re.compile(r"^画太鼓歌名(?:\s|$)"),
    re.compile(r"^猜太鼓歌名$"),
    re.compile(r"^猜(?!太鼓歌名)\s*.+$"),
    re.compile(r"^(点赞|举报|查看)你画我猜id\s*\d+\s*$"),
    re.compile(r"^我的你画我猜$"),
    re.compile(r"^(?:你画我猜排行|太鼓你画我猜排行)(?:\s*.*)?$"),
    re.compile(r"^(开启|关闭)太鼓技术吸取功能$"),
    re.compile(r"^重置太鼓技术吸取记录$"),
    re.compile(r"^太鼓技术吸取保护$"),
    re.compile(r"^解除太鼓技术吸取保护$"),
    re.compile(r"^查看太鼓技术吸取保护名单$"),
    re.compile(r"^太鼓技术吸取记录$"),
    re.compile(r"^太鼓技术吸取.*$"),
]
QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS = (
    "请先绑定账号",
    "请输入正确",
    "参数错误",
    "查不到呢",
    "失败",
    "未找到",
    "暂无",
    "没有可用于",
    "没有可用",
    "没有待确认",
    "请更新数据后",
    "还未上传数据",
    "查询失败",
    "生成失败",
    "推荐计算失败",
    "验证未通过",
    "请确认",
    "请检查",
    "未支持",
    "未完成",
    "未找到该鼓众ID",
    "缺少登录cookie",
    "当前未绑定",
    "该歌曲没有",
    "未找到匹配",
    "未找到满足",
)
ONEBOT_EXTERNAL_BOT_QQ = "3889003795"


def _is_qq_official_unsupported_command(event: MessageEvent) -> bool:
    if not is_qq_official_group_event(event):
        return False
    text = extract_plain_text(event)
    if not text:
        return False
    return any(pattern.match(text) for pattern in QQ_OFFICIAL_UNSUPPORTED_PATTERNS)


def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)


def _is_private_message_event(event: MessageEvent) -> bool:
    if isinstance(event, PrivateMessageEvent):
        return True
    return is_qq_official_private_event(event)


def _is_external_bot_mentioned(event: MessageEvent) -> bool:
    if is_qq_official_event(event):
        return False
    for seg in event.get_message():
        if seg.type == "at" and seg.data.get("qq") == ONEBOT_EXTERNAL_BOT_QQ:
            return True
    return False


def _is_update_command_targeting_other_account(event: MessageEvent) -> bool:
    # In mixed-bot groups, "@other bot /更新广场" is still visible to OneBot.
    return is_onebot_message_targeting_other_account(event)


def _should_attach_quick_actions_to_text(event: MessageEvent, text: str) -> bool:
    if not is_qq_official_group_event(event):
        return False
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return any(
        keyword in normalized for keyword in QQ_OFFICIAL_QUICK_ACTION_FAILURE_KEYWORDS
    )


async def _finish_text_reply(
    matcher: Matcher,
    event: MessageEvent,
    text: str,
    *,
    quick_actions: Optional[bool] = None,
) -> None:
    attach_quick_actions = (
        _should_attach_quick_actions_to_text(event, text)
        if quick_actions is None
        else bool(quick_actions)
    )
    await send_text_reply(
        matcher,
        event,
        text,
        quick_actions=attach_quick_actions,
    )


def _resolve_onebot_forward_sender_id(bot: Bot, event: MessageEvent) -> int:
    for candidate in (
        getattr(bot, "self_id", None),
        getattr(event, "self_id", None),
        event.get_user_id() if hasattr(event, "get_user_id") else None,
    ):
        try:
            return int(str(candidate or "").strip())
        except Exception:
            continue
    return 10000


def _build_city_arcade_forward_messages(
    bot: Bot,
    event: MessageEvent,
    result: CityShopQueryResult,
) -> list[MessageSegment]:
    sender_id = _resolve_onebot_forward_sender_id(bot, event)
    if not result.shops:
        return []
    nodes = [
        MessageSegment.node_custom(
            user_id=sender_id,
            nickname="太鼓地图",
            content=format_taiko_city_shop_summary(result),
        )
    ]
    for index, shop in enumerate(result.shops, start=1):
        map_json = build_tencent_map_location_json(shop)
        if map_json:
            content = MessageSegment.json(map_json)
        else:
            content = format_taiko_city_shop_entry(index, shop)
        nodes.append(
            MessageSegment.node_custom(
                user_id=sender_id,
                nickname=format_city_shop_forward_nickname(index, shop),
                content=content,
            )
        )
    return nodes


async def _send_text_reply_without_finish(
    matcher: Matcher,
    _event: MessageEvent,
    text: str,
) -> None:
    await matcher.send(text)


async def _finish_image_reply(
    matcher: Matcher,
    event: MessageEvent,
    image_bytes: bytes | BytesIO | Path,
    prefix_text: str = "",
    *,
    quick_actions: bool = False,
    prefer_markdown_image: bool = False,
    markdown_image_name: str = "taiko",
) -> None:
    await send_image_reply(
        matcher,
        event,
        image_bytes,
        prefix_text=prefix_text,
        quick_actions=quick_actions,
        prefer_markdown_image=prefer_markdown_image,
        markdown_image_name=markdown_image_name,
    )


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


def load_song_data():
    """读取 song_data.json（dict 列表）"""
    with SONG_DATA_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


@lru_cache(maxsize=1)
def _load_progress_name_set() -> Set[str]:
    path = SONGS_DIR / "music_donda_list.json"
    if not path.exists():
        return set()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    if not isinstance(data, dict):
        return set()
    return {str(k) for k in data.keys()}


@lru_cache(maxsize=1)
def _load_decimal_progress_set() -> Set[str]:
    return available_const_progress_keys()


@lru_cache(maxsize=1)
def _load_pass_progress_set() -> Set[str]:
    return available_pass_progress_keys()


@lru_cache(maxsize=1)
def _load_star_progress_set() -> Set[int]:
    return available_star_progress_values()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _low_miss_total(ok_cnt: Any, ng_cnt: Any) -> int:
    return _to_int(ok_cnt, 0) + _to_int(ng_cnt, 0)


def _build_song_title_map() -> Dict[int, Dict[str, Any]]:
    title_map: Dict[int, Dict[str, Any]] = {}
    for item in load_song_data():
        if not isinstance(item, dict):
            continue
        song_id = _to_int(item.get("id"), -1)
        if song_id < 0:
            continue
        title_jp = str(
            item.get("song_name_jp") or item.get("song_name") or f"ID{song_id}"
        )
        title_cn = str(item.get("song_name") or "").strip()
        # 获取上架状态：0=在架，1=下架
        shelf_status = item.get("shelf_status", 0)
        stars: Dict[int, str] = {}
        for lv in (1, 2, 3, 4, 5):
            star_raw = item.get(f"level_{lv}")
            if star_raw is None:
                continue
            star_text = str(star_raw).strip()
            if not star_text or star_text == "-":
                continue
            stars[lv] = star_text
        title_map[song_id] = {
            "title_jp": title_jp,
            "title_cn": title_cn,
            "stars": stars,
            "shelf_status": shelf_status,
        }
    return title_map


def _load_user_song_records(user_id: int) -> List[Dict[str, Any]]:
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    if not userdata_path.exists():
        raise FileNotFoundError(f"userdata not found: {userdata_path}")
    with userdata_path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    songs = payload.get("songs")
    if not isinstance(songs, list):
        return []
    return [item for item in songs if isinstance(item, dict)]


async def _upload_json_file_for_event(
    bot: Bot, event: MessageEvent, file_path: Path, display_name: str
) -> None:
    resolved = str(file_path.resolve())
    if isinstance(event, GroupMessageEvent):
        await bot.call_api(
            "upload_group_file",
            group_id=int(event.group_id),
            file=resolved,
            name=display_name,
        )
        return
    if isinstance(event, PrivateMessageEvent):
        await bot.call_api(
            "upload_private_file",
            user_id=int(event.get_user_id()),
            file=resolved,
            name=display_name,
        )
        return
    raise RuntimeError("当前消息类型不支持发送 JSON 文件")


async def _fetch_developer_userdata_via_forum(
    token: str, user_id: str
) -> Dict[str, Any]:
    url = f"{TAIKO_FORUM_BASE_URL}/api/developer/userdata/{user_id}"
    async with httpx.AsyncClient(timeout=90.0) as client:
        response = await client.get(
            url,
            headers={"Authorization": f"Bearer {token.strip()}"},
        )
    if response.status_code >= 400:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        message = (
            payload.get("statusMessage")
            or payload.get("message")
            or f"请求失败，HTTP {response.status_code}"
        )
        raise RuntimeError(str(message))
    try:
        payload = response.json()
    except Exception as error:
        raise RuntimeError("开发者接口返回的 JSON 无法解析") from error
    if not isinstance(payload, dict):
        raise RuntimeError("开发者接口返回的内容不是对象 JSON")
    return payload


def _collect_song_metric_matches(
    user_id: int,
    mode: str,
    target_value: Optional[int] = None,
    order_mode: str = "default",
) -> List[Dict[str, Any]]:
    records = _load_user_song_records(user_id)
    title_map = _build_song_title_map()
    matched: List[Dict[str, Any]] = []
    for record in records:
        song_no = _to_int(record.get("song_no"), -1)
        level = _to_int(record.get("level"), -1)
        if song_no < 0 or level not in (1, 2, 3, 4, 5):
            continue

        ok_cnt = _to_int(record.get("ok_cnt"), 0)
        ng_cnt = _to_int(record.get("ng_cnt", record.get("bad_cnt")), 0)
        dondaful_cnt = _to_int(record.get("dondaful_combo_cnt"), 0)
        full_combo_cnt = _to_int(record.get("full_combo_cnt"), 0)

        # 过滤规则：
        # - xx可：仅过滤全良（保留全连）
        # - 单可：仅过滤全良（保留全连）
        # - xx不可：过滤全连与全良
        if mode in ("ok", "single_ok") and dondaful_cnt > 0:
            continue
        if mode == "ng" and (full_combo_cnt > 0 or dondaful_cnt > 0):
            continue

        if mode == "ok":
            if target_value == 1:
                if _low_miss_total(ok_cnt, ng_cnt) != 1:
                    continue
            elif target_value is None or ok_cnt != target_value:
                continue
        elif mode == "single_ok":
            if _low_miss_total(ok_cnt, ng_cnt) >= 10:
                continue
        elif mode == "ng":
            if target_value is None or ng_cnt != target_value:
                continue
        elif mode == "dondaful":
            if dondaful_cnt <= 0:
                continue
        else:
            continue

        song_meta = title_map.get(song_no, {})
        # 过滤已下架歌曲（shelf_status=1 表示已下架）
        if isinstance(song_meta, dict) and song_meta.get("shelf_status") == 1:
            continue
        stars = song_meta.get("stars") if isinstance(song_meta, dict) else {}
        star = "-"
        if isinstance(stars, dict):
            star = str(stars.get(level, "-"))

        matched.append(
            {
                "song_no": song_no,
                "level": level,
                "title": (
                    str(song_meta.get("title_jp"))
                    if isinstance(song_meta, dict) and song_meta.get("title_jp")
                    else f"ID{song_no}"
                ),
                "title_cn": (
                    str(song_meta.get("title_cn", ""))
                    if isinstance(song_meta, dict)
                    else ""
                ),
                "star": star,
                "ok_cnt": ok_cnt,
                "ng_cnt": ng_cnt,
                "dondaful_combo_cnt": dondaful_cnt,
                "full_combo_cnt": full_combo_cnt,
            }
        )

    if order_mode == "asc":
        matched.sort(
            key=lambda item: (
                _get_song_metric_level_bucket(item["level"]),
                *_build_song_metric_star_sort_key(item.get("star"), descending=False),
                item["song_no"],
            )
        )
    elif order_mode == "desc":
        matched.sort(
            key=lambda item: (
                -_get_song_metric_level_bucket(item["level"]),
                *_build_song_metric_star_sort_key(item.get("star"), descending=True),
                item["song_no"],
            )
        )
    else:
        matched.sort(
            key=lambda item: (
                SONG_METRIC_DIFF_PRIORITY.get(item["level"], 99),
                *_build_song_metric_star_sort_key(item.get("star"), descending=True),
                item["song_no"],
            )
        )
    return matched


def _parse_song_metric_order(order_token: Optional[str]) -> str:
    if not order_token:
        return "default"
    token = order_token.strip().lower()
    if token in ("正序", "升序", "asc"):
        return "asc"
    if token in ("倒序", "降序", "desc"):
        return "desc"
    return "default"


def _get_song_metric_level_bucket(level: int) -> int:
    return 4 if level in (4, 5) else level


def _parse_song_metric_star_value(star: Any) -> Optional[float]:
    text = str(star or "").strip()
    if not text or text == "-":
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    value = float(match.group())
    if "+" in text:
        value += 0.5
    return value


def _build_song_metric_star_sort_key(
    star: Any, *, descending: bool = False
) -> Tuple[bool, float]:
    value = _parse_song_metric_star_value(star)
    if value is None:
        return True, float("inf")
    return False, (-value if descending else value)


def _render_song_metric_list_image(
    metric_label: str,
    songs: List[Dict[str, Any]],
    total_count: int,
) -> bytes:
    width = 1120
    padding = 24
    line_gap = 8
    icon_size = 24
    num_w = 54
    icon_gap = 10

    bg_color = (245, 247, 250, 255)
    fg_color = (28, 32, 36, 255)

    font = _load_alias_font(SONG_METRIC_FONT_PATH, 24)
    title_font = _load_alias_font(SONG_METRIC_FONT_PATH, 30)
    sub_font = _load_alias_font(SONG_METRIC_FONT_PATH, 22)
    tmp = Image.new("RGBA", (width, 10), bg_color)
    draw = ImageDraw.Draw(tmp)

    title_line = f"{metric_label}曲目"
    sub_line = f"共 {total_count} 首，展示前 {len(songs)} 首"
    title_lines = _wrap_text(draw, title_line, title_font, width - padding * 2)
    sub_lines = _wrap_text(draw, sub_line, sub_font, width - padding * 2)

    title_h = int(30 * 1.4)
    sub_h = int(22 * 1.35)
    row_h = 36

    if songs:
        rows_h = len(songs) * (row_h + line_gap)
    else:
        rows_h = row_h

    content_h = (
        len(title_lines) * (title_h + 4) + len(sub_lines) * (sub_h + 4) + 10 + rows_h
    )
    height = max(240, padding * 2 + content_h)

    img = Image.new("RGBA", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    y = padding
    for line in title_lines:
        draw.text((padding, y), line, fill=fg_color, font=title_font)
        y += title_h + 4
    for line in sub_lines:
        draw.text((padding, y), line, fill=fg_color, font=sub_font)
        y += sub_h + 4
    y += 8

    if not songs:
        draw.text((padding, y), "暂无符合条件的曲目", fill=fg_color, font=font)
    else:
        star_font = _load_alias_font(SONG_METRIC_FONT_PATH, 22)
        icon_x = padding + num_w + icon_gap
        star_x = icon_x + icon_size + 8
        star_block_w = 56
        title_x = star_x + star_block_w + 10
        title_max_w = width - padding - title_x
        for idx, item in enumerate(songs, start=1):
            number_text = f"{idx:02d}."
            draw.text((padding, y + 4), number_text, fill=fg_color, font=font)

            level = _to_int(item.get("level"), 0)
            icon_path = ASSETS_DIR / "icons" / "diff" / f"{level}.png"
            if icon_path.exists():
                try:
                    icon = (
                        Image.open(icon_path)
                        .convert("RGBA")
                        .resize((icon_size, icon_size), Image.LANCZOS)
                    )
                    icon_y = (
                        y
                        + max(0, (row_h - icon_size) // 2)
                        + int(round(icon_size * 0.25))
                    )
                    img.alpha_composite(icon, (icon_x, icon_y))
                except Exception:
                    pass

            star_raw = str(item.get("star") or "-").strip()
            star_text = f"★{star_raw}" if star_raw and star_raw != "-" else "★-"
            star_bbox = draw.textbbox((0, 0), star_text, font=star_font)
            star_h = max(1, star_bbox[3] - star_bbox[1])
            star_y = y + max(0, (row_h - star_h) // 2)
            draw.text((star_x, star_y), star_text, fill=fg_color, font=star_font)

            title_jp = str(item.get("title") or f"ID{item.get('song_no')}")
            title_cn = str(item.get("title_cn") or "").strip()
            if title_cn and title_cn != title_jp:
                display_title = f"{title_jp}（{title_cn}）"
            else:
                display_title = title_jp
            title = _truncate_text(draw, display_title, font, title_max_w)
            text_bbox = draw.textbbox((0, 0), title, font=font)
            text_h = max(1, text_bbox[3] - text_bbox[1])
            text_y = y + max(0, (row_h - text_h) // 2)
            draw.text((title_x, text_y), title, fill=fg_color, font=font)
            y += row_h + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _compose_song_metric_result_image(my_don_img: bytes, list_img: bytes) -> bytes:
    left = Image.open(BytesIO(my_don_img)).convert("RGBA")
    right = Image.open(BytesIO(list_img)).convert("RGBA")
    gap = 16
    pad = 10
    canvas_w = left.width + right.width + gap + pad * 2
    canvas_h = max(left.height, right.height) + pad * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (255, 255, 255, 0))
    canvas.alpha_composite(left, (pad, pad))
    canvas.alpha_composite(right, (pad + left.width + gap, pad))
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def load_alias_data():
    """读取 song_alias.json（dict 列表）"""
    with open("songs/song_alias.json", "r", encoding="utf-8") as f:
        return json.load(f)


def load_region_map() -> Dict[str, int]:
    with REGION_MAP_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _parse_rank_diff_token(token: str) -> Optional[int]:
    t = token.strip()
    if not t:
        return None
    if t in RANK_DIFF_INPUT_MAP:
        return RANK_DIFF_INPUT_MAP[t]
    t_lower = t.lower()
    if t_lower in RANK_DIFF_EN_MAP:
        return RANK_DIFF_EN_MAP[t_lower]
    if t.isdigit():
        v = int(t)
        if 1 <= v <= 5:
            return v
    m = re.match(r"^(?:难度|等级|level|lv)\s*([1-5])$", t, flags=re.IGNORECASE)
    if m:
        return int(m.group(1))
    m = re.match(r"^(?:难度|等级)\s*(.+)$", t)
    if m:
        suffix = m.group(1).strip()
        if suffix in RANK_DIFF_INPUT_MAP:
            return RANK_DIFF_INPUT_MAP[suffix]
        if suffix.isdigit():
            v = int(suffix)
            if 1 <= v <= 5:
                return v
    return None


def _normalize_region_token(
    token: str, region_map: Dict[str, int], id_to_name: Dict[int, str]
) -> Optional[Tuple[str, int]]:
    t = token.strip().strip("，,。.;；")
    if not t:
        return None
    if t in region_map:
        return (t, region_map[t])
    if t.isdigit():
        rid = int(t)
        if rid in id_to_name:
            return (id_to_name[rid], rid)
    for suf in REGION_SUFFIXES:
        if t.endswith(suf):
            base = t[: -len(suf)]
            if base in region_map:
                return (base, region_map[base])
    return None


def _parse_song_rank_args(
    arg_str: str, region_map: Dict[str, int]
) -> Tuple[str, Optional[int], Optional[int], Optional[str]]:
    text = re.sub(r"\s+", " ", arg_str).strip()
    if not text:
        return "", None, None, None

    tokens = text.split(" ")
    id_to_name: Dict[int, str] = {}
    for name, rid in region_map.items():
        if rid not in id_to_name:
            id_to_name[rid] = name

    diff_id: Optional[int] = None
    province_id: Optional[int] = None
    province_name: Optional[str] = None
    alias_tokens: List[str] = []

    if len(tokens) > 1:
        for tok in tokens:
            if not tok:
                continue
            key_val = re.split(r"[=:：]", tok, maxsplit=1)
            if len(key_val) == 2:
                key, val = key_val[0].strip(), key_val[1].strip()
                if key.lower() in ("难度", "等级", "level", "lv"):
                    diff = _parse_rank_diff_token(val)
                    if diff is not None and diff_id is None:
                        diff_id = diff
                        continue
                if key.lower() in ("省份", "地区", "地域", "region"):
                    region = _normalize_region_token(val, region_map, id_to_name)
                    if region and province_id is None:
                        province_name, province_id = region
                        continue

            if diff_id is None:
                diff = _parse_rank_diff_token(tok)
                if diff is not None:
                    diff_id = diff
                    continue
            if province_id is None:
                if tok in ("全国", "全服", "全区", "全国榜", "全服榜"):
                    province_name = "全国"
                    province_id = None
                    continue
                region = _normalize_region_token(tok, region_map, id_to_name)
                if region:
                    province_name, province_id = region
                    continue
            alias_tokens.append(tok)

    parsed_any = diff_id is not None or province_name is not None
    if alias_tokens:
        alias = " ".join(alias_tokens).strip()
    else:
        alias = "" if parsed_any and len(tokens) > 1 else text

    # 兼容无空格输入：从首尾提取难度/地区
    remainder = alias
    if remainder and (diff_id is None or province_id is None):
        if province_id is None:
            region_keys = sorted(region_map.keys(), key=len, reverse=True)
            for key in region_keys:
                if remainder.endswith(key) and len(remainder) > len(key):
                    province_name = key
                    province_id = region_map[key]
                    remainder = remainder[: -len(key)].strip()
                    break
            if province_id is None:
                for suf in REGION_SUFFIXES:
                    if remainder.endswith(suf) and len(remainder) > len(suf):
                        base = remainder[: -len(suf)].strip()
                        if base in region_map:
                            province_name = base
                            province_id = region_map[base]
                            remainder = remainder[: -len(suf)].strip()
                            break
        if diff_id is None:
            diff_keys = sorted(RANK_DIFF_INPUT_MAP.keys(), key=len, reverse=True)
            for key in diff_keys:
                if remainder.endswith(key) and len(remainder) > len(key):
                    diff_id = RANK_DIFF_INPUT_MAP[key]
                    remainder = remainder[: -len(key)].strip()
                    break
            if diff_id is None:
                for key in diff_keys:
                    if remainder.startswith(key) and len(remainder) > len(key):
                        diff_id = RANK_DIFF_INPUT_MAP[key]
                        remainder = remainder[len(key) :].strip()
                        break

    alias = remainder or alias
    return alias, diff_id, province_id, province_name


def save_alias_data(data: List[Dict[str, Any]]) -> None:
    with open("songs/song_alias.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_alias_log(entry: Dict[str, Any]) -> None:
    ALIAS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if ALIAS_LOG_PATH.exists():
        try:
            with ALIAS_LOG_PATH.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                data = []
        except Exception:
            data = []
    else:
        data = []
    data.append(entry)
    with ALIAS_LOG_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_song_title_by_id(song_id: str) -> str:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item.get("song_name_jp") or item.get("song_name") or ""
    return ""


def get_song_entry_by_id(song_id: str) -> Optional[Dict[str, Any]]:
    data = load_song_data()
    for item in data:
        if str(item.get("id")) == str(song_id):
            return item
    return None


def _upload_cover_to_oss(cover_path: Path) -> Tuple[bool, str]:
    oss_target = f"{OSS_COVER_PREFIX}/{cover_path.name}"
    try:
        subprocess.run(
            ["ossutil", "cp", "-f", str(cover_path), oss_target],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, oss_target
    except Exception as e:
        return False, str(e)


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


def _truncate_text(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_w: int
) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "…"
    if draw.textlength(ell, font=font) > max_w:
        return ""
    left, right = 0, len(text)
    while left < right:
        mid = (left + right) // 2
        t = text[:mid] + ell
        if draw.textlength(t, font=font) <= max_w:
            left = mid + 1
        else:
            right = mid
    return text[: right - 1] + ell if right > 0 else ell


def render_alias_image(
    song_title: str,
    song_id: str,
    aliases: List[str],
    width: int = 980,
    padding: int = 28,
    font_size: int = 26,
    line_gap: int = 8,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(FONT_PATH, font_size)
    title_font = _load_alias_font(FONT_PATH, font_size + 4)
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


def render_draw_guess_list_image(
    header: str,
    lines: List[str],
    width: int = 1120,
    padding: int = 28,
    font_size: int = 24,
    line_gap: int = 8,
    bg_color: Tuple[int, int, int] = (245, 247, 250),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(FONT_PATH, font_size)
    title_font = _load_alias_font(FONT_PATH, font_size + 6)
    tmp = Image.new("RGBA", (width, 10), (*bg_color, 255))
    draw = ImageDraw.Draw(tmp)

    wrapped: List[Tuple[str, bool]] = []
    wrapped.extend(
        (line, True)
        for line in _wrap_text(draw, header, title_font, width - padding * 2)
    )
    wrapped.append(("", False))
    for line in lines:
        chunks = _wrap_text(draw, line, font, width - padding * 2)
        if not chunks:
            wrapped.append(("", False))
            continue
        for chunk in chunks:
            wrapped.append((chunk, False))

    title_line_h = int((font_size + 6) * 1.45)
    body_line_h = int(font_size * 1.4)
    content_height = 0
    for _, is_title in wrapped:
        content_height += title_line_h if is_title else body_line_h
        content_height += line_gap
    height = max(220, padding * 2 + content_height)

    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)
    y = padding
    for line, is_title in wrapped:
        use_font = title_font if is_title else font
        draw.text((padding, y), line, fill=fg_color, font=use_font)
        y += (title_line_h if is_title else body_line_h) + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_ranking_image(
    song_title: str,
    sections: List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]],
    province_name: Optional[str] = None,
    width: int = 1040,
    padding: int = 28,
    font_size: int = 22,
    line_gap: int = 10,
    bg_color: Tuple[int, int, int] = (244, 246, 249),
    fg_color: Tuple[int, int, int] = (28, 32, 36),
) -> bytes:
    font = _load_alias_font(SONG_RANK_FONT_PATH, font_size)
    title_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size + 10)
    section_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size + 3)
    header_font = _load_alias_font(SONG_RANK_FONT_PATH, font_size)
    tmp = Image.new("RGBA", (width, 10), (*bg_color, 255))
    draw = ImageDraw.Draw(tmp)

    title = f"歌曲排行 {song_title}"
    if province_name:
        title += f"（{province_name}）"

    title_lines = _wrap_text(draw, title, title_font, width - padding * 2)
    title_h = int((font_size + 10) * 1.55) * len(title_lines)
    section_h = int((font_size + 3) * 1.45)
    row_h = int(font_size * 1.5)
    rank_w = 52
    score_w = 140
    gap = 10
    min_name_w = int(draw.textlength("测" * 5, font=font)) + 8
    columns = max(1, len(sections))
    col_gap = 32 if columns >= 4 else 28
    min_col_width = rank_w + gap + score_w + gap + min_name_w
    width = max(
        width,
        padding * 2 + columns * min_col_width + col_gap * (columns - 1),
    )
    col_width = int((width - padding * 2 - col_gap * (columns - 1)) / columns)

    def section_height(rankings: Optional[List[Tuple[int, str, Optional[int]]]]) -> int:
        row_count = 1
        if rankings:
            row_count = len(rankings)
        return section_h + line_gap + row_h + line_gap + row_count * (row_h + line_gap)

    rows: List[List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]]] = []
    for i in range(0, len(sections), columns):
        rows.append(sections[i : i + columns])

    height = padding * 2 + title_h + line_gap
    for row in rows:
        row_heights = [section_height(rankings) for _, rankings in row]
        height += max(row_heights) + line_gap

    img = Image.new("RGBA", (width, height), (*bg_color, 255))
    draw = ImageDraw.Draw(img)

    y = padding
    for line in title_lines:
        line_w = draw.textlength(line, font=title_font)
        draw.text(((width - line_w) / 2, y), line, fill=fg_color, font=title_font)
        y += int((font_size + 10) * 1.55)
    y += line_gap

    section_bg = (230, 235, 242)
    row_alt = (236, 239, 244)
    header_fg = (60, 66, 75)
    line_color = (210, 214, 220)

    for row in rows:
        row_heights = [section_height(rankings) for _, rankings in row]
        row_height = max(row_heights)
        for col_idx, (diff_label, rankings) in enumerate(row):
            x = padding + col_idx * (col_width + col_gap)
            score_right = x + col_width
            name_x = x + rank_w + gap
            name_w = max(min_name_w, score_right - score_w - name_x - gap)

            draw.rectangle([x, y, x + col_width, y + section_h], fill=section_bg)
            section_text = f"{diff_label} Top20"
            section_w = draw.textlength(section_text, font=section_font)
            draw.text(
                (x + (col_width - section_w) / 2, y + 2),
                section_text,
                fill=fg_color,
                font=section_font,
            )
            y_section = y + section_h + line_gap

            rank_text = "排名"
            rank_text_w = draw.textlength(rank_text, font=header_font)
            draw.text(
                (x + (rank_w - rank_text_w) / 2, y_section),
                rank_text,
                fill=header_fg,
                font=header_font,
            )
            name_text = "玩家"
            name_text_w = draw.textlength(name_text, font=header_font)
            draw.text(
                (name_x + (name_w - name_text_w) / 2, y_section),
                name_text,
                fill=header_fg,
                font=header_font,
            )
            score_text = "分数"
            score_text_w = draw.textlength(score_text, font=header_font)
            draw.text(
                (score_right - score_w + (score_w - score_text_w) / 2, y_section),
                score_text,
                fill=header_fg,
                font=header_font,
            )
            y_section += row_h + line_gap

            data_rows: List[Tuple[Optional[int], str, Optional[int]]] = []
            if rankings is None:
                data_rows = [(None, "获取失败", None)]
            elif not rankings:
                data_rows = [(None, "暂无排行数据", None)]
            else:
                data_rows = rankings

            for idx, row_item in enumerate(data_rows):
                if idx % 2 == 0:
                    draw.rectangle(
                        [x, y_section - 2, x + col_width, y_section + row_h + 2],
                        fill=row_alt,
                    )
                rank, name, score = row_item
                rank_text = "--" if rank is None else str(rank)
                rank_text_w = draw.textlength(rank_text, font=font)
                draw.text(
                    (x + (rank_w - rank_text_w) / 2, y_section),
                    rank_text,
                    fill=fg_color,
                    font=font,
                )

                name_text = name or "未知"
                name_disp = _truncate_text(draw, name_text, font, name_w)
                name_disp_w = draw.textlength(name_disp, font=font)
                draw.text(
                    (name_x + (name_w - name_disp_w) / 2, y_section),
                    name_disp,
                    fill=fg_color,
                    font=font,
                )

                score_text = "--" if score is None else f"{score:,}"
                score_w_text = draw.textlength(score_text, font=font)
                draw.text(
                    (score_right - score_w + (score_w - score_w_text) / 2, y_section),
                    score_text,
                    fill=fg_color,
                    font=font,
                )
                draw.line(
                    [x, y_section + row_h + 2, x + col_width, y_section + row_h + 2],
                    fill=line_color,
                    width=1,
                )
                y_section += row_h + line_gap

        y += row_height + line_gap

    buf = BytesIO()
    img.convert("RGB").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _build_taiko_headers(authorization: str) -> Dict[str, str]:
    return {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF WindowsWechat(0x63090a13) UnifiedPCWindowsWechat(0xf2541020) XWEB/16459",
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": authorization,
    }


def _extract_rankings(
    payload: Dict[str, Any], diff_id: int
) -> Optional[List[Tuple[int, str, Optional[int]]]]:
    if "status" in payload and payload.get("status") not in (0, "0"):
        return None
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rank_data = data.get("rank_data", [])
    if isinstance(rank_data, dict):
        rank_data = [rank_data]
    target = None
    for item in rank_data:
        if item.get("level") == diff_id:
            target = item
            break
    if target is None and rank_data:
        target = rank_data[0]
    if not target:
        return []

    rankings = []
    for entry in target.get("rankings", []) or []:
        rank = entry.get("rank")
        costume = entry.get("gameCostume") or {}
        name = costume.get("mydon_name") or entry.get("mydon_name") or "未知"
        score = entry.get("score")
        try:
            rank_val = int(rank)
        except Exception:
            continue
        score_val = None
        try:
            score_val = int(score) if score is not None else None
        except Exception:
            score_val = None
        rankings.append((rank_val, name, score_val))
    rankings.sort(key=lambda x: x[0])
    return rankings[:20]


def song_id_exists(target_id: str) -> bool:
    """判断 song_data.json 中是否存在给定 id"""
    data = load_song_data()
    for item in data:
        # id 可能是 int 也可能是 str，这里统一转成 str 比较
        if str(item.get("id")) == target_id:
            return True
    return False


def find_aliases_by_song_id(song_id: str) -> Tuple[str, List[str]]:
    data = load_alias_data()
    for entry in data:
        if str(entry.get("id")) == str(song_id):
            title = entry.get("song_name_jp") or ""
            aliases = entry.get("aliases") or []
            return title, aliases
    return "", []


def _normalize_identity_key(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(str(identity_key or "").strip())
    return f"{platform}:{raw_id}" if raw_id else ""


def _resolve_requested_identity_key(event: MessageEvent) -> Tuple[str, bool]:
    self_identity = _normalize_identity_key(get_identity_key(event=event))
    target_identity = _normalize_identity_key(resolve_target_identity_key(event=event))
    is_self_query = self_identity == target_identity
    return target_identity or self_identity, is_self_query


def _resolve_bound_taiko_id(event: MessageEvent):
    identity_key, is_self_query = _resolve_requested_identity_key(event)
    info = _get_taiko_bind_info(identity_key)
    if info is None:
        return 404
    taiko_id = info["id"]
    visible = info["visible"]
    if visible == 0 and not is_self_query:
        return 403
    return taiko_id


def _get_taiko_bind_info(identity_key: str) -> Optional[Dict[str, Any]]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        identity_key = _normalize_identity_key(identity_key)
        cursor.execute(
            "select id, coalesce(visible, 0) from bind where qq=%s", (identity_key,)
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return {"id": str(row[0] or "").strip(), "visible": int(row[1] or 0)}
    except Exception:
        return None
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _set_taiko_bind_visibility(identity_key: str, visible: int) -> int:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        identity_key = _normalize_identity_key(identity_key)
        cursor.execute("select count(1) from bind where qq=%s", (identity_key,))
        row = cursor.fetchone()
        matched = int(row[0] or 0) if row is not None else 0
        if matched <= 0:
            return 0
        cursor.execute(
            "update bind set visible=%s where qq=%s", (int(visible), identity_key)
        )
        db.commit()
        return matched
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return 0
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _taiko_bind_usage_message(event: Optional[MessageEvent] = None) -> str:
    base = "请先绑定账号，发送“绑定+你的鼓众广场ID”进行绑定。"
    if event is not None and is_qq_official_event(event):
        return (
            f"{base}\n"
            "如果您以前在其他 bot 上绑定过数据，直接点击【绑定QQ】按钮并输入 QQ 号完成快捷绑定。"
            "如发现冒绑将被拉入黑名单。"
        )
    return base


def _get_taiko_db_connection():
    return get_taiko_db_connection()


def _execute_taiko_update(
    taiko_id: str,
    *,
    show_all_changes: bool = False,
    include_changes_image: bool = True,
) -> Dict[str, Any]:
    # region agent log
    _agent_debug_log(
        "taiko.py:_execute_taiko_update:enter",
        "execute taiko update",
        {
            "taiko_id": str(taiko_id),
            "show_all_changes": show_all_changes,
            "include_changes_image": include_changes_image,
        },
        hypothesis_id="A",
    )
    # endregion
    fetch_started = time.perf_counter()
    result = getUserData(taiko_id)
    fetch_ms = int((time.perf_counter() - fetch_started) * 1000)
    # region agent log
    _agent_debug_log(
        "taiko.py:_execute_taiko_update:after_getUserData",
        "getUserData finished",
        {"taiko_id": str(taiko_id), "result": result, "elapsed_ms": fetch_ms},
        hypothesis_id="A",
    )
    # endregion
    if result == -1:
        return {"ok": False, "message": "更新失败，怎么回事呢？", "image": None}
    if result == 404:
        return {"ok": False, "message": "请确认绑定鼓众ID是否正确？", "image": None}

    img_buf = None
    if include_changes_image:
        render_started = time.perf_counter()
        try:
            img_buf = render_update_changes_image(
                int(taiko_id), show_all=show_all_changes
            )
            render_ms = int((time.perf_counter() - render_started) * 1000)
            # region agent log
            _agent_debug_log(
                "taiko.py:_execute_taiko_update:after_render",
                "render_update_changes_image finished",
                {
                    "taiko_id": str(taiko_id),
                    "show_all_changes": show_all_changes,
                    "image_bytes": len(img_buf) if img_buf else 0,
                    "elapsed_ms": render_ms,
                },
                hypothesis_id="B",
            )
            # endregion
        except Exception as exc:
            # region agent log
            _agent_debug_log(
                "taiko.py:_execute_taiko_update:render_error",
                "render_update_changes_image failed",
                {
                    "taiko_id": str(taiko_id),
                    "show_all_changes": show_all_changes,
                    "error": type(exc).__name__,
                },
                hypothesis_id="B",
            )
            # endregion
            img_buf = None
    return {"ok": True, "message": "更新成功！", "image": img_buf}


def _get_current_bind_entry(identity_key: str) -> Optional[Dict[str, Any]]:
    identity_key = _normalize_identity_key(identity_key)
    bind_info = _get_taiko_bind_info(identity_key)
    if bind_info is None:
        return None
    store = _load_multi_bind_store()
    return _ensure_multi_bind_entry(store, identity_key, bind_info["id"])


def _get_bind_ids(entry: Optional[Dict[str, Any]]) -> List[str]:
    if not entry:
        return []
    return [
        str(raw or "").strip()
        for raw in (entry.get("ids") or [])
        if str(raw or "").strip()
    ]


def _has_virtual_bind_slot(entry: Optional[Dict[str, Any]]) -> bool:
    return len(_get_bind_ids(entry)) >= 2


def _get_selected_bind_slot_number(entry: Optional[Dict[str, Any]]) -> int:
    ids = _get_bind_ids(entry)
    if not ids:
        return 0
    if len(ids) < 2:
        return 1
    try:
        current_slot = int(
            entry.get("current_slot", int(entry.get("current_index", 0) or 0) + 1) or 0
        )
    except Exception:
        current_slot = int(entry.get("current_index", 0) or 0) + 1
    return max(0, min(current_slot, len(ids)))


def _get_current_real_bind_slot_number(entry: Optional[Dict[str, Any]]) -> int:
    if not entry:
        return None
    ids = _get_bind_ids(entry)
    if not ids:
        return 0
    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    return current_index + 1


def _get_current_real_bind_taiko_id(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not entry:
        return None
    ids = _get_bind_ids(entry)
    if not ids:
        return None
    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    return str(ids[current_index])


def _get_current_bind_taiko_id(entry: Optional[Dict[str, Any]]) -> Optional[str]:
    ids = _get_bind_ids(entry)
    if not ids:
        return None
    selected_slot = _get_selected_bind_slot_number(entry)
    if selected_slot <= 0:
        return None
    selected_index = max(0, min(selected_slot - 1, len(ids) - 1))
    return str(ids[selected_index])


def _build_bind_switch_hint(entry: Optional[Dict[str, Any]]) -> str:
    ids = _get_bind_ids(entry)
    if len(ids) <= 1:
        return ""
    slots = [f"u{idx}" for idx in range(1, len(ids) + 1)]
    if _has_virtual_bind_slot(entry):
        slots.insert(0, "u0")
    return "\n如需切换其他账号，请先发送 " + " / ".join(slots) + "。"


def _build_u0_readonly_message(
    entry: Optional[Dict[str, Any]], *, action_text: str
) -> str:
    summary = _format_multi_bind_summary(entry)
    real_slot = _get_current_real_bind_slot_number(entry)
    real_id = _get_current_real_bind_taiko_id(entry) or "-"
    return (
        "当前正在使用 u0：合并账户（只读）。\n"
        f"{action_text} 仅支持真实绑定账号，请先切换到 u1~u{len(_get_bind_ids(entry))} 后再试。\n"
        f"当前展示资料来源：u{real_slot}：{real_id}\n"
        f"当前绑定：{summary}{_build_bind_switch_hint(entry)}"
    )


def _resolve_read_bind_target(event: MessageEvent):
    identity_key, is_self_query = _resolve_requested_identity_key(event)
    info = _get_taiko_bind_info(identity_key)
    if info is None:
        return 404
    visible = info["visible"]
    if visible == 0 and not is_self_query:
        return 403

    entry = _get_current_bind_entry(identity_key)
    if entry is None:
        return {
            "identity_key": identity_key,
            "entry": None,
            "is_virtual": False,
            "user_id": str(info["id"] or "").strip(),
        }

    if _get_selected_bind_slot_number(entry) == 0:
        materialized = materialize_merged_bind_userdata(identity_key, entry)
        return {
            "identity_key": identity_key,
            "entry": entry,
            "is_virtual": True,
            "user_id": materialized.virtual_user_id,
            "materialized": materialized,
        }

    selected_id = _get_current_bind_taiko_id(entry) or str(info["id"] or "").strip()
    return {
        "identity_key": identity_key,
        "entry": entry,
        "is_virtual": False,
        "user_id": selected_id,
    }


def _resolve_read_bind_target_safe(event: MessageEvent):
    try:
        return _resolve_read_bind_target(event)
    except (MergedBindMissingUserdataError, MergedBindError) as error:
        return {"error": str(error)}


def _build_update_command_hint(
    identity_key: str,
    *,
    expected_source: str,
) -> str:
    entry = _get_current_bind_entry(identity_key)
    if entry is None:
        return _taiko_bind_usage_message()

    selected_slot = _get_selected_bind_slot_number(entry)
    if selected_slot == 0:
        return _build_u0_readonly_message(entry, action_text="更新命令")

    taiko_id = _get_current_bind_taiko_id(entry)
    if not taiko_id:
        return _taiko_bind_usage_message()

    actual_source = _infer_bind_source(taiko_id, entry.get("sources") or {})
    actual_label = _bind_source_label(actual_source)
    recommended_command = "更新hiroba" if actual_source == "hiroba" else "taikoupdate"
    expected_label = _bind_source_label(expected_source)
    return (
        f"当前正在使用 u{selected_slot}：{taiko_id}（{actual_label}）。\n"
        f"这不是 {expected_label} 服账号，请改用“{recommended_command}”。\n"
        f"当前绑定：{_format_multi_bind_summary(entry)}{_build_bind_switch_hint(entry)}"
    )


def _execute_hiroba_update(
    taiko_id: str,
    *,
    show_all_changes: bool = False,
    include_changes_image: bool = True,
    progress=None,
) -> Dict[str, Any]:
    cooldown_msg = peek_hiroba_sync_cooldown(taiko_id)
    if cooldown_msg:
        return {"ok": False, "message": cooldown_msg, "image": None}

    creds = load_hiroba_credentials(taiko_id)
    if creds is None:
        return {
            "ok": False,
            "message": f"当前账号 {taiko_id} 未配置 Hiroba 凭据，请发送“绑定hiroba 邮箱 密码”。",
            "image": None,
        }
    email, password = creds
    try:
        sync_hiroba_userdata(email, password, taiko_no=taiko_id, progress=progress)
    except Exception as exc:
        logger.exception("hiroba sync failed for taiko_id=%s", taiko_id)
        return {"ok": False, "message": f"Hiroba 更新失败：{exc}", "image": None}

    img_buf = None
    if include_changes_image:
        try:
            img_buf = render_update_changes_image(
                int(taiko_id), show_all=show_all_changes
            )
        except Exception:
            img_buf = None
    return {"ok": True, "message": "Hiroba 更新成功！", "image": img_buf}


def _create_hiroba_progress_reporter(
    matcher: Matcher,
    event: MessageEvent,
    *,
    min_interval: float = 8.0,
):
    loop = asyncio.get_running_loop()
    lock = threading.Lock()
    state = {"last_ts": 0.0, "last_msg": ""}

    def report(message: str, *, force: bool = False) -> None:
        text = str(message or "").strip()
        if not text:
            return
        now = time.monotonic()
        with lock:
            if not force and text == state["last_msg"]:
                return
            if not force and now - state["last_ts"] < min_interval:
                return
            state["last_ts"] = now
            state["last_msg"] = text
        asyncio.run_coroutine_threadsafe(
            _send_text_reply_without_finish(matcher, event, text),
            loop,
        )

    return report


def _load_wahlap_cookie() -> str:
    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return ""
    return str(config.get("cookie") or "").strip()


async def _fetch_bind_player_profile(
    user_id: str,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    auth = _load_wahlap_cookie()
    if not auth:
        return None, "未配置鼓众 cookie，暂时无法验证绑定。"

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Referer": "https://servicewechat.com/wxeafab0667490cd23/21/page-frame.html",
        "Authorization": auth,
    }
    payload = {"keyword": str(user_id).strip(), "page": 1, "pageSize": 10}
    url = "https://wl-taiko.wahlap.net/api/user/search/player"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload, headers=headers)
    except Exception as e:
        return None, f"读取鼓众资料失败：{e}"

    if resp.status_code not in (200, 201):
        return None, f"读取鼓众资料失败，HTTP {resp.status_code}"

    try:
        data = resp.json()
    except Exception:
        return None, "读取鼓众资料失败：返回内容无法解析。"

    players = (
        ((data.get("data") or {}).get("players") or [])
        if isinstance(data, dict)
        else []
    )
    if not isinstance(players, list) or not players:
        return None, "未找到该鼓众ID，请确认输入是否正确。"

    user_id_text = str(user_id).strip()
    for player in players:
        if (
            isinstance(player, dict)
            and str(player.get("userid") or "").strip() == user_id_text
        ):
            return player, None

    if len(players) == 1 and isinstance(players[0], dict):
        return players[0], None
    return None, "未找到该鼓众ID，请确认输入是否正确。"


def _extract_bind_title_info(profile: Dict[str, Any]) -> Tuple[str, int]:
    costume = profile.get("gameCostume") or {}
    if not isinstance(costume, dict):
        costume = {}
    title = str(costume.get("title") or "").strip()
    try:
        titleplate_id = int(costume.get("titleplate_id"))
    except Exception:
        titleplate_id = -1
    return title, titleplate_id


def _get_bind_verify_session(qq: str) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq))
    session = BIND_VERIFY_SESSIONS.get(qq)
    if session is None:
        return None
    if int(session.get("expires_at", 0) or 0) <= _now_ts():
        BIND_VERIFY_SESSIONS.pop(qq, None)
        return None
    return session


def _bind_title_changed(session: Dict[str, Any], profile: Dict[str, Any]) -> bool:
    current_title, current_titleplate_id = _extract_bind_title_info(profile)
    return current_title != str(
        session.get("title") or ""
    ).strip() or current_titleplate_id != int(session.get("titleplate_id", -1) or -1)


def _build_bind_verify_prompt(
    player_name: str,
    taiko_id: str,
    current_title: str,
    province: str = "",
) -> str:
    title_text = current_title or "空称号"
    province_text = f"\n地区：{province}" if province else ""
    return (
        f"已发起绑定验证。\n玩家：{player_name}\n当前称号：{title_text}{province_text}\n"
        f"请先在鼓众广场更换称号，再发送“确认绑定”完成验证。\n"
        f"更换后也可再次发送“绑定 {taiko_id}”完成验证。\n"
        f"本次验证 {BIND_VERIFY_TIMEOUT_SECONDS // 60} 分钟内有效。"
    )


def _build_bind_title_unchanged_message(
    session: Dict[str, Any], current_title: str, taiko_id: str
) -> str:
    original_title = str(session.get("title") or "").strip() or "空称号"
    return (
        "验证未通过，检测到称号尚未变化。\n"
        f"当前称号：{current_title or '空称号'}\n"
        f"初始称号：{original_title}\n"
        f"请先更换称号后再发送“确认绑定”或重新发送“绑定 {taiko_id}”。"
    )


def _should_skip_bind_verification(taiko_id: str) -> bool:
    return str(taiko_id).strip() in BIND_VERIFY_BYPASS_IDS


def _build_bind_auto_update_tip(
    identity_key: str, taiko_id: str, is_first_binding: bool
) -> str:
    if not is_first_binding:
        return ""
    update_result = _execute_taiko_update(taiko_id, include_changes_image=False)
    if update_result.get("ok"):
        return "\n首次绑定已自动执行一次 taikoupdate。"
    logger.warning(
        "首次绑定自动 taikoupdate 失败，qq=%s taiko_id=%s msg=%s",
        identity_key,
        taiko_id,
        update_result.get("message"),
    )
    return (
        "\n首次绑定后已自动尝试执行一次 taikoupdate，但本次更新未完成，可稍后手动执行。"
    )


def _finalize_bind_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> str:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_tip = _build_bind_auto_update_tip(
        identity_key, taiko_id, is_first_binding
    )
    return (
        f"{reply_msg}\n已通过称号变更验证。\n当前称号：{current_title or '空称号'}"
        f"{auto_update_tip}"
    )


def _finalize_bind_without_verification(
    identity_key: str, taiko_id: str, current_title: str
) -> str:
    reply_msg, is_first_binding = _upsert_bind_record(
        identity_key, taiko_id, source="wahlap"
    )
    BIND_VERIFY_SESSIONS.pop(identity_key, None)
    auto_update_tip = _build_bind_auto_update_tip(
        identity_key, taiko_id, is_first_binding
    )
    return (
        f"{reply_msg}\n已按临时白名单跳过绑定验证。\n当前称号：{current_title or '空称号'}"
        f"{auto_update_tip}"
    )


def _build_legacy_qq_identity_key(qq_number: str) -> str:
    return _normalize_identity_key(
        build_identity_key(ONEBOT_V11_PLATFORM, str(qq_number or "").strip())
    )


def _merge_bind_id_lists(primary_ids: List[str], secondary_ids: List[str]) -> List[str]:
    merged: List[str] = []
    for raw_id in list(primary_ids) + list(secondary_ids):
        taiko_id = str(raw_id or "").strip()
        if not taiko_id or taiko_id in merged:
            continue
        merged.append(taiko_id)
    return merged


def _migrate_bind_from_legacy_qq(
    legacy_qq: str, target_identity_key: str
) -> Tuple[bool, str]:
    source_identity_key = _build_legacy_qq_identity_key(legacy_qq)
    target_identity_key = _normalize_identity_key(target_identity_key)
    if not source_identity_key or not target_identity_key:
        return False, "缺少有效身份信息，无法迁移绑定。"

    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        source_row = None
        for source_lookup_key in [source_identity_key, str(legacy_qq or "").strip()]:
            if not source_lookup_key:
                continue
            cursor.execute(
                "select id, coalesce(visible, 0) from bind where qq=%s",
                (source_lookup_key,),
            )
            source_row = cursor.fetchone()
            if source_row is not None:
                break
        if source_row is None:
            return (
                False,
                f"未找到 QQ {legacy_qq} 的历史绑定记录。\n"
                "请直接发送“绑定 你的鼓众广场ID”进行挑战验证。",
            )

        source_db_id = str(source_row[0] or "").strip()
        source_visible = int(source_row[1] or 0)
        store = _load_multi_bind_store()
        source_entry = _ensure_multi_bind_entry(
            store, source_identity_key, source_db_id
        )
        source_ids = list((source_entry or {}).get("ids") or [])
        if not source_ids and source_db_id:
            source_ids = [source_db_id]
        if not source_ids:
            return (
                False,
                f"QQ {legacy_qq} 的历史绑定记录不完整。\n"
                "请直接发送“绑定 你的鼓众广场ID”进行挑战验证。",
            )

        source_current_index = int((source_entry or {}).get("current_index", 0) or 0)
        source_current_index = max(0, min(source_current_index, len(source_ids) - 1))
        source_current_id = source_ids[source_current_index]

        cursor.execute(
            "select id, coalesce(visible, 0) from bind where qq=%s",
            (target_identity_key,),
        )
        target_row = cursor.fetchone()
        target_db_id = str(target_row[0] or "").strip() if target_row else ""
        target_visible = int(target_row[1] or 0) if target_row else source_visible
        target_entry = _ensure_multi_bind_entry(
            store, target_identity_key, target_db_id
        )
        target_ids = list((target_entry or {}).get("ids") or [])
        if not target_ids and target_db_id:
            target_ids = [target_db_id]

        merged_ids = _merge_bind_id_lists(source_ids, target_ids)
        merged_current_index = merged_ids.index(source_current_id)

        if target_row is None:
            cursor.execute(
                "insert into bind values(%s,%s,%s)",
                (target_identity_key, source_current_id, source_visible),
            )
            is_first_binding = True
        else:
            cursor.execute(
                "update bind set id=%s, visible=%s where qq=%s",
                (source_current_id, target_visible, target_identity_key),
            )
            is_first_binding = False

        store[str(target_identity_key)] = {
            "ids": merged_ids,
            "current_index": merged_current_index,
            "current_slot": merged_current_index + 1,
        }
        _save_multi_bind_store(store)
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        raise
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()

    BIND_VERIFY_SESSIONS.pop(target_identity_key, None)
    action_text = "完成迁移" if is_first_binding else "完成合并"
    summary = _format_multi_bind_summary(
        {"ids": merged_ids, "current_index": merged_current_index}
    )
    auto_update_tip = _build_bind_auto_update_tip(
        target_identity_key, source_current_id, is_first_binding
    )
    return (
        True,
        f"已根据 QQ {legacy_qq} 的历史绑定{action_text}。\n当前绑定：{summary}"
        f"{auto_update_tip}",
    )


def _normalize_multi_bind_ids(ids: Any) -> List[str]:
    out: List[str] = []
    seen = set()
    if not isinstance(ids, list):
        return out
    for raw in ids:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _load_multi_bind_store() -> Dict[str, Dict[str, Any]]:
    path = TAIKO_MULTI_BIND_PATH
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}

    cleaned: Dict[str, Dict[str, Any]] = {}
    for raw_qq, payload in raw.items():
        if not isinstance(payload, dict):
            continue
        qq = _normalize_identity_key(str(raw_qq).strip())
        ids = _normalize_multi_bind_ids(payload.get("ids"))
        if not qq or not ids:
            continue
        try:
            current_index = int(payload.get("current_index", 0) or 0)
        except Exception:
            current_index = 0
        current_index = max(0, min(current_index, len(ids) - 1))
        try:
            current_slot = int(payload.get("current_slot", current_index + 1) or 0)
        except Exception:
            current_slot = current_index + 1
        if len(ids) < 2:
            current_slot = 1
        else:
            current_slot = max(0, min(current_slot, len(ids)))
        sources = payload.get("sources") if isinstance(payload, dict) else {}
        if not isinstance(sources, dict):
            sources = {}
        cleaned_sources = {
            str(taiko_id): str(source)
            for taiko_id, source in sources.items()
            if str(taiko_id) in ids and str(source).strip()
        }
        cleaned[qq] = {
            "ids": ids,
            "current_index": current_index,
            "current_slot": current_slot,
            "sources": cleaned_sources,
        }
    return cleaned


def _save_multi_bind_store(store: Dict[str, Dict[str, Any]]) -> None:
    TAIKO_MULTI_BIND_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TAIKO_MULTI_BIND_PATH.open("w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def _ensure_multi_bind_entry(
    store: Dict[str, Dict[str, Any]], qq: str, fallback_id: str = ""
) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq).strip())
    fallback = str(fallback_id or "").strip()
    payload = store.get(qq)
    ids = _normalize_multi_bind_ids(
        payload.get("ids") if isinstance(payload, dict) else None
    )
    if not ids and fallback:
        ids = [fallback]
    if not ids:
        return None

    try:
        current_index = int((payload or {}).get("current_index", 0) or 0)
    except Exception:
        current_index = 0
    try:
        current_slot = int((payload or {}).get("current_slot", current_index + 1) or 0)
    except Exception:
        current_slot = current_index + 1
    if fallback and fallback in ids:
        current_index = ids.index(fallback)
        if current_slot != 0:
            current_slot = current_index + 1
    current_index = max(0, min(current_index, len(ids) - 1))
    if len(ids) < 2:
        current_slot = 1
    else:
        current_slot = max(0, min(current_slot, len(ids)))
    sources = (payload or {}).get("sources") if isinstance(payload, dict) else {}
    if not isinstance(sources, dict):
        sources = {}
    entry = {
        "ids": ids,
        "current_index": current_index,
        "current_slot": current_slot,
        "sources": {
            str(taiko_id): str(source)
            for taiko_id, source in sources.items()
            if str(taiko_id) in ids and str(source).strip()
        },
    }
    store[qq] = entry
    return entry


def _infer_bind_source(taiko_id: str, sources: Optional[Dict[str, str]] = None) -> str:
    taiko_id = str(taiko_id or "").strip()
    sources = sources or {}
    explicit = str(sources.get(taiko_id) or "").strip().lower()
    if explicit in {"hiroba", "wahlap"}:
        return explicit
    if has_hiroba_credentials(taiko_id):
        return "hiroba"
    return "wahlap"


def _bind_source_label(source: str) -> str:
    return "JP" if source == "hiroba" else "CN"


def _set_bind_source(
    entry: Dict[str, Any], taiko_id: str, source: str
) -> Dict[str, Any]:
    sources = dict(entry.get("sources") or {})
    sources[str(taiko_id)] = str(source)
    entry["sources"] = sources
    return entry


def _format_multi_bind_summary(entry: Optional[Dict[str, Any]]) -> str:
    if not entry:
        return "暂无已绑定的鼓众广场ID。"
    ids = _get_bind_ids(entry)
    current_slot = _get_selected_bind_slot_number(entry)
    parts = []
    if _has_virtual_bind_slot(entry):
        marker = "（当前）" if current_slot == 0 else ""
        parts.append(f"u0:合并账户(只读){marker}")
    for idx, taiko_id in enumerate(ids, start=1):
        marker = "（当前）" if idx == current_slot else ""
        source = _infer_bind_source(str(taiko_id), entry.get("sources") or {})
        parts.append(f"u{idx}:{taiko_id}({_bind_source_label(source)}){marker}")
    return " / ".join(parts)


def _get_bind_delete_confirm_session(qq: str) -> Optional[Dict[str, Any]]:
    qq = _normalize_identity_key(str(qq))
    session = BIND_DELETE_CONFIRM_SESSIONS.get(qq)
    if not session:
        return None
    if float(session.get("expires_at", 0) or 0) < _now_ts():
        BIND_DELETE_CONFIRM_SESSIONS.pop(qq, None)
        return None
    return session


def _resolve_bind_remove_target(entry: Dict[str, Any], target: str) -> Tuple[int, str]:
    ids = list(entry.get("ids") or [])
    if not ids:
        raise ValueError("当前没有可删除的鼓众广场ID。")

    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    target = str(target or "").strip()
    if not target:
        return current_index, ids[current_index]

    slot_match = re.fullmatch(r"[uU]([1-9]\d*)", target)
    if slot_match:
        slot_index = int(slot_match.group(1)) - 1
        if slot_index < 0 or slot_index >= len(ids):
            raise ValueError(f"当前仅已绑定 u1~u{len(ids)}。")
        return slot_index, ids[slot_index]

    if target in ids:
        return ids.index(target), target

    if target.isdigit():
        raise ValueError("当前未绑定该鼓众广场ID。")

    raise ValueError(
        "参数错误，请使用 删除绑定 / 删除绑定 u2 / 删除绑定 123456 这类形式。"
    )


def _upsert_bind_record(
    qq: str, taiko_id: str, *, source: Optional[str] = None
) -> Tuple[str, bool]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        qq = _normalize_identity_key(qq)
        taiko_id = str(taiko_id).strip()
        cursor.execute("select id from bind where qq=%s", (qq,))
        row = cursor.fetchone()
        current_db_id = str(row[0] or "").strip() if row else ""
        store = _load_multi_bind_store()
        entry = _ensure_multi_bind_entry(store, qq, current_db_id)
        is_first_binding = row is None
        if row is None:
            cursor.execute("insert into bind values(%s,%s,%s)", (qq, taiko_id, 0))
            entry = {
                "ids": [taiko_id],
                "current_index": 0,
                "current_slot": 1,
                "sources": {taiko_id: source or "wahlap"},
            }
            store[str(qq)] = entry
            reply_msg = "绑定成功！已设为 u1。"
        else:
            if entry is None:
                entry = {"ids": [], "current_index": 0, "sources": {}}
            ids = list(entry.get("ids") or [])
            if taiko_id in ids:
                current_index = ids.index(taiko_id)
                entry["current_index"] = current_index
                entry["current_slot"] = current_index + 1
                if source:
                    _set_bind_source(entry, taiko_id, source)
                if current_db_id != taiko_id:
                    cursor.execute("update bind set id=%s where qq=%s", (taiko_id, qq))
                    reply_msg = f"该ID已绑定，已切换到 u{current_index + 1}。"
                else:
                    reply_msg = f"该ID已绑定，当前使用 u{current_index + 1}。"
            else:
                ids.append(taiko_id)
                entry["ids"] = ids
                entry["current_index"] = len(ids) - 1
                entry["current_slot"] = len(ids)
                _set_bind_source(entry, taiko_id, source or "wahlap")
                cursor.execute("update bind set id=%s where qq=%s", (taiko_id, qq))
                reply_msg = f"新增绑定成功！已设为 u{len(ids)}。"
            store[str(qq)] = entry
        if row is None:
            pass
        _save_multi_bind_store(store)
        db.commit()
        summary = _format_multi_bind_summary(store.get(str(qq)))
        return f"{reply_msg}\n当前绑定：{summary}", is_first_binding
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _switch_bind_record(
    qq: str, slot_number: int, event: Optional[MessageEvent] = None
) -> Tuple[bool, str]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        qq = _normalize_identity_key(qq)
        cursor.execute("select id from bind where qq=%s", (qq,))
        row = cursor.fetchone()
        if row is None:
            return False, _taiko_bind_usage_message(event)

        current_db_id = str(row[0] or "").strip()
        store = _load_multi_bind_store()
        entry = _ensure_multi_bind_entry(store, qq, current_db_id)
        if entry is None:
            return False, "当前没有可切换的鼓众广场ID。"

        ids = _get_bind_ids(entry)
        has_virtual_slot = _has_virtual_bind_slot(entry)
        if slot_number == 0:
            if not has_virtual_slot:
                return False, "当前至少需要绑定 2 个鼓众广场ID 后才能切换到 u0。"
            entry["current_slot"] = 0
            store[str(qq)] = entry
            _save_multi_bind_store(store)
            db.commit()
            summary = _format_multi_bind_summary(entry)
            return True, f"已切换到 u0：合并账户（只读）\n当前绑定：{summary}"

        if slot_number < 1 or slot_number > len(ids):
            if has_virtual_slot:
                return False, f"当前仅已绑定 u0~u{len(ids)}。"
            return False, f"当前仅已绑定 u1~u{len(ids)}。"

        target_index = slot_number - 1
        target_id = ids[target_index]
        entry["current_index"] = target_index
        entry["current_slot"] = slot_number
        store[str(qq)] = entry
        if current_db_id != target_id:
            cursor.execute("update bind set id=%s where qq=%s", (target_id, qq))
        _save_multi_bind_store(store)
        db.commit()
        summary = _format_multi_bind_summary(entry)
        return True, f"已切换到 u{slot_number}：{target_id}\n当前绑定：{summary}"
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _remove_bind_record(
    qq: str,
    target: str = "",
    force_last: bool = False,
    event: Optional[MessageEvent] = None,
) -> Tuple[bool, str, bool]:
    db = _get_taiko_db_connection()
    cursor = db.cursor()
    try:
        qq = _normalize_identity_key(qq)
        cursor.execute("select id from bind where qq=%s", (qq,))
        row = cursor.fetchone()
        if row is None:
            return False, _taiko_bind_usage_message(event), False

        current_db_id = str(row[0] or "").strip()
        store = _load_multi_bind_store()
        entry = _ensure_multi_bind_entry(store, qq, current_db_id)
        if entry is None:
            return False, "当前没有可删除的鼓众广场ID。", False

        try:
            remove_index, remove_id = _resolve_bind_remove_target(entry, target)
        except ValueError as e:
            return False, str(e), False

        ids = list(entry.get("ids") or [])
        current_index = int(entry.get("current_index", 0) or 0)
        current_index = max(0, min(current_index, len(ids) - 1))

        if len(ids) == 1 and not force_last:
            return (
                False,
                f"当前只剩最后 1 个鼓众广场ID：{remove_id}\n"
                f"如需确认删除，请在 {BIND_DELETE_CONFIRM_TIMEOUT_SECONDS // 60} 分钟内发送“确认删除绑定”。",
                True,
            )

        ids.pop(remove_index)
        removed_sources = dict(entry.get("sources") or {})
        removed_source = _infer_bind_source(remove_id, removed_sources)
        if remove_id in removed_sources:
            removed_sources.pop(remove_id, None)
        if removed_source == "hiroba":
            try:
                delete_hiroba_credentials(remove_id)
            except Exception:
                pass
        if ids:
            if remove_index < current_index:
                current_index -= 1
            elif remove_index == current_index:
                current_index = min(remove_index, len(ids) - 1)

            selected_slot = int(entry.get("current_slot", current_index + 1) or 0)
            if len(ids) < 2:
                current_slot = 1
            elif selected_slot == 0:
                current_slot = 0
            else:
                current_slot = current_index + 1

            entry = {
                "ids": ids,
                "current_index": current_index,
                "current_slot": current_slot,
                "sources": {
                    str(taiko_id): str(source)
                    for taiko_id, source in removed_sources.items()
                    if str(taiko_id) in ids
                },
            }
            store[str(qq)] = entry
            cursor.execute(
                "update bind set id=%s where qq=%s", (ids[current_index], qq)
            )
            summary = _format_multi_bind_summary(entry)
            reply = f"已删除绑定：{remove_id}\n当前绑定：{summary}"
        else:
            store.pop(str(qq), None)
            cursor.execute("delete from bind where qq=%s", (qq,))
            reply = f"已删除最后一个绑定：{remove_id}\n当前已无绑定的鼓众广场ID。"

        _save_multi_bind_store(store)
        db.commit()
        BIND_DELETE_CONFIRM_SESSIONS.pop(str(qq), None)
        return True, reply, False
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def _query_music_with_mode(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> Tuple[List[List[Any]], Optional[str]]:
    alias_data = json.load(open("songs/song_alias.json", "r", encoding="utf-8"))
    song_data = json.load(open("songs/song_data.json", "r", encoding="utf-8"))
    query = (name or "").strip()
    if not query:
        return [], None
    query_lower = query.lower()

    id_to_title: Dict[int, str] = {}
    for music in song_data:
        try:
            sid = int(music.get("id"))
        except Exception:
            continue
        title = music.get("song_name_jp") or music.get("song_name") or f"ID{sid}"
        id_to_title[sid] = title

    def _dedupe_by_id(rows: List[List[Any]]) -> List[List[Any]]:
        seen = set()
        out: List[List[Any]] = []
        for row in rows:
            if not row:
                continue
            sid = row[0]
            if sid in seen:
                continue
            seen.add(sid)
            out.append(row)
        return out

    # 1) 精准匹配全名（song_name_jp / song_name，不区分大小写）
    exact_name_hits: List[List[Any]] = []
    for music in song_data:
        jp = str(music.get("song_name_jp") or "")
        cn = str(music.get("song_name") or "")
        jp_lower = jp.lower()
        cn_lower = cn.lower()
        if query_lower == jp_lower or query_lower == cn_lower:
            exact_name_hits.append([music.get("id"), jp or cn])
    exact_name_hits = _dedupe_by_id(exact_name_hits)
    if exact_name_hits:
        return exact_name_hits, "exact_name"

    # 2) 精准匹配 id（兼容 id 前缀）
    id_token = query_lower
    if id_token.startswith("id"):
        id_token = id_token[2:]
    id_token = id_token.strip()
    if id_token.isdigit():
        target_id = int(id_token)
        if target_id in id_to_title:
            return [[target_id, id_to_title[target_id]]], "exact_id"

    # 3) 精准匹配别名（不区分大小写）
    exact_alias_hits: List[List[Any]] = []
    for entry in alias_data:
        aliases = entry.get("aliases") or []
        sid = entry.get("id")
        try:
            sid_int = int(sid)
        except Exception:
            sid_int = sid
        for alias in aliases:
            if isinstance(alias, str) and query_lower == alias.lower():
                title = (
                    entry.get("song_name_jp") or id_to_title.get(sid_int) or str(sid)
                )
                exact_alias_hits.append([sid_int, title])
                break
    exact_alias_hits = _dedupe_by_id(exact_alias_hits)
    if exact_alias_hits:
        return exact_alias_hits, "exact_alias"

    # 4) 全名部分匹配（输入是曲名连续子串，不区分大小写）
    if allow_partial:
        partial_name_hits: List[List[Any]] = []
        for music in song_data:
            jp = str(music.get("song_name_jp") or "")
            cn = str(music.get("song_name") or "")
            jp_lower = jp.lower()
            cn_lower = cn.lower()
            if (jp_lower and query_lower in jp_lower) or (
                cn_lower and query_lower in cn_lower
            ):
                partial_name_hits.append([music.get("id"), jp or cn])
        partial_name_hits = _dedupe_by_id(partial_name_hits)
        if partial_name_hits:
            return partial_name_hits, "partial_name"

    if not allow_fuzzy:
        return [], None

    # 5) 模糊匹配（返回单条，并附带匹配度）
    best_match: Optional[Dict[str, Any]] = None

    for music in song_data:
        sid = music.get("id")
        title = music.get("song_name_jp") or music.get("song_name") or str(sid)
        candidates = [
            str(music.get("song_name_jp") or "").lower(),
            str(music.get("song_name") or "").lower(),
        ]
        scores = [fuzz.ratio(query_lower, cand) for cand in candidates if cand]
        if not scores:
            continue
        ratio = max(scores)
        if best_match is None or ratio > best_match["ratio"]:
            best_match = {"id": sid, "title": title, "ratio": ratio}

    for entry in alias_data:
        sid = entry.get("id")
        if str(sid).isdigit():
            sid_as_int = int(sid)
            title = entry.get("song_name_jp") or id_to_title.get(sid_as_int) or str(sid)
        else:
            title = entry.get("song_name_jp") or str(sid)
        aliases = entry.get("aliases") or []
        for alias in aliases:
            if not isinstance(alias, str):
                continue
            ratio = fuzz.ratio(query_lower, alias.lower())
            if best_match is None or ratio > best_match["ratio"]:
                best_match = {"id": sid, "title": title, "ratio": ratio}

    if best_match is None:
        return [], None
    return [[best_match["id"], best_match["title"], best_match["ratio"]]], "fuzzy"


def queryMusic(
    name: str, *, allow_partial: bool = True, allow_fuzzy: bool = True
) -> List[List[Any]]:
    results, _ = _query_music_with_mode(
        name, allow_partial=allow_partial, allow_fuzzy=allow_fuzzy
    )
    return results


def _resolve_what_song_query(raw_q: str, stripped_q: str) -> List[List[Any]]:
    if not stripped_q or stripped_q == raw_q:
        return queryMusic(raw_q)

    # 先保留真正存在的“里xxx/鬼xxx”精确别名或曲名，再优先解析去前缀后的关键词。
    raw_exact_results, _ = _query_music_with_mode(
        raw_q, allow_partial=False, allow_fuzzy=False
    )
    if raw_exact_results:
        return raw_exact_results

    stripped_non_fuzzy_results = queryMusic(stripped_q, allow_fuzzy=False)
    if stripped_non_fuzzy_results:
        return stripped_non_fuzzy_results

    raw_non_fuzzy_results = queryMusic(raw_q, allow_fuzzy=False)
    if raw_non_fuzzy_results:
        return raw_non_fuzzy_results

    stripped_results = queryMusic(stripped_q)
    if stripped_results:
        return stripped_results

    return queryMusic(raw_q)


def _is_fuzzy_query_result(results: List[List[Any]]) -> bool:
    return (
        bool(results)
        and len(results) == 1
        and len(results[0]) >= 3
        and isinstance(results[0][2], (int, float))
    )


def _build_fuzzy_query_hint(results: List[List[Any]]) -> str:
    title = results[0][1]
    ratio = float(results[0][2]) / 100.0
    return f"你要找的可能是：{title}\n匹配度：{ratio:.2f}"


async def _finish_fuzzy_query_with_fumen(
    matcher: Matcher,
    event: MessageEvent,
    results: List[List[Any]],
    difficulty: str = "Oni",
) -> None:
    hint = _build_fuzzy_query_hint(results)
    song_id = str(results[0][0]).strip()
    path = _get_fumen_path(difficulty, song_id)
    if path.exists():
        bio = file_to_bytesio(path)
        await _finish_with_image_fallback(
            matcher,
            event,
            hint,
            bio,
            fallback_note="（谱面图片发送失败，请稍后重试）",
        )
    await _finish_text_reply(matcher, event, hint)


def _now_ts() -> int:
    return int(datetime.utcnow().timestamp())


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _song_id_to_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _draw_guess_user_session_key(event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    scope = f"group:{group_id}" if group_id is not None else "private"
    return f"{scope}:user:{event.get_user_id()}"


def _draw_guess_group_session_key(event: MessageEvent) -> Optional[str]:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return None
    return str(group_id)


def _session_is_expired(last_active_ts: Any) -> bool:
    return (_now_ts() - _as_int(last_active_ts, 0)) >= DRAW_GUESS_TIMEOUT_SECONDS


def _touch_session(session: Dict[str, Any]) -> None:
    session["updated_at"] = _now_ts()


def _format_song_ids(song_ids: List[int]) -> str:
    cleaned = sorted({_as_int(v, -1) for v in song_ids if _as_int(v, -1) > 0})
    return "、".join(str(v) for v in cleaned)


def _normalize_song_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip()).lower()


def _extract_first_image_segment(msg: Message) -> Optional[MessageSegment]:
    for seg in msg:
        if seg.type == "image":
            return seg
    return None


def _sender_attr(sender: Any, key: str) -> str:
    if sender is None:
        return ""
    if isinstance(sender, dict):
        value = sender.get(key)
    else:
        value = getattr(sender, key, None)
    return str(value).strip() if value is not None else ""


def _extract_uploader_nickname(event: MessageEvent) -> str:
    sender = getattr(event, "sender", None)
    card = _sender_attr(sender, "card")
    if card:
        return card
    nickname = _sender_attr(sender, "nickname")
    if nickname:
        return nickname
    return event.get_user_id()


async def _extract_uploader_group_name(bot: Bot, event: MessageEvent) -> str:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return "私聊"
    try:
        info = await bot.call_api(
            "get_group_info", group_id=int(group_id), no_cache=True
        )
        name = info.get("group_name") if isinstance(info, dict) else ""
        if isinstance(name, str) and name.strip():
            return name.strip()
    except Exception as e:
        logger.debug("get_group_info_failed group_id=%s err=%s", group_id, e)
    return f"群{group_id}"


async def _download_image_segment_bytes(
    bot: Bot, image_seg: MessageSegment
) -> Optional[bytes]:
    img_url = image_seg.data.get("url")
    if not img_url:
        file_key = image_seg.data.get("file")
        if file_key:
            try:
                img_info = await bot.call_api("get_image", file=file_key)
                img_url = img_info.get("url") if isinstance(img_info, dict) else None
            except Exception:
                img_url = None
    if not img_url:
        return None

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(img_url)
            resp.raise_for_status()
            return resp.content
    except Exception:
        return None


def _convert_image_to_png_bytes(image_bytes: bytes) -> bytes:
    with Image.open(BytesIO(image_bytes)) as img:
        mode = "RGBA" if "A" in img.getbands() else "RGB"
        normalized = img.convert(mode)
        out = BytesIO()
        normalized.save(out, format="PNG")
        return out.getvalue()


def _default_draw_guess_db() -> Dict[str, Any]:
    return {"next_id": 1, "records": [], "user_guess_stats": {}}


def _ensure_draw_guess_storage() -> None:
    DRAW_GUESS_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    if not DRAW_GUESS_DB_PATH.exists():
        with DRAW_GUESS_DB_PATH.open("w", encoding="utf-8") as f:
            json.dump(_default_draw_guess_db(), f, ensure_ascii=False, indent=2)
            f.write("\n")


def _load_draw_guess_db() -> Dict[str, Any]:
    _ensure_draw_guess_storage()
    try:
        with DRAW_GUESS_DB_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = _default_draw_guess_db()

    if not isinstance(data, dict):
        data = _default_draw_guess_db()
    next_id = _as_int(data.get("next_id"), 1)
    if next_id < 1:
        next_id = 1
    records = data.get("records")
    if not isinstance(records, list):
        records = []
    user_guess_stats = data.get("user_guess_stats")
    if not isinstance(user_guess_stats, dict):
        user_guess_stats = {}

    cleaned: List[Dict[str, Any]] = []
    for item in records:
        if not isinstance(item, dict):
            continue
        rid = _as_int(item.get("id"), 0)
        if rid <= 0:
            continue
        item["id"] = rid
        if "song_ids" not in item or not isinstance(item["song_ids"], list):
            item["song_ids"] = []
        item["song_ids"] = [
            sid
            for sid in (_song_id_to_int(v) for v in item["song_ids"])
            if sid is not None
        ]
        for key in (
            "guess_correct_count",
            "guess_wrong_count",
            "like_count",
            "report_count",
        ):
            item[key] = max(0, _as_int(item.get(key), 0))
        item["active"] = bool(item.get("active", True))
        cleaned.append(item)

    cleaned_user_stats: Dict[str, Dict[str, Any]] = {}
    for user_id_raw, payload in user_guess_stats.items():
        user_id = str(user_id_raw).strip()
        if not user_id:
            continue
        if not isinstance(payload, dict):
            payload = {}
        nickname = str(payload.get("nickname") or user_id)
        total_correct = max(0, _as_int(payload.get("total_correct"), 0))
        groups = payload.get("groups")
        if not isinstance(groups, dict):
            groups = {}
        cleaned_groups: Dict[str, Dict[str, Any]] = {}
        for gid_raw, g_payload in groups.items():
            gid = str(gid_raw).strip()
            if not gid:
                continue
            if not isinstance(g_payload, dict):
                g_payload = {}
            cleaned_groups[gid] = {
                "correct": max(0, _as_int(g_payload.get("correct"), 0)),
                "group_name": str(g_payload.get("group_name") or f"群{gid}"),
            }
        cleaned_user_stats[user_id] = {
            "nickname": nickname,
            "total_correct": total_correct,
            "groups": cleaned_groups,
        }

    return {
        "next_id": next_id,
        "records": cleaned,
        "user_guess_stats": cleaned_user_stats,
    }


def _save_draw_guess_db(data: Dict[str, Any]) -> None:
    with DRAW_GUESS_DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def _draw_guess_record_image_path(record: Dict[str, Any]) -> Path:
    image_file = str(record.get("image_file") or "").strip()
    if image_file:
        p = Path(image_file)
        if p.is_absolute():
            return p
        return DRAW_GUESS_DATA_DIR / p
    return DRAW_GUESS_IMAGE_DIR / f"{_as_int(record.get('id'), 0)}.png"


def _find_draw_guess_record(
    records: List[Dict[str, Any]], record_id: int
) -> Optional[Dict[str, Any]]:
    for item in records:
        if _as_int(item.get("id"), -1) == record_id:
            return item
    return None


def _resolve_draw_song_selection(
    results: List[List[Any]],
) -> Tuple[Optional[str], List[int], str]:
    if not results:
        return None, [], ""

    fuzzy_hint = (
        _build_fuzzy_query_hint(results) if _is_fuzzy_query_result(results) else ""
    )
    normalized: List[Tuple[int, str]] = []
    seen_ids: Set[int] = set()
    for row in results:
        if not row:
            continue
        song_id = _song_id_to_int(row[0])
        if song_id is None or song_id in seen_ids:
            continue
        seen_ids.add(song_id)
        title = str(row[1] if len(row) > 1 else "").strip()
        if not title:
            title = get_song_title_by_id(str(song_id)) or f"id{song_id}"
        normalized.append((song_id, title))

    if not normalized:
        return None, [], fuzzy_hint

    song_ids = [sid for sid, _ in normalized]
    title_keys = {
        _normalize_song_title(title) for _, title in normalized if title.strip()
    }
    if len(song_ids) == 1 or (title_keys and len(title_keys) == 1):
        display_title = normalized[0][1]
        for _, title in normalized:
            if title.strip():
                display_title = title
                break
        return display_title, song_ids, fuzzy_hint
    return None, [], fuzzy_hint


def _build_draw_song_candidates_text(results: List[List[Any]]) -> str:
    lines = ["匹配到多首歌曲，请输入更精确的歌名或歌曲id。可随时输入“0”退出"]
    for row in results[:20]:
        if not row:
            continue
        song_id = row[0]
        title = str(row[1] if len(row) > 1 else "").strip() or f"id{song_id}"
        lines.append(f"id{song_id} {title}")
    if len(results) > 20:
        lines.append("...")
    return "\n".join(lines)


def _build_draw_guess_confirm_text(
    song_title: str, song_ids: List[int], fuzzy_hint: str = ""
) -> str:
    song_ids_text = _format_song_ids(song_ids)
    confirm_text = (
        f"您要制作的歌名是{song_title}，id是{song_ids_text}，确认请发送“绘图”"
    )
    if fuzzy_hint:
        return f"{fuzzy_hint}\n{confirm_text}"
    return confirm_text


def _resolve_draw_guess_song_input_message(
    text: str,
) -> Tuple[str, str, Optional[str], List[int]]:
    plain = (text or "").strip()
    if not plain:
        return (
            "need_text",
            "请输入歌名或歌曲id。可随时输入“0”退出",
            None,
            [],
        )

    try:
        results = queryMusic(plain)
    except Exception as e:
        return ("error", f"查询歌曲失败：{e}", None, [])

    if not results:
        return (
            "not_found",
            "未找到匹配的歌曲，请输入歌名或歌曲id。可随时输入“0”退出",
            None,
            [],
        )

    song_title, song_ids, fuzzy_hint = _resolve_draw_song_selection(results)
    if not song_title or not song_ids:
        return ("multiple", _build_draw_song_candidates_text(results), None, [])

    return (
        "confirmed",
        _build_draw_guess_confirm_text(song_title, song_ids, fuzzy_hint),
        song_title,
        song_ids,
    )


def _draw_guess_user_rank_sort_key(item: Dict[str, Any]) -> Tuple[int, str]:
    return (-_as_int(item.get("correct"), 0), str(item.get("user_id") or ""))


async def _increment_draw_guess_user_correct_count(
    user_id: str,
    nickname: str,
    group_id: Optional[str],
    group_name: str,
    delta: int = 1,
) -> None:
    if delta <= 0:
        return
    user_id_text = str(user_id).strip()
    if not user_id_text:
        return
    group_id_text = str(group_id).strip() if group_id is not None else ""
    nickname_text = str(nickname or user_id_text).strip() or user_id_text
    group_name_text = str(group_name or "").strip()
    if group_id_text and not group_name_text:
        group_name_text = f"群{group_id_text}"

    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        user_stats = data.get("user_guess_stats")
        if not isinstance(user_stats, dict):
            user_stats = {}
            data["user_guess_stats"] = user_stats

        payload = user_stats.get(user_id_text)
        if not isinstance(payload, dict):
            payload = {}
            user_stats[user_id_text] = payload

        payload["nickname"] = nickname_text
        payload["total_correct"] = max(
            0, _as_int(payload.get("total_correct"), 0) + delta
        )

        groups = payload.get("groups")
        if not isinstance(groups, dict):
            groups = {}
            payload["groups"] = groups

        if group_id_text:
            group_payload = groups.get(group_id_text)
            if not isinstance(group_payload, dict):
                group_payload = {}
                groups[group_id_text] = group_payload
            group_payload["correct"] = max(
                0, _as_int(group_payload.get("correct"), 0) + delta
            )
            if group_name_text:
                group_payload["group_name"] = group_name_text
            elif not group_payload.get("group_name"):
                group_payload["group_name"] = f"群{group_id_text}"

        _save_draw_guess_db(data)


async def _list_draw_guess_user_rank_entries(
    group_id: Optional[str], all_groups: bool
) -> List[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        user_stats = data.get("user_guess_stats")
        if not isinstance(user_stats, dict):
            return []

        target_group = str(group_id) if group_id is not None else None
        out: List[Dict[str, Any]] = []
        for user_id_raw, payload in user_stats.items():
            user_id = str(user_id_raw).strip()
            if not user_id:
                continue
            if not isinstance(payload, dict):
                continue
            nickname = str(payload.get("nickname") or user_id)
            if all_groups:
                correct = max(0, _as_int(payload.get("total_correct"), 0))
                if correct <= 0:
                    continue
                out.append(
                    {
                        "user_id": user_id,
                        "nickname": nickname,
                        "correct": correct,
                    }
                )
                continue

            if target_group is None:
                continue
            groups = payload.get("groups")
            if not isinstance(groups, dict):
                continue
            group_payload = groups.get(target_group)
            if not isinstance(group_payload, dict):
                continue
            correct = max(0, _as_int(group_payload.get("correct"), 0))
            if correct <= 0:
                continue
            out.append(
                {
                    "user_id": user_id,
                    "nickname": nickname,
                    "correct": correct,
                    "group_name": str(
                        group_payload.get("group_name") or f"群{target_group}"
                    ),
                }
            )

        out.sort(key=_draw_guess_user_rank_sort_key)
        return out


def _resolve_guess_with_query_music(text: str) -> Tuple[Set[int], str]:
    guessed_ids, guessed_title, _ = _resolve_guess_with_query_music_detail(text)
    return guessed_ids, guessed_title


def _resolve_guess_with_query_music_detail(
    text: str,
) -> Tuple[Set[int], str, Optional[str]]:
    plain = (text or "").strip()
    if not plain:
        return set(), "", None

    try:
        results = queryMusic(plain)
    except Exception:
        return set(), plain, None

    if not results:
        return set(), plain, None

    normalized: List[Tuple[int, str]] = []
    for row in results:
        if not row:
            continue
        sid = _song_id_to_int(row[0])
        if sid is None:
            continue
        title = str(row[1] if len(row) > 1 else "").strip()
        if not title:
            title = get_song_title_by_id(str(sid)) or f"id{sid}"
        normalized.append((sid, title))

    if not normalized:
        return set(), plain, None

    display_title = normalized[0][1]
    for _, title in normalized:
        if title:
            display_title = title
            break

    resolved_title, resolved_ids, _ = _resolve_draw_song_selection(results)
    if resolved_ids:
        return set(resolved_ids), (resolved_title or display_title), None

    if _is_fuzzy_query_result(results):
        return {normalized[0][0]}, display_title, None

    lines = ["你要猜的可能是以下歌曲："]
    for sid, title in normalized:
        lines.append(f"id{sid} {title}")
    return set(), display_title, "\n".join(lines)


async def _pick_random_active_draw_guess_record() -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records", [])
        if not isinstance(records, list):
            return None
        candidates: List[Dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if not bool(record.get("active", True)):
                continue
            song_ids = [
                sid
                for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
                if sid is not None
            ]
            if not song_ids:
                continue
            if not _draw_guess_record_image_path(record).exists():
                continue
            candidates.append(dict(record))
        if not candidates:
            return None
        return random.choice(candidates)


async def _get_draw_guess_record(record_id: int) -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records", [])
        if not isinstance(records, list):
            return None
        record = _find_draw_guess_record(records, record_id)
        if record is None:
            return None
        return dict(record)


async def _create_draw_guess_record(
    song_title: str,
    song_ids: List[int],
    uploader: Dict[str, str],
    image_bytes: bytes,
) -> Tuple[Optional[int], Optional[str]]:
    try:
        png_bytes = _convert_image_to_png_bytes(image_bytes)
    except Exception as e:
        return None, f"图片处理失败：{e}"

    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            records = []
            data["records"] = records

        record_id = max(1, _as_int(data.get("next_id"), 1))
        data["next_id"] = record_id + 1
        image_name = f"{record_id}.png"
        image_path = DRAW_GUESS_IMAGE_DIR / image_name
        image_rel = f"images/{image_name}"

        try:
            with image_path.open("wb") as f:
                f.write(png_bytes)
        except Exception as e:
            try:
                _save_draw_guess_db(data)
            except Exception:
                pass
            return None, f"保存图片失败：{e}"

        record = {
            "id": record_id,
            "song_title": song_title,
            "song_ids": sorted(
                {_as_int(sid, -1) for sid in song_ids if _as_int(sid, -1) > 0}
            ),
            "uploader_qq": uploader.get("qq", ""),
            "uploader_nickname": uploader.get("nickname", ""),
            "uploader_group_id": uploader.get("group_id", ""),
            "uploader_group_name": uploader.get("group_name", ""),
            "image_file": image_rel,
            "active": True,
            "guess_correct_count": 0,
            "guess_wrong_count": 0,
            "like_count": 0,
            "report_count": 0,
            "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        }
        records.append(record)
        try:
            _save_draw_guess_db(data)
        except Exception as e:
            try:
                image_path.unlink()
            except Exception:
                pass
            return None, f"保存记录失败：{e}"
        return record_id, None


async def _update_draw_guess_record_counters(
    record_id: int,
    guess_correct_delta: int = 0,
    guess_wrong_delta: int = 0,
    like_delta: int = 0,
    report_delta: int = 0,
    set_active: Optional[bool] = None,
) -> Optional[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            return None
        record = _find_draw_guess_record(records, record_id)
        if record is None:
            return None

        record["guess_correct_count"] = max(
            0, _as_int(record.get("guess_correct_count"), 0) + guess_correct_delta
        )
        record["guess_wrong_count"] = max(
            0, _as_int(record.get("guess_wrong_count"), 0) + guess_wrong_delta
        )
        record["like_count"] = max(0, _as_int(record.get("like_count"), 0) + like_delta)
        record["report_count"] = max(
            0, _as_int(record.get("report_count"), 0) + report_delta
        )
        if set_active is not None:
            record["active"] = bool(set_active)

        _save_draw_guess_db(data)
        return dict(record)


async def _list_draw_guess_records_by_uploader(user_id: str) -> List[Dict[str, Any]]:
    async with DRAW_GUESS_DB_LOCK:
        data = _load_draw_guess_db()
        records = data.get("records")
        if not isinstance(records, list):
            return []
        matched = [
            dict(item)
            for item in records
            if isinstance(item, dict)
            and str(item.get("uploader_qq", "")) == str(user_id)
        ]
        matched.sort(key=lambda x: _as_int(x.get("id"), 0))
        return matched


def _get_active_group_guess_session(group_key: str) -> Optional[Dict[str, Any]]:
    session = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
    if session is None:
        return None
    if _session_is_expired(session.get("updated_at")):
        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        return None
    return session


async def _draw_guess_make_session_rule(event: Event) -> bool:
    if not isinstance(event, MessageEvent):
        return False
    session_key = _draw_guess_user_session_key(event)
    return session_key in DRAW_GUESS_MAKE_SESSIONS


qq_official_unsupported_gate = on_message(
    priority=0,
    rule=Rule(_is_qq_official_unsupported_command),
    block=True,
)


@qq_official_unsupported_gate.handle()
async def qq_official_unsupported_gate_handle(event: MessageEvent):
    await send_text_reply(
        qq_official_unsupported_gate,
        event,
        QQ_OFFICIAL_UNSUPPORTED_MESSAGE,
        quick_actions=True,
    )


qq_official_ping = on_regex(
    r"^/ping\s*$",
    priority=1,
    rule=Rule(_is_qq_official_event),
    block=True,
)


@qq_official_ping.handle()
async def qq_official_ping_handle(event: MessageEvent):
    await _finish_text_reply(qq_official_ping, event, "pong")


bind_qq = on_regex(r"(?i)^/?绑定\s*qq\s*([1-9]\d{4,11})$", rule=taiko_rule)


@bind_qq.handle()
async def bind_qq_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    legacy_qq = str(match.group(1) or "").strip()
    try:
        success, reply_msg = _migrate_bind_from_legacy_qq(legacy_qq, identity_key)
    except Exception as e:
        await _finish_text_reply(bind_qq, event, f"迁移绑定失败：{e}")

    await _finish_text_reply(bind_qq, event, reply_msg, quick_actions=success)


bind = on_regex(r"^/?绑定\s?([0-9]{0,12})$", rule=taiko_rule)


@bind.handle()
async def bind_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    taiko_id = str(match.group(1) or "").strip()
    if len(taiko_id) < 5:
        await _finish_text_reply(bind, event, "请输入正确的鼓众广场ID。")

    profile, err = await _fetch_bind_player_profile(taiko_id)
    if err:
        await _finish_text_reply(bind, event, err)
    if not isinstance(profile, dict):
        await _finish_text_reply(bind, event, "未找到该鼓众ID，请确认输入是否正确。")

    current_title, current_titleplate_id = _extract_bind_title_info(profile)
    player_name = str(profile.get("mydon_name") or taiko_id).strip() or taiko_id
    province = str(profile.get("province") or "").strip()
    if _should_skip_bind_verification(taiko_id):
        try:
            reply_msg = _finalize_bind_without_verification(
                identity_key, taiko_id, current_title
            )
        except Exception as e:
            await _finish_text_reply(bind, event, f"写入绑定失败：{e}")
        await _finish_text_reply(bind, event, reply_msg, quick_actions=True)

    existing_session = _get_bind_verify_session(identity_key)
    if (
        existing_session is not None
        and str(existing_session.get("taiko_id") or "").strip() == taiko_id
    ):
        if _bind_title_changed(existing_session, profile):
            try:
                reply_msg = _finalize_bind_verification(
                    identity_key, taiko_id, current_title
                )
            except Exception as e:
                await _finish_text_reply(bind, event, f"写入绑定失败：{e}")
            await _finish_text_reply(bind, event, reply_msg, quick_actions=True)
        await _finish_text_reply(
            bind,
            event,
            _build_bind_title_unchanged_message(
                existing_session, current_title, taiko_id
            ),
        )

    BIND_VERIFY_SESSIONS[identity_key] = {
        "taiko_id": taiko_id,
        "title": current_title,
        "titleplate_id": current_titleplate_id,
        "player_name": player_name,
        "province": province,
        "expires_at": _now_ts() + BIND_VERIFY_TIMEOUT_SECONDS,
    }
    await _finish_text_reply(
        bind,
        event,
        _build_bind_verify_prompt(player_name, taiko_id, current_title, province),
    )


bind_confirm = on_regex(
    r"^(确认绑定|绑定确认|验证绑定)\s*([0-9]{0,12})?$", rule=taiko_rule
)


@bind_confirm.handle()
async def bind_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    plain_text = extract_plain_text(event)
    match = re.match(r"^(确认绑定|绑定确认|验证绑定)\s*([0-9]{0,12})?$", plain_text)
    input_id = str(match.group(2) or "").strip() if match else ""

    session = _get_bind_verify_session(identity_key)
    if session is None:
        await _finish_text_reply(
            bind_confirm,
            event,
            "当前没有待确认的绑定请求，请先发送“绑定+你的鼓众广场ID”。",
        )

    taiko_id = str(session.get("taiko_id") or "").strip()
    if input_id and input_id != taiko_id:
        await _finish_text_reply(
            bind_confirm,
            event,
            f"待验证的鼓众ID是 {taiko_id}，请直接发送“确认绑定”或重新发起绑定。",
        )

    profile, err = await _fetch_bind_player_profile(taiko_id)
    if err:
        await _finish_text_reply(bind_confirm, event, err)
    if not isinstance(profile, dict):
        await _finish_text_reply(
            bind_confirm, event, "未找到该鼓众ID，请确认输入是否正确。"
        )

    current_title, _ = _extract_bind_title_info(profile)
    if not _bind_title_changed(session, profile):
        await _finish_text_reply(
            bind_confirm,
            event,
            _build_bind_title_unchanged_message(session, current_title, taiko_id),
        )

    try:
        reply_msg = _finalize_bind_verification(identity_key, taiko_id, current_title)
    except Exception as e:
        await _finish_text_reply(bind_confirm, event, f"写入绑定失败：{e}")
    await _finish_text_reply(
        bind_confirm,
        event,
        reply_msg,
        quick_actions=True,
    )


bind_switch = on_regex(r"^[uU](0|[1-9]\d*)$", rule=taiko_rule)


@bind_switch.handle()
async def bind_switch_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    try:
        slot_number = int(match.group(1))
    except Exception:
        await _finish_text_reply(
            bind_switch, event, "参数错误，请使用 u0 / u1 / u2 这类形式。"
        )

    try:
        ok, msg = _switch_bind_record(identity_key, slot_number, event=event)
    except Exception as e:
        await _finish_text_reply(bind_switch, event, f"切换绑定失败：{e}")

    await _finish_text_reply(bind_switch, event, msg)


bind_hiroba = on_regex(
    r"^/?绑定hiroba\s+(\S+@\S+\.\S+)\s+(\S+)(?:\s+(\d{10,14}))?\s*$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)


@bind_hiroba.handle()
async def bind_hiroba_handle(event: MessageEvent, match=RegexMatched()):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    email = str(match.group(1) or "").strip()
    password = str(match.group(2) or "").strip()
    target_taiko_no = str(match.group(3) or "").strip()
    if not email or not password:
        await _finish_text_reply(
            bind_hiroba, event, "格式错误，请使用：绑定hiroba 邮箱 密码 [太鼓番]"
        )
        return

    progress = _create_hiroba_progress_reporter(bind_hiroba, event)
    try:
        ensure_hiroba_credentials_table()
        await _send_text_reply_without_finish(
            bind_hiroba,
            event,
            "开始绑定 Hiroba 账号",
        )
        synced_ids = await asyncio.to_thread(
            sync_multiple_hiroba_userdatas,
            email,
            password,
            target_taiko_no=target_taiko_no or None,
            progress=progress,
            max_workers=4,
        )
        if not synced_ids:
            raise RuntimeError("未找到可绑定的 Hiroba 太鼓番。")

        for taiko_no in synced_ids:
            save_hiroba_credentials(
                taiko_no,
                email,
                password,
                configured_by_qq=identity_key,
            )

        reply_msg = ""
        for taiko_no in synced_ids:
            reply_msg, _ = _upsert_bind_record(
                identity_key, str(taiko_no), source="hiroba"
            )

        preferred_taiko_no = target_taiko_no or str(synced_ids[0])
        entry = _get_current_bind_entry(identity_key)
        preferred_slot_number = 1
        if entry is not None:
            ids = list(entry.get("ids") or [])
            if preferred_taiko_no in ids:
                preferred_slot_number = ids.index(preferred_taiko_no) + 1
        ok, switch_msg = _switch_bind_record(
            identity_key, preferred_slot_number, event=event
        )
        if ok:
            reply_msg = switch_msg
    except Exception as exc:
        await _finish_text_reply(bind_hiroba, event, f"Hiroba 绑定失败：{exc}")
        return

    bind_count = len(synced_ids)
    bind_mode_text = (
        f"已按指定太鼓番绑定 Hiroba 账号 {target_taiko_no}。"
        if target_taiko_no
        else f"已自动同步并绑定该 Bandai Namco ID 下的 {bind_count} 个 Hiroba 账号。"
    )
    await _finish_text_reply(
        bind_hiroba,
        event,
        f"{bind_mode_text}\n{reply_msg}\n已完成 Hiroba 同步（默认仅鬼/里）。",
        quick_actions=True,
    )


hiroba_update = on_regex(
    r"^(?:hirobaupdate|更新hiroba|更新ひろば)(?:(?:\s+|)(?P<show_all>all|全部|全量|-a|--all))?\s*$",
    flags=re.IGNORECASE,
    rule=taiko_rule,
)


@hiroba_update.handle()
async def hiroba_update_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    plain_text = extract_plain_text(event)
    show_all_match = re.fullmatch(
        r"^(?:hirobaupdate|更新hiroba|更新ひろば)(?:(?:\s+|)(all|全部|全量|-a|--all))?\s*$",
        plain_text.strip(),
        flags=re.IGNORECASE,
    )
    show_all_changes = bool(show_all_match and show_all_match.group(1))

    entry = _get_current_bind_entry(identity_key)
    if entry is None:
        await _finish_text_reply(hiroba_update, event, _taiko_bind_usage_message(event))
        return
    if _get_selected_bind_slot_number(entry) == 0:
        await _finish_text_reply(
            hiroba_update,
            event,
            _build_u0_readonly_message(entry, action_text="更新hiroba"),
        )
        return
    taiko_id = _get_current_bind_taiko_id(entry)
    if not taiko_id:
        await _finish_text_reply(hiroba_update, event, _taiko_bind_usage_message(event))
        return
    source = _infer_bind_source(taiko_id, entry.get("sources") or {})
    if source != "hiroba":
        await _finish_text_reply(
            hiroba_update,
            event,
            _build_update_command_hint(identity_key, expected_source="hiroba"),
        )
        return

    cooldown_msg = peek_hiroba_sync_cooldown(taiko_id)
    if cooldown_msg:
        await _finish_text_reply(hiroba_update, event, cooldown_msg)
        return

    progress = _create_hiroba_progress_reporter(hiroba_update, event)
    await _send_text_reply_without_finish(
        hiroba_update,
        event,
        f"开始更新 Hiroba 账号 {taiko_id}",
    )
    update_result = await asyncio.to_thread(
        _execute_hiroba_update,
        taiko_id,
        show_all_changes=show_all_changes,
        include_changes_image=True,
        progress=progress,
    )
    if not update_result.get("ok"):
        await _finish_text_reply(
            hiroba_update,
            event,
            str(update_result.get("message") or "Hiroba 更新失败。"),
        )
        return

    img_buf = update_result.get("image")
    success_message = str(update_result.get("message") or "Hiroba 更新成功！")
    if show_all_changes:
        success_message += "\n已展示全部变更。"
    if img_buf is not None:
        await _finish_image_reply(
            hiroba_update,
            event,
            img_buf,
            prefix_text=success_message,
            quick_actions=True,
            prefer_markdown_image=True,
            markdown_image_name="hirobaupdate",
        )
    await _finish_text_reply(hiroba_update, event, success_message, quick_actions=True)


bind_remove = on_regex(
    r"^(删除绑定|解绑)(?:\s*(u[1-9]\d*|[0-9]{5,12}))?$", rule=taiko_rule
)


@bind_remove.handle()
async def bind_remove_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    plain_text = extract_plain_text(event).strip()
    match = re.match(r"^(删除绑定|解绑)(?:\s*(u[1-9]\d*|[0-9]{5,12}))?$", plain_text)
    target = str(match.group(2) or "").strip() if match else ""

    try:
        ok, msg, needs_confirm = _remove_bind_record(
            identity_key, target, force_last=False, event=event
        )
    except Exception as e:
        await _finish_text_reply(bind_remove, event, f"删除绑定失败：{e}")

    if needs_confirm:
        session = _load_multi_bind_store().get(identity_key)
        current_id = ""
        if session:
            try:
                _, current_id = _resolve_bind_remove_target(session, target)
            except Exception:
                current_id = ""
        BIND_DELETE_CONFIRM_SESSIONS[identity_key] = {
            "taiko_id": current_id,
            "expires_at": _now_ts() + BIND_DELETE_CONFIRM_TIMEOUT_SECONDS,
        }

    await _finish_text_reply(bind_remove, event, msg)


bind_remove_confirm = on_regex(
    r"^(确认删除绑定|删除绑定确认|确认解绑)$", rule=taiko_rule
)


@bind_remove_confirm.handle()
async def bind_remove_confirm_handle(event: MessageEvent):
    identity_key = _normalize_identity_key(get_identity_key(event=event))
    session = _get_bind_delete_confirm_session(identity_key)
    if session is None:
        await _finish_text_reply(
            bind_remove_confirm,
            event,
            "当前没有待确认的删除请求，请先发送“删除绑定”或“解绑”。",
        )

    try:
        ok, msg, _ = _remove_bind_record(
            identity_key,
            str(session.get("taiko_id") or "").strip(),
            force_last=True,
            event=event,
        )
    except Exception as e:
        await _finish_text_reply(bind_remove_confirm, event, f"删除绑定失败：{e}")

    await _finish_text_reply(bind_remove_confirm, event, msg)


show_bind = on_fullmatch("给看", rule=taiko_rule)


@show_bind.handle()
async def show_bind_handle(event: MessageEvent):
    updated = _set_taiko_bind_visibility(get_identity_key(event=event), 1)
    if updated == 0:
        await _finish_text_reply(show_bind, event, _taiko_bind_usage_message(event))
    await _finish_text_reply(show_bind, event, "给看!")


unshow_bind = on_fullmatch("不给看", rule=taiko_rule)


@unshow_bind.handle()
async def unshow_bind_handle(event: MessageEvent):
    updated = _set_taiko_bind_visibility(get_identity_key(event=event), 0)
    if updated == 0:
        await _finish_text_reply(unshow_bind, event, _taiko_bind_usage_message(event))
    await _finish_text_reply(unshow_bind, event, "不给看!")


async def _update_typo_rule(event: MessageEvent) -> bool:
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return False
    return _is_update_typo_candidate_text(extract_plain_text(event))


update_typo = on_message(rule=taiko_rule & Rule(_update_typo_rule), block=False)


@update_typo.handle()
async def update_typo_handle(event: MessageEvent):
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return
    plain_text = extract_plain_text(event)
    if _should_trigger_update_command(plain_text):
        return
    normalized = _normalize_update_command_text(plain_text)
    if not normalized:
        return
    if normalized in UPDATE_TYPO_VARIANTS:
        await _finish_text_reply(update_typo, event, "别急")


async def _update_command_rule(event: MessageEvent) -> bool:
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return False
    return _should_trigger_update_command(extract_plain_text(event))


update = on_message(rule=taiko_rule & Rule(_update_command_rule), block=False)


@update.handle()
async def update_handle(event: MessageEvent):
    if _is_external_bot_mentioned(event) or _is_update_command_targeting_other_account(
        event
    ):
        return
    plain_text = extract_plain_text(event)
    parsed_command = _parse_update_command(plain_text)
    if parsed_command is None:
        return
    show_all_changes = bool(parsed_command.get("show_all"))
    identity_key, _ = _resolve_requested_identity_key(event)
    # region agent log
    _agent_debug_log(
        "taiko.py:update_handle:enter",
        "taikoupdate command received",
        {
            "qq": identity_key,
            "user_id": str(event.get_user_id()),
            "show_all_changes": show_all_changes,
            "plain_text": plain_text.strip(),
        },
        hypothesis_id="D",
    )
    # endregion

    taiko_id = _resolve_bound_taiko_id(event)
    if taiko_id == 404:
        await _finish_text_reply(update, event, _taiko_bind_usage_message(event))
        return
    if taiko_id == 403:
        await _finish_text_reply(update, event, "查不到呢，可能不给看哦~")
        return
    identity_key, _ = _resolve_requested_identity_key(event)
    entry = _get_current_bind_entry(identity_key)
    if _get_selected_bind_slot_number(entry) == 0:
        await _finish_text_reply(
            update,
            event,
            _build_u0_readonly_message(entry, action_text="taikoupdate"),
        )
        return
    source = (
        _infer_bind_source(str(taiko_id), entry.get("sources") or {})
        if entry
        else "wahlap"
    )
    if source != "wahlap":
        # region agent log
        _agent_debug_log(
            "taiko.py:update_handle:reject_non_wahlap",
            "taikoupdate rejected for non-wahlap bind",
            {"qq": identity_key, "taiko_id": str(taiko_id), "source": source},
            hypothesis_id="D",
        )
        # endregion
        await _finish_text_reply(
            update,
            event,
            _build_update_command_hint(identity_key, expected_source="wahlap"),
        )
        return
    # region agent log
    _agent_debug_log(
        "taiko.py:update_handle:before_execute",
        "starting sync taiko update on event loop",
        {
            "qq": identity_key,
            "taiko_id": str(taiko_id),
            "show_all_changes": show_all_changes,
            "source": source,
        },
        hypothesis_id="A",
    )
    # endregion
    execute_started = time.perf_counter()
    update_result = _execute_taiko_update(
        taiko_id,
        show_all_changes=show_all_changes,
        include_changes_image=True,
    )
    # region agent log
    _agent_debug_log(
        "taiko.py:update_handle:after_execute",
        "sync taiko update finished",
        {
            "qq": identity_key,
            "taiko_id": str(taiko_id),
            "ok": bool(update_result.get("ok")),
            "has_image": update_result.get("image") is not None,
            "elapsed_ms": int((time.perf_counter() - execute_started) * 1000),
        },
        hypothesis_id="A",
    )
    # endregion
    if not update_result.get("ok"):
        # region agent log
        _agent_debug_log(
            "taiko.py:update_handle:finish_failure",
            "finishing with failure text",
            {
                "qq": identity_key,
                "message": str(update_result.get("message") or ""),
            },
            hypothesis_id="C",
        )
        # endregion
        await _finish_text_reply(
            update,
            event,
            str(update_result.get("message") or "更新失败，怎么回事呢？"),
        )
        return

    img_buf = update_result.get("image")
    success_message = "更新成功！"
    if show_all_changes:
        success_message += "\n已展示全部变更。"
    else:
        success_message += (
            "\n默认每项最多展示5个；查看全部请使用“taikoupdate all”或“更新广场 全部”。"
        )
    if img_buf is not None:
        # region agent log
        _agent_debug_log(
            "taiko.py:update_handle:finish_image",
            "finishing with image reply",
            {
                "qq": identity_key,
                "image_bytes": len(img_buf),
                "show_all_changes": show_all_changes,
            },
            hypothesis_id="C",
        )
        # endregion
        await _finish_image_reply(
            update,
            event,
            img_buf,
            prefix_text=success_message,
            quick_actions=True,
            prefer_markdown_image=True,
            markdown_image_name="taikoupdate",
        )
    # region agent log
    _agent_debug_log(
        "taiko.py:update_handle:finish_text",
        "finishing with text reply after image branch",
        {"qq": identity_key, "had_image": img_buf is not None},
        hypothesis_id="C",
    )
    # endregion
    await _finish_text_reply(update, event, success_message, quick_actions=True)


quick_actions_panel = on_regex(r"^/?快捷操作$", rule=taiko_rule)


@quick_actions_panel.handle()
async def quick_actions_panel_handle(event: MessageEvent):
    await _finish_text_reply(
        quick_actions_panel,
        event,
        "快捷操作面板：点击下方按钮可快速填入常用指令。",
        quick_actions=True,
    )


developer_userdata = on_regex(
    r"^(?:开发者数据|taikodevdata)\s+([0-9A-Za-z]{24})\s+([0-9]{5,12})$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)


@developer_userdata.handle()
async def developer_userdata_handle(event: MessageEvent, bot: Bot):
    plain_text = extract_plain_text(event).strip()
    command_match = re.match(
        r"^(?:开发者数据|taikodevdata)\s+([0-9A-Za-z]{24})\s+([0-9]{5,12})$",
        plain_text,
        flags=re.IGNORECASE,
    )
    if not command_match:
        await developer_userdata.finish(
            "格式错误，请使用：开发者数据 <24位token> <userid>",
            reply_message=True,
        )

    token = command_match.group(1).strip()
    user_id = command_match.group(2).strip()
    try:
        payload = await _fetch_developer_userdata_via_forum(token, user_id)
    except Exception as error:
        await developer_userdata.finish(
            f"开发者数据查询失败：{error}",
            reply_message=True,
        )

    try:
        DEVELOPER_QQ_EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        export_path = (
            DEVELOPER_QQ_EXPORT_DIR
            / f"developer_userdata_{user_id}_{event.get_user_id()}_{timestamp}.json"
        )
        export_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        await _upload_json_file_for_event(
            bot,
            event,
            export_path,
            f"developer_userdata_{user_id}.json",
        )
    except Exception as error:
        preview = json.dumps(payload, ensure_ascii=False, indent=2)[:1200]
        await developer_userdata.finish(
            f"完整 JSON 获取成功，但发送文件失败：{error}\n以下为前 1200 字预览：\n{preview}",
            reply_message=True,
        )

    await developer_userdata.finish(
        f"已发送 userid={user_id} 的完整 JSON 文件。",
        reply_message=True,
    )


public_score_token = on_regex(
    r"^(?:网页成绩token|成绩token|scoretoken|获取token)(?:\s*(?:重置|刷新|reset))?$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)


@public_score_token.handle()
async def public_score_token_handle(event: MessageEvent):
    if not _is_private_message_event(event):
        await public_score_token.finish(
            "该 token 可直接读取完整成绩，请私聊机器人发送“网页成绩token”生成，避免群聊泄露。",
            reply_message=True,
        )

    taiko_id = _resolve_bound_taiko_id(event)
    if taiko_id == 404:
        await public_score_token.finish(
            _taiko_bind_usage_message(event), reply_message=True
        )
    if taiko_id == 403:
        await public_score_token.finish(
            "当前绑定不可见，无法生成网页成绩 token。", reply_message=True
        )
    identity_key, _ = _resolve_requested_identity_key(event)
    entry = _get_current_bind_entry(identity_key)
    if _get_selected_bind_slot_number(entry) == 0:
        await public_score_token.finish(
            _build_u0_readonly_message(entry, action_text="网页成绩 token"),
            reply_message=True,
        )

    try:
        issued = issue_public_score_token_for_taiko_id(str(taiko_id))
    except PublicScoreTokenError as error:
        await public_score_token.finish(str(error), reply_message=True)
    except Exception as error:
        logger.exception("生成网页成绩 token 失败")
        await public_score_token.finish(
            f"生成网页成绩 token 失败：{error}", reply_message=True
        )

    token = str(issued["token"])
    await public_score_token.finish(
        "已生成新的网页成绩 token。再次执行本指令会使旧 token 失效。\n"
        f"当前鼓众ID：{issued['taiko_id']}\n"
        f"来源绑定：{issued['owner_display']}\n"
        f"token：{token}\n"
        f"请在对应的网页输入这串token"
        "请妥善保管，不要发到群里。",
        reply_message=True,
    )


trend = on_regex(
    r"^/?(taikotrend|rating走势)\s*(.*)$", rule=taiko_rule, flags=re.IGNORECASE
)


@trend.handle()
async def trend_handle(event: MessageEvent):
    plain_text = extract_plain_text(event)
    raw_msg = str(event.get_message()).strip()
    m = re.match(r"^/?(taikotrend|rating走势)\s*(.*)$", plain_text, flags=re.IGNORECASE)
    if not m:
        await trend.finish(TREND_USAGE_MESSAGE)
    arg_text = (m.group(2) or "").strip()
    try:
        trend_args = _parse_trend_args(arg_text)
    except ValueError as error:
        await trend.finish(str(error))

    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(trend, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(trend, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(trend, event, str(bind_target["error"]))
    user_id = str(bind_target["user_id"])
    img_buf = generate_rating_trend_image(user_id, **trend_args)
    if not img_buf:
        await _finish_text_reply(
            trend, event, "暂无历史快照，请多次使用“taikoupdate”后再试"
        )
    img_jpg = _to_jpeg_bytes(img_buf, quality=85)
    await _finish_image_reply(trend, event, img_jpg)


playtrend = on_regex(
    r"^/?(taikoplaytrend|rating场次|rating游玩)\s*(.*)$",
    rule=taiko_rule,
    flags=re.IGNORECASE,
)


@playtrend.handle()
async def playtrend_handle(event: MessageEvent):
    plain_text = extract_plain_text(event)
    m = re.match(
        r"^/?(taikoplaytrend|rating场次|rating游玩)\s*(.*)$",
        plain_text,
        flags=re.IGNORECASE,
    )
    if not m:
        await playtrend.finish(PLAYTREND_USAGE_MESSAGE)
    arg_text = (m.group(2) or "").strip()
    try:
        playtrend_args = _parse_playtrend_args(arg_text)
    except ValueError as error:
        await playtrend.finish(str(error))

    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(playtrend, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(playtrend, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(playtrend, event, str(bind_target["error"]))
    user_id = str(bind_target["user_id"])
    img_buf = generate_rating_playcount_image(user_id, **playtrend_args)
    if not img_buf:
        await _finish_text_reply(
            playtrend,
            event,
            "暂无历史快照，请多次使用“taikoupdate”后再试（曲线按总曲数展示，"
            "两次更新之间的多场游玩会合并为一个点）",
        )
    img_jpg = _to_jpeg_bytes(img_buf, quality=85)
    await _finish_image_reply(playtrend, event, img_jpg)


song_rank = on_regex(r"^(歌曲排行|歌曲排名|排行歌曲)\s*(.*)$", rule=taiko_rule)


@song_rank.handle()
async def song_rank_handle(event: MessageEvent):
    plain_text = extract_plain_text(event)
    m = re.match(r"^(歌曲排行|歌曲排名|排行歌曲)\s*(.*)$", plain_text)
    if not m:
        await song_rank.finish("参数错误。示例：歌曲排行 歌名 困难 广东")

    arg_str = (m.group(2) or "").strip()
    if not arg_str:
        await song_rank.finish("歌曲别名为必填参数。示例：歌曲排行 歌名 困难 广东")

    region_map = load_region_map()
    song_alias, diff_id, province_id, province_name = _parse_song_rank_args(
        arg_str, region_map
    )
    if not song_alias:
        await song_rank.finish("歌曲别名为必填参数。示例：歌曲排行 歌名 困难 广东")

    music_list = queryMusic(song_alias)
    if len(music_list) == 0:
        await _finish_text_reply(song_rank, event, "未找到任何歌曲？")
    fuzzy_hint = ""
    if _is_fuzzy_query_result(music_list):
        fuzzy_hint = _build_fuzzy_query_hint(music_list)
    elif len(music_list) > 1:
        msg = "你要找的可能是：\n"
        for music in music_list:
            msg += f"id{music[0]} {music[1]}\n"
        await song_rank.finish(msg)

    song_id = int(music_list[0][0])
    song_title = music_list[0][1]
    song_entry = get_song_entry_by_id(song_id)
    if not song_entry:
        await _finish_text_reply(song_rank, event, "歌曲信息缺失，无法查询排行。")

    if diff_id is not None:
        level_val = song_entry.get(f"level_{diff_id}")
        if level_val is None or (
            isinstance(level_val, str) and level_val.strip() == "-"
        ):
            await _finish_text_reply(song_rank, event, "该歌曲没有该难度。")
        diff_ids = [diff_id]
    else:
        diff_ids = []
        for i in range(1, 6):
            level_val = song_entry.get(f"level_{i}")
            if level_val is None:
                continue
            if isinstance(level_val, str) and level_val.strip() == "-":
                continue
            diff_ids.append(i)

    if not diff_ids:
        await _finish_text_reply(song_rank, event, "该歌曲没有可用难度。")

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            config = json.load(f)
        authorization = config.get("cookie")
    except Exception:
        authorization = None

    if not authorization:
        await _finish_text_reply(
            song_rank, event, "缺少登录cookie，请检查 config.json。"
        )

    headers = _build_taiko_headers(authorization)
    sections: List[Tuple[str, Optional[List[Tuple[int, str, Optional[int]]]]]] = []

    async with httpx.AsyncClient(timeout=20) as client:

        async def fetch_rankings(
            diff: int,
        ) -> Optional[List[Tuple[int, str, Optional[int]]]]:
            url = f"https://wl-taiko.wahlap.net/api/ranking/{song_id}/{diff}"
            if province_id is not None:
                url += f"/{province_id}"
            try:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                payload = resp.json()
                return _extract_rankings(payload, diff)
            except Exception:
                return None

        results = await asyncio.gather(*(fetch_rankings(d) for d in diff_ids))
        for d, rankings in zip(diff_ids, results):
            sections.append((RANK_DIFF_LABEL_MAP.get(d, f"难度{d}"), rankings))

    img_buf = render_ranking_image(song_title, sections, province_name=province_name)
    img_jpg = _to_jpeg_bytes(img_buf, quality=85)
    if fuzzy_hint:
        await _finish_image_reply(song_rank, event, img_jpg, prefix_text=fuzzy_hint)
    else:
        await _finish_image_reply(song_rank, event, img_jpg)


summary = on_fullmatch("taiko2025", rule=taiko_rule)


@summary.handle()
async def summary_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await summary.finish(_taiko_bind_usage_message(event), reply_message=True)
    if bind_target == 403:
        await summary.finish("查不到呢，可能不给看哦~", reply_message=True)
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await summary.finish(str(bind_target["error"]), reply_message=True)
    taiko_id = str(bind_target["user_id"])
    try:
        utime = getUtime(taiko_id)
        t = utime.split("-")
    except Exception as e:
        await summary.finish("请更新数据后使用~", reply_message=True)
    if int(t[0]) < 2026:
        await summary.finish("请更新数据后使用~", reply_message=True)
    elif int(t[1]) == 1 and int(t[2][:2]) < 3:
        await summary.finish("请更新数据后使用~", reply_message=True)
    try:
        result = render_taiko_2025_summary(taiko_id)
    except Exception as e:
        await summary.finish("查不到捏，怎么回事呢？", reply_message=True)
    await summary.finish(MessageSegment.image(result), reply_message=True)


my_don = on_fullmatch("我的小咚", rule=taiko_rule)


@my_don.handle()
async def my_don_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(my_don, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(my_don, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(my_don, event, str(bind_target["error"]))
    taiko_id = str(bind_target["user_id"])
    try:
        img_buf = render_my_don_image(taiko_id)
    except FileNotFoundError:
        await _finish_text_reply(my_don, event, "请更新数据后使用~")
    except Exception:
        await _finish_text_reply(my_don, event, "生成失败了，请稍后再试~")
    await _finish_image_reply(my_don, event, img_buf)


song_metric_query = on_regex(
    SONG_METRIC_QUERY_PATTERN,
    rule=taiko_rule,
    flags=re.IGNORECASE,
)


@song_metric_query.handle()
async def song_metric_query_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(
            song_metric_query, event, _taiko_bind_usage_message(event)
        )
    if bind_target == 403:
        await _finish_text_reply(song_metric_query, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(song_metric_query, event, str(bind_target["error"]))
    taiko_id = str(bind_target["user_id"])

    plain_text = extract_plain_text(event)
    m = re.match(SONG_METRIC_QUERY_PATTERN, plain_text, flags=re.IGNORECASE)
    if not m:
        await _finish_text_reply(
            song_metric_query,
            event,
            "格式不正确。示例：太鼓1不可 / 我的3可倒序 / 我的单可正序 / 太鼓全良",
        )

    ng_token = m.group("ng")
    ok_token = m.group("ok")
    single_ok_token = m.group("single_ok")
    order_mode = _parse_song_metric_order(m.group("order"))
    if ng_token is not None:
        mode = "ng"
        target_value = int(ng_token)
        metric_label = f"{target_value}不可"
    elif ok_token is not None:
        mode = "ok"
        target_value = int(ok_token)
        metric_label = f"{target_value}可"
    elif single_ok_token is not None:
        mode = "single_ok"
        target_value = None
        metric_label = "单可"
    else:
        mode = "dondaful"
        target_value = None
        metric_label = "全良"

    try:
        matched = _collect_song_metric_matches(
            user_id=taiko_id,
            mode=mode,
            target_value=target_value,
            order_mode=order_mode,
        )
        my_don_img = render_my_don_image(taiko_id)
    except FileNotFoundError:
        await _finish_text_reply(
            song_metric_query, event, "您还未上传数据哦~请先发送“taikoupdate”进行上传"
        )
    except Exception as e:
        logger.exception("song_metric_query_failed error=%s", e)
        await _finish_text_reply(song_metric_query, event, "查询失败了，请稍后再试~")

    total_count = len(matched)
    shown = matched[:SONG_METRIC_MAX_SHOW]
    list_img = _render_song_metric_list_image(metric_label, shown, total_count)
    merged = _compose_song_metric_result_image(my_don_img, list_img)
    await _finish_image_reply(song_metric_query, event, merged)


async def _tcloud_command_rule(event: MessageEvent) -> bool:
    if _is_external_bot_mentioned(event):
        return False
    return _should_trigger_tcloud_command(extract_plain_text(event))


tcloud = on_message(rule=taiko_rule & Rule(_tcloud_command_rule), block=False)


@tcloud.handle()
async def tcloud_handle(event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await tcloud.finish(
            _taiko_bind_usage_message(event),
            reply_message=True,
        )
    if bind_target == 403:
        await tcloud.finish("查不到呢，可能不给看哦~", reply_message=True)
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await tcloud.finish(str(bind_target["error"]), reply_message=True)
    user_id = str(bind_target["user_id"])

    try:
        img_buf = render_tcloud_image(user_id)
    except FileNotFoundError:
        await _finish_text_reply(
            tcloud, event, "您还未上传数据哦~请先发送“taikoupdate”进行上传"
        )
    except ValueError:
        await _finish_text_reply(tcloud, event, "没有可用于生成词云的游玩数据~")
    except Exception:
        await _finish_text_reply(tcloud, event, "生成失败了，请稍后再试~")
    await _finish_image_reply(
        tcloud,
        event,
        img_buf,
        prefer_markdown_image=True,
        markdown_image_name="tcloud",
    )


TAIKOB_COMMAND_RE = re.compile(
    r"^/?taikob\s*(50|[1-4]\d|[1-9])(?:\s*(.*))?$", flags=re.IGNORECASE
)


taikob = on_regex(TAIKOB_COMMAND_RE.pattern, rule=taiko_rule, flags=re.IGNORECASE)


@taikob.handle()
async def taikob_handle(event: MessageEvent):
    plain_text = extract_plain_text(event).strip()
    m = TAIKOB_COMMAND_RE.match(plain_text)
    if not m:
        await taikob.finish("参数错误。示例：taikob 30 / taikob 30 精度 / taikob30 -r")

    N = int(m.group(1))
    arg_str = (m.group(2) or "").strip()
    args = arg_str.split() if arg_str else []

    # 解析 -r
    dynamic_origin = any(a.lower() == "-r" for a in args)

    # 解析维度（出现任意一个匹配即进入“单维列表模式”）
    dim = None
    for a in args:
        if a.lower() == "-r":
            continue
        if a in DIM_ALIASES:
            dim = DIM_ALIASES[a]
            break

    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(taikob, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(taikob, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(taikob, event, str(bind_target["error"]))
    taiko_id = str(bind_target["user_id"])

    try:
        result = compute_all_from_userdata(taiko_id)
    except FileNotFoundError:
        await taikob.finish("您还未上传数据哦~请先发送“taikoupdate”进行上传")
    except TypeError as e:
        await taikob.finish("请更新数据~")

    if not result:
        await taikob.finish("请游玩鬼难度歌曲后再来使用哦~")

    # 无附加参数：使用 b30 模板汇总图
    if not args:
        img_buf = render_b30_image(taiko_id, N=N)
        img_jpg = _to_jpeg_bytes(img_buf, quality=85)
        await _finish_image_reply(taikob, event, img_jpg)
        return

    # 单维列表模式：只画该维度 TopN
    if dim is not None:
        img_buf = generate_dim_top_image(
            result, N=N, dim=dim, user_id=taiko_id, font_path=TAIKOB_FONT_PATH
        )
        img_jpg = _to_jpeg_bytes(img_buf, quality=85)
        await _finish_image_reply(taikob, event, img_jpg)
        return

    # 默认模式：总雷达 + rating 列表；-r 控制原点
    img_buf = generate_top_N_image(
        result,
        N,
        user_id=taiko_id,
        dynamic_origin=dynamic_origin,
        font_path=TAIKOB_FONT_PATH,
    )
    img_jpg = _to_jpeg_bytes(img_buf, quality=85)
    await _finish_image_reply(taikob, event, img_jpg)


music_info = on_regex(r"^/?tinfo\s?(.+)$", rule=taiko_rule)


@music_info.handle()
async def music_info_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(music_info, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await music_info.finish("查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(music_info, event, str(bind_target["error"]))
    user_id = str(bind_target["user_id"])
    # 获取去除 at 的纯文本
    plain_text = extract_plain_text(event)

    # 用纯文本重新匹配参数（而不是直接用 match.group）
    m = re.match(r"^/?tinfo\s?(.+)$", plain_text)
    if not m:
        await music_info.finish("格式不正确，应为：tinfo 歌名")
    music_name = m.group(1)
    music_list = queryMusic(music_name)
    music_id = -1
    fuzzy_hint = ""
    msg = ""
    if len(music_list) == 0:
        await _finish_text_reply(music_info, event, "未找到任何歌曲？")
    elif _is_fuzzy_query_result(music_list):
        fuzzy_hint = _build_fuzzy_query_hint(music_list)
        music_id = int(music_list[0][0])
    elif len(music_list) == 1:
        music_id = int(music_list[0][0])
    else:
        msg = "你要找的可能是：\n"
        for music in music_list:
            msg += f"id{music[0]} {music[1]}\n"
        await music_info.finish(msg)
    if music_id == -1:
        await music_info.finish("查询失败，怎么回事呢？")
    else:
        try:
            res_img = generate_score_image(song_no=music_id, user_id=user_id)
        except FileNotFoundError as e:
            print(e)
            await _finish_text_reply(
                music_info, event, "您还未上传数据哦~请先发送“taikoupdate”进行上传"
            )
        except Exception as e:
            await music_info.finish(f"{e}")
        img_jpg = _to_jpeg_bytes(res_img, quality=85)
        if fuzzy_hint:
            await _finish_image_reply(
                music_info, event, img_jpg, prefix_text=fuzzy_hint
            )
        else:
            await _finish_image_reply(music_info, event, img_jpg)


# 查配置
# [n分音符] 配置 [bpm] [难度]
# 若省略分音符，则默认按 16 分音符处理
# 也支持仅输入 bpm / bpm区间 查歌名
patterns = on_regex(r"^/?查配置(?:\s*.+)?$", rule=taiko_rule)

_CHART_CONFIG_BPM_RE = re.compile(r"^\d+(?:-\d+)?$")
_CHART_CONFIG_PATTERN_RE = re.compile(r"^[ox]+$", re.IGNORECASE)
_CHART_CONFIG_LEVEL_RE = re.compile(r"^[鬼松竹梅]\d+$")


def _parse_chart_config_query(command_text: str) -> Optional[Dict[str, str]]:
    args_text = re.sub(r"^/?查配置\s*", "", command_text).strip()
    if not args_text:
        return None

    tokens = args_text.split()
    if len(tokens) == 1 and _CHART_CONFIG_BPM_RE.fullmatch(tokens[0]):
        return {"mode": "bpm_only", "bpm_str": tokens[0]}
    if (
        len(tokens) == 2
        and any(_CHART_CONFIG_BPM_RE.fullmatch(token) for token in tokens)
        and any(_CHART_CONFIG_LEVEL_RE.fullmatch(token) for token in tokens)
    ):
        return {
            "mode": "bpm_level_only",
            "bpm_str": next(
                token for token in tokens if _CHART_CONFIG_BPM_RE.fullmatch(token)
            ),
            "level": next(
                token for token in tokens if _CHART_CONFIG_LEVEL_RE.fullmatch(token)
            ),
        }

    division = "16"
    token_index = 0
    if (
        len(tokens) >= 2
        and _CHART_CONFIG_BPM_RE.fullmatch(tokens[0])
        and _CHART_CONFIG_PATTERN_RE.fullmatch(tokens[1])
    ):
        division = tokens[0]
        token_index = 1

    if token_index >= len(tokens):
        return None

    pattern_name = tokens[token_index].lower()
    if not _CHART_CONFIG_PATTERN_RE.fullmatch(pattern_name):
        return None

    bpm_str = None
    level = None
    remain_tokens = tokens[token_index + 1 :]
    if remain_tokens:
        first = remain_tokens.pop(0)
        if _CHART_CONFIG_BPM_RE.fullmatch(first):
            bpm_str = first
            if remain_tokens:
                second = remain_tokens.pop(0)
                if not _CHART_CONFIG_LEVEL_RE.fullmatch(second):
                    return None
                level = second
        elif _CHART_CONFIG_LEVEL_RE.fullmatch(first):
            level = first
        else:
            return None

    if remain_tokens:
        return None

    return {
        "mode": "pattern",
        "division": division,
        "pattern_name": pattern_name,
        "bpm_str": bpm_str,
        "level": level,
    }


def _parse_chart_config_bpm_range(
    bpm_str: Optional[str],
) -> Optional[Tuple[int, int]]:
    if not bpm_str:
        return None
    if "-" in bpm_str:
        lo, hi = map(int, bpm_str.split("-", 1))
        return (min(lo, hi), max(lo, hi))

    bpm = int(bpm_str)
    return (bpm, bpm)


def _collect_chart_config_bpm_ids(
    by_bpm: Dict[str, List[str]], bpm_range: Optional[Tuple[int, int]]
) -> Set[str]:
    if not bpm_range:
        return set()

    bpm_ids = set()
    for bpm in range(bpm_range[0], bpm_range[1] + 1):
        ids = by_bpm.get(str(bpm))
        if ids:
            bpm_ids.update(ids)
    return bpm_ids


def _collect_chart_config_level_ids(
    by_level: Dict[str, List[str]], level: Optional[str], level_map: Dict[str, str]
) -> Set[str]:
    if not level:
        return set()

    level_number = level[1:]
    level_rank = level[0]
    target_diff = by_level.get(str(level_number), [])

    if level_rank == "鬼":
        return set(filter(lambda x: x[-3:] in ["dit", "Oni"], target_diff))

    suffix = level_map.get(level_rank, "")
    return set(filter(lambda x: x[-3:] == suffix, target_diff))


def _resolve_chart_config_song_name(song_meta: Dict[str, Any], title: str) -> str:
    meta = song_meta.get(title, {})
    return meta.get("song_name") or meta.get("song_name_jp") or title


def _sample_chart_config_items(items: List[str], limit: int = 10) -> List[str]:
    if len(items) > limit:
        return random.sample(items, limit)
    return items


@patterns.handle()
async def music_info_handle(event: MessageEvent):
    level_map = {
        "松": "ard",
        "竹": "mal",
        "梅": "asy",
    }
    letter_map = {
        "Edit": "里谱",
        "Oni": "魔王",
        "Hard": "困难",
        "Normal": "一般",
        "Easy": "简单",
    }

    parsed_query = _parse_chart_config_query(str(event.get_message()).strip())
    if not parsed_query:
        await _finish_text_reply(
            patterns,
            event,
            "格式不正确，应为：查配置 [分音符] 配置 [BPM] [难度]；省略分音符时默认按16分，也可仅输入 BPM 或 BPM+难度。",
        )

    bpm_range = _parse_chart_config_bpm_range(parsed_query.get("bpm_str"))
    pattern_data = json.load(
        open("songs/analyze_result_filtered.json", "r", encoding="utf-8")
    )
    by_bpm = pattern_data["by_bpm"]
    by_level = pattern_data["by_level"]
    by_tag = pattern_data["by_tag"]
    song_meta = pattern_data["song_meta"]

    def format_items(ids: List[str]) -> List[str]:
        out = []
        for song_id in ids:
            title, course = song_id.split("||", 1)
            out.append(
                f"{_resolve_chart_config_song_name(song_meta, title)} {letter_map.get(course, course)}"
            )
        return out

    if parsed_query["mode"] == "bpm_only":
        bpm_ids = _collect_chart_config_bpm_ids(by_bpm, bpm_range)
        if not bpm_ids:
            await _finish_text_reply(patterns, event, "未找到满足该 BPM 条件的歌曲。")

        song_names = sorted(
            {
                _resolve_chart_config_song_name(song_meta, song_id.split("||", 1)[0])
                for song_id in bpm_ids
            }
        )
        song_count = len(song_names)
        song_show = _sample_chart_config_items(song_names, 10)

        msg_lines = ["为您找到以下歌曲：", f"【BPM匹配】{song_count} 首"]
        if song_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(song_show)
        await _finish_text_reply(patterns, event, "\n".join(msg_lines))
    if parsed_query["mode"] == "bpm_level_only":
        level = parsed_query["level"]
        bpm_ids = _collect_chart_config_bpm_ids(by_bpm, bpm_range)
        level_ids = _collect_chart_config_level_ids(by_level, level, level_map)
        matched_ids = list(bpm_ids & level_ids)
        if not matched_ids:
            await _finish_text_reply(
                patterns, event, "未找到满足该 BPM 和难度条件的谱面。"
            )

        match_count = len(matched_ids)
        match_show = _sample_chart_config_items(matched_ids, 10)
        msg_lines = ["为您找到以下谱面：", f"【BPM+难度匹配】{match_count} 条"]
        if match_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(match_show))
        await _finish_text_reply(patterns, event, "\n".join(msg_lines))

    division = parsed_query["division"]
    pattern_name = parsed_query["pattern_name"]
    level = parsed_query.get("level")
    dp = f"{division} {pattern_name}"

    # ---------- 1) 获取“精确命中集合” ----------
    exact_list = by_tag.get(dp, [])
    exact_set = set(exact_list)

    # ---------- 2) 若输入长度>=6，获取“子串命中集合”（同division下的 tag key 做包含判断） ----------
    substr_set = set()
    if len(pattern_name) >= 6:
        prefix = f"{division} "
        for tag_key, ids in by_tag.items():
            if not tag_key.startswith(prefix):
                continue
            long_pat = tag_key[len(prefix) :].lower()
            if pattern_name in long_pat:
                substr_set.update(ids)

        # 子串集合里去掉已经在精确集合中的部分，避免重复计入“子串命中”
        substr_set -= exact_set

    if not exact_set and not substr_set:
        await _finish_text_reply(patterns, event, "未找到匹配的谱面")

    # ---------- 3) BPM / 难度过滤函数（复用） ----------
    def apply_filters(song_ids: Set[str]) -> List[str]:
        if not song_ids:
            return []

        filtered = set(song_ids)

        if bpm_range:
            filtered &= _collect_chart_config_bpm_ids(by_bpm, bpm_range)

        if level:
            filtered &= _collect_chart_config_level_ids(by_level, level, level_map)

        return list(filtered)

    exact_res = apply_filters(exact_set)
    substr_res = apply_filters(substr_set)

    if not exact_res and not substr_res:
        await _finish_text_reply(patterns, event, "未找到满足该条件的谱面。")

    exact_count = len(exact_res)
    substr_count = len(substr_res)
    exact_show = _sample_chart_config_items(exact_res, 10)
    substr_show = _sample_chart_config_items(substr_res, 10)

    msg_lines = ["为您找到以下谱面："]

    if exact_count > 0:
        msg_lines.append(f"\n【精确匹配】{exact_count} 条")
        if exact_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(exact_show))

    if len(pattern_name) >= 6 and substr_count > 0:
        msg_lines.append(f"\n【子串匹配】{substr_count} 条")
        if substr_count > 10:
            msg_lines.append("（随机返回10条）")
        msg_lines.extend(format_items(substr_show))

    await _finish_text_reply(patterns, event, "\n".join(msg_lines))


twso = on_regex(r"^/?查分$", rule=taiko_rule)


@twso.handle()
async def twso_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(twso, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(twso, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(twso, event, str(bind_target["error"]))
    user_id = str(bind_target["user_id"])
    target_music_list = [1384, 354, 979, 1277, 412, 283, 194, 835, 518, 463]
    target_title_list = [
        "YOU're your HERO",
        "埼玉2000",
        "震天动地！太鼓之达人",
        "打破空想",
        "Night of Knights / Knight of Nights",
        "初音未来的消失-剧场版-",
        "Ignis Danse",
        "What's in the box?",
        "!!!Chaos Time!!!",
        "幽玄之乱",
    ]
    result_list = []
    for id in target_music_list:
        res = get_score_by_id_and_level(id, user_id, 4)
        result_list.append(res if res else None)
    res = "目前课题曲最高分数一览：\n"
    for index in range(0, 10):
        res += f"{index+1}.{target_title_list[index]}：{result_list[index]['high_score'] if result_list[index] else '未游玩'}\n"
    total_score = sum(list(map(lambda x: x["high_score"] if x else 0, result_list)))
    res += f"总和：{total_score}\n\n"
    try:
        if isinstance(bind_target, dict) and bind_target.get("is_virtual"):
            res += "u0 合并账户不提供活动排行信息"
        else:
            score_dict = find_player(str(user_id))
            res += f"昵称：{score_dict['mydon_name']}\n全球排名：{score_dict['rank']}\n国内排名：{score_dict['cn_rank']}\n活动记录总分：{score_dict['total_score']}\n"
    except Exception as e:
        res += "未查询到参与活动信息，可能未报名活动"
    await _finish_text_reply(twso, event, res)


note_count = on_regex(r"^太鼓查物量\s?(\d+)\s*", rule=taiko_rule)

const_query = on_regex(
    r"^/?查定数\s*(\d+\.\d)(?:\s+(.+))?\s*$",
    rule=taiko_rule,
    block=True,
)


@const_query.handle()
async def const_query_handle(event: MessageEvent, match=RegexMatched()):
    const_text = match.group(1)
    extra_text = (match.group(2) or "").strip()
    try:
        const_value = float(const_text)
    except ValueError:
        await _finish_text_reply(const_query, event, "定数格式错误，示例：查定数6.6")
        return

    page = 1
    show_shelf_status = False
    for token in extra_text.split():
        if token in ("含下架", "下架"):
            show_shelf_status = True
            continue
        try:
            page = int(token)
        except ValueError:
            await _finish_text_reply(
                const_query,
                event,
                "参数错误。示例：查定数6.6 / 查定数8.5 2 / 查定数6.6 含下架",
            )
            return
        if page < 1:
            await _finish_text_reply(
                const_query, event, "页码必须是正整数，示例：查定数8.5 2"
            )
            return

    rows = query_charts_by_const(const_value)
    if not rows:
        png = render_const_query_notice(f"未找到定数 {const_value:g} 的曲目。")
        await _finish_image_reply(const_query, event, png)
        return

    total_pages = max(1, (len(rows) + DEFAULT_PAGE_SIZE - 1) // DEFAULT_PAGE_SIZE)
    if extra_text and page > total_pages:
        await _finish_text_reply(
            const_query,
            event,
            f"定数 {const_value:g} 共 {len(rows)} 首，有效页码 1-{total_pages}。",
        )
        return

    page_rows, page, total_pages = paginate_rows(rows, page=page)
    global_offset = (page - 1) * DEFAULT_PAGE_SIZE
    png = render_const_query_image(
        const_value,
        page_rows,
        page=page,
        global_offset=global_offset,
        total_count=len(rows),
        total_pages=total_pages,
        show_shelf_status=show_shelf_status,
    )
    await _finish_image_reply(const_query, event, png)


@note_count.handle()
async def note_count_handle(event: MessageEvent, match=RegexMatched()):
    number = match.group(1)
    print(type(number))
    nc_data = json.load(open("songs/tja_note_counts.json", "r"))
    res = find_by_volume(nc_data, int(number), "total")
    if len(res) != 0:
        msg = f"以下为对应物量的谱面：(共{len(res)}条)\n"
        if len(res) > 20:
            msg += f"仅显示前20条：\n"
            res = res[:20]
    else:
        msg = "没有找到对应物量的谱面。"
    for title, course in res:
        msg += f"{title} {course}\n"
    await _finish_text_reply(note_count, event, msg)


matcher = on_regex(r"^.+进度(?:\s+\d+)?$", rule=taiko_rule)


@matcher.handle()
async def _(event: MessageEvent):
    raw_text = extract_plain_text(event).strip()
    page_match = PROGRESS_WITH_PAGE_REGEX.fullmatch(raw_text)
    if not page_match:
        return
    text = page_match.group("body").strip()
    page = int(page_match.group("page") or "1")
    if page <= 0:
        await _finish_text_reply(matcher, event, "页码必须是正整数，示例：6星进度 2")
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(matcher, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(matcher, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(matcher, event, str(bind_target["error"]))
    taiko_id = str(bind_target["user_id"])

    dani_request = parse_dani_progress_request(text)
    if dani_request:
        png = render_dani_progress_image_bytes(
            user_id=taiko_id,
            grade_name=dani_request["grade"],
            version=dani_request["version"],
            explicit_version=dani_request.get("explicitVersion") == "1",
        )
        await _finish_image_reply(matcher, event, png)
        return

    m = re.fullmatch(r"^(?P<decimal>\d+\.\d)(?P<mode>综合|过关|定数)?进度$", text)
    if m:
        decimal = m.group("decimal")
        mode = m.group("mode") or ""
        dynamic_available = decimal in _load_decimal_progress_set()
        pass_available = decimal in _load_pass_progress_set()

        if mode == "过关":
            if not pass_available:
                await _finish_text_reply(
                    matcher,
                    event,
                    f"{decimal} 暂无过关难度进度表，可尝试“{decimal}综合进度”",
                )
                return
            png = render_pass_progress_image_bytes(
                user_id=taiko_id,
                decimal=decimal,
                page=page,
            )
        elif mode in {"综合", "定数"}:
            if not dynamic_available:
                await _finish_text_reply(
                    matcher,
                    event,
                    f"{decimal} 暂无综合难度进度表，可尝试“{decimal}过关进度”",
                )
                return
            png = render_progress_image_bytes(
                user_id=taiko_id,
                decimal=decimal,
                page=page,
            )
        else:
            if pass_available:
                png = render_pass_progress_image_bytes(
                    user_id=taiko_id,
                    decimal=decimal,
                    page=page,
                )
            elif dynamic_available:
                png = render_progress_image_bytes(
                    user_id=taiko_id,
                    decimal=decimal,
                    page=page,
                )
            else:
                return
        await _finish_image_reply(matcher, event, png)
        return

    m = re.fullmatch(r"^(?P<star>10|[1-9])(?:星|★|☆)进度$", text)
    if m:
        star_value = int(m.group("star"))
        if star_value not in _load_star_progress_set():
            return
        png = render_star_progress_image_bytes(
            user_id=taiko_id,
            star_value=star_value,
            page=page,
        )
        await _finish_image_reply(matcher, event, png)
        return

    # 否则走进度名逻辑：例如 SS进度、地力S进度
    text = re.sub(r"个", "個", text)  # 统一“个人差”写法
    text = re.sub(r"底", "地", text)  # 统一“地力”写法
    text = text.upper()  # 统一大写
    progress_name = text[:-2]  # 去掉“进度”
    if progress_name not in _load_progress_name_set():
        return
    png = render_progress_image_bytes_by_list(
        user_id=taiko_id,
        progress_name=progress_name,
        assets_base=str(ASSETS_DIR),
        page=page,
    )
    await _finish_image_reply(matcher, event, png)


# ========== NoneBot 命令 ==========
# 支持两种输入：
# 1) 查分 里/表 别名 良 可 [连打]
# 2) 查分 别名 良 可 [连打]           （等同于“表”）
score_line_cmd = on_regex(
    r"^分数线\b.*$",
    priority=5,
    rule=taiko_rule,
    block=True,
)


@score_line_cmd.handle()
async def _(event: MessageEvent):
    plain_text = extract_plain_text(event)
    try:
        request = parse_scoreline_request(plain_text)
    except ValueError as e:
        await score_line_cmd.finish(str(e))

    try:
        results: List[List[Any]] = queryMusic(request.song_query)
    except Exception as e:
        await score_line_cmd.finish(f"查询歌曲失败：{e}")

    fuzzy_hint = ""
    if not results:
        await score_line_cmd.finish("未找到匹配的歌曲，请检查别名或歌曲id。")
    if _is_fuzzy_query_result(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        await score_line_cmd.finish(
            f"匹配结果过多（{len(results)} 条），请提供更精确的歌曲别名或id。"
        )

    song_id = int(results[0][0])
    song_title = str(results[0][1] or "")
    entry = get_scoreline_entry(song_id, request.level, fallback_title=song_title)
    if entry is None:
        available_levels = available_levels_for_song(song_id, fallback_title=song_title)
        if request.level == 3:
            if 4 in available_levels or 5 in available_levels:
                await score_line_cmd.finish(
                    "当前分数线数据仅支持表谱/里谱，松谱暂不支持。"
                )
            await score_line_cmd.finish("该歌曲暂无松谱分数线数据。")
        if request.level == 4 and 5 in available_levels:
            await score_line_cmd.finish(
                f"这首歌暂无表谱分数线数据，可尝试：分数线 里{request.song_query} {request.rating_display} {int(request.speed_ips)}"
            )
        if request.level == 5 and 4 in available_levels:
            await score_line_cmd.finish(
                f"这首歌暂无里谱分数线数据，可尝试：分数线 表{request.song_query} {request.rating_display} {int(request.speed_ips)}"
            )
        await score_line_cmd.finish("该歌曲暂无该难度分数线数据。")

    try:
        result = compute_scoreline_result(entry, request.rating_key, request.speed_ips)
    except ValueError as e:
        await score_line_cmd.finish(str(e))
    except Exception as e:
        await score_line_cmd.finish(f"分数线计算失败：{e}")

    body = format_scoreline_message(entry, result, request)
    if fuzzy_hint:
        await score_line_cmd.finish(f"{fuzzy_hint}\n{body}")
    await score_line_cmd.finish(body)


score_cmd = on_regex(
    r"^/?查分(?:\s*(里|表))?\s*(\S+)\s+(\d+)\s+(\d+)(?:\s+(\d+))?$",
    priority=5,
    rule=taiko_rule,
    block=True,
)


@score_cmd.handle()
async def _(
    event: MessageEvent,
    groups: Tuple[Optional[str], str, str, str, Optional[str]] = RegexGroup(),
):
    flag, alias, good_s, ok_s, drumroll_s = groups

    # 解析 level：里=5；表/缺省=4
    if flag == "里":
        level = 5
    else:
        level = 4  # flag 为 "表" 或 None

    # 1) 用你的 queryMusic 做别名->id
    try:
        results: List[List] = queryMusic(alias)
    except Exception as e:
        await score_cmd.finish(f"查询别名时出错：{e}")

    fuzzy_hint = ""
    if not results:
        await score_cmd.finish("未找到匹配的歌曲，请检查别名。")
    if _is_fuzzy_query_result(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        await score_cmd.finish(
            f"匹配结果过多（{len(results)} 条），请提供更精确的别名。"
        )

    # 唯一命中：取 id
    song_id = int(results[0][0])
    song_title = results[0][1]

    # 2) 解析数值入参
    try:
        good = int(good_s)
        ok = int(ok_s)
        drumroll = int(drumroll_s) if drumroll_s is not None else 0
    except (TypeError, ValueError):
        await score_cmd.finish("良/可/连打数必须为非负整数。")

    if good < 0 or ok < 0 or drumroll < 0:
        await score_cmd.finish("良/可/连打数必须为非负整数。")

    # 3) 计算分数
    try:
        total_score = compute_score(song_id, good, ok, drumroll, level=level)
    except FileNotFoundError as e:
        await score_cmd.finish(str(e))
    except (KeyError, TypeError, ValueError) as e:
        await score_cmd.finish(f"分值配置异常：{e}")
    except Exception as e:
        await score_cmd.finish(f"计算失败：{e}")

    # 4) 输出
    face = "（里谱）" if level == 5 else "（表谱）"
    body = f"歌曲：{song_title}{face}\n良：{good}  可：{ok}  连打：{drumroll}\n总分：{total_score}"
    if fuzzy_hint:
        await score_cmd.finish(f"{fuzzy_hint}\n{body}")
    else:
        await score_cmd.finish(body)


cover_cmd = on_regex(r"^cover\s*(\d+)", flags=re.IGNORECASE, rule=taiko_rule)


@cover_cmd.handle()
async def handle_cover(bot: Bot, event: Event, reg_group=RegexGroup()):
    """
    指令为：cover + 数字 + 图片
    - 无空格：cover1234
    - 有空格：cover 1234
    消息中必须有一张图片（同一条消息中）
    """

    # 1. 从正则捕获中获取数字
    if not reg_group or not reg_group[0]:
        # 正常情况下 on_regex 能保证这里有值，这个分支理论上不会走到
        await cover_cmd.finish("请使用：cover数字 + 一张图片，例如：cover1234 + 图片")

    song_id_str = reg_group[0]  # 第一个括号捕获的就是数字部分，例如 "1234"
    save_path = COVER_DIR / f"{song_id_str}.png"
    db_data = json.load(open(SONG_DATA_PATH, "r", encoding="utf-8"))
    id_list = [song["id"] for song in db_data]
    if int(song_id_str) not in id_list:
        await cover_cmd.finish("歌曲ID不存在，请确认后再上传封面。")
    # 2. 检查文件是否已存在
    if save_path.exists():
        await cover_cmd.finish("该歌曲封面已存在，若要更换请先删除旧文件。")

    # 3. 从消息中提取图片
    msg = event.get_message()
    image_seg = None
    for seg in msg:
        if seg.type == "image":
            image_seg = seg
            break

    if image_seg is None:
        await cover_cmd.finish("请在指令中附带一张图片，例如：cover1234 + 图片")

    # 4. 获取图片 URL 并下载
    img_url = image_seg.data.get("url")

    # 某些实现下没有 url，可以尝试调用 get_image
    if not img_url:
        try:
            img_info = await bot.call_api("get_image", file=image_seg.data["file"])
            img_url = img_info.get("url")
        except Exception:
            img_url = None

    if not img_url:
        await cover_cmd.finish(
            "无法获取图片地址，可能是适配器或 go-cqhttp 配置不支持 get_image"
        )

    # 下载图片
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(img_url)
            resp.raise_for_status()
            img_bytes = resp.content
    except Exception as e:
        await cover_cmd.finish(f"下载图片失败：{e}")

    # 5. 使用 Pillow 将图片强制压缩为 400×400 并保存
    try:
        img = Image.open(BytesIO(img_bytes))
        img = img.resize((400, 400), Image.Resampling.LANCZOS)

        img.save(save_path, format="PNG")
    except Exception as e:
        await cover_cmd.finish(f"处理或保存图片失败：{e}")

    # 6. 上传到 OSS
    uploaded, detail = await asyncio.to_thread(_upload_cover_to_oss, save_path)
    if uploaded:
        await cover_cmd.finish("上传成功，并已同步到OSS")
    await cover_cmd.finish(f"上传成功，但同步到OSS失败：{detail}")


# 支持：
# taikorec
# taikorec 体力
# taikorec 体力 30
# taikorec stamina 15
taikorec = on_regex(r"^(?:taikorec|推荐歌曲).*$", flags=re.IGNORECASE, rule=taiko_rule)


@taikorec.handle()
async def taikorec_handle(event: MessageEvent):
    bind_target = _resolve_read_bind_target_safe(event)
    if bind_target == 404:
        await _finish_text_reply(taikorec, event, _taiko_bind_usage_message(event))
    if bind_target == 403:
        await _finish_text_reply(taikorec, event, "查不到呢，可能不给看哦~")
    if isinstance(bind_target, dict) and bind_target.get("error"):
        await _finish_text_reply(taikorec, event, str(bind_target["error"]))
    taiko_id = str(bind_target["user_id"])

    # 2) 解析参数（兼容无空格：taikorec体力30 / 推荐歌曲体力30）
    msg_text = extract_plain_text(event).strip()
    m = re.match(r"^(?:taikorec|推荐歌曲)\s*(.*)$", msg_text, flags=re.IGNORECASE)
    tail = (m.group(1) if m else "") or ""
    tail = tail.strip()
    dim_in = "rating"
    n_in = "20"
    if tail:
        parts = tail.split()
        if len(parts) >= 2:
            dim_in = parts[0]
            n_in = parts[1]
        else:
            token = parts[0]
            if token.isdigit():
                n_in = token
            else:
                m2 = re.match(r"^(.*?)(\d{1,2})$", token)
                if m2 and m2.group(1):
                    dim_in = m2.group(1)
                    n_in = m2.group(2)
                else:
                    dim_in = token

    dim_key = DIM_MAP.get(dim_in, None)
    if not dim_key:
        await _finish_text_reply(
            taikorec,
            event,
            "维度不支持。可用：rating/综合、大歌力、体力、高速处理、精度力、节奏处理、复合处理",
        )

    try:
        limit = int(n_in)
        if limit < 1:
            limit = 1
        if limit > 50:
            limit = 50
    except Exception:
        limit = 20

    # 3) 调用推荐（你已整合好的函数）
    try:
        recs = compute_recommendations_for_user(
            user_id=taiko_id,
            best_key=dim_key,
            limit=limit,
            json_path="./songs/rating_structured_with_ids.json",  # 按你项目实际路径
        )
    except FileNotFoundError as e:
        print(e)
        await _finish_text_reply(
            taikorec, event, "您还未上传数据哦~请先发送“taikoupdate”进行上传"
        )
    except Exception as e:
        print(e)
        await _finish_text_reply(
            taikorec, event, "推荐计算失败，请检查曲库/数据匹配是否正常"
        )

    # 4) 生成推荐图片并返回
    # subtitle = f"维度：{dim_in}（best_key={dim_key}）  数量：{limit}"
    subtitle = f"维度：{dim_in}  数量：{limit}"
    img_buf = generate_recommend_image(
        recs,
        title="以下是可供参考的推荐歌曲",
        subtitle=subtitle,
        font_path=FONT_PATH,
    )

    await _finish_image_reply(taikorec, event, img_buf)


# ================
# 工具函数
# ================
def _get_fumen_path(difficulty: str, song_id: str) -> Path:
    # 统一只允许数字 id（更稳健）
    song_id = str(song_id).strip()
    return FUMENS_DIR / difficulty / f"{song_id}.png"


def file_to_bytesio(path: Path) -> BytesIO:
    """
    将本地文件读入 BytesIO，并重置指针到起始位置
    """
    bio = BytesIO()
    with path.open("rb") as f:
        bio.write(f.read())
    bio.seek(0)
    return bio


async def _finish_with_image_fallback(
    matcher: Matcher,
    event: MessageEvent,
    text: str,
    image: BytesIO,
    fallback_note: str = "（图片发送失败，请稍后重试）",
) -> None:
    try:
        await _finish_image_reply(matcher, event, image, prefix_text=text)
    except MatcherException:
        raise
    except Exception as e:
        logger.warning("send_image_failed text=%s error=%s", text.splitlines()[0], e)
        await _finish_text_reply(matcher, event, f"{text}\n{fallback_note}")


async def _send_fumen_or_hint(
    matcher: Matcher, event: MessageEvent, difficulty: str, song_id: str
) -> None:
    path = _get_fumen_path(difficulty, song_id)
    if not path.exists():
        await matcher.finish(
            f"未找到谱面文件：{difficulty}/{song_id}.png（路径：{path}）"
        )
    bio = file_to_bytesio(path)
    await _finish_with_image_fallback(
        matcher,
        event,
        f"你要找的是不是：\n{DIFF_MAP_REVERSE[difficulty]} id{song_id}",
        bio,
        fallback_note="（谱面图片发送失败，请稍后重试）",
    )


# =========================
# 指令：tsearch on/off
# =========================
tsearch_switch = on_regex(
    r"^tsearch\s*(?P<state>on|off)$",
    priority=10,
    rule=taiko_rule,
    permission=SUPERUSER | GROUP_ADMIN | GROUP_OWNER,
    block=True,
)


@tsearch_switch.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event).strip().lower()
    m = re.match(r"^tsearch\s*(?P<state>on|off)$", msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：tsearch on/off")

    group_id = getattr(event, "group_id", None)
    if group_id is None:
        await matcher.finish("该指令仅支持群聊使用。")

    enabled = m.group("state") == "on"
    group_key = get_group_key(event=event)
    if group_key is None:
        await matcher.finish("该指令仅支持群聊使用。")
    changed = apply_switch(group_key, "tsearch", enabled)
    state_text = "开启" if enabled else "关闭"
    if changed:
        await matcher.finish(f"tsearch 已{state_text}（本群）")
    else:
        await matcher.finish(f"tsearch 已是{state_text}状态（本群）")


# =========================
# 指令：xx有什么别名
# =========================
alias_query = on_regex(
    ALIAS_QUERY_REGEX.pattern, priority=10, rule=taiko_rule & tsearch_rule, block=True
)


@alias_query.handle()
async def _(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = ALIAS_QUERY_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx有什么别名")

    q = m.group("q").strip()
    if not q:
        await matcher.finish("请提供歌曲名或别名")

    try:
        results = queryMusic(q)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    fuzzy_hint = ""
    if not results:
        await matcher.finish("未找到匹配的歌曲。")
    if _is_fuzzy_query_result(results):
        fuzzy_hint = _build_fuzzy_query_hint(results)
    if len(results) > 1:
        msg = "你要找的可能是：\n"
        for music in results:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg.strip())

    song_id = str(results[0][0])
    song_title = results[0][1]
    alias_title, aliases = find_aliases_by_song_id(song_id)
    show_title = alias_title or song_title

    cleaned: List[str] = []
    seen = set()
    for a in aliases:
        if not a:
            continue
        if a in seen:
            continue
        seen.add(a)
        cleaned.append(a)

    img_buf = render_alias_image(show_title, song_id, cleaned)
    if fuzzy_hint:
        await _finish_image_reply(matcher, event, img_buf, prefix_text=fuzzy_hint)
    else:
        await _finish_image_reply(matcher, event, img_buf)


# =========================
# 指令：tset xxx to xxx
# =========================
tset_alias = on_regex(r"^tset\b.*", priority=10, rule=taiko_rule, block=True)


@tset_alias.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event)
    m = re.match(r"^tset\s*(.+?)\s*to\s*(.+)$", msg_text, flags=re.IGNORECASE)
    if not m:
        await matcher.finish("格式好像有问题捏，格式：tsetxxx to xxx")

    alias_to_add = m.group(1).strip()
    target_key = m.group(2).strip()
    if not alias_to_add or not target_key:
        await matcher.finish("格式好像有问题捏，格式：tsetxxx to xxx")

    try:
        results = queryMusic(target_key)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    if not results:
        await matcher.finish("未找到匹配的歌曲。")
    if _is_fuzzy_query_result(results):
        await matcher.finish(_build_fuzzy_query_hint(results))
    if len(results) > 1:
        msg = "你要找的可能是：\n"
        for music in results:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg.strip())

    song_id = str(results[0][0])
    song_title = results[0][1]
    alias_data = load_alias_data()

    target_entry = None
    for entry in alias_data:
        if str(entry.get("id")) == song_id:
            target_entry = entry
            break

    if target_entry is None:
        title = get_song_title_by_id(song_id) or song_title
        target_entry = {"id": int(song_id), "aliases": [], "song_name_jp": title}
        alias_data.append(target_entry)

    aliases = target_entry.get("aliases") or []
    existing_lower = {str(a).lower() for a in aliases}
    base_title = (target_entry.get("song_name_jp") or song_title or "").lower()
    if alias_to_add.lower() in existing_lower or alias_to_add.lower() == base_title:
        await matcher.finish("该别名已存在，无需重复添加。")

    aliases.append(alias_to_add)
    target_entry["aliases"] = aliases

    try:
        save_alias_data(alias_data)
    except Exception as e:
        await matcher.finish(f"保存失败：{e}")

    group_id = getattr(event, "group_id", None)
    group_text = str(group_id) if group_id is not None else "private"

    # 获取用户昵称和群昵称
    user_nickname = ""
    group_name = ""
    if hasattr(event, "sender") and event.sender:
        user_nickname = getattr(event.sender, "nickname", "") or ""
    if group_id is not None:
        group_name = getattr(event, "group_name", "") or ""

    logger.info(
        "alias_add user_id=%s user_nickname=%s group_id=%s group_name=%s song_id=%s alias=%s",
        event.get_user_id(),
        user_nickname,
        group_text,
        group_name,
        song_id,
        alias_to_add,
    )

    try:
        append_alias_log(
            {
                "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "action": "add_alias",
                "user_id": event.get_user_id(),
                "user_nickname": user_nickname,
                "group_id": group_id,
                "group_name": group_name,
                "song_id": song_id,
                "song_title": song_title,
                "alias": alias_to_add,
            }
        )
    except Exception as e:
        logger.warning("alias_add_log_failed error=%s", e)

    await matcher.finish(f"已添加别名：{alias_to_add} -> {song_title} (id{song_id})")


def _strip_song_query_diff_prefix(raw_q: str) -> str:
    if raw_q.startswith("简单"):
        return raw_q[2:].strip()
    if raw_q.startswith("普通"):
        return raw_q[2:].strip()
    if raw_q.startswith("困难"):
        return raw_q[2:].strip()
    if raw_q.startswith("魔王"):
        return raw_q[2:].strip()
    if raw_q.startswith(("梅", "竹", "松", "鬼", "里")):
        return raw_q[1:].strip()
    return raw_q


async def _finish_song_position_by_id(
    matcher: Matcher, event: MessageEvent, song_id: int
) -> None:
    result = get_song_position_by_id(song_id)
    if not result:
        await matcher.finish(f"未找到 id{song_id} 的歌曲信息。")
    await _finish_text_reply(matcher, event, format_position_reply(result))


async def _finish_song_position_by_name(
    matcher: Matcher, event: MessageEvent, raw_q: str
) -> None:
    stripped_q = _strip_song_query_diff_prefix(raw_q)
    try:
        results = _resolve_what_song_query(raw_q, stripped_q)
    except Exception as e:
        await matcher.finish(f"查询歌曲失败：{e}")

    if not results:
        await matcher.finish("未找到匹配的歌曲。")
    if _is_fuzzy_query_result(results):
        await matcher.finish(_build_fuzzy_query_hint(results))
    if len(results) > 1:
        msg = "你要找的可能是：\n"
        for music in results:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg.strip())

    song_id = int(results[0][0])
    await _finish_song_position_by_id(matcher, event, song_id)


# =========================
# 指令：歌曲分类位序
# =========================
song_where = on_regex(
    SONG_WHERE_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)
song_position_phrase = on_regex(
    SONG_POSITION_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)
song_pos_by_id = on_regex(
    SONG_POS_BY_ID_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)


@song_where.handle()
async def song_where_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_WHERE_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx在哪")
    raw_q = (m.group("q") or "").strip()
    if not raw_q:
        await matcher.finish("请提供歌曲名或别名，例如：千本桜在哪")
    await _finish_song_position_by_name(matcher, event, raw_q)


@song_position_phrase.handle()
async def song_position_phrase_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_POSITION_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx在什么位置")
    raw_q = (m.group("q") or "").strip()
    if not raw_q:
        await matcher.finish("请提供歌曲名或别名，例如：千本桜在什么位置")
    await _finish_song_position_by_name(matcher, event, raw_q)


@song_pos_by_id.handle()
async def song_pos_by_id_handle(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return
    msg_text = extract_plain_text(event)
    m = SONG_POS_BY_ID_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：位置 id1156")
    song_id = int(m.group("id"))
    await _finish_song_position_by_id(matcher, event, song_id)


# =========================
# 指令：xx哪有鼓
# =========================
city_arcade_query = on_regex(
    CITY_ARCADE_QUERY_REGEX.pattern, priority=10, rule=taiko_rule, block=True
)


@city_arcade_query.handle()
async def city_arcade_query_handle(bot: Bot, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return

    msg_text = extract_plain_text(event).strip()
    match = CITY_ARCADE_QUERY_REGEX.fullmatch(msg_text)
    if not match:
        await _finish_text_reply(
            city_arcade_query,
            event,
            "格式错误，请直接发送“鞍山哪有鼓”这类指令。",
        )
        return

    city_name = match.group("city").strip()
    try:
        result = await query_taiko_shops_by_city(city_name)
    except ValueError as exc:
        await _finish_text_reply(city_arcade_query, event, str(exc))
        return
    except RuntimeError as exc:
        await _finish_text_reply(city_arcade_query, event, str(exc))
        return
    except Exception:
        logger.exception("query taiko city shops failed: city=%s", city_name)
        await _finish_text_reply(
            city_arcade_query,
            event,
            "查询失败，鼓众地图可能暂时不可用，请稍后再试。",
        )
        return

    reply_text = format_taiko_city_shop_reply(result)
    if not is_qq_official_event(event):
        try:
            forward_messages = _build_city_arcade_forward_messages(
                bot,
                event,
                result,
            )
            if forward_messages and await send_onebot_forward_messages(
                city_arcade_query,
                bot,
                event,
                forward_messages,
            ):
                return
        except Exception:
            logger.exception(
                "send city arcade forward reply failed: city=%s", city_name
            )

    await _finish_text_reply(city_arcade_query, event, reply_text)


# =========================
# 指令 1：xx是什么歌
# =========================
# 例：千本桜是什么歌
# 这里用正则捕获 xx
what_song = on_regex(
    WHAT_SONG_REGEX.pattern, priority=10, rule=taiko_rule & tsearch_rule, block=True
)


@what_song.handle()
async def _(matcher: Matcher, event: MessageEvent):
    if _is_external_bot_mentioned(event):
        return

    msg_text = extract_plain_text(event)

    # =========================
    # ② 以 "@菌菌" 开头：提示不能复制粘贴
    # =========================
    if msg_text.startswith("@菌菌"):
        # await matcher.finish("您似乎复制粘贴了'@菌菌'3个字符，这是个无法复制的指令哦~")
        await matcher.finish()

    m = WHAT_SONG_REGEX.match(msg_text)
    if not m:
        await matcher.finish("格式不正确，应为：xx是什么歌")

    raw_q = m.group("q").strip()
    if not raw_q:
        await matcher.finish("请提供要查询的关键词，例如：千本桜是什么歌")

    diff = "Oni"
    stripped_q = raw_q
    # 兼容难度前缀（梅/竹/松/鬼/里/简单/普通/困难/魔王）
    if raw_q.startswith("简单"):
        diff = "Kantan"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("普通"):
        diff = "Futsuu"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("困难"):
        diff = "Muzukashii"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("魔王"):
        diff = "Oni"
        stripped_q = raw_q[2:].strip()
    elif raw_q.startswith("梅"):
        diff = "Kantan"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("竹"):
        diff = "Futsuu"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("松"):
        diff = "Muzukashii"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("鬼"):
        diff = "Oni"
        stripped_q = raw_q[1:].strip()
    elif raw_q.startswith("里"):
        diff = "InnerOni"
        stripped_q = raw_q[1:].strip()

    try:
        res: Any = _resolve_what_song_query(raw_q, stripped_q)
    except Exception as e:
        await matcher.finish(f"queryMusic 调用失败：{e}")

    if len(res) == 0:
        await _finish_text_reply(matcher, event, "未找到任何歌曲？")
    elif _is_fuzzy_query_result(res):
        await _finish_fuzzy_query_with_fumen(matcher, event, res, difficulty=diff)
    elif len(res) > 1:
        msg = "你要找的可能是：\n"
        for music in res:
            msg += f"id{music[0]} {music[1]}\n"
        await matcher.finish(msg)

    song_id = str(res[0][0]).strip()

    # 返回 Oni 难度谱面
    await _send_fumen_or_hint(matcher, event, diff, song_id)


# =========================
# 指令 2：里/鬼/表/松/竹/梅 idxxxx
# =========================
# 允许：里id1234 / 里 id1234 / 里 1234 / 里  id1234
# 也允许：鬼id0001、表 999、松 id12
diff_by_id = on_regex(
    DIFF_BY_ID_REGEX.pattern,
    priority=10,
    block=True,
    rule=taiko_rule & tsearch_rule,
)


@diff_by_id.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = extract_plain_text(event)
    m = DIFF_BY_ID_REGEX.match(msg)
    if not m:
        await matcher.finish(
            "格式不正确，应为：里/鬼/表/松/竹/梅/简单/一般/困难/魔王 idxxxx（例如：里 id1234）"
        )

    diff_alias = m.group("diff")
    song_id = m.group("id")

    difficulty = DIFF_MAP.get(diff_alias)
    if not difficulty:
        await matcher.finish(f"未知难度标记：{diff_alias}")

    await _send_fumen_or_hint(matcher, event, difficulty, song_id)


# =========================
# 你画我猜：功能开关
# =========================
draw_guess_switch = on_regex(
    r"^(开启|关闭)太鼓你画我猜功能$",
    priority=10,
    rule=taiko_rule,
    permission=SUPERUSER | GROUP_ADMIN | GROUP_OWNER,
    block=True,
)


@draw_guess_switch.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        await matcher.finish("该指令仅支持群聊使用。")

    enabled = (groups[0] if groups else "") == "开启"
    group_key = get_group_key(event=event)
    if group_key is None:
        await matcher.finish("该指令仅支持群聊使用。")
    changed = apply_switch(group_key, "taiko_draw_guess", enabled)
    if not enabled:
        DRAW_GUESS_GROUP_SESSIONS.pop(str(group_id), None)
        prefix = f"group:{group_id}:user:"
        for key in list(DRAW_GUESS_MAKE_SESSIONS.keys()):
            if key.startswith(prefix):
                DRAW_GUESS_MAKE_SESSIONS.pop(key, None)

    state_text = "开启" if enabled else "关闭"
    if changed:
        await matcher.finish(f"太鼓你画我猜功能已{state_text}（本群）")
    await matcher.finish(f"太鼓你画我猜功能已是{state_text}状态（本群）")


# =========================
# 你画我猜：制作流程
# =========================
draw_guess_make_start = on_regex(
    r"^画太鼓歌名(?:\s*(.+))?$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)
draw_guess_make_router = on_message(
    priority=4,
    rule=taiko_rule & draw_guess_rule & Rule(_draw_guess_make_session_rule),
    block=True,
)


@draw_guess_make_start.handle()
async def _(matcher: Matcher, event: MessageEvent, groups=RegexGroup()):
    session_key = _draw_guess_user_session_key(event)
    DRAW_GUESS_MAKE_SESSIONS[session_key] = {
        "stage": "await_song",
        "updated_at": _now_ts(),
        "song_title": "",
        "song_ids": [],
    }
    first_input = str(groups[0] if groups and groups[0] is not None else "").strip()
    if not first_input:
        await matcher.finish(
            "请输入歌名或歌曲id。可随时输入“0”退出", reply_message=True
        )
    if first_input == "0":
        DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
        await matcher.finish("流程已结束", reply_message=True)

    status, text, song_title, song_ids = _resolve_draw_guess_song_input_message(
        first_input
    )
    if status == "confirmed" and song_title and song_ids:
        DRAW_GUESS_MAKE_SESSIONS[session_key]["song_title"] = song_title
        DRAW_GUESS_MAKE_SESSIONS[session_key]["song_ids"] = song_ids
        DRAW_GUESS_MAKE_SESSIONS[session_key]["stage"] = "await_draw_confirm"
        _touch_session(DRAW_GUESS_MAKE_SESSIONS[session_key])
        await matcher.finish(text, reply_message=True)
    await matcher.finish(text, reply_message=True)


@draw_guess_make_router.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent):
    session_key = _draw_guess_user_session_key(event)
    session = DRAW_GUESS_MAKE_SESSIONS.get(session_key)
    if session is None:
        return

    if _session_is_expired(session.get("updated_at")):
        DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
        await matcher.finish("流程已结束", reply_message=True)

    stage = str(session.get("stage") or "")
    plain_text = extract_plain_text(event).strip()

    if stage == "await_song":
        _touch_session(session)
        if plain_text == "0":
            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish("流程已结束", reply_message=True)
        status, text, song_title, song_ids = _resolve_draw_guess_song_input_message(
            plain_text
        )
        if status == "confirmed" and song_title and song_ids:
            session["song_title"] = song_title
            session["song_ids"] = song_ids
            session["stage"] = "await_draw_confirm"
            _touch_session(session)
            await matcher.finish(text, reply_message=True)
        await matcher.finish(text, reply_message=True)

    if stage == "await_draw_confirm":
        _touch_session(session)
        if plain_text == "0":
            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish("流程已结束", reply_message=True)
        if plain_text != "绘图":
            await matcher.finish("确认请发送“绘图”", reply_message=True)

        session["stage"] = "await_image"
        _touch_session(session)
        if DRAW_GUESS_TEMPLATE_PATH.exists():
            await matcher.finish(
                MessageSegment.image(file_to_bytesio(DRAW_GUESS_TEMPLATE_PATH))
                + Message("\n请上传图片"),
                reply_message=True,
            )
        logger.warning("draw_guess_template_missing path=%s", DRAW_GUESS_TEMPLATE_PATH)
        await matcher.finish("请上传图片", reply_message=True)

    if stage == "await_image":
        image_seg = _extract_first_image_segment(event.get_message())
        if image_seg is None:
            _touch_session(session)
            if plain_text == "0":
                DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
                await matcher.finish("流程已结束", reply_message=True)
            await matcher.finish("请上传图片", reply_message=True)

        _touch_session(session)
        image_bytes = await _download_image_segment_bytes(bot, image_seg)
        if not image_bytes:
            await matcher.finish("请上传图片", reply_message=True)

        song_title = str(session.get("song_title") or "").strip()
        song_ids = [
            sid
            for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
            if sid is not None
        ]
        if not song_title or not song_ids:
            DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
            await matcher.finish("流程已结束", reply_message=True)

        group_id = getattr(event, "group_id", None)
        uploader = {
            "qq": event.get_user_id(),
            "nickname": _extract_uploader_nickname(event),
            "group_id": str(group_id) if group_id is not None else "",
            "group_name": await _extract_uploader_group_name(bot, event),
        }
        record_id, err = await _create_draw_guess_record(
            song_title=song_title,
            song_ids=song_ids,
            uploader=uploader,
            image_bytes=image_bytes,
        )
        if record_id is None:
            logger.warning("draw_guess_create_record_failed err=%s", err)
            await matcher.finish("请上传图片", reply_message=True)

        DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
        await matcher.finish(
            f"图片已上传，本条太鼓你画我猜编号为{record_id}", reply_message=True
        )

    DRAW_GUESS_MAKE_SESSIONS.pop(session_key, None)
    await matcher.finish("流程已结束", reply_message=True)


# =========================
# 你画我猜：猜歌流程
# =========================
draw_guess_start = on_fullmatch(
    "猜太鼓歌名", priority=10, rule=taiko_rule & draw_guess_rule, block=True
)
draw_guess_answer = on_regex(
    r"^猜(?!太鼓歌名)\s*(.+)$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)


@draw_guess_start.handle()
async def _(matcher: Matcher, event: MessageEvent):
    group_key = _draw_guess_group_session_key(event)
    if group_key is None:
        await matcher.finish("该指令仅支持群聊使用。", reply_message=True)

    active_session = _get_active_group_guess_session(group_key)
    if active_session is not None:
        await matcher.finish("本群尚有猜歌名未结束", reply_message=True)

    record = await _pick_random_active_draw_guess_record()
    if record is None:
        await matcher.finish("暂无可用你画我猜图片。", reply_message=True)

    image_path = _draw_guess_record_image_path(record)
    if not image_path.exists():
        await matcher.finish("暂无可用你画我猜图片。", reply_message=True)

    song_ids = [
        sid
        for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
        if sid is not None
    ]
    DRAW_GUESS_GROUP_SESSIONS[group_key] = {
        "record_id": _as_int(record.get("id"), 0),
        "song_title": str(record.get("song_title") or ""),
        "song_ids": song_ids,
        "uploader_group_name": str(record.get("uploader_group_name") or ""),
        "uploader_nickname": str(record.get("uploader_nickname") or ""),
        "remaining": DRAW_GUESS_MAX_TRIES,
        "wrong_attempts": 0,
        "updated_at": _now_ts(),
    }
    await matcher.finish(
        MessageSegment.image(file_to_bytesio(image_path))
        + Message(
            f"\n已发送图片，请输入“猜+歌名”，例如猜测图片中歌曲为百花缭乱，则输入“猜百花缭乱”，目前有{DRAW_GUESS_MAX_TRIES}次机会"
        ),
        reply_message=True,
    )


@draw_guess_answer.handle()
async def _(matcher: Matcher, bot: Bot, event: MessageEvent, groups=RegexGroup()):
    group_key = _draw_guess_group_session_key(event)
    if group_key is None:
        return

    existing = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
    if existing and _session_is_expired(existing.get("updated_at")):
        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        await matcher.finish("流程已结束", reply_message=True)

    session = DRAW_GUESS_GROUP_SESSIONS.get(group_key)
    if session is None:
        return

    guess_text = str(groups[0] if groups and groups[0] is not None else "").strip()
    _touch_session(session)

    guessed_song_ids, guessed_song_title, candidate_tip = (
        _resolve_guess_with_query_music_detail(guess_text)
    )
    if candidate_tip:
        await matcher.finish(candidate_tip, reply_message=True)
    target_song_ids = {
        sid
        for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
        if sid is not None
    }
    is_correct = bool(guessed_song_ids & target_song_ids)
    if is_correct:
        record_id = _as_int(session.get("record_id"), 0)
        wrong_attempts = max(0, _as_int(session.get("wrong_attempts"), 0))
        group_name = await _extract_uploader_group_name(bot, event)
        await _increment_draw_guess_user_correct_count(
            user_id=event.get_user_id(),
            nickname=_extract_uploader_nickname(event),
            group_id=group_key,
            group_name=group_name,
            delta=1,
        )
        updated = await _update_draw_guess_record_counters(
            record_id,
            guess_correct_delta=1,
            guess_wrong_delta=wrong_attempts,
        )
        song_title = str(session.get("song_title") or "")
        song_ids = list(target_song_ids)
        uploader_group_name = str(session.get("uploader_group_name") or "未知群")
        uploader_nickname = str(session.get("uploader_nickname") or "未知用户")
        if updated is not None:
            song_title = str(updated.get("song_title") or song_title)
            song_ids = [
                sid
                for sid in (
                    _song_id_to_int(v) for v in (updated.get("song_ids") or song_ids)
                )
                if sid is not None
            ]
            uploader_group_name = str(
                updated.get("uploader_group_name") or uploader_group_name
            )
            uploader_nickname = str(
                updated.get("uploader_nickname") or uploader_nickname
            )

        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        await matcher.finish(
            f"恭喜你猜对了，这张图的歌名是{song_title}，歌曲id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}，本图片编号为{record_id}。如果你也想绘制图片，可以发送“画太鼓歌名”",
            reply_message=True,
        )

    session["wrong_attempts"] = _as_int(session.get("wrong_attempts"), 0) + 1
    session["remaining"] = max(
        0, _as_int(session.get("remaining"), DRAW_GUESS_MAX_TRIES) - 1
    )
    remaining = _as_int(session.get("remaining"), 0)
    if remaining > 0:
        guess_display = guessed_song_title if guessed_song_title else "你输入的歌名"
        await matcher.finish(
            f"正确答案不是{guess_display}哦，你猜错了，目前尚有{remaining}次机会",
            reply_message=True,
        )

    record_id = _as_int(session.get("record_id"), 0)
    wrong_attempts = _as_int(session.get("wrong_attempts"), 0)
    updated = await _update_draw_guess_record_counters(
        record_id, guess_wrong_delta=wrong_attempts
    )
    song_title = str(session.get("song_title") or "")
    song_ids = [
        sid
        for sid in (_song_id_to_int(v) for v in (session.get("song_ids") or []))
        if sid is not None
    ]
    uploader_group_name = str(session.get("uploader_group_name") or "未知群")
    uploader_nickname = str(session.get("uploader_nickname") or "未知用户")
    if updated is not None:
        song_title = str(updated.get("song_title") or song_title)
        song_ids = [
            sid
            for sid in (
                _song_id_to_int(v) for v in (updated.get("song_ids") or song_ids)
            )
            if sid is not None
        ]
        uploader_group_name = str(
            updated.get("uploader_group_name") or uploader_group_name
        )
        uploader_nickname = str(updated.get("uploader_nickname") or uploader_nickname)

    DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
    await matcher.finish(
        f"本次游戏没有人猜对，这张图的歌名是{song_title}，id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}，本图片编号为{record_id}。如果你也想绘制图片，可以发送“画太鼓歌名”",
        reply_message=True,
    )


# =========================
# 你画我猜：评价与查看
# =========================
draw_guess_like = on_regex(
    r"^点赞你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)
draw_guess_report = on_regex(
    r"^举报你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)
draw_guess_view = on_regex(
    r"^查看你画我猜id\s*(\d+)\s*$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)
draw_guess_mine = on_fullmatch(
    "我的你画我猜", priority=10, rule=taiko_rule & draw_guess_rule, block=True
)
draw_guess_rank = on_regex(
    r"^(?:你画我猜排行|太鼓你画我猜排行)(?:\s*.*)?$",
    priority=10,
    rule=taiko_rule & draw_guess_rule,
    block=True,
)
draw_guess_manual_exit = on_fullmatch("0", priority=10, rule=taiko_rule, block=False)


@draw_guess_like.handle()
async def _(matcher: Matcher, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _update_draw_guess_record_counters(record_id, like_delta=1)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)
    await matcher.finish(
        f"已为你画我猜id{record_id}点赞，本你画我猜已被{_as_int(record.get('like_count'), 0)}人点赞！",
        reply_message=True,
    )


@draw_guess_report.handle()
async def _(matcher: Matcher, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _update_draw_guess_record_counters(record_id, report_delta=1)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)

    report_count = _as_int(record.get("report_count"), 0)
    msg = f"已举报你画我猜id{record_id}，本你画我猜已被{report_count}人举报！"
    if report_count == DRAW_GUESS_REPORT_DELETE_THRESHOLD:
        await _update_draw_guess_record_counters(record_id, set_active=False)
        msg += f"\n你画我猜id{record_id}已删除。"
    await matcher.finish(msg, reply_message=True)


@draw_guess_view.handle()
async def _(matcher: Matcher, groups=RegexGroup()):
    record_id = _as_int(groups[0] if groups else 0, 0)
    record = await _get_draw_guess_record(record_id)
    if record is None:
        await matcher.finish("该id不存在", reply_message=True)

    image_path = _draw_guess_record_image_path(record)
    if not image_path.exists():
        await matcher.finish("该id不存在", reply_message=True)

    song_ids = [
        sid
        for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
        if sid is not None
    ]
    song_title = str(record.get("song_title") or "")
    uploader_group_name = str(record.get("uploader_group_name") or "未知群")
    uploader_nickname = str(record.get("uploader_nickname") or "未知用户")
    detail = (
        f"这张图的歌名是{song_title}，id是{_format_song_ids(song_ids)}，绘图者是{uploader_group_name}的{uploader_nickname}。"
        f"该图已被猜对{_as_int(record.get('guess_correct_count'), 0)}次，"
        f"已被猜错{_as_int(record.get('guess_wrong_count'), 0)}次，"
        f"已被点赞{_as_int(record.get('like_count'), 0)}次"
    )
    await matcher.finish(
        MessageSegment.image(file_to_bytesio(image_path)) + Message(f"\n{detail}"),
        reply_message=True,
    )


@draw_guess_mine.handle()
async def _(matcher: Matcher, event: MessageEvent):
    user_id = event.get_user_id()
    records = await _list_draw_guess_records_by_uploader(user_id)
    if not records:
        await matcher.finish(
            "目前没有上传过你画我猜。如果你也想绘制图片，可以发送“画太鼓歌名”",
            reply_message=True,
        )

    lines: List[str] = []
    for record in records:
        song_ids = [
            sid
            for sid in (_song_id_to_int(v) for v in (record.get("song_ids") or []))
            if sid is not None
        ]
        lines.append(
            f"id{_as_int(record.get('id'), 0)}，歌名是{record.get('song_title', '')}，id是{_format_song_ids(song_ids)}，"
            f"该图已被猜对{_as_int(record.get('guess_correct_count'), 0)}次，"
            f"已被猜错{_as_int(record.get('guess_wrong_count'), 0)}次，"
            f"已被点赞{_as_int(record.get('like_count'), 0)}次"
        )
    nickname = _extract_uploader_nickname(event)
    header = f"用户 {nickname}的你画我猜如下："
    img_buf = render_draw_guess_list_image(header, lines)
    await matcher.finish(MessageSegment.image(img_buf), reply_message=True)


@draw_guess_rank.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg_text = extract_plain_text(event).strip()
    m = re.match(r"^(?:你画我猜排行|太鼓你画我猜排行)\s*(.*)$", msg_text)
    arg_text = (m.group(1) if m else "") or ""
    arg_text = arg_text.strip()
    args = arg_text.split() if arg_text else []

    all_groups = False
    page = 1
    for arg in args:
        low = arg.lower()
        if low in ("-a", "--all"):
            all_groups = True
            continue
        if arg.isdigit():
            page = int(arg)
            continue
        await matcher.finish(
            "格式不正确，应为：你画我猜排行 [页码] [-a|--all]",
            reply_message=True,
        )

    if page <= 0:
        page = 1

    group_id = getattr(event, "group_id", None)
    if not all_groups and group_id is None:
        await matcher.finish(
            "默认展示本群排行，私聊请使用：你画我猜排行 -a",
            reply_message=True,
        )

    group_key = None if all_groups else str(group_id)
    entries = await _list_draw_guess_user_rank_entries(group_key, all_groups)
    if not entries:
        mode_text = "总群" if all_groups else "本群"
        await matcher.finish(f"当前{mode_text}暂无排行数据。", reply_message=True)

    page_size = 20 if all_groups else 10
    total = len(entries)
    total_pages = (total + page_size - 1) // page_size
    if page > total_pages:
        page = total_pages

    start = (page - 1) * page_size
    items = entries[start : start + page_size]
    mode_text = "总群" if all_groups else "本群"
    lines = [
        f"{mode_text}你画我猜猜歌排行 第{page}/{total_pages}页（每页{page_size}条，共{total}条）"
    ]
    for idx, item in enumerate(items, start=start + 1):
        user_id = str(item.get("user_id") or "")
        nickname = str(item.get("nickname") or user_id or "未知用户")
        correct_count = _as_int(item.get("correct"), 0)
        if all_groups:
            lines.append(f"{idx}. {nickname}(QQ:{user_id}) | 猜对{correct_count}次")
        else:
            lines.append(f"{idx}. {nickname}(QQ:{user_id}) | 本群猜对{correct_count}次")
    await matcher.finish("\n".join(lines), reply_message=True)


@draw_guess_manual_exit.handle()
async def _(matcher: Matcher, event: MessageEvent):
    exited = False
    user_key = _draw_guess_user_session_key(event)
    if user_key in DRAW_GUESS_MAKE_SESSIONS:
        DRAW_GUESS_MAKE_SESSIONS.pop(user_key, None)
        exited = True

    group_key = _draw_guess_group_session_key(event)
    if group_key is not None and group_key in DRAW_GUESS_GROUP_SESSIONS:
        DRAW_GUESS_GROUP_SESSIONS.pop(group_key, None)
        exited = True

    if exited:
        await matcher.finish("流程已结束", reply_message=True)


anti_sb = on_regex(r"^@菌菌.*", priority=10, rule=taiko_rule, block=True)


@anti_sb.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = event.get_message()

    # =========================
    # ① 若 at 了指定 QQ（3889003795），完全不响应
    # =========================
    # for seg in msg:
    #     if seg.type == "at" and seg.data.get("qq") == "3889003795":
    #         return

    msg_text = str(msg).strip()

    # =========================
    # ② 以 "@菌菌" 开头：提示不能复制粘贴
    # =========================
    if msg_text.startswith("@菌菌"):
        await anti_sb.finish("您似乎复制粘贴了'@菌菌'3个字符，这是个无法复制的指令哦~")


anti = on_regex(r".*", priority=1000, rule=taiko_rule, block=True)


@anti.handle()
async def _(matcher: Matcher, event: MessageEvent):
    msg = event.get_message()

    # =========================
    # ① 若 at 了指定 QQ（3889003795），完全不响应
    # =========================
    for seg in msg:
        if seg.type == "json":
            print(seg.data["data"])
            return
