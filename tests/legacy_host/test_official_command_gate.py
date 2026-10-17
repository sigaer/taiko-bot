from __future__ import annotations

import importlib
from runtime_owner import load_community_owner

import nonebot

from test_taiko_runtime import FakeQQGroupEvent, FakeSegment


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    return load_community_owner()


def test_public_score_token_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-1",
        segments=[FakeSegment("text", {"text": "网页成绩token"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is False


def test_developer_userdata_still_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-2",
        segments=[FakeSegment("text", {"text": "开发者数据 abc 123"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is True


def test_draw_guess_commands_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-3",
        segments=[FakeSegment("text", {"text": "猜太鼓歌名"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is False


def test_tsearch_switch_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-4",
        segments=[FakeSegment("text", {"text": "关闭太鼓搜歌功能"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is False


def test_generic_feature_switch_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-5",
        segments=[FakeSegment("text", {"text": "关闭taiko功能"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is False
