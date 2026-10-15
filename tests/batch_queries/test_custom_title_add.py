from __future__ import annotations

import asyncio
import importlib
from types import SimpleNamespace

import nonebot
import pytest
from nonebot.exception import FinishedException


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    return importlib.import_module("taiko_bot.runtime.player.center.management_cluster")


class _FakeMatcher:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def finish(self, message: str):
        self.messages.append(message)
        raise FinishedException()


class _FakeEvent:
    def get_user_id(self) -> str:
        return "12345"


def test_custom_title_add_accepts_high_confidence_fuzzy_song(monkeypatch):
    taiko = _load_taiko_module()
    created: list[dict[str, object]] = []
    matcher = _FakeMatcher()

    monkeypatch.setattr(
        taiko,
        "extract_plain_text",
        lambda _event: "添加称号 测试称号 to 测试歌曲",
    )
    monkeypatch.setattr(
        taiko,
        "queryMusic",
        lambda _query: [[100, "匹配到的歌曲", 88]],
    )
    monkeypatch.setattr(
        taiko,
        "load_song_data",
        lambda: [{"id": 100, "level_4": 8}],
    )
    monkeypatch.setattr(taiko, "_event_group_scope_id", lambda _event: "group-1")
    monkeypatch.setattr(taiko, "_default_group_scope_name", lambda _event: "测试群")
    monkeypatch.setattr(taiko, "_extract_uploader_nickname", lambda _event: "测试玩家")
    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "qq:12345")

    def fake_create_custom_title(**kwargs):
        created.append(kwargs)
        return SimpleNamespace(
            title_name=kwargs["title_name"],
            difficulty_level=kwargs["difficulty_level"],
            achievement_type=kwargs["achievement_type"],
        )

    monkeypatch.setattr(taiko, "create_custom_title", fake_create_custom_title)

    with pytest.raises(FinishedException):
        asyncio.run(taiko.custom_title_add_handle(matcher, _FakeEvent()))

    assert len(created) == 1
    assert created[0]["song_id"] == 100
    assert matcher.messages == [
        "已添加自定义称号：测试称号\n"
        "获得条件：全连《匹配到的歌曲》表谱\n"
        "称号固定显示为金色样式，不会随更高成绩自动升级。"
    ]


def test_custom_title_add_rejects_low_confidence_fuzzy_song(monkeypatch):
    taiko = _load_taiko_module()
    matcher = _FakeMatcher()

    monkeypatch.setattr(
        taiko,
        "extract_plain_text",
        lambda _event: "添加称号 测试称号 to 测试歌曲",
    )
    monkeypatch.setattr(
        taiko,
        "queryMusic",
        lambda _query: [[100, "匹配到的歌曲", 74]],
    )
    monkeypatch.setattr(
        taiko,
        "create_custom_title",
        lambda **_kwargs: pytest.fail("低置信度模糊匹配不应创建称号"),
    )

    with pytest.raises(FinishedException):
        asyncio.run(taiko.custom_title_add_handle(matcher, _FakeEvent()))

    assert matcher.messages == ["你要找的可能是：匹配到的歌曲\n匹配度：0.74"]
