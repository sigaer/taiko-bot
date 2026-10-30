"""Attach the shared Rating v2 survey to query replies, outside rendered images."""
from dataclasses import replace

from taiko_application.commands import CommandResult

RATING_V2_FEEDBACK_URL = "https://wj.qq.com/s2/28362775/f4fn/"
RATING_V2_FEEDBACK_TEXT = f"Rating v2 反馈问卷：{RATING_V2_FEEDBACK_URL}"


def with_rating_v2_feedback(result: CommandResult) -> CommandResult:
    if result.kind not in ("text", "image"):
        return result
    field = "prefix_text" if result.kind == "image" else "payload"
    text = getattr(result, field) or ""
    if RATING_V2_FEEDBACK_URL in text:
        return result
    return replace(result, **{field: f"{text}\n{RATING_V2_FEEDBACK_TEXT}" if text else RATING_V2_FEEDBACK_TEXT})
