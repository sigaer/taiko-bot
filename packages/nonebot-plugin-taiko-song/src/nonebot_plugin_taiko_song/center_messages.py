from __future__ import annotations
import logging
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Optional
from PIL import Image
logger=logging.getLogger(__name__)
ONEBOT_V11_PLATFORM="onebot_v11"
QQ_OFFICIAL_PLATFORM="qq_official"
PlatformKind=str

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

def is_qq_official_event(event: Any) -> bool:
    module_name = _event_module_name(event)
    return module_name.startswith("nonebot.adapters.qq") or hasattr(
        event, "group_openid"
    )

def is_qq_official_group_event(event: Any) -> bool:
    if not is_qq_official_event(event):
        return False
    return bool(get_group_identifier(event=event))

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
