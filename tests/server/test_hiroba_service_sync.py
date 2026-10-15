from __future__ import annotations

import pytest

from taiko_bot.runtime.player.center.hiroba.client import HirobaError, HirobaProfilePrivateError
from taiko_bot.runtime.player.center.hiroba.parser import HirobaProfile
from taiko_bot.runtime.player.center.hiroba.sync import (
    sync_bound_hiroba_userdata,
    sync_public_hiroba_userdata,
)


def test_sync_bound_hiroba_userdata_prefers_credentials_when_available(monkeypatch):
    calls: list[tuple[str, str]] = []

    def fake_public_sync(taiko_no: str, **_kwargs):
        calls.append(("public", taiko_no))
        return taiko_no

    def fake_private_sync(*_args, **kwargs):
        calls.append(("private", str(kwargs["taiko_no"])))
        return str(kwargs["taiko_no"])

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.sync_public_hiroba_userdata",
        fake_public_sync,
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.sync_hiroba_userdata",
        fake_private_sync,
    )

    result = sync_bound_hiroba_userdata("123456789012", email="user@example.com", password="secret")

    assert result == "123456789012"
    assert calls == [("private", "123456789012")]


def test_sync_bound_hiroba_userdata_raises_private_profile_without_credentials(
    monkeypatch,
):
    def fake_public_sync(_taiko_no: str, **_kwargs):
        raise HirobaProfilePrivateError("private")

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.sync_public_hiroba_userdata",
        fake_public_sync,
    )

    with pytest.raises(HirobaError) as excinfo:
        sync_bound_hiroba_userdata("123456789012")

    assert "非公开资料" in str(excinfo.value)
    assert "绑定hiroba 邮箱 密码 123456789012" in str(excinfo.value)


def test_sync_public_hiroba_userdata_releases_cooldown_on_failure(monkeypatch):
    released: list[str] = []

    class _FakeClient:
        timeout = 30
        token = "service-token"

        def fetch_public_profile(self, _taiko_no: str) -> str:
            return "<html></html>"

        def fetch_public_score_list(self, _taiko_no: str, _genre: int) -> str:
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.peek_hiroba_sync_cooldown",
        lambda _taiko_no: None,
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.acquire_hiroba_sync_slot",
        lambda _taiko_no: None,
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.release_hiroba_sync_slot",
        lambda taiko_no: released.append(str(taiko_no)),
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.login_hiroba_service_client",
        lambda timeout=30: _FakeClient(),
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.parse_profile",
        lambda _html: HirobaProfile(
            taiko_no="123456789012",
            nickname="tester",
            title="title",
            region="JP",
        ),
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.hiroba.sync.parse_mypage_achievement",
        lambda _html: {},
    )

    with pytest.raises(RuntimeError):
        sync_public_hiroba_userdata("123456789012")

    assert released == ["123456789012"]
