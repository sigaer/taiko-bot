import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from taiko_bot.runtime import request_timing as timing


def test_default_log_sink_emits_the_complete_structured_record():
    from nonebot.log import logger
    messages = []
    sink = logger.add(lambda message: messages.append(message.record['message']), level='INFO')
    try:
        with timing.RequestTrace(platform='qq_official', profile='center').scope():
            pass
    finally:
        logger.remove(sink)
    records = [json.loads(m.removeprefix('Taiko B30 timing: ')) for m in messages
               if m.startswith('Taiko B30 timing: ')]
    assert len(records) == 1 and records[0]['status'] == 'completed'
    assert records[0]['platform'] == 'qq_official'


def test_dispatch_clock_survives_scheduling_without_leaking_to_next_event():
    async def scenario():
        from taiko_bot.runtime.qq_adapter import Adapter
        now = [1_000_000_000]
        rows = []
        class Bot:
            async def handle_event(self, event):
                with timing.RequestTrace(platform="qq_official", profile="center",
                                         emit=rows.append, clock=lambda: now[0]).scope():
                    now[0] += 75_000_000
        adapter = object.__new__(Adapter)
        adapter.tasks = set()
        adapter.payload_to_event = lambda payload: object()
        with patch.object(timing, "perf_counter_ns", lambda: now[0]):
            adapter.dispatch_event(Bot(), object())
        assert timing._ingress.get() is None
        now[0] += 25_000_000  # Actual dispatch-to-handler scheduling delay.
        await asyncio.gather(*tuple(adapter.tasks))
        assert rows[0]["boundary"] == "qq_adapter_dispatch"
        assert rows[0]["dispatch_to_handler_ms"] == 25
        assert rows[0]["handler_total_ms"] == 75
        assert rows[0]["dispatch_to_finish_ms"] == 100
        assert timing._current.get() is None
    asyncio.run(scenario())


def test_real_qq_send_api_hooks_separate_upload_send_and_concurrent_requests():
    from nonebot.adapters.qq import Bot, MessageSegment
    from nonebot.adapters.qq.config import BotInfo
    timing.install_api_hooks()
    rows = []
    class Adapter:
        async def _call_api(self, bot, api, **data):
            await asyncio.sleep(.002)
            return SimpleNamespace(file_info="PRIVATE_FILE_INFO")
    async def query():
        bot = Bot(Adapter(), "123", BotInfo(id="123", token="PRIVATE", secret="PRIVATE"))
        with timing.RequestTrace(platform="qq_official", profile="center", emit=rows.append).scope():
            await bot.send_to_group("PRIVATE_GROUP", MessageSegment.file_image(b"PRIVATE_IMAGE"))
    async def scenario():
        await asyncio.gather(query(), query())
    asyncio.run(scenario())
    assert len(rows) == 2 and len({r["request_id"] for r in rows}) == 2
    for row in rows:
        assert [s["name"] for s in row["spans"]] == ["api.post_group_files", "api.post_group_messages"]
        upload, send = row["spans"]
        assert upload["start_ms"] + upload["duration_ms"] <= send["start_ms"] + .002
        assert row["dispatch_to_send_ack_ms"] is not None
        assert row["unfinished_api_calls"] == 0
    assert "PRIVATE" not in json.dumps(rows)


def test_api_error_and_cancellation_do_not_claim_success_or_leak_payload():
    timing.install_api_hooks()
    rows = []
    async def scenario():
        with pytest.raises(asyncio.CancelledError):
            with timing.RequestTrace(platform="qq_official", profile="center", emit=rows.append).scope():
                data = {"group_openid": "PRIVATE", "file_data": b"PRIVATE_IMAGE"}
                await timing._api_calling(None, "post_group_files", data)
                await timing._api_called(None, ValueError("PRIVATE_ERROR"), "post_group_files", data, None)
                await timing._api_calling(None, "post_group_messages", data)
                raise asyncio.CancelledError()
    asyncio.run(scenario())
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["dispatch_to_send_ack_ms"] is None
    assert rows[0]["spans"][0]["status"] == "error"
    assert rows[0]["unfinished_api_calls"] == 1
    assert "PRIVATE" not in json.dumps(rows)
    assert timing._current.get() is None


def test_render_worker_only_receives_explicit_numeric_trace():
    rows = []
    async def scenario():
        with timing.RequestTrace(platform="onebot_v11", profile="center", emit=rows.append).scope() as trace:
            def worker():
                assert timing._current.get() is None
                with trace.activate(), trace.phase("render.compute"):
                    assert timing._current.get() is trace
                    return 42
            assert await asyncio.get_running_loop().run_in_executor(None, worker) == 42
    asyncio.run(scenario())
    assert rows[0]["spans"][0]["name"] == "render.compute"


def test_nested_intervals_bounded_storage_and_logger_failure_preserve_behavior():
    rows = []
    with timing.RequestTrace(platform="PRIVATE", profile="center", emit=rows.append).scope() as trace:
        trace.select((20, ["PRIVATE_COMMAND"], True, False, "PRIVATE_DIMENSION"))
        with timing.phase("outer"):
            with timing.phase("inner"):
                pass
        for _ in range(timing.MAX_SPANS + 100):
            with trace.phase("bounded"):
                pass
    assert len(rows[0]["spans"]) == timing.MAX_SPANS
    assert rows[0]["dropped_spans"] == 102
    assert "PRIVATE" not in json.dumps(rows)
    class FinishedException(Exception):
        pass
    def broken_logger(row):
        raise ValueError("sink failure")
    with pytest.raises(FinishedException):
        with timing.RequestTrace(platform="qq_official", profile="center", emit=broken_logger).scope():
            raise FinishedException()
    assert timing._current.get() is None
