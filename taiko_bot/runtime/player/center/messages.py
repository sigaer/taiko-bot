from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Literal, Optional, Sequence, Tuple

from PIL import Image

from .qq_markdown_media import cache_markdown_image_url

ONEBOT_V11_PLATFORM = "onebot_v11"
QQ_OFFICIAL_PLATFORM = "qq_official"
PlatformKind = Literal["onebot_v11", "qq_official"]
logger = logging.getLogger(__name__)


def _is_qq_passive_reply_limit_error(exc: BaseException) -> bool:
    """QQ error 40034128 means the passive reply window/count was exceeded."""
    text = str(exc)
    return "40034128" in text or "被动回复时间或者次数超过限制" in text


async def _send_qq_proactive(matcher_or_bot: Any, event: Any, message: Any) -> bool:
    """Send without msg_id/msg_seq so a late Hiroba result can still reach users."""
    bot = getattr(matcher_or_bot, "bot", None) or matcher_or_bot
    if not (hasattr(bot, "send_to_group") or hasattr(bot, "send_to_c2c")):
        # Matcher does not consistently retain the Bot instance after dispatch.
        # Resolve it from the event's self_id for late/background replies.
        try:
            import nonebot

            self_id = str(getattr(event, "self_id", "") or "").strip()
            if self_id:
                bot = nonebot.get_bot(self_id)
        except Exception:
            bot = None
    try:
        if is_qq_official_group_event(event):
            group_openid = str(getattr(event, "group_openid", "") or "").strip()
            if group_openid and hasattr(bot, "send_to_group"):
                await bot.send_to_group(group_openid=group_openid, message=message)
                return True
        else:
            user_openid = str(
                getattr(getattr(event, "author", None), "id", "")
                or getattr(event, "user_openid", "")
                or (event.get_user_id() if hasattr(event, "get_user_id") else "")
            ).strip()
            if user_openid and hasattr(bot, "send_to_c2c"):
                await bot.send_to_c2c(openid=user_openid, message=message)
                return True
    except Exception:
        logger.exception("QQ proactive message failed")
    return False


def _event_module_name(event: Any) -> str:
    return str(getattr(event.__class__, "__module__", "") or "")


def is_onebot_v11_event(event: Any) -> bool:
    return _event_module_name(event).startswith("nonebot.adapters.onebot.v11")


def is_qq_official_event(event: Any) -> bool:
    module_name = _event_module_name(event)
    return module_name.startswith("nonebot.adapters.qq") or hasattr(
        event, "group_openid"
    )


def is_onebot_group_message_event(event: Any) -> bool:
    return is_onebot_v11_event(event) and getattr(event, "group_id", None) is not None


def is_qq_official_group_event(event: Any) -> bool:
    if not is_qq_official_event(event):
        return False
    return bool(get_group_identifier(event=event))


def is_qq_official_private_event(event: Any) -> bool:
    return is_qq_official_event(event) and not is_qq_official_group_event(event)


def get_platform_kind(bot: Any = None, event: Any = None) -> PlatformKind:
    target = event if event is not None else bot
    if target is not None and is_qq_official_event(target):
        return QQ_OFFICIAL_PLATFORM
    return ONEBOT_V11_PLATFORM


def build_identity_key(platform: PlatformKind, user_id: str) -> str:
    normalized = str(user_id or "").strip()
    return f"{platform}:{normalized}" if normalized else ""


def build_group_key(platform: PlatformKind, group_id: str) -> str:
    normalized = str(group_id or "").strip()
    return f"{platform}:{normalized}" if normalized else ""


def parse_identity_key(identity_key: str) -> Tuple[PlatformKind, str]:
    normalized = str(identity_key or "").strip()
    if ":" not in normalized:
        return ONEBOT_V11_PLATFORM, normalized
    platform, raw_id = normalized.split(":", 1)
    if platform not in {ONEBOT_V11_PLATFORM, QQ_OFFICIAL_PLATFORM}:
        return ONEBOT_V11_PLATFORM, normalized
    return platform, raw_id


