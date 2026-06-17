from __future__ import annotations

import asyncio
import importlib
import re
from dataclasses import dataclass

import nonebot
import pytest
from nonebot.exception import FinishedException


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    return importlib.import_module("plugins.taiko")


class FakeSegment:
    def __init__(self, seg_type: str, data: dict):
        self.type = seg_type
        self.data = data

    def is_text(self) -> bool:
        return self.type == "text"


class FakeMessage(list):
    def extract_plain_text(self) -> str:
        return "".join(seg.data.get("text", "") for seg in self if seg.type == "text")


class FakeOneBotGroupEvent:
    __module__ = "nonebot.adapters.onebot.v11.event"

    def __init__(
        self,
        *,
        user_id: str = "12345",
        group_id: str = "67890",
        message_id: str = "1001",
        text: str = "",
        segments=None,
        self_id: str = "10000",
    ):
        self._user_id = str(user_id)
        self.self_id = int(self_id)
        self.group_id = int(group_id)
        self.message_id = int(message_id)
        base_segments = segments if segments is not None else [FakeSegment("text", {"text": text})]
        self._message = FakeMessage(base_segments)

    def get_user_id(self) -> str:
        return self._user_id

    def get_message(self):
        return self._message

    def get_type(self) -> str:
        return "message"


class FakeQQGroupEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(
        self,
        *,
        user_id: str = "member_openid_self",
        group_openid: str = "group_openid_1",
        event_id: str = "evt-1",
        text: str = "",
        segments=None,
    ):
        self._user_id = str(user_id)
        self.group_openid = str(group_openid)
        self.id = str(event_id)
        base_segments = segments if segments is not None else [FakeSegment("text", {"text": text})]
        self._message = FakeMessage(base_segments)

    def get_user_id(self) -> str:
        return self._user_id

    def get_message(self):
        return self._message

    def get_type(self) -> str:
        return "message"


@dataclass
class _DummyMatch:
    parts: dict[int, str]

    def group(self, index: int) -> str:
        return self.parts[index]


def test_bind_rule_accepts_spaced_and_plus_forms():
    taiko = _load_taiko_module()
    pattern = re.compile(r"^/?绑定(?:\s+|\+)?([0-9]{0,12})$")

    spaced = pattern.fullmatch("绑定 12345")
    plus = pattern.fullmatch("绑定+12345")
    missing = pattern.fullmatch("绑定abc")

    assert spaced is not None
    assert taiko._normalize_bind_input(spaced.group(1)) == "12345"
    assert plus is not None
    assert taiko._normalize_bind_input(plus.group(1)) == "12345"
    assert missing is None


def test_bind_id_classification_ranges():
    taiko = _load_taiko_module()

    assert taiko._is_wahlap_taiko_id("12345") is True
    assert taiko._is_wahlap_taiko_id("12345678901") is True
    assert taiko._is_wahlap_taiko_id("1234") is False
    assert taiko._is_wahlap_taiko_id("123456789012") is False

    assert taiko._is_hiroba_taiko_no("123456789012") is True
    assert taiko._is_hiroba_taiko_no("12345678901") is False


def test_bind_qq_prompt_handle_returns_instruction(monkeypatch):
    taiko = _load_taiko_module()
    replies: list[str] = []

    async def fake_finish_text(_matcher, _event, text: str, **_kwargs):
        replies.append(text)
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text)

    with pytest.raises(FinishedException):
        asyncio.run(taiko.bind_qq_prompt_handle(FakeOneBotGroupEvent(text="绑定QQ")))

    assert replies == [
        "快捷绑定需要手动输入 QQ 号。\n"
        "请发送“绑定QQ 你的QQ号”继续。\n"
        "注意：官 bot 无法直接获取你的 QQ 号，所以点按钮后不会自动完成绑定。"
    ]


def test_can_direct_bind_hiroba_requires_center_credentials(monkeypatch):
    taiko = _load_taiko_module()

    monkeypatch.setattr(taiko, "load_hiroba_credential_owner", lambda _taiko_id: None)
    monkeypatch.setattr(taiko, "_has_center_hiroba_credentials_cached", lambda _taiko_id: False)

    ok, message = taiko._can_direct_bind_hiroba_id("onebot_v11:123", "123456789012")

    assert ok is False
    assert "绑定hiroba" in message


def test_can_direct_bind_hiroba_rejects_other_owner(monkeypatch):
    taiko = _load_taiko_module()

    monkeypatch.setattr(taiko, "load_hiroba_credential_owner", lambda _taiko_id: "onebot_v11:other")

    ok, message = taiko._can_direct_bind_hiroba_id("onebot_v11:123", "123456789012")

    assert ok is False
    assert "为防止冒绑" in message


