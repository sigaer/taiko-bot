from __future__ import annotations

import asyncio
import importlib
import nonebot
import pytest
from nonebot.exception import FinishedException


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    nonebot.require("taiko_bot.runtime.community.community_entry")
    return importlib.import_module("taiko_bot.runtime.community.center.draw_guess")


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "group-openid"


def test_finish_with_image_fallback_reraises_finished_exception(monkeypatch):
    taiko = _load_taiko_module()
    fallback_called = False

    async def fake_finish_image_reply(*args, **kwargs):
        raise FinishedException()

    async def fake_finish_text_reply(*args, **kwargs):
        nonlocal fallback_called
        fallback_called = True

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko._finish_with_image_fallback(
                matcher=object(),
                event=object(),
                text="test",
                image=b"",
            )
        )

    assert fallback_called is False


def test_finish_with_image_fallback_still_uses_text_fallback(monkeypatch):
    taiko = _load_taiko_module()
    fallback_messages: list[str] = []

    async def fake_finish_image_reply(*args, **kwargs):
        raise RuntimeError("send failed")

    async def fake_finish_text_reply(_matcher, _event, text: str):
        fallback_messages.append(text)

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    asyncio.run(
        taiko._finish_with_image_fallback(
            matcher=object(),
            event=object(),
            text="test",
            image=b"",
            fallback_note="fallback",
        )
    )

    assert fallback_messages == ["test\nfallback"]


def test_finish_with_image_fallback_prefers_markdown_for_qq_official(monkeypatch):
    taiko = _load_taiko_module()
    captured_kwargs = []

    async def fake_finish_image_reply(*args, **kwargs):
        captured_kwargs.append(kwargs)
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko._finish_with_image_fallback(
                matcher=object(),
                event=_FakeQQGroupEvent(),
                text="test",
                image=b"",
            )
        )

    assert captured_kwargs == [
        {
            "prefix_text": "test",
            "prefer_markdown_image": True,
            "markdown_image_name": "fumen",
        }
    ]


def test_finish_with_image_fallback_can_disable_markdown_for_qq_official(monkeypatch):
    taiko = _load_taiko_module()
    captured_kwargs = []

    async def fake_finish_image_reply(*args, **kwargs):
        captured_kwargs.append(kwargs)
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko._finish_with_image_fallback(
                matcher=object(),
                event=_FakeQQGroupEvent(),
                text="test",
                image=b"",
                prefer_markdown_image=False,
            )
        )

    assert captured_kwargs == [
        {
            "prefix_text": "test",
            "prefer_markdown_image": False,
            "markdown_image_name": "fumen",
        }
    ]


def _owned_fumen(monkeypatch, tmp_path, song_id):
    from taiko_bot.runtime.public import delivery
    from types import SimpleNamespace
    path = tmp_path / "assets/fumens/Oni" / f"{song_id}.png"
    path.parent.mkdir(parents=True);path.write_bytes(b"synthetic-png")
    monkeypatch.setattr(delivery, "root", lambda: tmp_path)
    monkeypatch.setattr(delivery.provider, "asset_ready", lambda: (True, ""))
    return delivery, SimpleNamespace(kind="fumen", payload=("Oni", str(song_id)))


def test_send_fumen_or_hint_disables_markdown_for_qq_official(monkeypatch, tmp_path):
    delivery, result = _owned_fumen(monkeypatch, tmp_path, 856)
    captured=[]
    async def reply(matcher,event,text,image=None):
        captured.append(image.getvalue());raise FinishedException
    monkeypatch.setattr(delivery, "reply", reply)
    monkeypatch.setattr(delivery.provider, "brief", lambda sid: "")
    with pytest.raises(FinishedException):
        asyncio.run(delivery.deliver(object(),_FakeQQGroupEvent(),result))
    assert captured == [b"synthetic-png"]


def test_send_fumen_or_hint_includes_song_title_and_bpm(monkeypatch, tmp_path):
    delivery, result = _owned_fumen(monkeypatch, tmp_path, 191)
    captured=[]
    monkeypatch.setattr(delivery.provider, "brief", lambda sid: "【魔王】\n分类：南梦宫原创音乐\nBPM：185")
    async def reply(matcher,event,text,image=None):
        captured.append(text);raise FinishedException
    monkeypatch.setattr(delivery, "reply", reply)
    with pytest.raises(FinishedException):
        asyncio.run(delivery.deliver(object(),object(),result))
    assert captured == ["你要找的是不是：\n魔王 id191\n【魔王】\n分类：南梦宫原创音乐\nBPM：185"]


def test_format_song_brief_line_splits_bpm_and_includes_category(monkeypatch, tmp_path):
    from taiko_bot.runtime.public import provider
    import json
    (tmp_path/'songs').mkdir()
    (tmp_path/'songs/song_data.json').write_text(json.dumps([{'id':191,'song_name_jp':'魔王','type':'南梦宫原创音乐','bpm':'185'}]))
    monkeypatch.setattr(provider,'root',lambda:tmp_path)
    assert provider.brief('191') == '【魔王】\n分类：南梦宫原创音乐\nBPM：185'


def test_fuzzy_query_acceptance_uses_shared_threshold():
    taiko = _load_taiko_module()

    assert taiko._is_accepted_fuzzy_query_result([[191, "魔王", 88]])
    assert taiko._is_accepted_fuzzy_query_result([[191, "魔王", 0.75]])
    assert not taiko._is_rejected_fuzzy_query_result([[191, "魔王", 75]])
    assert taiko._is_rejected_fuzzy_query_result([[191, "魔王", 74]])
    assert not taiko._is_accepted_fuzzy_query_result([[191, "魔王"]])


@pytest.mark.parametrize(
    ("similarity", "expected_ids", "expected_hint"),
    [
        (88, {191}, None),
        (74, set(), "你要找的可能是：魔王\n匹配度：0.74"),
    ],
)
def test_draw_guess_uses_shared_fuzzy_threshold(
    monkeypatch, similarity, expected_ids, expected_hint
):
    taiko = _load_taiko_module()
    monkeypatch.setattr(
        taiko,
        "queryMusic",
        lambda _text: [[191, "魔王", similarity]],
    )

    guessed_ids, guessed_title, hint = taiko._resolve_guess_with_query_music_detail(
        "魔汪"
    )

    assert guessed_ids == expected_ids
    assert guessed_title == "魔王"
    assert hint == expected_hint
