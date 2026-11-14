"""Installed NoneBot dispatch, synthetic data and intercepted outbound messages.

Run with the existing memory QA wrapper and the candidate's absolute Python -I.
"""
import asyncio
import json
import os
from pathlib import Path
import shutil
import sys
import types
from unittest.mock import AsyncMock

sys.dont_write_bytecode = True
work = Path(os.environ["QA_RUN_TMPDIR"]) / "dispatch"
work.mkdir()
(work / "songs").mkdir()
fixtures = Path(__file__).resolve().parents[1] / "archive/public-song-plugin/tests"
for path in (fixtures / "fixtures").glob("*.json"):
    shutil.copyfile(path, work / "songs" / path.name)
for name in ("rating_structured_with_ids.json", "analyze_result_filtered.json"):
    shutil.copyfile(fixtures / "catalog-fixtures" / name, work / "songs" / name)
os.chdir(work)
os.environ.update(TAIKO_RUNTIME_ROOT=str(work), TAIKO_CENTER_ROOT=str(work),
    TAIKO_BOT_ROOT=str(work), TAIKO_RUNTIME_ENV_FILE=str(work / "absent.env"))


def guard(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        raise AssertionError("Forbidden QA IO: " + event)
    if event == "open" and isinstance(args[0], str) and args[0].startswith(
        ("/home/sigaer/taiko/", "/etc/taiko")
    ) and not args[0].startswith(str(work.parent) + "/"):
        raise AssertionError("Production data access: " + args[0])


sys.addaudithook(guard)
import nonebot
nonebot.init(_env_file=None, driver="~fastapi+~httpx", log_level="ERROR",
    taiko_song_profile="center", taiko_song_public_root=str(work))
public = nonebot.load_plugin("taiko_bot.runtime.public")
player = nonebot.load_plugin("taiko_bot.runtime.player.entry")
assert public and player and len(public.matcher) == 11

from nonebot.adapters.onebot.v11 import Adapter, Bot, Message, GroupMessageEvent
from nonebot.adapters.qq import Adapter as QQAdapter, Bot as QQBot
from nonebot.adapters.qq.config import BotInfo
from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
from nonebot.message import handle_event, run_postprocessor
from sakura_taiko_core.models.calculation import V2SongData
from taiko_bot import fanmade
from taiko_bot.runtime.player.center import score_rating_target as service
from taiko_bot.runtime.player.center import score_handlers as handlers
import feature_handler.feature_handler as features

enabled = {"taiko": True, "tsearch": True}
features.is_group_allowed = lambda *a, **kw: True
features.is_feature_enabled = lambda group, name, **kw: enabled.get(name, True)
fanmade.search = AsyncMock(return_value={"items": [{"id": "a" * 32, "title": "测试自制谱",
    "maker": "测试谱师", "difficulties": [{"course": "Oni", "level": 10}]}],
    "page": 1, "pageSize": 12, "total": 1})
service.load_rating_config = lambda path: {"songs": {"test": {
    "id": 1367, "level": 4, "combo": 1000, "score": 10}},
    "const_table": {"const_to_score": {"10": 12}}}
service.load_v2_snapshot = lambda: types.SimpleNamespace(song_map={(1367, 4): V2SongData(
    1367, 4, "测试歌曲", 1000, 8, 10, 12, 10, 10, 10, 10, 10)})
handlers.query_with_mode = lambda query: ([[1367, "测试歌曲", 100]], "exact")
handlers.get_scoreline_entry = lambda *a, **kw: {"title": "测试歌曲", "max_combo": 1000,
    "initial_points": 1000, "ok_points": 500, "rating_scores": {"goku": 900000}}

driver = nonebot.get_driver()
driver.register_adapter(Adapter)
driver.register_adapter(QQAdapter)
bot = Bot(nonebot.get_adapter(Adapter), "90000")
qq = QQBot(nonebot.get_adapter(QQAdapter), "90000", BotInfo(id="90000", token="fixture", secret="fixture"))
sent, errors = [], []


async def capture(self, event, message, **kwargs):
    sent.append(str(message))
    return {"message_id": 1}


bot.send = types.MethodType(capture, bot)
qq.send = types.MethodType(capture, qq)


@run_postprocessor
async def post(exception: Exception | None):
    if exception:
        errors.append((type(exception).__name__, str(exception)))


async def dispatch(platform, text):
    sent.clear()
    errors.clear()
    if platform == "onebot":
        message = Message(text)
        event = GroupMessageEvent(time=1, self_id=90000, post_type="message", message_type="group",
            sub_type="normal", message_id=1, user_id=10001, group_id=123, message=message,
            original_message=message, raw_message=text, font=0, sender={"user_id": 10001}, to_me=True)
        target = bot
    else:
        event = GroupAtMessageCreateEvent(id="fixture", content=text, timestamp="2026-11-14T00:00:00+00:00",
            author={"id": "fixture-user", "member_openid": "fixture-user", "bot": False, "member_role": "member"},
            group_id="fixture-group", group_openid="fixture-group", to_me=True)
        target = qq
    await handle_event(target, event)
    assert not errors, errors
    return "\n".join(sent)


async def main():
    for platform in ("onebot", "qq"):
        for command in ("查自制 神威", "/查自制 神威", "太鼓 查自制 神威"):
            assert "测试自制谱" in await dispatch(platform, command), (platform, command, sent)
        target = await dispatch(platform, "分数线 id1367 10")
        assert "【Rating v1】" in target and "【Rating v2】" in target, (platform, target)
        assert target.count("最低良数") == 2, target
        evaluation = await dispatch(platform, "分数线 极 id1367 30")
        assert "目标分：900000" in evaluation and "最多可数：200" in evaluation, evaluation
        for switch in ("taiko", "tsearch"):
            enabled[switch] = False
            assert not await dispatch(platform, "查自制 神威")
            enabled[switch] = True
    print("PASS: OneBot/QQ fanmade commands, Rating v1/v2 targets, evaluation scoreline and feature switches")


asyncio.run(main())
