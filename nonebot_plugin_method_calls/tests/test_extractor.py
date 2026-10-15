import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

import nonebot

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def load_tinfo_owner():
    try: nonebot.get_driver()
    except ValueError: nonebot.init()
    return nonebot.require("taiko_bot.runtime.player.entry")
taiko_player = load_tinfo_owner()

from nonebot import on_command, on_endswith, on_fullmatch, on_regex, on_startswith
from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message, MessageSegment
from nonebot.consts import ENDSWITH_KEY, PREFIX_KEY, RAW_CMD_KEY, STARTSWITH_KEY

from nonebot_plugin_method_calls.extractor import (
    build_record,
    decode_method_name,
    extract_display_name,
    extract_method_name,
    should_record,
)
from nonebot_plugin_method_calls.taiko_commands import normalize_taiko_command
nonebot.require("taiko_bot.runtime.community.community_entry")
from taiko_bot.runtime.community.center import cover as taiko_plugin



class DummyMatcher:
    priority = 5

    def __init__(self, module: str, rule=None, priority: int = 5):
        self.__module__ = module
        self.rule = rule
        self.module_name = module
        type(self).priority = priority
        type(self).__module__ = module


def _group_event(text: str, group_id: int = 123456, self_id: int = 10001) -> GroupMessageEvent:
    return GroupMessageEvent(
        time=1710000000,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=10002,
        message_id=1,
        message_type="group",
        message=Message(text),
        original_message=Message(text),
        raw_message=text,
        font=0,
        sender={"user_id": 10002, "nickname": "tester", "card": "", "role": "member"},
        group_id=group_id,
    )


def _onebot_event_with_segments(*segments, group_id: int = 123456, self_id: int = 10001) -> GroupMessageEvent:
    message = Message(list(segments))
    raw_message = "".join(str(seg) for seg in message)
    return GroupMessageEvent(
        time=1710000000,
        self_id=self_id,
        post_type="message",
        sub_type="normal",
        user_id=10002,
        message_id=1,
        message_type="group",
        message=message,
        original_message=message,
        raw_message=raw_message,
        font=0,
        sender={"user_id": 10002, "nickname": "tester", "card": "", "role": "member"},
        group_id=group_id,
    )


def _matcher(matcher, module: str = "plugins.demo", priority: int = 5) -> DummyMatcher:
    return DummyMatcher(module=module, rule=matcher.rule, priority=priority)


class FakeQQSegment:
    def __init__(self, seg_type: str, data: dict[str, str]):
        self.type = seg_type
        self.data = data


class FakeQQMessage(list):
    def extract_plain_text(self):
        parts = []
        for seg in self:
            if getattr(seg, "type", "") == "text":
                parts.append(str(getattr(seg, "data", {}).get("text", "")))
        return "".join(parts)


class FakeQQEvent:
    __module__ = "nonebot.adapters.qq.event"

    def __init__(self, plain_text: str, *, mentioned_user_id: str = "bot-openid", group_openid: str = "group-openid"):
        self.id = "evt-1"
        self.group_openid = group_openid
        self.group_id = "group-id"
        self.self_id = "bot-openid"
        self._user_id = "user-openid"
        self._message = FakeQQMessage(
            [
                FakeQQSegment("mention_user", {"user_id": mentioned_user_id}),
                FakeQQSegment("text", {"text": plain_text}),
            ]
        )

    def get_message(self):
        return self._message

    def get_user_id(self):
        return self._user_id