def test_finalize_hiroba_direct_bind_uses_hiroba_source(monkeypatch):
    taiko = _load_taiko_module()
    calls: list[tuple[str, str, bool, str]] = []

    monkeypatch.setattr(
        taiko,
        "_upsert_bind_record",
        lambda identity_key, taiko_id, source=None: (f"绑定 {taiko_id}", True),
    )
    monkeypatch.setattr(
        taiko,
        "_build_bind_auto_update_tip",
        lambda identity_key, taiko_id, is_first_binding, source=None: (
            calls.append((identity_key, taiko_id, is_first_binding, str(source))),
            "\n首次绑定已自动执行一次 更新hiroba。",
        )[1],
    )

    text = taiko._finalize_hiroba_direct_bind("onebot_v11:123", "123456789012")

    assert "已按日服/Hiroba 太鼓番绑定。" in text
    assert "如需后续同步，请发送“更新hiroba”。" in text
    assert calls == [("onebot_v11:123", "123456789012", True, "hiroba")]


def test_fetch_hiroba_public_profile_via_service_account_requires_service_creds(monkeypatch):
    taiko = _load_taiko_module()

    monkeypatch.setattr(taiko, "ensure_hiroba_credentials_table", lambda: None)
    monkeypatch.setattr(taiko, "load_hiroba_credentials", lambda _taiko_id: None)

    with pytest.raises(RuntimeError, match="862074224984"):
        taiko._fetch_hiroba_public_profile_via_service_account("123456789012")


def test_bind_hiroba_handle_keeps_running_after_initial_notice(monkeypatch):
    taiko = _load_taiko_module()
    sent_messages: list[str] = []
    finished_messages: list[str] = []

    class _FakeMatcher:
        async def send(self, text: str):
            sent_messages.append(text)

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    def fake_bind_hiroba_credentials(*_args, **_kwargs):
        return {
            "taikoIds": ["123456789012", "876543210987"],
            "bind": {
                "id": "123456789012",
                "visible": 0,
                "currentSlot": 1,
                "currentSource": "hiroba",
                "bindings": [],
            },
        }

    def fake_center_bind_info_to_entry(_info):
        return {
            "ids": ["123456789012", "876543210987"],
            "current_index": 0,
            "current_slot": 1,
            "sources": {
                "123456789012": "hiroba",
                "876543210987": "hiroba",
            },
        }

    async def fake_finish_text(_matcher, _event, text: str, **_kwargs):
        finished_messages.append(text)
        raise FinishedException()

    monkeypatch.setattr(taiko, "bind_hiroba", _FakeMatcher())
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(taiko, "bind_hiroba_credentials", fake_bind_hiroba_credentials)
    monkeypatch.setattr(taiko, "_center_bind_info_to_entry", fake_center_bind_info_to_entry)
    async def fake_send_text_without_finish(_matcher, _event, text: str):
        sent_messages.append(text)

    monkeypatch.setattr(taiko, "_send_text_reply_without_finish", fake_send_text_without_finish)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text)
    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "onebot_v11:21219135")

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko.bind_hiroba_handle(
                FakeOneBotGroupEvent(text="绑定hiroba test@example.com secret"),
                match=_DummyMatch({1: "test@example.com", 2: "secret", 3: ""}),
            )
        )

    assert sent_messages == ["开始绑定 Hiroba 账号"]
    assert finished_messages == [
        "已自动同步并绑定该 Bandai Namco ID 下的 2 个 Hiroba 账号。\n"
        "已切换到 u1：123456789012\n"
        "当前绑定：u1:123456789012(JP)（当前） / u2:876543210987(JP)\n"
        "已在中心保存 Hiroba 凭据，请后续使用“更新hiroba”同步中心成绩。"
    ]


def test_bind_12_digit_hiroba_rejects_private_profile(monkeypatch):
    taiko = _load_taiko_module()
    finished_messages: list[str] = []

    async def fake_finish_text(_matcher, _event, text: str, **_kwargs):
        finished_messages.append(text)
        raise FinishedException()

    async def fake_to_thread(func, *args, **kwargs):
        raise taiko.HirobaProfilePrivateError("private")

    monkeypatch.setattr(taiko, "get_identity_key", lambda **_kwargs: "qq_official:test")
    monkeypatch.setattr(taiko, "_normalize_identity_key", lambda value: value)
    monkeypatch.setattr(taiko, "load_hiroba_credential_owner", lambda _taiko_id: None)
    monkeypatch.setattr(taiko, "_has_center_hiroba_credentials_cached", lambda _taiko_id: True)
    monkeypatch.setattr(taiko.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko.bind_handle(
                FakeQQGroupEvent(text="绑定 519635636897"),
                match=_DummyMatch({1: "519635636897"}),
            )
        )

    assert finished_messages == [
        "该 Hiroba 账号当前为非公开资料，服务账号无法读取称号信息。\n请先发送“绑定hiroba 邮箱 密码 太鼓番”完成登录验证。"
    ]


