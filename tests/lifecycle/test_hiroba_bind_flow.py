from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import nonebot
from nonebot.exception import FinishedException


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


class _DummyMatch:
    def __init__(self, email: str, password: str, taiko_no: str = ""):
        self._parts = {1: email, 2: password, 3: taiko_no}

    def group(self, index: int) -> str:
        return self._parts[index]


class _DummyBindMatch:
    def __init__(self, taiko_no: str):
        self._taiko_no = taiko_no
        self.string = f"绑定 {taiko_no}"

    def group(self, index: int) -> str:
        if index != 1:
            raise IndexError(index)
        return self._taiko_no


def test_bind_hiroba_handle_keeps_running_after_initial_notice(monkeypatch):
    taiko = _load_taiko_module()
    sent_messages: list[str] = []
    finished_messages: list[str] = []

    class _FakeMatcher:
        async def send(self, text: str):
            sent_messages.append(text)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def fake_execute_hiroba_bind(*_args, **_kwargs):
        return SimpleNamespace(taiko_ids=("12345678", "87654321"), entry={"current_index":0}), 2

    async def fake_send_text_without_finish(_matcher, _event, text: str):
        sent_messages.append(text)

    async def fake_finish_text(_matcher, _event, text: str, **_kwargs):
        if text.startswith("开始绑定 Hiroba 账号"):
            raise FinishedException()
        finished_messages.append(text)

    monkeypatch.setattr(taiko, "bind_hiroba", _FakeMatcher())
    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "21219135")
    monkeypatch.setattr(taiko, "_normalize_identity_key", lambda value: value)
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(taiko, "_execute_hiroba_bind", fake_execute_hiroba_bind)
    monkeypatch.setattr(taiko, "_format_bind_entry_summary_safe", lambda entry: "绑定摘要")
    monkeypatch.setattr(
        taiko, "_send_text_reply_without_finish", fake_send_text_without_finish
    )
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text)

    asyncio.run(
        taiko.bind_hiroba_handle(
            object(),
            match=_DummyMatch("test@example.com", "secret"),
        )
    )

    assert sent_messages == ["开始绑定 Hiroba 账号"]
    assert finished_messages == [
        "已自动同步并绑定该 Bandai Namco ID 下的 2 个 Hiroba 账号。\n已切换到 u1：12345678\n当前绑定：绑定摘要\n已完成 Hiroba 同步（默认仅鬼/里）。"
    ]


def test_bind_12_digit_hiroba_rejects_private_profile(monkeypatch):
    taiko = _load_taiko_module()
    finished_messages: list[str] = []

    async def fake_finish_text(_matcher, _event, text: str, **_kwargs):
        finished_messages.append(text)

    async def fake_to_thread(func, *args, **kwargs):
        raise taiko.HirobaProfilePrivateError("private")

    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "qq_official:test")
    monkeypatch.setattr(taiko, "_normalize_identity_key", lambda value: value)
    monkeypatch.setattr(taiko, "load_hiroba_credential_owner", lambda _taiko_id: None)
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text)

    asyncio.run(
        taiko.bind_handle(
            object(),
            match=_DummyBindMatch("519635636897"),
        )
    )

    assert finished_messages == [
        "该 Hiroba 账号当前为非公开资料，服务账号无法读取称号信息。\n请先发送“绑定hiroba 邮箱 密码 太鼓番”完成登录验证。"
    ]
