from __future__ import annotations

import asyncio
import importlib

import nonebot


class _FakeQQOfficialEvent:
    __module__ = "nonebot.adapters.qq.event"

    def get_user_id(self):
        return "user-openid"


class _FakeMatch:
    string = "绑定 你的鼓众广场id"


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


def test_bind_id_classification_ranges():
    taiko = _load_taiko_module()

    assert taiko._is_wahlap_taiko_id("12345") is True
    assert taiko._is_wahlap_taiko_id("12345678") is True
    assert taiko._is_wahlap_taiko_id("12345678901") is True
    assert taiko._is_wahlap_taiko_id("1234") is False
    assert taiko._is_wahlap_taiko_id("123456789012") is False

    assert taiko._is_hiroba_taiko_no("123456789012") is True
    assert taiko._is_hiroba_taiko_no("12345678901") is False


def test_infer_bind_source_prefers_12_digit_hiroba(monkeypatch):
    taiko = _load_taiko_module()

    monkeypatch.setattr(taiko, "has_hiroba_credentials", lambda identity: False)
    assert taiko._infer_bind_source("862074224984", {}) == "hiroba"
    assert taiko._infer_bind_source("12345678901", {}) == "wahlap"


def test_extract_bind_input_accepts_prefilled_placeholder_text():
    taiko = _load_taiko_module()

    assert taiko._extract_bind_input("绑定 你的鼓众广场id 123456") == "123456"
    assert taiko._extract_bind_input("绑定 你的鼓众广场ID123456") == "123456"


def test_detect_prefilled_bind_tutorial_request_only_without_id():
    taiko = _load_taiko_module()

    assert taiko._is_wahlap_bind_tutorial_request("绑定 你的鼓众广场id") is True
    assert taiko._is_wahlap_bind_tutorial_request("/绑定  你的鼓众广场ID") is True
    assert taiko._is_wahlap_bind_tutorial_request("绑定") is False
    assert taiko._is_wahlap_bind_tutorial_request("绑定 你的鼓众广场id 123456") is False


def test_prefilled_bind_tutorial_keeps_markdown_keyboard(monkeypatch):
    taiko = _load_taiko_module()
    calls = []

    async def fake_finish_image_reply(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)

    asyncio.run(taiko.bind_handle(_FakeQQOfficialEvent(), _FakeMatch()))

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args[2] == taiko.WAHLAP_BIND_TUTORIAL_IMAGE_PATH
    assert kwargs["quick_actions"] is True
    assert kwargs["prefer_markdown_image"] is True
    assert kwargs["markdown_image_name"] == "wahlap-bind-tutorial"


def test_extract_bind_qq_input_accepts_prefilled_placeholder_text():
    taiko = _load_taiko_module()

    assert taiko._extract_bind_qq_input("绑定QQ 你的QQ号 12345678") == "12345678"
    assert taiko._extract_bind_qq_input("绑定qq你的qq号12345678") == "12345678"
