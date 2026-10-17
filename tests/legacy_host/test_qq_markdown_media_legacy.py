from __future__ import annotations

import asyncio
import os
import time
from io import BytesIO

from nonebot.adapters.qq import Bot
from PIL import Image

from taiko_bot.runtime import center_platform_adapter as platform_adapter
from taiko_bot.runtime import center_markdown_media as qq_markdown_media


class FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(self, event_id: str = "evt-quick-action") -> None:
        self.id = event_id


class FakeMatcher:
    def __init__(self) -> None:
        self.sent_messages = []
        self.finished = False

    async def send(self, message):
        self.sent_messages.append(message)
        return message

    async def finish(self):
        self.finished = True
        return "finished"


def _build_png_bytes() -> bytes:
    img = Image.new("RGB", (4, 4), (255, 0, 0))
    out = BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


def test_cache_markdown_image_url_and_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(
        qq_markdown_media,
        "QQ_MARKDOWN_IMAGE_CACHE_DIR",
        tmp_path,
    )
    monkeypatch.setattr(
        qq_markdown_media,
        "QQ_MARKDOWN_IMAGE_BASE_URL",
        "https://viewer.sakura-bot.cn/qqbot-cache/taiko",
    )

    image_bytes = _build_png_bytes()
    image_url = qq_markdown_media.cache_markdown_image_url(
        image_bytes,
        prefix="taikoupdate",
    )

    assert image_url.startswith("https://viewer.sakura-bot.cn/qqbot-cache/taiko/")
    created_files = list(tmp_path.iterdir())
    assert len(created_files) == 1
    assert created_files[0].suffix == ".png"

    expired = tmp_path / "expired.png"
    expired.write_bytes(image_bytes)
    expired_ts = time.time() - qq_markdown_media.QQ_MARKDOWN_IMAGE_TTL_SECONDS - 5
    os.utime(expired, (expired_ts, expired_ts))

    deleted = qq_markdown_media.cleanup_expired_markdown_images(now=time.time())

    assert deleted >= 1
    assert not expired.exists()


def test_build_qq_markdown_reply_message_with_quick_actions():
    event = FakeQQGroupEvent()
    markdown_text = platform_adapter._build_qq_markdown_content(
        text="更新成功！",
        image_url="https://viewer.sakura-bot.cn/qqbot-cache/taiko/demo.png",
        image_bytes=_build_png_bytes(),
    )
    message = platform_adapter._build_qq_markdown_reply_message(
        event,
        markdown_text=markdown_text,
        include_quick_actions=True,
    )

    assert len(message["markdown"]) == 1
    assert len(message["text"]) == 0
    assert "demo.png" in message["markdown"][-1].data["markdown"].content
    assert "![img#4px #4px]" in message["markdown"][-1].data["markdown"].content
    assert len(message["keyboard"]) == 1

    kwargs = Bot._extract_send_message(message, escape_text=False)
    payload = Bot._parse_send_message({**kwargs, "msg_type": 2, "msg_id": "evt"})
    assert "content" not in payload["json"]
    assert "message_reference" not in payload["json"]
    assert "markdown" in payload["json"]
    assert "keyboard" in payload["json"]

    keyboard = message["keyboard"][-1].data["keyboard"]
    rows = keyboard.content.rows
    assert len(rows) == 5
    assert len(rows[0].buttons) == 2
    assert rows[0].buttons[0].action.data == "绑定 你的鼓众广场id"
    assert rows[0].buttons[1].action.data == "绑定QQ"
    assert rows[0].buttons[1].render_data.label == "旧绑定迁移"
    assert rows[1].buttons[0].action.data == "taikoupdate"
    assert rows[2].buttons[0].action.data == "我的小咚"
    assert rows[2].buttons[1].action.data == "太鼓词云"
    assert rows[-1].buttons[0].action.data == "taikob20"


def test_send_reply_uses_markdown_with_keyboard_for_preferred_image(monkeypatch):
    matcher = FakeMatcher()
    event = FakeQQGroupEvent()
    quick_action_calls = []

    async def fake_quick_action_message(_matcher, _event):
        quick_action_calls.append((_matcher, _event))

    def fake_cache(*args, **kwargs):
        return "https://viewer.sakura-bot.cn/qqbot-cache/taiko/unused.png"

    monkeypatch.setattr(
        platform_adapter,
        "_send_qq_quick_action_message",
        fake_quick_action_message,
    )
    monkeypatch.setattr(
        platform_adapter,
        "cache_markdown_image_url",
        fake_cache,
    )

    result = asyncio.run(
        platform_adapter._send_reply(
            matcher,
            event,
            text="更新成功！",
            image_bytes=_build_png_bytes(),
            quick_actions=True,
            prefer_markdown_image=True,
            markdown_image_name="taikoupdate",
        )
    )

    assert result == "finished"
    assert matcher.finished is True
    assert len(matcher.sent_messages) == 1
    markdown_message = matcher.sent_messages[0]
    assert len(markdown_message["file_image"]) == 0
    assert len(markdown_message["markdown"]) == 1
    assert len(markdown_message["keyboard"]) == 1
    assert len(markdown_message["text"]) == 0
    assert "![img#4px #4px]" in markdown_message["markdown"][-1].data["markdown"].content
    assert quick_action_calls == []


def test_send_reply_keeps_single_markdown_message_for_text_quick_actions(monkeypatch):
    matcher = FakeMatcher()
    event = FakeQQGroupEvent()
    quick_action_calls = []

    async def fake_quick_action_message(_matcher, _event):
        quick_action_calls.append((_matcher, _event))

    monkeypatch.setattr(
        platform_adapter,
        "_send_qq_quick_action_message",
        fake_quick_action_message,
    )

    result = asyncio.run(
        platform_adapter._send_reply(
            matcher,
            event,
            text="快捷操作面板：点击下方按钮可快速填入常用指令。",
            quick_actions=True,
        )
    )

    assert result == "finished"
    assert matcher.finished is True
    assert len(matcher.sent_messages) == 1
    markdown_message = matcher.sent_messages[0]
    assert len(markdown_message["markdown"]) == 1
    assert len(markdown_message["keyboard"]) == 1
    assert len(markdown_message["text"]) == 0
    assert len(markdown_message["file_image"]) == 0
    assert quick_action_calls == []
