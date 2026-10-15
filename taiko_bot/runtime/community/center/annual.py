from __future__ import annotations
import os
from pathlib import Path
_CENTER_ROOT = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))

from ...public.provider import query_with_mode as _query_music_with_mode

from .annual_report_command import COMMANDS as ANNUAL_REPORT_COMMANDS

from nonebot.adapters import Event

from nonebot.matcher import Matcher

from nonebot.rule import Rule

from feature_handler.feature_handler import feature_on

from .annual_report_command import handle_annual_report

from ...player.center.messages import is_qq_official_event

from nonebot.plugin import on_regex

import re

MessageEvent = Event

taiko_rule = feature_on("taiko")  # 复用这个 Rule

def _annual_official_rule(event: MessageEvent) -> bool:
    return is_qq_official_event(event)

annual_2025_report = on_regex(
    r"^/?(?:" + "|".join(re.escape(name) for name in sorted(ANNUAL_REPORT_COMMANDS)) + r")\s*$",
    rule=taiko_rule & Rule(_annual_official_rule), priority=5, block=True
)

@annual_2025_report.handle()
async def annual_2025_report_handle(matcher: Matcher, event: MessageEvent):
    await handle_annual_report(matcher, event)