def test_hiroba_success_reply_falls_back_to_text_when_image_reply_fails(monkeypatch):
    taiko = _load_taiko_module()
    calls: list[tuple[str, str]] = []

    async def fake_finish_image_reply(*_args, **_kwargs):
        raise TimeoutError("image send timeout")

    async def fake_finish_text_reply(_matcher, _event, text: str, **_kwargs):
        calls.append(("text", text))
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko._finish_hiroba_update_success_reply(
                object(),
                FakeOneBotGroupEvent(text="更新hiroba"),
                success_message="Hiroba 更新成功！",
                img_buf=b"fake-image",
            )
        )

    assert calls == [("text", "Hiroba 更新成功！")]


def test_hiroba_success_reply_keeps_image_path_when_image_reply_finishes(monkeypatch):
    taiko = _load_taiko_module()
    calls: list[str] = []

    async def fake_finish_image_reply(*_args, **_kwargs):
        calls.append("image")
        raise FinishedException()

    async def fake_finish_text_reply(*_args, **_kwargs):
        calls.append("text")
        raise FinishedException()

    monkeypatch.setattr(taiko, "_finish_image_reply", fake_finish_image_reply)
    monkeypatch.setattr(taiko, "_finish_text_reply", fake_finish_text_reply)

    with pytest.raises(FinishedException):
        asyncio.run(
            taiko._finish_hiroba_update_success_reply(
                object(),
                FakeOneBotGroupEvent(text="更新hiroba"),
                success_message="Hiroba 更新成功！",
                img_buf=b"fake-image",
            )
        )

    assert calls == ["image"]


def test_public_score_token_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(text="网页成绩token")

    assert taiko._is_qq_official_unsupported_command(event) is False


def test_developer_userdata_still_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(text="开发者数据 abc 123")

    assert taiko._is_qq_official_unsupported_command(event) is True


def test_build_update_command_hint_for_hiroba_account(monkeypatch):
    taiko = _load_taiko_module()
    entry = {
        "ids": ["519635636897", "12345678"],
        "current_index": 0,
        "current_slot": 1,
        "sources": {"519635636897": "hiroba", "12345678": "wahlap"},
    }

    monkeypatch.setattr(taiko, "_get_current_bind_entry", lambda _identity_key: entry)

    text = taiko._build_update_command_hint("onebot_v11:21219135", expected_source="wahlap")

    assert "当前正在使用 u1：519635636897（JP）。" in text
    assert "这不是 CN 服账号，请改用“更新hiroba”。" in text
    assert "当前绑定：u1:519635636897(JP)（当前） / u2:12345678(CN)" in text
    assert "如需切换其他账号，请先发送 u1 / u2。" in text


def test_build_update_command_hint_for_wahlap_account(monkeypatch):
    taiko = _load_taiko_module()
    entry = {
        "ids": ["99887766"],
        "current_index": 0,
        "current_slot": 1,
        "sources": {"99887766": "wahlap"},
    }

    monkeypatch.setattr(taiko, "_get_current_bind_entry", lambda _identity_key: entry)

    text = taiko._build_update_command_hint("onebot_v11:9988", expected_source="hiroba")

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

    text = taiko._build_update_command_hint("onebot_v11:9988", expected_source="hiroba")

    assert "当前正在使用 u0：合并账户（只读）。" in text
    assert "更新命令 仅支持真实绑定账号" in text
    assert "当前展示资料来源：u2：11223344" in text


def test_resolve_taikob_dim_arg_supports_wrapped_and_flag_forms():
    taiko = _load_taiko_module()

    assert taiko._resolve_taikob_dim_arg(["精度"]) == "accuracy_power"
    assert taiko._resolve_taikob_dim_arg(["[精度]"]) == "accuracy_power"
    assert taiko._resolve_taikob_dim_arg(["【体力】"]) == "stamina"
    assert taiko._resolve_taikob_dim_arg(["--dim=精度"]) == "accuracy_power"
    assert taiko._resolve_taikob_dim_arg(["-d", "精度"]) == "accuracy_power"
    assert taiko._resolve_taikob_dim_arg(["维度", "体力"]) == "stamina"
    assert taiko._resolve_taikob_dim_arg(["-r"]) is None


def test_qq_official_what_song_trigger_variants():
    taiko = _load_taiko_module()

    assert taiko._extract_official_what_song_query("taiko 千本樱是什么歌") == "千本樱"
    assert taiko._extract_official_what_song_query("太鼓 什么歌 千本樱") == "千本樱"
    assert taiko._extract_official_what_song_query("太鼓是啥歌 红莲华") == "红莲华"
    assert taiko._extract_official_what_song_query("千本樱是什么歌") is None


def test_what_song_rule_allows_official_variants():
    taiko = _load_taiko_module()
    official_ok = taiko._should_handle_what_song(FakeQQGroupEvent(text="taiko 千本樱是什么歌"))
    official_bad = taiko._should_handle_what_song(FakeQQGroupEvent(text="taiko 千本樱"))

    assert official_ok is True
    assert official_bad is False
