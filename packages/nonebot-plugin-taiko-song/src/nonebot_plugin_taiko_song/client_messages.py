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

def _event_module_name(event: Any) -> str:
    return str(getattr(event.__class__, "__module__", "") or "")

def is_qq_official_event(event: Any) -> bool:
    module_name = _event_module_name(event)
    return module_name.startswith("nonebot.adapters.qq") or hasattr(
        event, "group_openid"
    )

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
                        _build_button("bind", "绑定", "绑定"),
                        _build_button("bind_qq", "旧绑定迁移", "绑定QQ"),
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
                    buttons=[_build_button("taikob", "查看rt", "taikob20")]
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
    content_text: str = "Markdown消息",
):
    QQMessage, QQMessageSegment = _load_qq_message_api()
    message = QQMessage()
    reference_id = str(getattr(event, "id", "") or "").strip()
    if reference_id:
        message += QQMessageSegment.reference(reference_id, ignore_error=True)
    if content_text:
        message += QQMessageSegment.text(content_text)
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
