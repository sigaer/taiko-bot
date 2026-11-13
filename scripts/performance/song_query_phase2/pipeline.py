"""Independent Phase-2 pipeline replay: real SDK messages, zero QQ API calls.

No subtraction of Phase-1 percentiles. API dispatch below is a recording stub;
actual API/client timing, when available, belongs to separate live evidence.
"""
import argparse
import asyncio
import gc
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sys
import time
from types import SimpleNamespace

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'song_query'))
from run import initialize, memory, cgroup_resources


def prepare(args):
    sys.path.insert(0, str(args.source))
    from taiko_bot.offline.static_fumens import atomic_write
    from taiko_bot.static_fumens import canonical, digest, POLICY
    root = args.fixture
    (root/'songs').mkdir(parents=True, exist_ok=False)
    for name in ('song_data.json', 'song_alias.json'):
        shutil.copyfile(args.catalog/'songs'/name, root/'songs'/name)
    folder = root/'assets/fumens/Oni'
    folder.mkdir(parents=True)
    source = folder/'649.png'
    shutil.copyfile('/home/sigaer/taiko/assets/fumens/Oni/649.png', source)
    policy = dict(schema=1, scope='public-static-fumen', base_url='https://static.example.test/phase2',
                  valid_until=time.time()+86400,
                  grants=[dict(difficulty='Oni', song_id='649', sha256=digest(source.read_bytes()), public=True,
                               authorization_ref='User conversation 2026-11-13: all chart images permitted public')])
    atomic_write(root/'songs'/POLICY, canonical(policy))
    return refresh(args)


def refresh(args):
    sys.path.insert(0, str(args.source))
    from taiko_bot.offline.static_fumens import publish
    from taiko_bot.static_fumens import POLICY
    import httpx
    root = args.fixture
    policy = json.loads((root/'songs'/POLICY).read_text())
    def server(request):
        path = root/'publication/sha256'/request.url.path.rsplit('/', 1)[1]
        return httpx.Response(200, headers={'Content-Type': 'image/png'}, content=path.read_bytes())
    with httpx.Client(transport=httpx.MockTransport(server)) as client:
        result = publish(root, root/'publication', policy['base_url'], client, lease=900)
    print(json.dumps(dict(fixture=str(root), **result)))


def stats(values):
    ordered = sorted(values)
    return {name: ordered[math.ceil(len(ordered)*p)-1] for name, p in [('p50', .5), ('p95', .95), ('p99', .99)]}