def _mask_identifier(raw_id: str, head: int = 4, tail: int = 4) -> str:
    normalized = str(raw_id or "").strip()
    if not normalized:
        return ""
    if len(normalized) <= head + tail:
        return normalized
    return f"{normalized[:head]}...{normalized[-tail:]}"


def format_identity_for_display(identity_key: str) -> str:
    platform, raw_id = parse_identity_key(identity_key)
    if platform == QQ_OFFICIAL_PLATFORM:
        return f"官方群用户({_mask_identifier(raw_id)})"
    return raw_id


def get_identity_key(bot: Any = None, event: Any = None) -> str:
    target = event if event is not None else bot
    if target is None or not hasattr(target, "get_user_id"):
        return ""
    platform = get_platform_kind(bot=bot, event=event)
    return build_identity_key(platform, str(target.get_user_id()))


def get_group_identifier(bot: Any = None, event: Any = None) -> Optional[str]:
    target = event if event is not None else bot
    if target is None:
        return None

    if is_qq_official_event(target):
        for attr in ("group_openid", "group_id"):
            raw_value = str(getattr(target, attr, "") or "").strip()
            if raw_value:
                return raw_value
        return None

    raw_group_id = str(getattr(target, "group_id", "") or "").strip()
    if raw_group_id:
        return raw_group_id
    return None


def get_group_key(bot: Any = None, event: Any = None) -> Optional[str]:
    group_id = get_group_identifier(bot=bot, event=event)
    if not group_id:
        return None
    platform = get_platform_kind(bot=bot, event=event)
    return build_group_key(platform, group_id)


def get_message_claim_key(bot: Any = None, event: Any = None) -> str:
    target = event if event is not None else bot
    if target is None:
        return ""
    message_id = getattr(target, "message_id", None)
    if message_id is None:
        message_id = getattr(target, "id", None)
    platform = get_platform_kind(bot=bot, event=event)
    if message_id is None:
        return f"{platform}:"
    return f"{platform}:{message_id}"


def _iter_message_segments(message_or_event: Any) -> Iterable[Any]:
    if hasattr(message_or_event, "get_message"):
        message_or_event = message_or_event.get_message()
    if message_or_event is None:
        return []
    return message_or_event


def extract_plain_text(event: Any) -> str:
    if event is None or not hasattr(event, "get_message"):
        return ""
    message = event.get_message()
    if hasattr(message, "extract_plain_text"):
        try:
            return str(message.extract_plain_text() or "").strip()
        except Exception:
            pass
    parts = []
    for seg in _iter_message_segments(message):
        if getattr(seg, "type", "") == "text":
            parts.append(str(getattr(seg, "data", {}).get("text", "")))
    return "".join(parts).strip()


def get_onebot_at_targets(event: Any) -> list[str]:
    if not is_onebot_v11_event(event) or event is None or not hasattr(event, "get_message"):
        return []
    results: list[str] = []
    seen = set()
    for seg in _iter_message_segments(event):
        if getattr(seg, "type", "") != "at":
            continue
        raw_id = str((getattr(seg, "data", {}) or {}).get("qq") or "").strip()
        if not raw_id or raw_id in seen:
            continue
        seen.add(raw_id)
        results.append(raw_id)
    return results


def is_onebot_message_targeting_other_account(event: Any) -> bool:
    if not is_onebot_v11_event(event):
        return False
    self_id = str(getattr(event, "self_id", "") or "").strip()
    for target_id in get_onebot_at_targets(event):
        if target_id == "all":
            continue
        if self_id and target_id == self_id:
            continue
        return True
    return False


