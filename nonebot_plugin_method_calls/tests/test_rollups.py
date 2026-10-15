"""Pure aggregation + recorder boundary; never start a DB or change stored data."""
import asyncio
from collections import Counter
from datetime import datetime
from types import SimpleNamespace

from .test_extractor import FakeQQEvent, _group_event, migrated_cases, taiko_plugin
from nonebot_plugin_method_calls import recorder
from nonebot_plugin_method_calls.store import _build_rollup_rows


def test_recorder_enqueues_once_per_matcher_and_rollups_do_not_duplicate(monkeypatch):
    records = []
    async def capture(record):
        records.append({**record, 'timestamp': datetime(2026, 10, 14, 11, 30)})
    monkeypatch.setattr(recorder, 'CONFIG', SimpleNamespace(enabled=True))
    monkeypatch.setattr(recorder, 'enqueue_record', capture)
    async def exercise():
        for text, matcher, _, _ in migrated_cases():
            for event in (_group_event(text), FakeQQEvent(text)):
                before = len(records)
                await recorder.record_method_call(matcher(), None, None, event, {})
                assert len(records) == before + 1
                await recorder.record_method_call(matcher(), RuntimeError('failed'), None, event, {})
                assert len(records) == before + 1
        # A retained Sakura command still contributes exactly once per platform.
        for event in (_group_event('taikoupdate'), FakeQQEvent('taikoupdate')):
            await recorder.record_method_call(__import__("taiko_bot.runtime.player.entry", fromlist=["update_cluster"]).update_cluster.update(), None, None, event, {})
    asyncio.run(exercise())
    assert len(records) == 2 * (len(migrated_cases()) + 1)
    rows = _build_rollup_rows(records)
    assert len(rows) == len({row[:3] for row in rows})
    commands = Counter(record['normalized_command'] for record in records)
    assert commands['位置'] == 6 and commands['tinfo'] == 2
    expected = {'taiko_commands_v2:total': len(records),
                'taiko_commands_v2:platform:onebot_v11': len(records)//2,
                'taiko_commands_v2:platform:qq_official': len(records)//2,
                **{'taiko_commands_v2:command:' + command: count for command, count in commands.items()}}
    for granularity, bucket in [('hour', '2026-10-14 11:00:00'), ('day', '2026-10-14 00:00:00')]:
        assert {source: count for source, grain, timestamp, count in rows
                if grain == granularity and timestamp == bucket} == expected


def test_rollups_exclude_generic_and_incomplete_records():
    timestamp = datetime(2026, 10, 14, 11, 30)
    records = [
        {'timestamp': timestamp, 'platform': None, 'normalized_command': None},
        {'timestamp': timestamp, 'platform': 'onebot_v11', 'normalized_command': None},
        {'timestamp': timestamp, 'platform': None, 'normalized_command': 'tinfo'},
        {'timestamp': None, 'platform': 'qq_official', 'normalized_command': 'tinfo'},
    ]
    assert _build_rollup_rows(records) == []
