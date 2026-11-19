"""Hiroba emits start, success and image replies without intermediate progress."""
import ast
import asyncio
import importlib
import logging
from pathlib import Path
import re
import time
from types import SimpleNamespace

from nonebot.exception import FinishedException, MatcherException
import pytest


SOURCE = Path(importlib.import_module("taiko_bot").__file__).parent / "runtime/player"


def handler(profile, name, values, filename="identity_cluster.py"):
    tree = ast.parse((SOURCE / profile / filename).read_text())
    node = next(node for node in tree.body if getattr(node, "name", None) == name)
    node.decorator_list = []
    module = ast.Module(body=[ast.ImportFrom(
        module="__future__", names=[ast.alias(name="annotations")], level=0
    ), node], type_ignores=[])
    values.update(asyncio=asyncio, re=re, RegexMatched=lambda: None,
                  __package__=f"taiko_bot.runtime.player.{profile}")
    exec(compile(ast.fix_missing_locations(module), "<actual-hiroba-command>", "exec"), values)
    return values[name]


class PrivateEvent:
    __module__ = "nonebot.adapters.qq.event"
    id = "synthetic-incoming-message"

    def get_user_id(self):
        return "synthetic-user"


class GroupEvent(PrivateEvent):
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "synthetic-group"


class PassiveMatcher:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        if len(self.sent) >= 5:
            raise RuntimeError("40034128 被动回复时间或者次数超过限制")
        self.sent.append(message)

    async def finish(self):
        raise FinishedException()


@pytest.mark.parametrize("profile", ["center", "client"])
@pytest.mark.parametrize("event_type", [PrivateEvent, GroupEvent])
@pytest.mark.parametrize("result", ["image", "text", "failure"])
@pytest.mark.parametrize("show_all", [False, True])
def test_update_sends_start_success_and_image_without_progress(profile, event_type, result, show_all, monkeypatch):
    messages = importlib.import_module(f"taiko_bot.runtime.player.{profile}.messages")
    monkeypatch.setattr(messages, "cache_markdown_image_url", lambda *a, **k: "https://fixture.invalid/update.png")
    matcher = PassiveMatcher()
    event = event_type()
    command = "更新hiroba all" if show_all else "更新hiroba"
    calls = []

    async def send(matcher, event, text):
        await matcher.send(text)

    async def finish_text(matcher, event, text, **kwargs):
        await messages.send_text_reply(matcher, event, text, **kwargs)

    async def finish_image(matcher, event, img_buf, **kwargs):
        await messages.send_image_reply(matcher, event, img_buf, **kwargs)

    finish_success = handler(profile, "_finish_hiroba_update_success_reply", dict(
        _send_text_reply_without_finish=send, _finish_text_reply=finish_text,
        _finish_image_reply=finish_image, time=time, MatcherException=MatcherException,
        FinishedException=FinishedException, logger=logging.getLogger(__name__),
    ), filename="lifecycle_host.py")

    def update(identity, **kwargs):
        assert len(matcher.sent) == 1 and str(matcher.sent[0]).startswith("开始")
        assert kwargs.get("progress") is None
        assert kwargs["include_changes_image"] is True
        assert kwargs["show_all_changes"] is show_all
        calls.append(identity)
        return {"ok": result != "failure", "message": "同步失败" if result == "failure" else "Hiroba 更新成功！",
                "image": b"synthetic-image" if result == "image" else None}

    values = dict(
        hiroba_update=matcher, extract_plain_text=lambda _: command,
        _normalize_identity_key=lambda value: value, get_identity_key=lambda **_: "qq_official:synthetic",
        _resolve_requested_identity_key=lambda _: ("qq_official:synthetic", None),
        _get_taiko_bind_info_from_center=lambda _: {"currentSource": "hiroba"},
        _resolve_bound_taiko_id=lambda _: "123456789012",
        _get_current_bind_entry=lambda _: {}, _get_selected_bind_slot_number=lambda _: 1,
        _get_current_bind_taiko_id=lambda _: "123456789012", _infer_bind_source=lambda *a: "hiroba",
        peek_hiroba_sync_cooldown=lambda _: None,
        _send_text_reply_without_finish=send, _finish_text_reply=finish_text,
        _finish_hiroba_update_success_reply=finish_success, _execute_hiroba_update=update,
    )
    with pytest.raises(FinishedException):
        asyncio.run(handler(profile, "hiroba_update_handle", values)(event))
    assert calls == ["123456789012"]
    assert len(matcher.sent) == (3 if result == "image" else 2)
    content = str(matcher.sent[1])
    assert ("Hiroba 更新成功！" in content) is (result != "failure")
    assert ("同步失败" in content) is (result == "failure")
    assert content.count("已展示全部变更。") == int(show_all and result != "failure")
    content = str(matcher.sent[-1])
    assert ("update.png" in content) is (result == "image")
    if result == "image":
        assert "Hiroba 更新结果" in content


@pytest.mark.parametrize("profile", ["center", "client"])
@pytest.mark.parametrize("failed", [False, True])
def test_bind_only_sends_start_and_final_reply(profile, failed):
    replies = []
    calls = []

    async def send(matcher, event, text):
        replies.append(text)

    async def finish(matcher, event, text, **kwargs):
        replies.append(text)

    def bind(*args, **kwargs):
        assert replies == ["开始绑定 Hiroba 账号"]
        assert kwargs.get("progress") is None and len(args) <= 4
        calls.append(True)
        if failed:
            raise RuntimeError("synthetic failure")
        if profile == "client":
            return {"taikoIds": ["123456789012"], "bind": {}}
        return SimpleNamespace(taiko_ids=("123456789012",), entry={"current_index": 0}), 1

    values = dict(
        bind_hiroba=object(), _normalize_identity_key=lambda value: value,
        get_identity_key=lambda **_: "qq_official:synthetic", _execute_hiroba_bind=bind,
        bind_hiroba_credentials=bind, _send_text_reply_without_finish=send,
        _finish_text_reply=finish, _format_bind_entry_summary_safe=lambda _: "u1",
        _get_taiko_bind_info_from_center=lambda _: {},
        _get_current_bind_entry=lambda _: {},
        _center_bind_info_to_entry=lambda _: {"current_index": 0},
        _format_multi_bind_summary=lambda _: "u1",
    )
    match = SimpleNamespace(group=lambda i: {1: "synthetic@example.test", 2: "synthetic", 3: ""}[i])
    asyncio.run(handler(profile, "bind_hiroba_handle", values)(PrivateEvent(), match=match))
    assert calls == [True]
    assert len(replies) == 2
    assert ("失败" in replies[1] or "暂无法确认" in replies[1]) is failed