def get_mentioned_identity_keys(bot: Any = None, event: Any = None) -> list[str]:
    if event is None or not hasattr(event, "get_message"):
        return []
    platform = get_platform_kind(bot=bot, event=event)
    results: list[str] = []
    seen = set()
    for seg in _iter_message_segments(event):
        seg_type = getattr(seg, "type", "")
        seg_data = getattr(seg, "data", {}) or {}
        raw_id = ""
        if platform == QQ_OFFICIAL_PLATFORM and seg_type == "mention_user":
            raw_id = str(seg_data.get("user_id") or "").strip()
        elif platform == ONEBOT_V11_PLATFORM and seg_type == "at":
            raw_id = str(seg_data.get("qq") or "").strip()
        if not raw_id:
            continue
        identity_key = build_identity_key(platform, raw_id)
        if identity_key in seen:
            continue
        seen.add(identity_key)
        results.append(identity_key)
    return results


def resolve_target_identity_key(bot: Any = None, event: Any = None) -> str:
    self_identity = get_identity_key(bot=bot, event=event)
    for identity_key in get_mentioned_identity_keys(bot=bot, event=event):
        if identity_key != self_identity:
            return identity_key
    return self_identity


def _load_qq_message_api():
    from nonebot.adapters.qq import Message as QQMessage
    from nonebot.adapters.qq import MessageSegment as QQMessageSegment

    return QQMessage, QQMessageSegment


def _load_onebot_message_api():
    from nonebot.adapters.onebot.v11 import Message as OneBotMessage
    from nonebot.adapters.onebot.v11 import MessageSegment as OneBotMessageSegment

    return OneBotMessage, OneBotMessageSegment


def _normalize_image_payload(image_bytes: bytes | BytesIO | Path) -> bytes | BytesIO | Path:
    if isinstance(image_bytes, BytesIO):
        image_bytes.seek(0)
    return image_bytes


def _build_qq_reply_message(
    event: Any,
    *,
    text: str = "",
    image_bytes: bytes | BytesIO | Path | None = None,
):
    QQMessage, QQMessageSegment = _load_qq_message_api()
    message = QQMessage()
    reference_id = str(getattr(event, "id", "") or "").strip()
    if reference_id:
        message += QQMessageSegment.reference(reference_id, ignore_error=True)
    if text:
        message += QQMessageSegment.text(str(text))
    if image_bytes is not None:
        message += QQMessageSegment.file_image(_normalize_image_payload(image_bytes))
    return message


def _get_image_dimensions(
    image_bytes: bytes | BytesIO | Path | None,
) -> tuple[Optional[int], Optional[int]]:
    if image_bytes is None:
        return None, None
    normalized = _normalize_image_payload(image_bytes)
    try:
        if isinstance(normalized, Path):
            with Image.open(normalized) as img:
                return img.size
        if isinstance(normalized, BytesIO):
            raw = normalized.getvalue()
        elif isinstance(normalized, bytes):
            raw = normalized
        else:
            return None, None
        with Image.open(BytesIO(raw)) as img:
            return img.size
    except Exception:
        return None, None


def _build_qq_markdown_image_block(
    image_url: str,
    image_bytes: bytes | BytesIO | Path | None = None,
) -> str:
    width, height = _get_image_dimensions(image_bytes)
    normalized_image_url = str(image_url or "").strip()
    if not normalized_image_url:
        return ""
    if width and height:
        return f"![img#{width}px #{height}px]({normalized_image_url})"
    return f"![img]({normalized_image_url})"


def _build_qq_markdown_content(
    text: str = "",
    image_url: str = "",
    image_bytes: bytes | BytesIO | Path | None = None,
) -> str:
    content_blocks = []
    normalized_text = str(text or "").strip()
    if normalized_text:
        content_blocks.append(normalized_text)
    normalized_image_url = str(image_url or "").strip()
    if normalized_image_url:
        content_blocks.append(
            _build_qq_markdown_image_block(normalized_image_url, image_bytes)
        )
    return "\n\n".join(content_blocks) or "快捷操作"


