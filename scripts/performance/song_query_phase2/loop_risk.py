"""Actual Phase-1 kernel + optional warmup; synthetic load, no Bot/network/DB.

P95/P99 use nearest rank. Concurrent latency includes queueing from a shared
release time. Heartbeat max lag is measured per trial, not mixed with idle ticks.
"""
import argparse
import asyncio
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import resource
import shutil
import sys
import time

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'song_query'))
from run import initialize, command, memory, cgroup_resources


def stats(values):
    ordered = sorted(values)
    return {name: ordered[math.ceil(len(ordered)*p)-1] for name, p in [('p50', .5), ('p95', .95), ('p99', .99), ('max', 1)]}


async def trial(operation, concurrency=1):
    stop = False
    lags = []
    async def heartbeat():
        deadline = time.perf_counter()+.005
        while not stop:
            await asyncio.sleep(max(0, deadline-time.perf_counter()))
            now = time.perf_counter()
            lags.append(max(0, now-deadline)*1000)
            deadline = now+.005
    ticker = asyncio.create_task(heartbeat())
    await asyncio.sleep(.01)
    lags.clear()
    start_cpu, started = time.process_time_ns(), time.perf_counter_ns()
    async def request():
        await operation()
        return (time.perf_counter_ns()-started)/1e6
    try:
        values = await asyncio.gather(*(request() for _ in range(concurrency)))
        cpu = (time.process_time_ns()-start_cpu)/1e6
        await asyncio.sleep(.011)  # Let the heartbeat observe a synchronous stall.
        return dict(latency_ms=values, cpu_ms=cpu, loop_max_lag_ms=max(lags, default=0))
    finally:
        stop = True
        await ticker


async def main(args):
    assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
    root = Path(os.environ['QA_RUN_TMPDIR'])/'loop-catalog'
    (root/'songs').mkdir(parents=True)
    for name in ('song_data.json', 'song_alias.json'):
        shutil.copyfile(args.fixture/'songs'/name, root/'songs'/name)
    provider = initialize(args.source, root, 'center')
    catalog = importlib.import_module(provider.__package__+'.catalog')
    spec = importlib.util.spec_from_file_location(provider.__package__+'.warmup', args.candidate/'taiko_bot/runtime/public/warmup.py')
    warmup = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(warmup)
    os.environ['TAIKO_SONG_QUERY_PREWARM'] = '1'
    payload = json.loads((root/'songs/song_data.json').read_text())
    generation = 0
    rows = {}
    async def query():
        command(provider, 'id649', 'center')
    async def fuzzy():
        command(provider, 'warulooo', 'center')
    def update():
        nonlocal generation
        generation += 1
        payload[0]['bpm'] = f'phase2-{generation}'
        temporary = root/'songs/song_data.next'
        temporary.write_text(json.dumps(payload, ensure_ascii=False))
        temporary.replace(root/'songs/song_data.json')
    for name, concurrent in [('first_load', 1), ('warm', 1), ('verify_30s_branch', 1), ('update', 1),
                              ('cold_concurrent_8', 8), ('verify_concurrent_8', 8), ('update_concurrent_8', 8),
                              ('prewarm', 1), ('after_prewarm', 1), ('warm_concurrent_32', 32), ('fuzzy_concurrent_8', 8)]:
        samples = []
        count = 12 if concurrent > 1 else args.repetitions
        for _ in range(count):
            operation = query
            if name in ('first_load', 'cold_concurrent_8', 'prewarm', 'after_prewarm'):
                catalog._store = catalog.CatalogStore()
            if name == 'after_prewarm':
                assert await warmup.prewarm()
            if name.startswith('verify'):
                command(provider, 'id649', 'center')
                catalog._store._verify_after = 0  # Compress the SAME 30s branch.
            if name.startswith('update'):
                command(provider, 'id649', 'center')
                await asyncio.to_thread(update)
            if name == 'prewarm':
                operation = warmup.prewarm
            if name == 'fuzzy_concurrent_8':
                operation = fuzzy
            samples.append(await trial(operation, concurrent))
        rows[name] = dict(trials=len(samples), requests=sum(len(row['latency_ms']) for row in samples),
                         latency_ms=stats([value for row in samples for value in row['latency_ms']]),
                         loop_max_lag_ms=stats([row['loop_max_lag_ms'] for row in samples]),
                         cpu_ms=stats([row['cpu_ms'] for row in samples]), raw=samples)
        print(json.dumps(dict(cohort=name, **{k: v for k, v in rows[name].items() if k != 'raw'})), flush=True)
    # One natural wall-clock expiry as well as the 100-trigger distribution.
    command(provider, 'id649', 'center')
    await asyncio.sleep(31)
    natural = await trial(query)
    result = dict(source=str(args.source), repetitions=args.repetitions, heartbeat_interval_ms=5,
                  cohorts=rows, natural_31s_expiry=natural, memory=memory(), cgroup=cgroup_resources(),
                  max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, qa_run_id=os.environ['QA_RUN_ID'],
                  caveat='12 concurrent trials: P99 is an observed tail, not a production SLA. '
                         'Warmup shifts work before admission; GIL and synchronous updates remain measurable.')
    args.output.write_text(json.dumps(result, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, default=100)
    asyncio.run(main(parser.parse_args()))
