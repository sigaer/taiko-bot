from __future__ import annotations

import asyncio
import sqlite3

from feature_handler.bot_group_whitelist import should_block_group_event
import feature_handler.bot_group_whitelist as whitelist_module
from feature_handler.feature_handler import (
    _migrate_misclassified_qq_group_keys,
    resolve_feature_group_key,
    resolve_message_claim_key,
)


class _FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(
        self,
        *,
        group_openid: str,
        group_id: str = "",
        self_id: str = "",
        event_id: str = "event-1",
    ):
        self.group_openid = group_openid
        self.group_id = group_id
        self.self_id = self_id
        self.id = event_id


class _FakeOneBotGroupEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, *, group_id: int, message_id: int):
        self.group_id = group_id
        self.message_id = message_id


def test_resolve_feature_group_key_uses_group_openid_for_official_group():
    event = _FakeQQGroupEvent(
        group_openid="group_openid_1",
        group_id="group_openid_1",
    )

    assert resolve_feature_group_key(event) == "qq_official:group_openid_1"


def test_resolve_message_claim_key_includes_platform():
    qq_event = _FakeQQGroupEvent(group_openid="group_openid_1", event_id="evt-1")
    onebot_event = _FakeOneBotGroupEvent(group_id=114514, message_id=123)

    assert resolve_message_claim_key(qq_event) == "qq_official:evt-1"
    assert resolve_message_claim_key(onebot_event) == "onebot_v11:123"


def test_should_block_group_event_uses_group_openid_when_present(monkeypatch):
    event = _FakeQQGroupEvent(group_openid="group_openid_1", group_id="", self_id="")
    captured: dict[str, str] = {}

    monkeypatch.setattr(whitelist_module, "is_restricted_bot", lambda _bot_id: True)

    def _fake_is_group_allowed(bot_id: str, group_id: str) -> bool:
        captured["bot_id"] = str(bot_id)
        captured["group_id"] = str(group_id)
        return False

    monkeypatch.setattr(whitelist_module, "is_group_allowed", _fake_is_group_allowed)

    assert asyncio.run(should_block_group_event(event)) is True
    assert captured == {"bot_id": "", "group_id": "group_openid_1"}


def test_migrate_misclassified_qq_group_keys_keeps_newest_state():
    conn = sqlite3.connect(":memory:")
    conn.execute(
        """
        CREATE TABLE feature_switch (
          group_id TEXT NOT NULL,
          feature TEXT NOT NULL,
          enabled INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY(group_id, feature)
        )
        """
    )
    openid = "A7FA774914C540A30AB1588D1E5B96AA"
    conn.executemany(
        "INSERT INTO feature_switch VALUES (?, ?, ?, ?)",
        [
            (f"onebot_v11:{openid}", "taiko", 0, 20),
            (f"qq_official:{openid}", "taiko", 1, 10),
            (f"onebot_v11:{openid}", "pjsk", 1, 5),
            ("onebot_v11:114514", "mai", 0, 30),
        ],
    )

    assert _migrate_misclassified_qq_group_keys(conn) == 2
    assert conn.execute(
        "SELECT group_id, feature, enabled, updated_at FROM feature_switch ORDER BY feature"
    ).fetchall() == [
        ("onebot_v11:114514", "mai", 0, 30),
        (f"qq_official:{openid}", "pjsk", 1, 5),
        (f"qq_official:{openid}", "taiko", 0, 20),
    ]
    conn.close()
