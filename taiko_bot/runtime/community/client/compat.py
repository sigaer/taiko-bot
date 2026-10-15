from __future__ import annotations

from ...public.provider import query_with_mode as _query_music_with_mode

from nonebot.adapters import Event

from nonebot.exception import FinishedException

from nonebot.matcher import Matcher

from typing import Optional

from nonebot.rule import Rule

from ...player.client.messages import extract_plain_text as extract_platform_plain_text

from feature_handler.feature_handler import feature_on

from ...player.client.messages import is_qq_official_event

from ...player.client.messages import is_qq_official_group_event

from nonebot.plugin import on_message

from nonebot.plugin import on_regex

import re

from ...player.client.messages import send_text_reply

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule

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

def _is_qq_official_unsupported_command(event: MessageEvent) -> bool:
    if not is_qq_official_group_event(event):
        return False
    text = extract_plain_text(event)
    if not text:
        return False
    return any(pattern.match(text) for pattern in QQ_OFFICIAL_UNSUPPORTED_PATTERNS)

def _is_qq_official_event(event: MessageEvent) -> bool:
    return is_qq_official_event(event)

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
    raise FinishedException

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
