from __future__ import annotations

import json
from datetime import datetime, timedelta

from taiko_bot.runtime.player.center.hiroba import cooldown


def test_hiroba_cooldown_blocks_for_one_hour(tmp_path, monkeypatch):
    cooldown_path = tmp_path / "hiroba_sync_cooldown.json"
    monkeypatch.setattr(cooldown, "HIROBA_SYNC_COOLDOWN_PATH", cooldown_path)

    assert cooldown.acquire_hiroba_sync_slot("123456789012") is None

    message = cooldown.peek_hiroba_sync_cooldown("123456789012")
    assert message is not None
    assert "每账号每小时限 1 次" in message
    assert "每日 0 点" not in message

    stored = json.loads(cooldown_path.read_text(encoding="utf-8"))
    assert isinstance(stored["123456789012"], int)


def test_hiroba_cooldown_allows_after_one_hour(tmp_path, monkeypatch):
    cooldown_path = tmp_path / "hiroba_sync_cooldown.json"
    cooldown_path.write_text(
        json.dumps(
            {"123456789012": int((datetime.now() - timedelta(hours=1, seconds=1)).timestamp())}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(cooldown, "HIROBA_SYNC_COOLDOWN_PATH", cooldown_path)

    assert cooldown.peek_hiroba_sync_cooldown("123456789012") is None
    assert cooldown.acquire_hiroba_sync_slot("123456789012") is None


def test_hiroba_cooldown_reads_legacy_day_marker(tmp_path, monkeypatch):
    cooldown_path = tmp_path / "hiroba_sync_cooldown.json"
    legacy_day = (datetime.now() - timedelta(days=1)).date().isoformat()
    cooldown_path.write_text(
        json.dumps({"123456789012": legacy_day}),
        encoding="utf-8",
    )
    monkeypatch.setattr(cooldown, "HIROBA_SYNC_COOLDOWN_PATH", cooldown_path)

    assert cooldown.peek_hiroba_sync_cooldown("123456789012") is None
    assert cooldown.acquire_hiroba_sync_slot("123456789012") is None
