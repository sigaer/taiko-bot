"""Installed-wheel regression: run separately for center/client via run_qa.sh.

Usage: python -I reporting_events.py center|client
Only synthetic records and images in a temporary directory are used.
"""
import asyncio
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    profile = sys.argv[1]
    assert profile in ("center", "client")
    with tempfile.TemporaryDirectory(prefix="draw-report-") as temporary:
        root = Path(temporary)
        os.chdir(root)
        os.environ.update(
            TAIKO_BOT_ROOT=str(root), TAIKO_CENTER_ROOT=str(root),
            TAIKO_RUNTIME_ENV_FILE=str(root / "absent.env"),
            QQ_MARKDOWN_IMAGE_CACHE_DIR=str(root / "media"),
            QQ_MARKDOWN_IMAGE_BASE_URL="https://fixture.invalid/media",
        )

        def guard(event, args):
            if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect", "subprocess.Popen"):
                raise AssertionError("Forbidden IO: " + event)
            if event == "open" and isinstance(args[0], str) and args[0].startswith(
                ("/home/sigaer/taiko/", "/etc/taiko")
            ) and args[0] != str(root) and not args[0].startswith(str(root) + "/"):
                raise AssertionError("Production data access")

        sys.addaudithook(guard)
        import nonebot
        nonebot.init(driver="~fastapi+~httpx", log_level="ERROR",
                     taiko_song_profile=profile, taiko_song_public_root=str(root))
        assert nonebot.load_plugin("taiko_bot.runtime.community.community_entry")
        module = importlib.import_module(f"taiko_bot.runtime.community.{profile}.draw_guess")
        from nonebot.adapters.onebot.v11 import GroupMessageEvent, Message
        from nonebot.adapters.qq.event import GroupAtMessageCreateEvent
        from nonebot.exception import FinishedException
        from PIL import Image

        def event(user=100, group=10, platform="onebot"):
            text = "举报你画我猜id1"
            if platform == "qq":
                return GroupAtMessageCreateEvent(
                    id="fixture", content=text, timestamp="2026-11-04T00:00:00+00:00",
                    author={"id": str(user), "member_openid": str(user), "bot": False,
                            "member_role": "member"},
                    group_id=str(group), group_openid=str(group), to_me=True,
                )
            return GroupMessageEvent(
                time=1, self_id=90000, post_type="message", sub_type="normal",
                user_id=user, message_id=1, message_type="group", message=Message(text),
                original_message=Message(text), raw_message=text, font=0,
                sender={"user_id": user, "nickname": "fixture", "role": "member"},
                group_id=group, to_me=True,
            )

        class Capture:
            async def finish(self, message, **kwargs):
                self.message = message
                raise FinishedException

        async def report(user=100, group=10, platform="onebot", record_id=1):
            capture = Capture()
            handler = module.draw_guess_report.handlers[0].call
            try:
                await handler(matcher=capture, event=event(user, group, platform),
                              groups=(str(record_id),))
            except FinishedException:
                pass
            return capture.message

        async def scenario():
            raw = io.BytesIO()
            Image.new("RGB", (2, 2)).save(raw, "PNG")
            rid, error = await module._create_draw_guess_record(
                song_title="合成歌", song_ids=[1], uploader={"qq": "999"},
                image_bytes=raw.getvalue(),
            )
            assert rid == 1 and error is None
            image = (module.DRAW_GUESS_IMAGE_DIR / "1.png").read_bytes()
            assert "1人举报" in await report()
            for _ in range(7):
                assert "请勿重复举报" in await report()
            assert "请勿重复举报" in await report(group=11)
            record = await module._get_draw_guess_record(1)
            assert record["report_count"] == 1 and record["active"]
            assert record["reporter_ids"] == ["onebot_v11:100"]

            # The JSON survives a new lock/reader, as it would on restart.
            module.DRAW_GUESS_DB_LOCK = asyncio.Lock()
            before = module.DRAW_GUESS_DB_PATH.read_bytes()
            assert "请勿重复举报" in await report()
            assert "该id不存在" == await report(record_id=99)
            assert module.DRAW_GUESS_DB_PATH.read_bytes() == before

            # Platform IDs cannot collide, and repeated official events dedupe.
            assert "2人举报" in await report(platform="qq")
            assert "请勿重复举报" in await report(platform="qq", group=11)
            replies = await asyncio.gather(*(report(user=101) for _ in range(20)))
            assert sum("已举报你画我猜" in text for text in replies) == 1
            assert sum("请勿重复举报" in text for text in replies) == 19

            # Counter writes interleaved with the threshold cannot lose state.
            replies = await asyncio.gather(
                report(user=102), report(user=103), report(user=104),
                *(module._update_draw_guess_record_counters(1, like_delta=1) for _ in range(10)),
            )
            assert sum(isinstance(text, str) and "已删除" in text for text in replies) == 1
            record = await module._get_draw_guess_record(1)
            assert record["report_count"] == 5 and not record["active"]
            assert len(set(record["reporter_ids"])) == 5 and record["like_count"] == 10
            assert "已停用" in await report(user=105)
            assert "请勿重复举报" in await report()
            assert (module.DRAW_GUESS_IMAGE_DIR / "1.png").read_bytes() == image

            # Old anonymous counts must not allow one person to finish deletion.
            data = module._load_draw_guess_db()
            data["records"].append({"id": 2, "report_count": 4, "active": True})
            data["records"].append({"id": 3, "report_count": 5, "active": False})
            module._save_draw_guess_db(data)
            assert "1人举报" in await report(record_id=2)
            assert "请勿重复举报" in await report(record_id=2)
            legacy = await module._get_draw_guess_record(2)
            assert legacy["active"] and legacy["report_count"] == 1
            assert "已停用" in await report(record_id=3)
            assert not (await module._get_draw_guess_record(3))["active"]

            from taiko_bot.runtime.community.reporting import submit_report
            before = module.DRAW_GUESS_DB_PATH.read_bytes()
            invalid = await submit_report(
                2, " ", lock=module.DRAW_GUESS_DB_LOCK, load_db=module._load_draw_guess_db,
                save_db=module._save_draw_guess_db, threshold=5,
            )
            assert invalid.status == "invalid_user"
            assert module.DRAW_GUESS_DB_PATH.read_bytes() == before
            assert json.loads(before)["next_id"] == 2

        asyncio.run(scenario())
        print(f"PASS {profile}: real handlers, duplicate/cross-group/reload/official identity, "
              "concurrent reports/counters, five-person deactivation, legacy/inactive/missing records")


if __name__ == "__main__":
    main()
