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


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"
    group_openid = "group-openid"

    def get_user_id(self):
        return "member-openid"


def test_finish_bind_success_reply_prefers_image_when_auto_update_has_result(monkeypatch):
    taiko = _load_taiko_module()
    captured: list[dict] = []

    async def _fake_finish_image_reply(*_args, **kwargs):
        captured.append(kwargs)

    async def _fake_finish_text_reply(*_args, **_kwargs):
        raise AssertionError("text fallback should not be used when image is available")

    monkeypatch.setattr(taiko, "_finish_image_reply", _fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", _fake_finish_text_reply)

    asyncio.run(
        taiko._finish_bind_success_reply(
            matcher=object(),
            event=_FakeQQGroupEvent(),
            base_message="绑定成功！",
            auto_update_result={
                "ok": True,
                "message": "首次绑定已自动执行一次 taikoupdate。",
                "image": b"fake-image",
            },
        )
    )

    assert captured == [
        {
            "prefix_text": "绑定成功！\n首次绑定已自动执行一次 taikoupdate。",
            "quick_actions": True,
            "prefer_markdown_image": True,
            "markdown_image_name": "taikoupdate",
        }
    ]
