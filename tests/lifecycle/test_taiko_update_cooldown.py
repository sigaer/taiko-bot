from __future__ import annotations

from taiko_bot.runtime.player.center import taiko_update_cooldown as cooldown


def test_taiko_update_cooldown_is_scoped_by_id(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(cooldown.time, "monotonic", lambda: now)
    cooldown._last_triggered_at.clear()

    assert cooldown.try_acquire_taiko_update_slot("12345") is True
    assert cooldown.try_acquire_taiko_update_slot("12345") is False
    assert cooldown.try_acquire_taiko_update_slot("67890") is True


def test_taiko_update_cooldown_expires_after_three_minutes(monkeypatch):
    now = 1000.0
    monkeypatch.setattr(cooldown.time, "monotonic", lambda: now)
    cooldown._last_triggered_at.clear()

    assert cooldown.try_acquire_taiko_update_slot("12345") is True
    now += 179
    assert cooldown.try_acquire_taiko_update_slot("12345") is False
    now += 1
    assert cooldown.try_acquire_taiko_update_slot("12345") is True
