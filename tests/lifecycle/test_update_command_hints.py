from __future__ import annotations

import importlib

import nonebot


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


def test_build_update_command_hint_for_hiroba_account(monkeypatch):
    taiko = _load_taiko_module()
    entry = {
        "ids": ["519635636897", "12345678"],
        "current_index": 0,
        "current_slot": 1,
        "sources": {"519635636897": "hiroba", "12345678": "wahlap"},
    }

    monkeypatch.setattr(taiko, "_get_current_bind_entry", lambda _identity_key: entry)

    text = taiko._build_update_command_hint(
        "onebot_v11:21219135", expected_source="wahlap"
    )

    assert "当前正在使用 u1：519635636897（JP）。" in text
    assert "这不是 CN 服账号，请改用“更新hiroba”。" in text
    assert "当前绑定：u0:合并账户(只读) / u1:519635636897(JP)（当前） / u2:12345678(CN)" in text
    assert "如需切换其他账号，请先发送 u0 / u1 / u2。" in text


def test_build_update_command_hint_for_wahlap_account(monkeypatch):
    taiko = _load_taiko_module()
    entry = {
        "ids": ["99887766"],
        "current_index": 0,
        "current_slot": 1,
        "sources": {"99887766": "wahlap"},
    }

    monkeypatch.setattr(taiko, "_get_current_bind_entry", lambda _identity_key: entry)

    text = taiko._build_update_command_hint(
        "onebot_v11:9988", expected_source="hiroba"
    )

    assert text == (
        "当前正在使用 u1：99887766（CN）。\n"
        "这不是 JP 服账号，请改用“taikoupdate”。\n"
        "当前绑定：u1:99887766(CN)（当前）"
    )


def test_build_update_command_hint_for_u0_readonly(monkeypatch):
    taiko = _load_taiko_module()
    entry = {
        "ids": ["99887766", "11223344"],
        "current_index": 1,
        "current_slot": 0,
        "sources": {"99887766": "wahlap", "11223344": "wahlap"},
    }

    monkeypatch.setattr(taiko, "_get_current_bind_entry", lambda _identity_key: entry)

    text = taiko._build_update_command_hint(
        "onebot_v11:9988", expected_source="hiroba"
    )

    assert "当前正在使用 u0：合并账户（只读）。" in text
    assert "更新命令 仅支持真实绑定账号" in text
    assert "当前展示资料来源：u2：11223344" in text
