from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from taiko_bot.runtime.center_platform_adapter import (
    ONEBOT_V11_PLATFORM,
    QQ_OFFICIAL_PLATFORM,
    build_group_key,
    build_identity_key,
    extract_plain_text,
    format_identity_for_display,
    get_group_key,
    get_identity_key,
    get_message_claim_key,
    get_mentioned_identity_keys,
    get_onebot_at_targets,
    is_onebot_message_targeting_other_account,
    resolve_target_identity_key,
    send_onebot_forward_messages,
)
from taiko_bot.runtime.center_startup_migration import (
    migrate_feature_switch_db,
    migrate_multi_bind_payload,
    normalize_legacy_group_key,
    normalize_legacy_identity_key,
)


class FakeSegment:
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data

    def is_text(self) -> bool:
        return self.type == "text"


class FakeMessage(list):
    def __init__(self, segments=()):
        if isinstance(segments, str):
            segments = [FakeSegment("text", {"text": segments})]
        super().__init__(segments)

    def extract_plain_text(self) -> str:
        return "".join(seg.data.get("text", "") for seg in self if seg.type == "text")

    def __str__(self) -> str:
        return self.extract_plain_text()


class FakeOneBotGroupEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(
        self,
        user_id: str,
        group_id: str,
        message_id: str,
        segments,
        *,
        self_id: str = "10000",
    ):
        self._user_id = str(user_id)
        self.self_id = int(self_id)
        self.group_id = int(group_id)
        self.message_id = int(message_id)
        self._message = FakeMessage(segments)

    def get_user_id(self) -> str:
        return self._user_id

    def get_message(self):
        return getattr(self, "message", self._message)


class FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(
        self,
        user_id: str,
        group_openid: str,
        event_id: str,
        segments,
        *,
        group_id: str = "",
    ):
        self._user_id = str(user_id)
        self.group_id = str(group_id)
        self.group_openid = str(group_openid)
        self.id = str(event_id)
        self._message = FakeMessage(segments)

    def get_user_id(self) -> str:
        return self._user_id

    def get_message(self):
        return getattr(self, "message", self._message)


class FakeOneBotPrivateEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(self, user_id: str, message_id: str, segments, *, self_id: str = "10000"):
        self._user_id = str(user_id)
        self.self_id = int(self_id)
        self.message_id = int(message_id)
        self._message = FakeMessage(segments)

    def get_user_id(self) -> str:
        return self._user_id

    def get_message(self):
        return getattr(self, "message", self._message)


class FakeMatcher:
    def __init__(self) -> None:
        self.finished = False

    async def finish(self):
        self.finished = True
        return "finished"


class FakeBot:
    def __init__(self) -> None:
        self.calls = []

    async def call_api(self, action: str, **params):
        self.calls.append((action, params))
        return {"action": action, "params": params}


def test_identity_and_group_keys_for_onebot_event():
    event = FakeOneBotGroupEvent(
        user_id="12345",
        group_id="67890",
        message_id="1001",
        segments=[FakeSegment("text", {"text": " taikoupdate "})],
    )

    assert get_identity_key(event=event) == "onebot_v11:12345"
    assert get_group_key(event=event) == "onebot_v11:67890"
    assert get_message_claim_key(event=event) == "onebot_v11:1001"
    assert extract_plain_text(event) == "taikoupdate"


def test_official_group_key_prefers_group_openid_when_group_id_is_blank():
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        group_id="",
        event_id="evt-1",
        segments=[FakeSegment("text", {"text": " taikoupdate "})],
    )

    assert get_group_key(event=event) == "qq_official:group_openid_1"


def test_onebot_at_targets_ignore_self_mentions():
    event = FakeOneBotGroupEvent(
        user_id="12345",
        group_id="67890",
        message_id="1001",
        segments=[
            FakeSegment("at", {"qq": "10000"}),
            FakeSegment("text", {"text": " /更新广场 "}),
        ],
        self_id="10000",
    )

    assert get_onebot_at_targets(event) == ["10000"]
    assert not is_onebot_message_targeting_other_account(event)


def test_onebot_at_targets_detect_other_bot_mentions():
    event = FakeOneBotGroupEvent(
        user_id="12345",
        group_id="67890",
        message_id="1001",
        segments=[
            FakeSegment("at", {"qq": "2854199949"}),
            FakeSegment("text", {"text": " /更新广场 "}),
        ],
        self_id="10000",
    )

    assert get_onebot_at_targets(event) == ["2854199949"]
    assert is_onebot_message_targeting_other_account(event)