def _build_qq_quick_action_keyboard():
    (
        _QQMessage,
        _QQMessageSegment,
        MessageKeyboard,
        InlineKeyboard,
        InlineKeyboardRow,
        Button,
        RenderData,
        Action,
        Permission,
    ) = _load_qq_quick_action_api()

    def _build_button(button_id: str, label: str, command: str) -> Any:
        return Button(
            id=button_id,
            render_data=RenderData(
                label=label,
                visited_label=label,
                style=1,
            ),
            action=Action(
                type=2,
                permission=Permission(type=2),
                data=command,
                unsupport_tips="当前客户端暂不支持按钮快捷指令，请手动输入命令。",
            ),
        )

    keyboard = MessageKeyboard(
        content=InlineKeyboard(
            rows=[
                InlineKeyboardRow(
                    buttons=[
                        _build_button("bind", "绑定", "绑定 你的鼓众广场id"),
                        _build_button(
                            "bind_qq",
                            "旧绑定迁移",
                            "绑定QQ",
                        ),
                    ]
                ),
                InlineKeyboardRow(
                    buttons=[
                        _build_button("update", "更新广场", "taikoupdate"),
                        _build_button(
                            "update_all", "更新广场(全部)", "taikoupdate all"
                        ),
                    ]
                ),
                InlineKeyboardRow(
                    buttons=[
                        _build_button("my_don", "个人信息", "我的小咚"),
                        _build_button("tcloud", "词云", "太鼓词云"),
                    ]
                ),
                InlineKeyboardRow(
                    buttons=[
                        _build_button("trend", "查询我的近期走势", "taikotrend"),
                        _build_button(
                            "playtrend", "查询曲数Rating曲线", "taikoplaytrend"
                        ),
                    ]
                ),
                InlineKeyboardRow(
                    buttons=[
                        _build_button("taikob", "查看rt", "taikob20"),
                        _build_button("taikob_v1", "查看rtv1", "taikob20 v1"),
                    ]
                ),
            ]
        )
    )

    return keyboard


def _build_qq_markdown_reply_message(
    event: Any,
    *,
    markdown_text: str,
    include_quick_actions: bool = False,
):
    QQMessage, QQMessageSegment = _load_qq_message_api()
    message = QQMessage()
    # QQ clients render markdown+keyboard+reference inconsistently; keep the
    # markdown/button message free of a quoted reference.
    message += QQMessageSegment.markdown(markdown_text)
    if include_quick_actions:
        message += QQMessageSegment.keyboard(_build_qq_quick_action_keyboard())
    return message


def _build_qq_quick_action_message(event: Any):
    return _build_qq_markdown_reply_message(
        event,
        markdown_text="快捷操作",
        include_quick_actions=True,
    )


def _build_onebot_reply_message(
    *,
    text: str = "",
    image_bytes: bytes | BytesIO | Path | None = None,
):
    OneBotMessage, OneBotMessageSegment = _load_onebot_message_api()
    if image_bytes is None:
        return text
    if text:
        return OneBotMessage(str(text) + "\n") + OneBotMessageSegment.image(
            _normalize_image_payload(image_bytes)
        )
    return OneBotMessageSegment.image(_normalize_image_payload(image_bytes))


def _load_qq_quick_action_api():
    from nonebot.adapters.qq import Message as QQMessage
    from nonebot.adapters.qq import MessageSegment as QQMessageSegment
    from nonebot.adapters.qq.models import (
        Action,
        Button,
        InlineKeyboard,
        InlineKeyboardRow,
        MessageKeyboard,
        Permission,
        RenderData,
    )

    return (
        QQMessage,
        QQMessageSegment,
        MessageKeyboard,
        InlineKeyboard,
        InlineKeyboardRow,
        Button,
        RenderData,
        Action,
        Permission,
    )


async def _send_qq_quick_action_message(matcher_or_bot: Any, event: Any) -> None:
    message = _build_qq_quick_action_message(event)
    try:
        if hasattr(matcher_or_bot, "finish"):
            await matcher_or_bot.send(message)
        else:
            await matcher_or_bot.send(event, message)
    except Exception:
        # Quick action buttons are auxiliary; primary replies should still succeed.
        return


