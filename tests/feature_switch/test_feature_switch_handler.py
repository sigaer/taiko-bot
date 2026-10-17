from __future__ import annotations

import asyncio
import importlib

import nonebot


def _load_switch_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    return importlib.import_module("feature_handler.feature_switch_handler")


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(self):
        self.group_openid = "group_openid_1"
        self.group_id = "group_openid_1"
        self.id = "evt-1"

    def get_user_id(self) -> str:
        return "member_openid_1"


class _FakeSender:
    def __init__(self, role: str):
        self.role = role


class _FakeOneBotGroupEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, *, role: str = "admin"):
        self.group_id = 114514
        self.message_id = 123
        self.self_id = 10000
        self.sender = _FakeSender(role)

    def get_user_id(self) -> str:
        return "1919810"


def test_switch_handler_uses_group_openid_for_official_group(monkeypatch):
    switch_module = _load_switch_module()
    event = _FakeQQGroupEvent()
    captured: dict[str, object] = {}
    replies: list[str] = []

    def _fake_is_first_handler(msg_id: str) -> bool:
        captured["msg_id"] = msg_id
        return True

    monkeypatch.setattr(switch_module, "is_first_handler", _fake_is_first_handler)

    def _fake_apply_switch(group_key: str, feature: str, enabled: bool) -> bool:
        captured["group_key"] = group_key
        captured["feature"] = feature
        captured["enabled"] = enabled
        return True

    async def _fake_send_text_reply(_matcher, _event, text: str, **_kwargs):
        replies.append(text)

    monkeypatch.setattr(switch_module, "apply_switch", _fake_apply_switch)
    monkeypatch.setattr(switch_module, "send_text_reply", _fake_send_text_reply)

    asyncio.run(switch_module._(event, ("关闭", "taiko")))

    assert captured == {
        "msg_id": "qq_official:evt-1",
        "group_key": "qq_official:group_openid_1",
        "feature": "taiko",
        "enabled": False,
    }
    assert replies == ["已在本群关闭 taiko 功能。"]


def test_switch_handler_keeps_onebot_group_id_path(monkeypatch):
    switch_module = _load_switch_module()
    event = _FakeOneBotGroupEvent(role="admin")
    captured: dict[str, object] = {}

    monkeypatch.setattr(switch_module, "is_first_handler", lambda _msg_id: True)

    def _fake_apply_switch(group_key: str, feature: str, enabled: bool) -> bool:
        captured["group_key"] = group_key
        captured["feature"] = feature
        captured["enabled"] = enabled
        return True

    async def _fake_send_text_reply(_matcher, _event, _text: str, **_kwargs):
        return None

    monkeypatch.setattr(switch_module, "apply_switch", _fake_apply_switch)
    monkeypatch.setattr(switch_module, "send_text_reply", _fake_send_text_reply)

    asyncio.run(switch_module._(event, ("开启", "mai")))

    assert captured == {
        "group_key": "onebot_v11:114514",
        "feature": "mai",
        "enabled": True,
    }
