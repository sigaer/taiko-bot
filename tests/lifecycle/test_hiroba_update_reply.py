from __future__ import annotations

import asyncio
import importlib

import nonebot
from nonebot.exception import FinishedException


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


def test_hiroba_success_reply_falls_back_to_text_when_image_reply_fails(monkeypatch):
    taiko = _load_taiko_module()
    calls: list[tuple[str, str]] = []

    async def fake_finish_image_reply(*_args, **_kwargs):
        raise TimeoutError("image send timeout")

    async def fake_finish_text_reply(_matcher, _event, text: str, **_kwargs):
        calls.append(("text", text))
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    try:
        asyncio.run(
            taiko._finish_hiroba_update_success_reply(
                object(),
                object(),
                success_message="Hiroba 更新成功！",
                img_buf=b"fake-image",
            )
        )
    except FinishedException:
        pass
    else:
        raise AssertionError("expected FinishedException")

    assert calls == [("text", "Hiroba 更新成功！")]


def test_hiroba_success_reply_keeps_image_path_when_image_reply_finishes(monkeypatch):
    taiko = _load_taiko_module()
    calls: list[str] = []

    async def fake_finish_image_reply(*_args, **_kwargs):
        calls.append("image")
        raise FinishedException()

    async def fake_finish_text_reply(*_args, **_kwargs):
        calls.append("text")
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    try:
        asyncio.run(
            taiko._finish_hiroba_update_success_reply(
                object(),
                object(),
                success_message="Hiroba 更新成功！",
                img_buf=b"fake-image",
            )
        )
    except FinishedException:
        pass
    else:
        raise AssertionError("expected FinishedException")

    assert calls == ["image"]


def test_qq_passive_limit_uses_resolved_bot_for_proactive_send(monkeypatch):
    taiko = _load_taiko_module()
    sent = []

    class Event:
        __module__ = "nonebot.adapters.qq.event"
        group_openid = "group-openid"
        self_id = "bot-id"

    class Bot:
        async def send_to_group(self, **kwargs):
            sent.append(kwargs)

    class Matcher:
        async def send(self, _message):
            raise RuntimeError("40034128 被动回复时间或者次数超过限制")

    import nonebot
    monkeypatch.setattr(nonebot, "get_bot", lambda _id: Bot())
    assert asyncio.run(taiko._send_text_reply_without_finish(Matcher(), Event(), "done")) is None
    assert sent == [{"group_openid": "group-openid", "message": "done"}]
