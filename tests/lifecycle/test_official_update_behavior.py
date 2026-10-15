from __future__ import annotations

import asyncio
import importlib

import nonebot

from tests.test_taiko_runtime import FakeQQGroupEvent, FakeSegment


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


def test_parse_update_command_accepts_embedded_keyword():
    taiko = _load_taiko_module()

    assert taiko._parse_update_command("@某人 更新广场") == {"show_all": False}
    assert taiko._parse_update_command("请帮我 taikoupdate all 谢谢") == {
        "show_all": True
    }




def test_update_handle_ignores_mentioned_user_for_official_group(monkeypatch):
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-2",
        segments=[
            FakeSegment("mention_user", {"user_id": "member_openid_other"}),
            FakeSegment("text", {"text": "更新广场"}),
        ],
    )
    captured: dict[str, str] = {}
    replies: list[str] = []

    monkeypatch.setattr(
        taiko, "get_identity_key", lambda **_kwargs: "qq_official:member_openid_self"
    )
    monkeypatch.setattr(
        taiko,
        "resolve_target_identity_key",
        lambda **_kwargs: "qq_official:member_openid_other",
    )

    def current(identity_key):
        captured['identity_key']=identity_key
        return {'ids':['12345'],'current_index':0,'current_slot':1,'sources':{'12345':'wahlap'}}
    monkeypatch.setattr(
        taiko,
        "_get_current_bind_entry",
        current,
    )
    monkeypatch.setattr(taiko, "_get_selected_bind_slot_number", lambda _entry: 1)
    monkeypatch.setattr(taiko,"_get_current_bind_taiko_id",lambda _entry:'12345')
    monkeypatch.setattr(taiko, "_infer_bind_source", lambda *_args, **_kwargs: "wahlap")
    monkeypatch.setattr(taiko, "try_acquire_taiko_update_slot", lambda _taiko_id: True)
    monkeypatch.setattr(
        taiko,
        "_execute_taiko_update",
        lambda *_args, **_kwargs: {"ok": True, "message": "更新成功！", "image": None},
    )

    async def _fake_finish_text_reply(_matcher, _event, text: str, **_kwargs):
        replies.append(text)

    monkeypatch.setattr(taiko, "_finish_text_reply", _fake_finish_text_reply)

    asyncio.run(taiko.update_handle(event))

    assert captured["identity_key"] == "qq_official:member_openid_self"
    assert replies[-1].startswith("更新成功！")


def test_update_handle_stays_silent_and_skips_fetch_during_id_cooldown(monkeypatch):
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-cooldown",
        segments=[FakeSegment("text", {"text": "taikoupdate"})],
    )
    replies: list[str] = []
    executed = False

    monkeypatch.setattr(
        taiko, "get_identity_key", lambda **_kwargs: "qq_official:member_openid_self"
    )
    monkeypatch.setattr(
        taiko, "_get_taiko_bind_info", lambda _identity: {"id": "12345", "visible": 0}
    )
    monkeypatch.setattr(
        taiko,
        "_get_current_bind_entry",
        lambda _identity: {
            "ids": ["12345"],
            "current_index": 0,
            "current_slot": 1,
            "sources": {"12345": "wahlap"},
        },
    )
    monkeypatch.setattr(taiko, "_get_selected_bind_slot_number", lambda _entry: 1)
    monkeypatch.setattr(taiko,"_get_current_bind_taiko_id",lambda _entry:'12345')
    monkeypatch.setattr(taiko, "_infer_bind_source", lambda *_args, **_kwargs: "wahlap")
    monkeypatch.setattr(taiko, "try_acquire_taiko_update_slot", lambda _taiko_id: False)

    def _fake_execute(*_args, **_kwargs):
        nonlocal executed
        executed = True
        return {"ok": True, "message": "更新成功！", "image": None}

    async def _fake_finish_text_reply(_matcher, _event, text: str, **_kwargs):
        replies.append(text)

    monkeypatch.setattr(taiko, "_execute_taiko_update", _fake_execute)
    monkeypatch.setattr(taiko, "_finish_text_reply", _fake_finish_text_reply)

    asyncio.run(taiko.update_handle(event))

    assert executed is False
    assert replies == []
