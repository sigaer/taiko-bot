"""Local bearer revocation across a center read, using an owned SQLite DB."""
from dataclasses import replace
from pathlib import Path

import httpx
import pytest

from taiko_bot import sqlite_db, userdata_provider as provider
from plugins.utils import public_score_token as tokens
from test_private_read_cache import cfg, transport


@pytest.fixture
def issued(cfg, monkeypatch):
    monkeypatch.setattr(sqlite_db, "get_settings", lambda: cfg)
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    sqlite_db.ensure_schema()
    with sqlite_db.connect_sqlite() as connection:
        locations = connection.execute("PRAGMA database_list").fetchall()
        assert Path(locations[0][2]).resolve() == cfg.sqlite_path.resolve()
        connection.execute("INSERT INTO bind(qq,id) VALUES ('onebot_v11:100','1001')")
    return tokens.issue_public_score_token_for_taiko_id("1001")["token"]


def test_public_token_returns_one_fresh_authorized_response_without_disk_fallback(issued, cfg, monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "unknown": [1]}))
    result = tokens.fetch_latest_userdata_by_token(issued)
    assert result["taikoId"] == "1001" and result["data"] == {"songs": [], "unknown": [1]}
    assert len(calls) == 1 and "if-none-match" not in calls[0].headers
    assert not cfg.userdata_dir.exists()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 503])
def test_public_token_center_denial_keeps_status_and_cannot_use_previous_success(issued, cfg, monkeypatch, status):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "private": 1}))
    tokens.fetch_latest_userdata_by_token(issued)
    calls = transport(monkeypatch, lambda request: httpx.Response(status, text="/private/password"))
    with pytest.raises(tokens.PublicScoreTokenError) as error:
        tokens.fetch_latest_userdata_by_token(issued)
    assert error.value.status_code == status and "password" not in str(error.value)
    assert len(calls) == 1 and not cfg.userdata_dir.exists()


@pytest.mark.parametrize("change", ["delete", "rotate", "move"])
def test_local_token_changed_during_center_read_cannot_return_private_payload(issued, monkeypatch, change):
    def answer(request):
        with sqlite_db.connect_sqlite() as connection:
            if change == "delete": connection.execute("DELETE FROM public_score_tokens")
            elif change == "rotate": connection.execute("UPDATE public_score_tokens SET token_hash='rotated'")
            else: connection.execute("UPDATE public_score_tokens SET taiko_id='1002'")
        return httpx.Response(200, json={"songs": [], "private": 1})
    calls = transport(monkeypatch, answer)
    with pytest.raises(tokens.PublicScoreTokenError) as error:
        tokens.fetch_latest_userdata_by_token(issued)
    assert error.value.status_code == 401 and len(calls) == 1


def test_invalid_local_token_never_reaches_center(issued, monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": []}))
    with pytest.raises(tokens.PublicScoreTokenError) as error:
        tokens.fetch_latest_userdata_by_token("invalid")
    assert error.value.status_code == 401 and calls == []
