from __future__ import annotations

from nonebot.message import run_postprocessor

from .config import CONFIG
from .extractor import build_record, should_record
from .store import enqueue_record


@run_postprocessor
async def record_method_call(matcher, exception, bot, event, state):
    if not CONFIG.enabled or exception is not None:
        return
    if not should_record(event, matcher):
        return

    record = build_record(event, matcher, state)
    if record is None:
        return
    await enqueue_record(record)
