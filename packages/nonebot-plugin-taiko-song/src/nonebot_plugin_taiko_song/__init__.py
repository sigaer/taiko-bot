"""Taiko-owned public song matcher; host generic feature switches stay host-owned."""
import re
from nonebot import on_regex, require
from nonebot.adapters import Event
from nonebot.matcher import Matcher
from nonebot.rule import Rule
require("feature_handler")
from feature_handler.feature_handler import feature_on
from taiko_application import commands
from .config import profile
from . import provider
from .delivery import deliver, transport

PATTERN = re.compile(r'^(?P<q>.+?)是什么歌[？?]?$')
OFFICIAL = (
    re.compile(r'^(?:taiko|太鼓)\s+(?P<q>.+?)是什么歌[？?]?$', re.I),
    re.compile(r'^(?:taiko|太鼓)\s*(?:什么歌|是啥歌)\s+(?P<q>.+)$', re.I),
)


def extract(text, official=False):
    patterns = (*OFFICIAL, PATTERN) if profile() == 'center' else (PATTERN, *OFFICIAL) if official else (PATTERN,)
    for pattern in patterns:
        match = pattern.match(str(text or '').strip())
        if match:
            return match.group('q').strip() or None
    return None


def eligible(event: Event):
    t = transport()
    text = t.extract_plain_text(event)
    if profile() == 'center':
        return extract(text) is not None
    return not t.is_qq_official_event(event) or any(p.match(text) for p in OFFICIAL)


what_song = on_regex(PATTERN.pattern, priority=10, block=True,
    rule=feature_on('taiko') & feature_on('tsearch') & Rule(eligible))


@what_song.handle()
async def handle(matcher: Matcher, event: Event):
    t = transport()
    if not t.is_qq_official_event(event):
        if any(seg.type == 'at' and seg.data.get('qq') == '3889003795' for seg in event.get_message()):
            return
    result = commands.execute_song(commands.CommandContext(profile=profile(), text=t.extract_plain_text(event)),
        commands.SongPorts(_extract_what_song_query=lambda text: extract(text, t.is_qq_official_event(event)),
            _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
            _resolve_what_song_query=provider.resolve))
    await deliver(matcher, event, result)


# Registration remains in a dedicated module as this plugin grows.
from . import public_commands  # noqa: E402,F401