def migrated_cases():
    public = nonebot.require("taiko_bot.runtime.public")
    commands = public.public_commands
    catalog = public.catalog_commands
    from taiko_bot.runtime.community.center import draw_guess as draw, annual, compat
    return [
        ("cover1", taiko_plugin.cover_cmd, "cover", "cover"),
        ("2025年度报告", annual.annual_2025_report, "2025年度报告", "2025年度报告"),
        ("/ping", compat.qq_official_ping, "ping", "ping"),
        ("画太鼓歌名", draw.draw_guess_make_start, "画太鼓歌名", "画太鼓歌名"),
        ("猜太鼓歌名", draw.draw_guess_start, "猜太鼓歌名", "猜太鼓歌名"),
        ("猜1", draw.draw_guess_answer, "猜太鼓答案", "猜太鼓答案"),
        ("点赞你画我猜id1", draw.draw_guess_like, "点赞你画我猜", "点赞你画我猜"),
        ("举报你画我猜id1", draw.draw_guess_report, "举报你画我猜", "举报你画我猜"),
        ("查看你画我猜id1", draw.draw_guess_view, "查看你画我猜", "查看你画我猜"),
        ("我的你画我猜", draw.draw_guess_mine, "我的你画我猜", "我的你画我猜"),
        ("你画我猜排行", draw.draw_guess_rank, "你画我猜排行", "你画我猜排行"),
        ("u0", taiko_player.identity_cluster.bind_switch, "切换绑定", "切换绑定"),
        ("迁移验证码", taiko_player.identity_cluster.qq_migration_code, "迁移验证码", "迁移验证码"),
        ("确认绑定", taiko_player.identity_cluster.bind_confirm, "确认绑定", "确认绑定"),
        ("确认删除绑定", taiko_player.identity_cluster.bind_remove_confirm, "确认删除绑定", "确认删除绑定"),
        ("taikoupdat", taiko_player.update_cluster.update_typo, "taikoupdate拼写提示", "taikoupdate拼写提示"),
        ("码来", taiko_player.update_cluster.game_login_qr, "码来", "码来"),
        ("新增空白账号", taiko_player.manual_cluster.manual_create, "新增空白账号", "新增空白账号"),
        ("空白账号改名", taiko_player.manual_cluster.manual_rename, "空白账号改名", "空白账号改名"),
        ("生成认领码", taiko_player.manual_cluster.manual_claim_code, "生成认领码", "生成认领码"),
        ("认领空白账号", taiko_player.manual_cluster.manual_claim, "认领空白账号", "认领空白账号"),
        ("解绑空白账号", taiko_player.manual_cluster.manual_detach, "解绑空白账号", "解绑空白账号"),
        ("永久删除空白账号", taiko_player.manual_cluster.manual_delete, "永久删除空白账号", "永久删除空白账号"),
        ("确认永久删除空白账号", taiko_player.manual_cluster.manual_delete_confirm, "确认永久删除空白账号", "确认永久删除空白账号"),
        ("录入成绩", taiko_player.manual_cluster.manual_score_upsert, "录入成绩", "录入成绩"),
        ("查看成绩", taiko_player.manual_cluster.manual_score_get, "查看成绩", "查看成绩"),
        ("删除成绩", taiko_player.manual_cluster.manual_score_delete, "删除成绩", "删除成绩"),
        ("确认删除成绩", taiko_player.manual_cluster.manual_score_delete_confirm, "确认删除成绩", "确认删除成绩"),
        ("快捷操作", taiko_player.query_cluster.quick_actions_panel, "快捷操作", "快捷操作"),
        ("歌曲排行 红", taiko_player.query_cluster.song_rank, "歌曲排行", "歌曲排行"),
        ("taiko2025", taiko_player.query_cluster.summary, "taiko2025", "taiko2025"),
        ("查分", taiko_player.query_cluster.twso, "活动查分", "查分"),
        ("鞍山哪有鼓", taiko_player.query_cluster.city_arcade_query, "哪有鼓", "哪有鼓"),
        ("tsearch on", taiko_player.management_cluster.tsearch_switch, "tsearch", "tsearch"),
        ("查称号 红", taiko_player.management_cluster.song_title_query, "查称号", "查称号"),
        ("加称号 红 to 红", taiko_player.management_cluster.custom_title_add, "加称号", "加称号"),
        ("tset red to 红", taiko_player.management_cluster.tset_alias, "tset", "tset"),
        ("分数线 极 红 30", taiko_player.scoring.score_line_cmd, "分数线", "分数线"),
        ("查分 红 500 10", taiko_player.scoring.score_cmd, "查分计算", "查分"),
        ("估分 红", taiko_player.scoring.score_estimate_cmd, "估分", "估分"),
        ("taikotrend", taiko_player.trend.trend, "taikotrend", "taikotrend"),
        ("rating游玩", taiko_player.trend.playtrend, "taikoplaytrend", "rating游玩"),
        ("我的小咚", taiko_player.personal.my_don, "我的小咚", "我的小咚"),
        ("太鼓1可", taiko_player.personal.song_metric_query, "成绩筛选", "成绩筛选"),
        ("词云", taiko_player.personal.tcloud, "tcloud", "词云"),
        ("taikob20 v2", taiko_player.b30.taikob, "taikob", "taikob"),
        ("id1367是什么歌", public.what_song, "是什么歌", "是什么歌"),
        ("id1367有什么别名", commands.alias_query, "有什么别名", "有什么别名"),
        ("id1367歌在哪", commands.song_where, "位置", "在哪"),
        ("id1367在什么位置", commands.song_position_phrase, "位置", "在什么位置"),
        ("位置id1367", commands.song_pos_by_id, "位置", "位置"),
        ("鬼id1367", commands.diff_by_id, "查谱", "查谱"),
        ("太鼓查物量872", commands.note_count, "太鼓查物量", "太鼓查物量"),
        ("查定数6.6", catalog.const_query, "查定数", "查定数"),
        ("查配置180", catalog.patterns, "查配置", "查配置"),
        ("tinfo 红", taiko_player.music_info, "tinfo", "tinfo"),
        ("9星进度 2", taiko_player.progress.matcher, "进度", "9星进度"),
        ("虹2025六段进度", taiko_player.progress.matcher, "进度", "虹2025六段进度"),
        ("taikorec体力30", taiko_player.recommendation.taikorec, "taikorec", "taikorec"),
        ("推荐歌曲 紫雅 9星", taiko_player.recommendation.taikorec, "taikorec", "推荐歌曲"),
        ("歌曲推荐 全连", taiko_player.recommendation.taikorec, "taikorec", "歌曲推荐"),
    ]


