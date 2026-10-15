from __future__ import annotations

import base64
import importlib

import nonebot
import pytest

from taiko_bot.runtime.player.center.game_login_qr import GameLoginQrError, decode_game_login_qr
from tests.test_taiko_runtime import FakeOneBotPrivateEvent, FakeQQGroupEvent, FakeSegment


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"test-image"


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    from lifecycle_test_host import host
    return host()


def test_decode_game_login_qr_returns_png_bytes():
    payload = {
        "status": 0,
        "message": "request succeed",
        "data": {"qrContent": base64.b64encode(PNG_BYTES).decode("ascii")},
    }

    assert decode_game_login_qr(payload) == PNG_BYTES


@pytest.mark.parametrize(
    "payload",
    [
        {"status": 1, "message": "request failed", "data": {}},
        {"status": 0, "message": "request succeed", "data": {}},
        {"status": 0, "message": "request succeed", "data": {"qrContent": "bad"}},
    ],
)
def test_decode_game_login_qr_rejects_invalid_payload(payload):
    with pytest.raises(GameLoginQrError):
        decode_game_login_qr(payload)


def test_game_login_qr_permission_allows_configured_openid():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="204E3C57BC20A36DF2079772ECA08A7A",
        group_openid="group_openid_1",
        event_id="evt-game-login-qr",
        segments=[FakeSegment("text", {"text": "码来"})],
    )

    assert taiko._game_login_qr_command_rule(event) is True
    assert taiko._can_request_game_login_qr(event) is True


def test_game_login_qr_permission_allows_configured_qq():
    taiko = _load_taiko_module()
    event = FakeOneBotPrivateEvent(
        user_id="1106865024",
        message_id="1001",
        segments=[FakeSegment("text", {"text": "码来"})],
    )

    assert taiko._game_login_qr_command_rule(event) is True
    assert taiko._can_request_game_login_qr(event) is True


def test_game_login_qr_permission_rejects_other_user():
    taiko = _load_taiko_module()
    event = FakeOneBotPrivateEvent(
        user_id="123456789",
        message_id="1002",
        segments=[FakeSegment("text", {"text": "码来"})],
    )

    assert taiko._can_request_game_login_qr(event) is False