async def replay(args):
    provider = initialize(args.source, args.fixture, 'center')
    from taiko_application.commands import CommandContext, SongPorts, execute_song
    from nonebot.exception import FinishedException
    from nonebot.adapters.qq import MessageSegment
    delivery = importlib.import_module(provider.__package__+'.delivery')
    import taiko_bot.runtime.center_markdown_media as cache
    cache.QQ_MARKDOWN_IMAGE_CACHE_DIR = args.fixture/('cache-'+args.variant+'-'+args.platform)
    cache.QQ_MARKDOWN_IMAGE_BASE_URL = 'https://static.example.test/cache'
    os.environ['TAIKO_STATIC_FUMEN_ENABLED'] = '1' if args.variant == 'after' else '0'
    os.environ['TAIKO_STATIC_FUMEN_BASE_URL'] = 'https://static.example.test/phase2'
    event = SimpleNamespace(group_openid='synthetic', id='synthetic') if args.platform == 'qq' else SimpleNamespace()
    current = {}
    originals = []
    def wrap(obj, name, label):
        original = getattr(obj, name)
        def measured(*a, **kw):
            started = time.perf_counter_ns()
            try:
                return original(*a, **kw)
            finally:
                current[label] = current.get(label, 0)+time.perf_counter_ns()-started
                current[label+'_calls'] = current.get(label+'_calls', 0)+1
        originals.append((obj, name, original))
        setattr(obj, name, measured)
    original_open = Path.open
    def opened(path, *a, **kw):
        stream = original_open(path, *a, **kw)
        if '/assets/fumens/' not in str(path) or path.suffix != '.png':
            return stream
        class Reader:
            def __enter__(self):
                stream.__enter__()
                return self
            def __exit__(self, *a):
                return stream.__exit__(*a)
            def __getattr__(self, name):
                return getattr(stream, name)
            def read(self, *a):
                started = time.perf_counter_ns()
                data = stream.read(*a)
                current['png_read_ns'] = current.get('png_read_ns', 0)+time.perf_counter_ns()-started
                current['png_reads'] = current.get('png_reads', 0)+1
                return data
        return Reader()
    Path.open = opened
    originals.append((Path, 'open', original_open))
    wrap(provider, 'brief', 'brief_ns')
    wrap(cache, 'write_public_image', 'cache_write_ns')
    wrap(MessageSegment, 'markdown', 'markdown_model_ns')
    receipt = []
    class Capture:
        async def send(self, message):
            current['pre_send_ns'] = time.perf_counter_ns()-current['started']
            started = time.perf_counter_ns()
            receipt.append(message)
            await asyncio.sleep(0)
            current['mock_send_dispatch_ns'] = time.perf_counter_ns()-started
        async def finish(self, message=None, **kwargs):
            if message is not None:
                await self.send(message)
            raise FinishedException
    async def run_one():
        nonlocal current
        current = dict(started=time.perf_counter_ns())
        receipt.clear()
        start_cpu = time.process_time_ns()
        with provider.catalog_request():
            started = time.perf_counter_ns()
            result = execute_song(CommandContext(text='id649是什么歌'), SongPorts(
                _extract_what_song_query=lambda text: 'id649',
                _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
                _resolve_what_song_query=provider.resolve))
            current['search_and_command_ns'] = time.perf_counter_ns()-started
            try:
                await delivery.deliver(Capture(), event, result)
            except FinishedException:
                pass
        current['total_ns'] = time.perf_counter_ns()-current.pop('started')
        current['cpu_ns'] = time.process_time_ns()-start_cpu
        assert len(receipt) == 1, 'pipeline omitted/duplicated a message'
        current['message_count'] = len(receipt)
        current['message_types'] = [segment.type for segment in receipt[0]]
        if args.platform == 'qq':
            assert current['message_types'] == ['markdown']
            content = receipt[0][0].data['markdown'].content
            assert content.startswith('你要找的是不是：\n魔王 id649\n【毒LOＣＡＮdy♡】')
            expected = 0 if args.variant == 'after' else 1
            assert current.get('png_reads', 0) == current.get('cache_write_ns_calls', 0) == expected
        else:
            assert current['message_types'] == ['text', 'image']
            assert current.get('png_reads') == 1 and current.get('cache_write_ns_calls', 0) == 0
        return dict(current)
    try:
        before = memory()
        cold = await run_one()
        rows = [await run_one() for _ in range(args.repetitions)]
        # Returned file names/bytes never enter reports. Remove owned random
        # copies only after the timing window; never touch production caches.
        cache_root = cache.QQ_MARKDOWN_IMAGE_CACHE_DIR
        if cache_root.exists():
            for path in cache_root.glob('taiko-*.png'):
                path.unlink()
        gc.collect()
        numeric = sorted({key for row in rows for key, value in row.items() if type(value) in (int, float)})
        result = dict(source=str(args.source), platform=args.platform, variant=args.variant,
                      repetitions=args.repetitions, cold=cold,
                      summary={key: stats([row.get(key, 0) for row in rows]) for key in numeric}, raw=rows,
                      memory_before=before, memory_after=memory(), cgroup=cgroup_resources(),
                      max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                      qa_run_id=os.environ['QA_RUN_ID'], qq_api_calls=0,
                      qq_api_latency_ms=None, native_client_first_ms=None, native_client_repeat_ms=None,
                      caveat='SDK recording transport only; mock dispatch is NOT QQ API latency. PNG is a real authorized chart.')
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
        print(json.dumps({key: value for key, value in result.items() if key not in ('raw', 'cold')}, ensure_ascii=False))
    finally:
        for obj, name, original in reversed(originals):
            setattr(obj, name, original)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('action', choices=['prepare', 'refresh', 'replay'])
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--platform', choices=['qq', 'onebot'], default='qq')
    parser.add_argument('--variant', choices=['before', 'after'], default='after')
    parser.add_argument('--repetitions', type=int, default=500)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
    os.environ['TAIKO_BOT_ROOT'] = str(args.fixture)
    os.environ['TAIKO_RUNTIME_ROOT'] = str(args.fixture)
    if args.action == 'prepare':
        prepare(args)
    elif args.action == 'refresh':
        refresh(args)
    else:
        asyncio.run(replay(args))
