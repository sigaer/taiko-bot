"""Public event entry codes, shared by center and client profiles."""
from importlib.resources import files

from nonebot import on_regex
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from feature_handler.feature_handler import feature_on

from .delivery import reply


AOHARU_CAPTION = "在机台使用该二维码即可进入限时活动【青春之达人】模式！"

aoharu = on_regex(
    r"^/?青春(?:之)?达人\s*$",
    rule=feature_on("taiko"),
    priority=10,
    block=True,
)


@aoharu.handle()
async def aoharu_handle(matcher: Matcher, event: Event):
    image = files(__package__).joinpath("images/aoharu_no_tatsujin.jpg").read_bytes()
    await reply(matcher, event, AOHARU_CAPTION, image)