def test_send_onebot_forward_messages_for_group_event():
    matcher = FakeMatcher()
    bot = FakeBot()
    event = FakeOneBotGroupEvent(
        user_id="12345",
        group_id="67890",
        message_id="1001",
        segments=[FakeSegment("text", {"text": "鞍山哪有鼓"})],
    )

    result = asyncio.run(
        send_onebot_forward_messages(
            matcher,
            bot,
            event,
            messages=[{"type": "node", "data": {"content": "示例"}}],
        )
    )

    assert result is True
    assert matcher.finished is False
    assert bot.calls == [
        (
            "send_group_forward_msg",
            {
                "group_id": 67890,
                "messages": [{"type": "node", "data": {"content": "示例"}}],
            },
        )
    ]


def test_send_onebot_forward_messages_for_private_event():
    matcher = FakeMatcher()
    bot = FakeBot()
    event = FakeOneBotPrivateEvent(
        user_id="12345",
        message_id="1002",
        segments=[FakeSegment("text", {"text": "北京哪有鼓"})],
    )

    result = asyncio.run(
        send_onebot_forward_messages(
            matcher,
            bot,
            event,
            messages=[{"type": "node", "data": {"content": "示例"}}],
        )
    )

    assert result is True
    assert matcher.finished is False
    assert bot.calls == [
        (
            "send_private_forward_msg",
            {
                "user_id": "12345",
                "messages": [{"type": "node", "data": {"content": "示例"}}],
            },
        )
    ]


def test_identity_and_mentions_for_qq_group_event():
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-1",
        segments=[
            FakeSegment("mention_user", {"user_id": "member_openid_self"}),
            FakeSegment("mention_user", {"user_id": "member_openid_other"}),
            FakeSegment("text", {"text": " 绑定 12345 "}),
        ],
    )

    assert get_identity_key(event=event) == "qq_official:member_openid_self"
    assert get_group_key(event=event) == "qq_official:group_openid_1"
    assert get_message_claim_key(event=event) == "qq_official:evt-1"
    assert extract_plain_text(event) == "绑定 12345"
    assert get_mentioned_identity_keys(event=event) == [
        "qq_official:member_openid_self",
        "qq_official:member_openid_other",
    ]
    assert resolve_target_identity_key(event=event) == "qq_official:member_openid_other"


def test_identity_display_and_legacy_normalization():
    assert normalize_legacy_identity_key("12345") == "onebot_v11:12345"
    assert normalize_legacy_group_key("67890") == "onebot_v11:67890"
    assert normalize_legacy_group_key("perf_test_group") == "perf_test_group"
    assert format_identity_for_display("onebot_v11:12345") == "12345"
    assert format_identity_for_display("qq_official:abcdef123456") == "官方群用户(abcd...3456)"
    assert build_identity_key(ONEBOT_V11_PLATFORM, "100") == "onebot_v11:100"
    assert build_group_key(QQ_OFFICIAL_PLATFORM, "g1") == "qq_official:g1"


def test_migrate_multi_bind_payload_prefixes_and_merges():
    payload = {
        "12345": {"ids": ["111", "222"], "current_index": 1},
        "onebot_v11:12345": {"ids": ["222", "333"], "current_index": 0},
        "qq_official:openid_1": {"ids": ["999"], "current_index": 0},
    }

    migrated, stats = migrate_multi_bind_payload(payload)

    assert migrated["onebot_v11:12345"]["ids"] == ["222", "333", "111"]
    assert migrated["onebot_v11:12345"]["current_index"] == 0
    assert migrated["onebot_v11:12345"]["current_slot"] == 1
    assert migrated["qq_official:openid_1"]["ids"] == ["999"]
    assert migrated["qq_official:openid_1"]["current_slot"] == 1
    assert stats["migrated"] == 1
    assert stats["merged"] == 1


def test_migrate_feature_switch_db_prefixes_group_ids(tmp_path: Path):
    db_path = tmp_path / "switch.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE feature_switch (
          group_id   TEXT NOT NULL,
          feature    TEXT NOT NULL,
          enabled    INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY(group_id, feature)
        )
        """
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("12345", "taiko", 1, 10),
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("onebot_v11:12345", "tsearch", 0, 20),
    )
    conn.execute(
        "INSERT INTO feature_switch (group_id, feature, enabled, updated_at) VALUES (?, ?, ?, ?)",
        ("perf_test_group", "taiko", 1, 30),
    )
    conn.commit()
    conn.close()

    stats = migrate_feature_switch_db(db_path)

    assert stats == {"migrated": 1, "merged": 0}
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT group_id, feature, enabled, updated_at FROM feature_switch ORDER BY group_id, feature"
    ).fetchall()
    conn.close()
    assert rows == [
        ("onebot_v11:12345", "taiko", 1, 10),
        ("onebot_v11:12345", "tsearch", 0, 20),
        ("perf_test_group", "taiko", 1, 30),
    ]
