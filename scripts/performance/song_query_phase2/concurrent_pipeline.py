"""Independent full local pipeline concurrency; recording sends, zero QQ APIs."""
import argparse
import asyncio
import importlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'song_query'))
from run import initialize, memory, cgroup_resources
from loop_risk import stats, trial


async def main(args):
    assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
    os.environ.update(TAIKO_BOT_ROOT=str(args.fixture), TAIKO_RUNTIME_ROOT=str(args.fixture))
    provider = initialize(args.source, args.fixture, 'center')
    from taiko_application.commands import CommandContext, SongPorts, execute_song
    from nonebot.exception import FinishedException
    delivery = importlib.import_module(provider.__package__+'.delivery')
    import taiko_bot.runtime.center_markdown_media as cache
    cache.QQ_MARKDOWN_IMAGE_CACHE_DIR = args.fixture/('concurrent-cache-'+args.variant)
    cache.QQ_MARKDOWN_IMAGE_BASE_URL = 'https://static.example.test/cache'
    os.environ['TAIKO_STATIC_FUMEN_ENABLED'] = '1' if args.variant == 'after' else '0'
    os.environ['TAIKO_STATIC_FUMEN_BASE_URL'] = 'https://static.example.test/phase2'
    event = SimpleNamespace(group_openid='synthetic', id='synthetic')
    before = memory()
    calls, prefixes = dict(png_reads=0, temporary_writes=0, messages=0), []
    original_open, original_write = Path.open, cache.write_public_image
    def opened(path, *a, **kw):
        if '/assets/fumens/' in str(path) and path.suffix == '.png':
            calls['png_reads'] += 1
        return original_open(path, *a, **kw)
    def written(*a, **kw):
        calls['temporary_writes'] += 1
        return original_write(*a, **kw)
    Path.open, cache.write_public_image = opened, written
    async def operation():
        started = time.perf_counter_ns()
        sends = 0
        class Capture:
            async def send(self, message):
                nonlocal sends
                sends += 1
                calls['messages'] += 1
                assert len(message) == 1 and message[0].type == 'markdown'
                content = message[0].data['markdown'].content
                assert content.startswith('你要找的是不是：\n魔王 id649\n【毒LOＣＡＮdy♡】')
                if args.variant == 'after':
                    assert '/sha256/238e29e26d75455743679bd8f85b705669ac60398678e033bcfd01b4898f9748.png' in content
                prefixes.append((time.perf_counter_ns()-started)/1e6)
                await asyncio.sleep(0)  # Local dispatch only, not API latency.
            async def finish(self, message=None, **kwargs):
                if message is not None:
                    await self.send(message)
                raise FinishedException
        with provider.catalog_request():
            result = execute_song(CommandContext(text='id649是什么歌'), SongPorts(
                _extract_what_song_query=lambda text: 'id649',
                _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
                _resolve_what_song_query=provider.resolve))
            try:
                await delivery.deliver(Capture(), event, result)
            except FinishedException:
                pass
        assert sends == 1
    try:
        await operation()  # Warm snapshot, imports and manifest outside samples.
        calls = dict.fromkeys(calls, 0)
        prefixes.clear()
        samples = [await trial(operation, concurrency=8) for _ in range(12)]
        expected = 0 if args.variant == 'after' else 96
        assert calls == dict(png_reads=expected, temporary_writes=expected, messages=96)
        result = dict(variant=args.variant, source=str(args.source), batches=12, concurrency=8, requests=96,
            completion_with_queue_ms=stats([v for row in samples for v in row['latency_ms']]),
            local_pre_send_ms=stats(prefixes), batch_cpu_ms=stats([row['cpu_ms'] for row in samples]),
            batch_loop_max_lag_ms=stats([row['loop_max_lag_ms'] for row in samples]),
            logical_io=calls, memory_before=before, memory_after=memory(), cgroup=cgroup_resources(),
            raw=samples, qa_run_id=os.environ['QA_RUN_ID'], qq_api_calls=0,
            caveat='Recording transport only. 12 batches: P99 observed tail, not SLA or network/client speed.')
        args.output.write_text(json.dumps(result, indent=2)+'\n')
    finally:
        Path.open, cache.write_public_image = original_open, original_write
        if cache.QQ_MARKDOWN_IMAGE_CACHE_DIR.exists():
            for path in cache.QQ_MARKDOWN_IMAGE_CACHE_DIR.glob('taiko-*.png'):
                path.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--variant', choices=['before', 'after'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