async def _send_reply(
    matcher_or_bot: Any,
    event: Any,
    *,
    text: str = "",
    markdown_text: str | None = None,
    image_bytes: bytes | BytesIO | Path | None = None,
    quick_actions: bool = False,
    prefer_markdown_image: bool = False,
    markdown_image_name: str = "taiko",
) -> Any:
    is_matcher_like = hasattr(matcher_or_bot, "finish")
    if is_qq_official_event(event):
        markdown_image_url = ""
        should_use_markdown_reply = quick_actions and image_bytes is None
        if image_bytes is not None and prefer_markdown_image:
            try:
                markdown_image_url = cache_markdown_image_url(
                    _normalize_image_payload(image_bytes),
                    prefix=markdown_image_name,
                )
            except Exception:
                logger.exception("failed to cache QQ markdown image")
            else:
                should_use_markdown_reply = True
        elif quick_actions and image_bytes is None:
            should_use_markdown_reply = True

        if should_use_markdown_reply:
            message = _build_qq_markdown_reply_message(
                event,
                markdown_text=_build_qq_markdown_content(
                    text=markdown_text if markdown_text is not None else text,
                    image_url=markdown_image_url,
                    image_bytes=image_bytes,
                ),
                include_quick_actions=quick_actions,
            )
        else:
            message = _build_qq_reply_message(
                event, text=text, image_bytes=image_bytes
            )
        if is_matcher_like:
            try:
                await matcher_or_bot.send(message)
            except Exception as exc:
                if not _is_qq_passive_reply_limit_error(exc) or not await _send_qq_proactive(matcher_or_bot, event, message):
                    raise
            if quick_actions and not should_use_markdown_reply:
                await _send_qq_quick_action_message(matcher_or_bot, event)
            return await matcher_or_bot.finish()
        try:
            result = await matcher_or_bot.send(event, message)
        except Exception as exc:
            if not _is_qq_passive_reply_limit_error(exc) or not await _send_qq_proactive(matcher_or_bot, event, message):
                raise
            result = None
        if quick_actions and not should_use_markdown_reply:
            await _send_qq_quick_action_message(matcher_or_bot, event)
        return result

    message = _build_onebot_reply_message(text=text, image_bytes=image_bytes)
    if is_matcher_like:
        return await matcher_or_bot.finish(message, reply_message=True)
    return await matcher_or_bot.send(event, message, reply_message=True)


async def send_text_reply(
    matcher_or_bot: Any,
    event: Any,
    text: str,
    *,
    quick_actions: bool = False,
    markdown_text: str | None = None,
) -> Any:
    return await _send_reply(
        matcher_or_bot,
        event,
        text=text,
        markdown_text=markdown_text,
        quick_actions=quick_actions,
    )


async def send_onebot_forward_messages(
    matcher_or_bot: Any,
    bot: Any,
    event: Any,
    messages: Sequence[Any],
) -> bool:
    if not is_onebot_v11_event(event):
        return False
    payload = list(messages)
    if not payload:
        return False

    if is_onebot_group_message_event(event):
        await bot.call_api(
            "send_group_forward_msg",
            group_id=getattr(event, "group_id"),
            messages=payload,
        )
    else:
        user_id = ""
        if hasattr(event, "get_user_id"):
            user_id = str(event.get_user_id() or "").strip()
        if not user_id:
            user_id = str(getattr(event, "user_id", "") or "").strip()
        if not user_id:
            return False
        await bot.call_api(
            "send_private_forward_msg",
            user_id=user_id,
            messages=payload,
        )

    return True


async def send_image_reply(
    matcher_or_bot: Any,
    event: Any,
    image_bytes: bytes | BytesIO | Path,
    prefix_text: str = "",
    *,
    quick_actions: bool = False,
    prefer_markdown_image: bool = False,
    markdown_image_name: str = "taiko",
) -> Any:
    return await _send_reply(
        matcher_or_bot,
        event,
        text=prefix_text,
        image_bytes=image_bytes,
        quick_actions=quick_actions,
        prefer_markdown_image=prefer_markdown_image,
        markdown_image_name=markdown_image_name,
    )
