import pytest

from taiko_bot.runtime.player.center import public_score_token
from taiko_bot.services.sync_dispatch_server import RequestError, parse_score_token_body


def test_ownerless_viewer_option_cannot_issue_token(monkeypatch):
    monkeypatch.setattr(public_score_token, "get_taiko_db_connection", lambda: pytest.fail("Ownerless request must not connect"))
    with pytest.raises(public_score_token.PublicScoreTokenError) as error:
        public_score_token.issue_public_score_token_for_taiko_id("2258735", require_bot_binding=False)
    assert error.value.status_code == 403


def test_token_status_requires_a_caller_principal(monkeypatch):
    monkeypatch.setattr(public_score_token, "get_taiko_db_connection", lambda: pytest.fail("Ownerless request must not connect"))
    with pytest.raises(public_score_token.PublicScoreTokenError) as error:
        public_score_token.get_public_score_token_status("2258735")
    assert error.value.status_code == 403


def test_revoke_requires_a_caller_principal(monkeypatch):
    monkeypatch.setattr(public_score_token, "get_taiko_db_connection", lambda: pytest.fail("Ownerless request must not connect"))
    with pytest.raises(public_score_token.PublicScoreTokenError) as error:
        public_score_token.revoke_public_score_token_for_taiko_id("2258735")
    assert error.value.status_code == 403


def test_score_token_gateway_body_validation():
    assert parse_score_token_body(b'{"userid":"2258735","action":"issue"}') == (
        "2258735",
        "issue",
    )

    with pytest.raises(RequestError) as error:
        parse_score_token_body(b'{"userid":"2258735","action":"unknown"}')
    assert error.value.code == "invalid_action"
