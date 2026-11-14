"""Fanmade search entry shared by OneBot and official QQ, center and client."""
import re

from nonebot import logger, on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from feature_handler.feature_handler import feature_on

from taiko_bot import fanmade
from .delivery import reply, transport

fanmade_search = on_regex(
    fanmade.COMMAND_PATTERN,
    flags=re.I | re.S,
    rule=feature_on("taiko") & feature_on("tsearch"),
    priority=10,
    block=True,
)


@fanmade_search.handle()
async def fanmade_handle(matcher: Matcher, event: Event):
    t = transport()
    if not t.is_qq_official_event(event) and any(
        seg.type == "at" and seg.data.get("qq") == "3889003795"
        for seg in event.get_message()
    ):
        return
    try:
        keyword, page = fanmade.parse_query(t.extract_plain_text(event))
    except ValueError as exc:
        await reply(matcher, event, str(exc))
        return
    try:
        result = await fanmade.search(keyword, page)
        text = fanmade.format_result(keyword, result)
    except fanmade.FanmadeUnavailable:
        logger.warning("OurTaiko fanmade search unavailable")
        text = "自制谱搜索服务暂时不可用，请稍后再试。"
    await reply(matcher, event, text)
