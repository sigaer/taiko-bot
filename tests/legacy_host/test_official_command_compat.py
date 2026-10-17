from __future__ import annotations

import asyncio
import importlib
from runtime_owner import load_community_owner
import re

import nonebot

from runtime_owner import load_tinfo_owner

from test_taiko_runtime import FakeQQGroupEvent, FakeSegment


def _load_taiko_module():
    try:
        nonebot.get_driver()
    except ValueError:
        nonebot.init()
    load_tinfo_owner()
    return load_community_owner()


def _build_official_mention_event(text: str) -> FakeQQGroupEvent:
    return FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id=f"evt-{text}",
        segments=[
            FakeSegment(
                "mention_user",
                {"user_id": "bot_openid", "username": "bot", "is_bot": True},
            ),
            FakeSegment("text", {"text": f" {text} "}),
        ],
    )


def test_cover_command_not_blocked_by_qq_official_gate():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-cover",
        segments=[FakeSegment("text", {"text": "cover1234"})],
    )

    assert taiko._is_qq_official_unsupported_command(event) is False


def test_official_at_prefix_command_matchers_ignore_mention_segment():
    taiko = _load_taiko_module()

    cover_match = taiko._extract_cover_command_match(
        _build_official_mention_event("/cover1234")
    )
    assert cover_match is not None
    assert cover_match.group(1) == "1234"

    runtime = nonebot.require("taiko_bot.runtime.player.entry")
    event = _build_official_mention_event("tinfo 红")
    assert asyncio.run(runtime.eligible(event))
    music_info_match = runtime.PATTERN.match(runtime.helpers.extract_plain_text(event).strip())
    assert not hasattr(taiko, "music_info")
    assert not hasattr(taiko, "music_info_handle")
    assert len(nonebot.get_plugin("entry").matcher) == 49
    assert runtime.music_info in nonebot.get_plugin("entry").matcher
    assert runtime.recommendation.taikorec in nonebot.get_plugin("entry").matcher
    assert not hasattr(taiko, "taikorec")
    assert not hasattr(taiko, "matcher")
    assert not hasattr(taiko, "taikob")
    assert runtime.b30.taikob in nonebot.get_plugin("entry").matcher
    assert runtime.trend.trend in nonebot.get_plugin("entry").matcher
    assert runtime.trend.playtrend in nonebot.get_plugin("entry").matcher
    assert not hasattr(taiko, "trend") and not hasattr(taiko, "playtrend")
    assert runtime.progress.matcher in nonebot.get_plugin("entry").matcher
    for name in ("my_don", "song_metric_query", "tcloud"):
        assert not hasattr(taiko, name)
        assert not hasattr(taiko, name + "_handle")
        assert getattr(runtime.personal, name) in nonebot.get_plugin("entry").matcher
    for name in ("score_line_cmd", "score_cmd", "score_estimate_cmd"):
        assert not hasattr(taiko, name)
        assert getattr(runtime.scoring, name) in nonebot.get_plugin("entry").matcher
    assert len(nonebot.get_plugin("public").matcher) == 9
    assert music_info_match is not None
    assert music_info_match.group(1) == "红"

    taikob_match = runtime.b30.extract_match(
        _build_official_mention_event("taikob20 v2")
    )
    assert taikob_match is not None
    assert taikob_match.group(1) == "20"
    assert taikob_match.group(2).strip() == "v2"

    progress_match = runtime.progress.extract_match(
        _build_official_mention_event("6星进度 2")
    )
    assert progress_match is not None
    assert progress_match.group("body") == "6星进度"
    assert progress_match.group("page") == "2"


def test_taikob_v2_dim_args_support_flag_and_alias():
    taiko = _load_taiko_module()

    dim, unknown_tokens = nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[0]._parse_taikob_dim_arg(
        ["v2", "--dim=手速"], nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[4].V2_TAIKOB_DIM_ALIASES
    )
    assert dim == "手速"
    assert unknown_tokens == []

    dim, unknown_tokens = nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[0]._parse_taikob_dim_arg(
        ["v2", "精度力"], nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[4].V2_TAIKOB_DIM_ALIASES
    )
    assert dim == "精度"
    assert unknown_tokens == []

    dim, unknown_tokens = nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[0]._parse_taikob_dim_arg(
        ["v2", "爆发", "foo"], nonebot.require("taiko_bot.runtime.player.entry").b30.modules()[4].V2_TAIKOB_DIM_ALIASES
    )
    assert dim == "爆发"
    assert unknown_tokens == ["foo"]


def test_taikob_v1_is_normalized_to_the_legacy_no_arg_form():
    taiko = _load_taiko_module()

    version, arg_text = taiko._extract_rating_version("v1")

    assert version == "v1"
    assert arg_text == ""


def test_taikob20_v1_selects_summary_on_owned_entry():
    _load_taiko_module()
    runtime = nonebot.require("taiko_bot.runtime.player.entry").b30
    from taiko_application.commands import CommandContext, prepare_b30
    command = prepare_b30(CommandContext(match=runtime.PATTERN.match("taikob20 v1")), runtime.build_ports())
    assert command == (20, [], False, False, None)


def test_official_at_prefix_my_don_command_rule_ignores_mention_segment():
    taiko = _load_taiko_module()

    assert asyncio.run(nonebot.require("taiko_bot.runtime.player.entry").personal.don_eligible(_build_official_mention_event("我的小咚"))) is True


def test_copied_sakura_prefix_is_normalized_for_official_regex_commands():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="member_openid_self",
        group_openid="group_openid_1",
        event_id="evt-copied-prefix",
        segments=[FakeSegment("text", {"text": "@Sakura taikotrend"})],
    )

    asyncio.run(taiko._normalize_copied_sakura_prefix_event(event))

    assert taiko.extract_plain_text(event) == "taikotrend"
    assert re.search(r"^/?(taikotrend|rating走势)\s*(.*)$", str(event.get_message()), re.IGNORECASE)


def test_silent_blocked_event_matches_configured_official_user():
    taiko = _load_taiko_module()
    event = FakeQQGroupEvent(
        user_id="E866D95E2836EE873E8D168039ABABE0",
        group_openid="group_openid_1",
        event_id="evt-blocked",
        segments=[FakeSegment("text", {"text": "tinfo 红"})],
    )

    assert taiko._is_silently_blocked_event(event) is True


def test_silent_blocked_event_tolerates_events_without_context_user_id():
    taiko = _load_taiko_module()

    class _NoContextOneBotEvent:
        __module__ = "nonebot.adapters.onebot.v11.event"

        def get_user_id(self) -> str:
            raise ValueError("Event has no context!")

    assert taiko._is_silently_blocked_event(_NoContextOneBotEvent()) is False
