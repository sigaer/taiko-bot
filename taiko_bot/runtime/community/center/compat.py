from __future__ import annotations
import os
from pathlib import Path
_CENTER_ROOT = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))

from ...public.provider import query_with_mode as _query_music_with_mode

from typing import Any

from typing import Dict

from nonebot.adapters import Event

from nonebot.exception import IgnoredException

from typing import List

from nonebot.matcher import Matcher

from ...player.center.messages import ONEBOT_V11_PLATFORM

from typing import Optional

from ...player.center.messages import QQ_OFFICIAL_PLATFORM

from nonebot.rule import Rule

from ...player.center.messages import build_identity_key

from nonebot.message import event_preprocessor

from ...player.center.messages import extract_plain_text as extract_platform_plain_text

from feature_handler.feature_handler import feature_on

from ...player.center.messages import is_qq_official_event

from ...player.center.messages import is_qq_official_group_event

import json

from nonebot import logger

from nonebot.plugin import on_message

from nonebot.plugin import on_regex

import re

from ...player.center.messages import send_text_reply

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule

COPIED_SAKURA_PREFIX_PATTERN = re.compile(
    r"^(?:[@＠]sakura)(?:(?=$)|[\s\u3000:：,，/]+)",
    flags=re.IGNORECASE,
)

def _strip_copied_sakura_prefix(text: str) -> str:
    normalized = str(text or "").lstrip()
    while normalized:
        match = COPIED_SAKURA_PREFIX_PATTERN.match(normalized)
        if not match:
            break
        normalized = normalized[match.end() :].lstrip()
    return normalized

def extract_plain_text(event: MessageEvent) -> str:
    """
    提取消息中的纯文本，自动忽略 at 段，并兼容复制后的 @Sakura 文本前缀。
    """
    return _strip_copied_sakura_prefix(extract_platform_plain_text(event))

QQ_OFFICIAL_UNSUPPORTED_MESSAGE = "该功能暂未支持 QQ 官方机器人。"

QQ_OFFICIAL_UNSUPPORTED_PATTERNS = [
    re.compile(r"^(?:开发者数据|taikodevdata)\b", re.IGNORECASE),
    re.compile(r"^taiko2025$", re.IGNORECASE),
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

SILENT_BLOCKED_IDENTITY_KEYS = frozenset(
    {
        "qq_official:E866D95E2836EE873E8D168039ABABE0",
        "qq_official:57A618AE41981F2F217F8EECB7FA6BE2",
    }
)

SILENT_BLOCKED_RAW_USER_IDS = frozenset(
    {
        "E866D95E2836EE873E8D168039ABABE0",
    }
)

def _is_qq_official_unsupported_command(event: MessageEvent) -> bool:
    if not is_qq_official_group_event(event):
        return False
    text = extract_plain_text(event)
    if not text:
        return False
    return any(pattern.match(text) for pattern in QQ_OFFICIAL_UNSUPPORTED_PATTERNS)

def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)

def _safe_event_user_id(event: MessageEvent) -> str:
    for attr in ("user_id", "member_openid", "openid", "_user_id"):
        raw_value = getattr(event, attr, None)
        if raw_value is None:
            continue
        normalized = str(raw_value or "").strip()
        if normalized:
            return normalized

    author = getattr(event, "author", None)
    if author is not None:
        for attr in ("id", "user_id", "member_openid", "openid"):
            raw_value = getattr(author, attr, None)
            if raw_value is None:
                continue
            normalized = str(raw_value or "").strip()
            if normalized:
                return normalized

    get_user_id = getattr(event, "get_user_id", None)
    if callable(get_user_id):
        try:
            normalized = str(get_user_id() or "").strip()
        except Exception:
            normalized = ""
        if normalized:
            return normalized
    return ""

def _is_silently_blocked_event(event: MessageEvent) -> bool:
    raw_user_id = _safe_event_user_id(event)
    if raw_user_id and raw_user_id in SILENT_BLOCKED_RAW_USER_IDS:
        return True
    if not raw_user_id:
        return False
    platform = QQ_OFFICIAL_PLATFORM if is_qq_official_event(event) else ONEBOT_V11_PLATFORM
    identity_key = build_identity_key(platform, raw_user_id)
    return bool(identity_key and identity_key in SILENT_BLOCKED_IDENTITY_KEYS)

@event_preprocessor
async def _normalize_copied_sakura_prefix_event(event: Event) -> None:
    if not is_qq_official_event(event) or not hasattr(event, "get_message"):
        return
    try:
        message = event.get_message()
    except Exception:
        return
    raw_text = (
        str(message.extract_plain_text()).strip()
        if hasattr(message, "extract_plain_text")
        else str(message).strip()
    )
    normalized_text = _strip_copied_sakura_prefix(raw_text)
    if not normalized_text or normalized_text == raw_text:
        return
    try:
        normalized_message = message.__class__(normalized_text)
    except Exception:
        return
    try:
        setattr(event, "message", normalized_message)
    except Exception:
        pass
    if hasattr(event, "_message"):
        try:
            setattr(event, "_message", normalized_message)
        except Exception:
            pass

