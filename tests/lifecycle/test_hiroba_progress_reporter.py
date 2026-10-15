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


class _FakeLoop:
    def create_future(self):
        return asyncio.Future()


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "group-openid"

    def get_user_id(self):
        return "group-user"


class _FakeQQPrivateEvent:
    __module__ = "nonebot.adapters.qq.event"

    def get_user_id(self):
        return "private-user"


def test_hiroba_progress_reporter_reduces_official_group_updates(monkeypatch):
    taiko = _load_taiko_module()
    sent: list[str] = []

    async def fake_send(_matcher, _event, text: str):
        sent.append(text)

    monkeypatch.setattr(taiko, "_send_text_reply_without_finish", fake_send)
    monkeypatch.setattr(taiko.asyncio, "get_running_loop", lambda: _FakeLoop())

    class _DoneFuture:
        def __init__(self):
            self._callbacks = []

        def done(self):
            return True

        def result(self):
            return None

        def add_done_callback(self, callback):
            self._callbacks.append(callback)
            callback(self)

    monkeypatch.setattr(
        taiko.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, _loop: (_drain(coro), _DoneFuture())[1],
    )

    reporter = taiko._create_hiroba_progress_reporter(object(), _FakeQQGroupEvent(), min_interval=0.0)
    reporter("已识别 1419 张游玩记录谱面，谱面较多，完整同步通常需要 5-7 分钟", force=True)
    reporter("正在拉取谱面详情 354/1419（鬼/里）...", force=True)
    reporter("正在拉取谱面详情 709/1419（鬼/里）...", force=True)
    reporter("正在拉取谱面详情 1064/1419（鬼/里）...", force=True)
    reporter("同步完成", force=True)

    assert sent == [
        "已识别 1419 张游玩记录谱面，谱面较多，完整同步通常需要 5-7 分钟",
        "正在拉取谱面详情 709/1419（鬼/里）...",
    ]


def test_hiroba_progress_reporter_keeps_all_updates_for_official_private(monkeypatch):
    taiko = _load_taiko_module()
    sent: list[str] = []

    async def fake_send(_matcher, _event, text: str):
        sent.append(text)

    monkeypatch.setattr(taiko, "_send_text_reply_without_finish", fake_send)
    monkeypatch.setattr(taiko.asyncio, "get_running_loop", lambda: _FakeLoop())

    class _DoneFuture:
        def done(self):
            return True

        def result(self):
            return None

        def add_done_callback(self, callback):
            callback(self)

    monkeypatch.setattr(
        taiko.asyncio,
        "run_coroutine_threadsafe",
        lambda coro, _loop: (_drain(coro), _DoneFuture())[1],
    )

    reporter = taiko._create_hiroba_progress_reporter(
        object(), _FakeQQPrivateEvent(), min_interval=0.0
    )
    reporter("已识别 1419 张游玩记录谱面，谱面较多，完整同步通常需要 5-7 分钟", force=True)
    reporter("正在拉取谱面详情 354/1419（鬼/里）...", force=True)
    reporter("正在拉取谱面详情 709/1419（鬼/里）...", force=True)
    reporter("正在拉取谱面详情 1064/1419（鬼/里）...", force=True)

    assert sent == [
        "已识别 1419 张游玩记录谱面，谱面较多，完整同步通常需要 5-7 分钟",
        "正在拉取谱面详情 354/1419（鬼/里）...",
        "正在拉取谱面详情 709/1419（鬼/里）...",
        "正在拉取谱面详情 1064/1419（鬼/里）...",
    ]


def _drain(coro):
    asyncio.run(coro)
