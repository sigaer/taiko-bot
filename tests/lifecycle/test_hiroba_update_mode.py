from __future__ import annotations

import asyncio
import importlib

import nonebot


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


class _FakeQQPrivateEvent:
    __module__ = "nonebot.adapters.qq.event"

    def get_user_id(self):
        return "private-user"


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "group-openid"

    def get_user_id(self):
        return "group-user"


class _FakeMatcher:
    async def send(self, _message):
        return None


def test_hiroba_update_private_keeps_changes_image(monkeypatch):
    taiko = _load_taiko_module()
    include_flags: list[bool] = []

    async def fake_to_thread(func, *args, **kwargs):
        include_flags.append(bool(kwargs.get("include_changes_image")))
        return {"ok": True, "message": "Hiroba 更新成功！", "image": None}

    monkeypatch.setattr(taiko, "hiroba_update", _FakeMatcher())
    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "qq_official:test")
    monkeypatch.setattr(taiko, "_normalize_identity_key", lambda value: value)
    monkeypatch.setattr(
        taiko,
        "_get_current_bind_entry",
        lambda _identity: {"ids": ["644046058331"], "current_index": 0, "sources": {"644046058331": "hiroba"}},
    )
    monkeypatch.setattr(taiko, "_get_selected_bind_slot_number", lambda _entry: 1)
    monkeypatch.setattr(taiko, "_get_current_bind_taiko_id", lambda _entry: "644046058331")
    monkeypatch.setattr(taiko, "_infer_bind_source", lambda *_args, **_kwargs: "hiroba")
    monkeypatch.setattr(taiko, "peek_hiroba_sync_cooldown", lambda _taiko: None)
    monkeypatch.setattr(taiko, "_create_hiroba_progress_reporter", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        taiko,
        "_send_text_reply_without_finish",
        lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        taiko,
        "_finish_hiroba_update_success_reply",
        lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)

    asyncio.run(taiko.hiroba_update_handle(_FakeQQPrivateEvent()))
    assert include_flags == [True]


def test_hiroba_update_group_keeps_changes_image(monkeypatch):
    taiko = _load_taiko_module()
    include_flags: list[bool] = []

    async def fake_to_thread(func, *args, **kwargs):
        include_flags.append(bool(kwargs.get("include_changes_image")))
        return {"ok": True, "message": "Hiroba 更新成功！", "image": None}

    monkeypatch.setattr(taiko, "hiroba_update", _FakeMatcher())
    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "qq_official:test")
    monkeypatch.setattr(taiko, "_normalize_identity_key", lambda value: value)
    monkeypatch.setattr(
        taiko,
        "_get_current_bind_entry",
        lambda _identity: {"ids": ["644046058331"], "current_index": 0, "sources": {"644046058331": "hiroba"}},
    )
    monkeypatch.setattr(taiko, "_get_selected_bind_slot_number", lambda _entry: 1)
    monkeypatch.setattr(taiko, "_get_current_bind_taiko_id", lambda _entry: "644046058331")
    monkeypatch.setattr(taiko, "_infer_bind_source", lambda *_args, **_kwargs: "hiroba")
    monkeypatch.setattr(taiko, "peek_hiroba_sync_cooldown", lambda _taiko: None)
    monkeypatch.setattr(taiko, "_create_hiroba_progress_reporter", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        taiko,
        "_send_text_reply_without_finish",
        lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(
        taiko,
        "_finish_hiroba_update_success_reply",
        lambda *_args, **_kwargs: asyncio.sleep(0),
    )
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)

    asyncio.run(taiko.hiroba_update_handle(_FakeQQGroupEvent()))
    assert include_flags == [True]


def test_hiroba_update_returns_actionable_error_for_unreadable_credentials(monkeypatch):
    taiko = _load_taiko_module()
    from taiko_bot.runtime.player.center.hiroba import native_binding
    monkeypatch.setattr(taiko, "peek_hiroba_sync_cooldown", lambda _taiko: None)
    def unreadable(*_args, **_kwargs):
        raise native_binding.NativeHirobaCredentialUnavailable()
    monkeypatch.setattr(
        native_binding, "sync_native_hiroba", unreadable,
    )

    result = taiko._execute_hiroba_update("679851146621", identity_key="qq_official:test")

    assert result["ok"] is False
    assert "凭据无法读取" in result["message"]
    assert "绑定hiroba 邮箱 密码 679851146621" in result["message"]