class ExtractorTestCase(unittest.TestCase):
    def test_migrated_matchers_preserve_all_record_fields(self):
        for text, matcher, canonical, display in migrated_cases():
            temporary = type("TemporaryMatcher", (matcher,), {})
            for target in (matcher, matcher(), temporary, temporary()):
                for event, platform, group in [
                    (_group_event(text), "onebot_v11", "123456"),
                    (FakeQQEvent(text), "qq_official", "group-openid"),
                ]:
                    with self.subTest(command=canonical, matcher=target, platform=platform):
                        self.assertTrue(should_record(event, target))
                        self.assertEqual(build_record(event, target), {
                            "method_name": "cmd::" + display, "normalized_command": canonical,
                            "platform": platform, "group_id": group,
                        })

    def test_migrated_matchers_reject_other_bot_mentions(self):
        for text, matcher, _, _ in migrated_cases():
            event = _onebot_event_with_segments(MessageSegment.at("20002"), MessageSegment.text(text))
            self.assertIsNone(normalize_taiko_command(event, matcher))
            self.assertFalse(should_record(event, matcher))

    def test_registry_uses_exact_owner_and_identity_without_loading_plugins(self):
        from unittest.mock import patch
        from nonebot_plugin_method_calls import taiko_commands as registry
        owner = "taiko_bot.runtime.player.entry"
        entry = sys.modules[owner]
        before = sum(len(items) for items in nonebot.matcher.matchers.values())
        with patch.dict(sys.modules, {owner: None}):
            self.assertIsNone(normalize_taiko_command(_group_event("tinfo 红"), entry.music_info))
        # A prior miss cannot permanently cache an incomplete registry.
        self.assertEqual(normalize_taiko_command(_group_event("tinfo 红"), entry.music_info).canonical, "tinfo")
        for module in (owner, "taiko_bot.runtime.foreign", "plugins.miku"):
            fake = type("music_info", (), {"module_name": module, "__module__": module})
            self.assertIsNone(normalize_taiko_command(_group_event("tinfo 红"), fake))
        with patch.object(taiko_plugin, "music_info", entry.music_info, create=True):
            self.assertEqual(sum(m is entry.music_info for m in registry._matcher_specs()), 1)
        self.assertEqual(before, sum(len(items) for items in nonebot.matcher.matchers.values()))

    def test_extract_command_uses_raw_command_with_prefix(self):
        event = _group_event("/taikob 参数")
        matcher = _matcher(on_command("taikob"))
        state = {PREFIX_KEY: {RAW_CMD_KEY: "/taikob"}}
        self.assertEqual(extract_display_name(event, matcher, state), "/taikob")
        self.assertEqual(extract_method_name(event, matcher, state), "cmd::/taikob")

    def test_extract_fullmatch(self):
        event = _group_event("晚安")
        matcher = _matcher(on_fullmatch("晚安"))
        self.assertEqual(extract_display_name(event, matcher), "晚安")
        self.assertEqual(extract_method_name(event, matcher), "cmd::晚安")

    def test_extract_startswith(self):
        event = _group_event("cover1234")
        matcher = _matcher(on_startswith("cover"))
        state = {STARTSWITH_KEY: "cover"}
        self.assertEqual(extract_method_name(event, matcher, state), "cmd::cover…")

    def test_extract_endswith(self):
        event = _group_event("鞍山哪有鼓")
        matcher = _matcher(on_endswith("哪有鼓"))
        state = {ENDSWITH_KEY: "哪有鼓"}
        self.assertEqual(extract_method_name(event, matcher, state), "cmd::…哪有鼓")

    def test_extract_regex_prefix(self):
        event = _group_event("cover1234")
        matcher = _matcher(on_regex(r"^cover\s*(\d+)"))
        self.assertEqual(extract_method_name(event, matcher), "cmd::cover…")

    def test_extract_regex_suffix(self):
        event = _group_event("红莲华进度 3")
        matcher = _matcher(on_regex(r"^.+进度(?:\s+\d+)?$"))
        self.assertEqual(extract_method_name(event, matcher), "cmd::…进度")

    def test_extract_regex_prefix_and_suffix(self):
        event = _group_event("cnpjsk 看看b30")
        matcher = _matcher(on_regex(r"^(?:tw|cn)?pjsk.*b30.*"))
        self.assertEqual(extract_method_name(event, matcher), "cmd::cnpjsk…b30")

    def test_extract_regex_rejects_broad_match(self):
        event = _group_event("我喜欢原神")
        matcher = _matcher(on_regex(r".*原神.*|.*元神.*"))
        self.assertIsNone(extract_method_name(event, matcher))

    def test_should_skip_feature_handler(self):
        event = _group_event("晚安")
        matcher = _matcher(on_fullmatch("晚安"), module="feature_handler")
        self.assertFalse(should_record(event, matcher))

    def test_decode_method_name(self):
        self.assertEqual(decode_method_name("cmd::/taikob"), "/taikob")
        self.assertIsNone(decode_method_name("晚安"))

    def test_build_record_generic(self):
        event = _group_event("哦哈哟", group_id=987654)
        matcher = _matcher(on_fullmatch("哦哈哟"))
        record = build_record(event, matcher)
        self.assertEqual(
            record,
            {
                "method_name": "cmd::哦哈哟",
                "group_id": "987654",
                "platform": None,
                "normalized_command": None,
            },
        )

    def test_taiko_update_aliases_normalize_to_same_canonical(self):
        event_a = _group_event("taikoupdate all")
        event_b = _group_event("更新广场 全部")
        match_a = normalize_taiko_command(event_a, taiko_player.update_cluster.update)
        match_b = normalize_taiko_command(event_b, taiko_player.update_cluster.update)
        self.assertIsNotNone(match_a)
        self.assertIsNotNone(match_b)
        self.assertEqual(match_a.canonical, "taikoupdate")
        self.assertEqual(match_b.canonical, "taikoupdate")
        self.assertEqual(match_a.display, "taikoupdate")
        self.assertEqual(match_b.display, "更新广场")

    def test_taiko_trend_aliases_normalize_to_same_canonical(self):
        trend = normalize_taiko_command(_group_event("taikotrend 20 30"), taiko_player.trend.trend)
        alias = normalize_taiko_command(_group_event("rating走势 体力"), taiko_player.trend.trend)
        self.assertEqual(trend.canonical, "taikotrend")
        self.assertEqual(alias.canonical, "taikotrend")
        self.assertEqual(trend.display, "taikotrend")
        self.assertEqual(alias.display, "rating走势")

    def test_taiko_playtrend_aliases_normalize_to_same_canonical(self):
        trend = normalize_taiko_command(_group_event("taikoplaytrend 20"), taiko_player.trend.playtrend)
        alias = normalize_taiko_command(_group_event("rating场次 体力"), taiko_player.trend.playtrend)
        self.assertEqual(trend.canonical, "taikoplaytrend")
        self.assertEqual(alias.canonical, "taikoplaytrend")

    def test_taiko_missing_commands_now_normalize(self):
        cases = [
            ("我的小咚", taiko_player.personal.my_don, "我的小咚"),
            ("tcloud", taiko_player.personal.tcloud, "tcloud"),
            ("taikob 30 体力", taiko_player.b30.taikob, "taikob"),
            ("tinfo 红莲华", taiko_player.music_info, "tinfo"),
            ("6星进度 2", taiko_player.progress.matcher, "进度"),
            ("cover1234", taiko_plugin.cover_cmd, "cover"),
        ]
        for text, matcher, canonical in cases:
            with self.subTest(text=text):
                match = normalize_taiko_command(_group_event(text), matcher)
                self.assertIsNotNone(match)
                self.assertEqual(match.canonical, canonical)

    def test_taiko_record_contains_platform_and_canonical(self):
        event = _group_event("taikoupdate")
        record = build_record(event, taiko_player.update_cluster.update)
        self.assertEqual(record["normalized_command"], "taikoupdate")
        self.assertEqual(record["platform"], "onebot_v11")
        self.assertEqual(record["group_id"], "123456")
        self.assertEqual(record["method_name"], "cmd::taikoupdate")

    def test_taiko_record_accepts_matcher_instance(self):
        event = _group_event("taikoupdate")
        record = build_record(event, taiko_player.update_cluster.update())
        self.assertEqual(record["normalized_command"], "taikoupdate")
        self.assertEqual(record["platform"], "onebot_v11")
        self.assertEqual(record["group_id"], "123456")
        self.assertEqual(record["method_name"], "cmd::taikoupdate")

    def test_onebot_at_self_still_counts(self):
        event = _onebot_event_with_segments(
            MessageSegment.at("10001"),
            MessageSegment.text(" taikoupdate"),
        )
        match = normalize_taiko_command(event, taiko_player.update_cluster.update)
        self.assertIsNotNone(match)
        self.assertEqual(match.canonical, "taikoupdate")

    def test_onebot_at_other_bot_does_not_count(self):
        event = _onebot_event_with_segments(
            MessageSegment.at("20002"),
            MessageSegment.text(" taikoupdate"),
        )
        self.assertIsNone(normalize_taiko_command(event, taiko_player.update_cluster.update))
        self.assertFalse(should_record(event, taiko_player.update_cluster.update))

    def test_qq_official_mention_counts_as_same_canonical(self):
        event = FakeQQEvent("taikoupdate")
        match = normalize_taiko_command(event, taiko_player.update_cluster.update)
        self.assertIsNotNone(match)
        self.assertEqual(match.canonical, "taikoupdate")
        self.assertEqual(match.platform, "qq_official")
        self.assertEqual(match.group_id, "group-openid")

    def test_bind_qq_prefilled_placeholder_still_normalizes(self):
        event = _group_event("绑定QQ 你的QQ号 12345678")
        match = normalize_taiko_command(event, taiko_player.identity_cluster.bind_qq)
        self.assertIsNotNone(match)
        self.assertEqual(match.canonical, "绑定QQ")
        self.assertEqual(match.display, "绑定QQ")

    def test_bind_prefilled_placeholder_still_normalizes(self):
        event = _group_event("绑定 你的鼓众广场id 123456")
        match = normalize_taiko_command(event, taiko_player.identity_cluster.bind)
        self.assertIsNotNone(match)
        self.assertEqual(match.canonical, "绑定")
        self.assertEqual(match.display, "绑定")


if __name__ == "__main__":
    unittest.main()


def test_silent_typo_probe_never_duplicates_another_command():
    event = GroupMessageEvent(time=1,self_id=90000,post_type="message",message_type="group",sub_type="normal",message_id=1,user_id=12345,group_id=123,message=Message("新增空白账号 合成名字"),original_message=Message("新增空白账号 合成名字"),raw_message="新增空白账号 合成名字",font=0,sender={"user_id":12345},to_me=True)
    assert not should_record(event, taiko_player.update_cluster.update_typo)
    assert should_record(event, taiko_player.manual_cluster.manual_create)


def test_every_command_spec_has_an_explicit_taiko_owner():
    from nonebot_plugin_method_calls import taiko_commands as registry
    assert set(registry._build_spec_map()) <= set(registry._MIGRATED_MATCHER_MODULES)
    assert all(owner.startswith('taiko_bot.runtime.') for owner in registry._MIGRATED_MATCHER_MODULES.values())
    assert 'plugins.taiko' not in registry._TAIKO_MATCHER_MODULES