@event_preprocessor
async def _ignore_silently_blocked_event(event: Event) -> None:
    if isinstance(event, MessageEvent) and _is_silently_blocked_event(event):
        raise IgnoredException("silently blocked user")

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
    markdown_text: Optional[str] = None,
) -> None:
    attach_quick_actions = (
        _should_attach_quick_actions_to_text(event, text)
        if quick_actions is None
        else bool(quick_actions)
    )
    resolved_markdown_text = markdown_text
    if resolved_markdown_text is None and text == _taiko_bind_usage_message(event):
        resolved_markdown_text = _taiko_bind_usage_markdown_message(event)
    await send_text_reply(
        matcher,
        event,
        text,
        quick_actions=attach_quick_actions,
        markdown_text=resolved_markdown_text,
    )

def _taiko_bind_usage_message(event: Optional[MessageEvent] = None) -> str:
    base = (
        "请先绑定账号。\n"
        "国服/CN：发送“绑定 你的鼓众广场ID”或“绑定+你的鼓众广场ID”进行绑定。\n"
        "日服/JP：可直接发送“绑定 12位Hiroba太鼓番”绑定，默认通过服务账号读取公开成绩；"
        "若账号设为非公开，可再发送“绑定hiroba 邮箱 密码 [太鼓番]”。"
    )
    if event is not None and is_qq_official_event(event):
        return (
            f"{base}\n"
            "如果您以前在其他搭建了 Sakura Taiko 模块的 bot 上绑定过数据，"
            "可用原 QQ 私聊旧 bot 发送“迁移验证码”，再私聊这里发送“绑定QQ QQ号 验证码”。\n"
            "验证码十分钟内有效。"
        )
    return base

def _taiko_bind_usage_markdown_message(
    event: Optional[MessageEvent] = None,
) -> str:
    lines = [
        "# 请先绑定账号",
        "> 当前还没有可用的成绩数据，请先完成绑定再继续查询或更新。",
        "",
        "## 国服 / CN",
        "- 发送 `绑定 你的鼓众广场ID`",
        "- 或发送 `绑定+你的鼓众广场ID`",
        "",
        "## 日服 / JP",
        "- 公开资料：发送 `绑定 12位Hiroba太鼓番`",
        "- 非公开资料：发送 `绑定hiroba 邮箱 密码 [太鼓番]`",
        "",
        "## 推荐操作",
        "1. 点击下方 `绑定` 按钮自动填入命令",
        "2. 把自己的 `鼓众广场ID / Hiroba太鼓番` 补完整后发送",
        "3. 绑定完成后点击 `更新广场` 拉取成绩数据",
    ]
    if event is not None and is_qq_official_event(event):
        lines.extend(
            [
                "",
                "## 旧绑定迁移",
                "- 如果你以前在其他 Sakura Taiko bot 上绑定过，可点击下方 `旧绑定迁移`",
                "- 用原 QQ 私聊旧 bot 发送 `迁移验证码`，再私聊这里发送 `绑定QQ QQ号 验证码`",
                "> 验证码十分钟内有效。",
            ]
        )
    return "\n".join(lines)

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

def _normalize_message_log_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {
            str(key): _normalize_message_log_value(item) for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set)):
        return [_normalize_message_log_value(item) for item in value]
    if hasattr(value, "__fields__"):
        return {
            field_name: _normalize_message_log_value(getattr(value, field_name, None))
            for field_name in value.__fields__.keys()
        }
    return repr(value)

def _serialize_message_segments(message: Any) -> List[Dict[str, Any]]:
    serialized: List[Dict[str, Any]] = []
    if message is None:
        return serialized
    for seg in message:
        serialized.append(
            {
                "type": getattr(seg, "type", ""),
                "data": _normalize_message_log_value(
                    getattr(seg, "data", {}) or {}
                ),
            }
        )
    return serialized

def _extract_markdown_payloads(message: Any) -> List[Dict[str, Any]]:
    payloads: List[Dict[str, Any]] = []
    if message is None:
        return payloads
    for seg in message:
        if getattr(seg, "type", "") != "markdown":
            continue
        markdown = (getattr(seg, "data", {}) or {}).get("markdown")
        payloads.append(_normalize_message_log_value(markdown))
    return payloads

def _markdown_message_rule(event: Event) -> bool:
    if event is None or not hasattr(event, "get_message"):
        return False
    try:
        message = event.get_message()
    except Exception:
        return False
    return any(getattr(seg, "type", "") == "markdown" for seg in message)

anti_sb = on_message(
    priority=10,
    rule=taiko_rule & Rule(_markdown_message_rule),
    block=False,
)

@anti_sb.handle()
async def _(event: MessageEvent):
    msg = event.get_message()
    logger.info("incoming_markdown_message raw={}", str(msg).strip())
    logger.info(
        "incoming_markdown_message payloads={}",
        json.dumps(_extract_markdown_payloads(msg), ensure_ascii=False),
    )
    logger.info(
        "incoming_markdown_message segments={}",
        json.dumps(_serialize_message_segments(msg), ensure_ascii=False),
    )
