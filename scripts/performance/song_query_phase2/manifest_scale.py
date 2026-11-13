"""Synthetic metadata scale only: no public copy, HTTPS claim or Bot send."""
import argparse
import asyncio
import gc
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import tracemalloc

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'song_query'))
from run import memory, cgroup_resources
from loop_risk import stats, trial


async def main(args):
    assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
    spec = importlib.util.spec_from_file_location('_static_scale', args.source/'taiko_bot/static_fumens.py')
    schema = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = schema
    spec.loader.exec_module(schema)
    root = Path(os.environ['QA_RUN_TMPDIR'])/'metadata-scale'
    (root/'songs').mkdir(parents=True)
    base, sha, now = 'https://static.example.test/metadata-scale', 'a'*64, time.time()
    rows = {}
    for count in (1, 13140):
        policy = dict(schema=1, scope='public-static-fumen', base_url=base, valid_until=now+86400,
                      grants=[dict(difficulty='Oni', song_id=str(i), sha256=sha, public=True,
                                   authorization_ref='synthetic metadata; not a resource verification') for i in range(1, count+1)])
        policy_bytes = schema.canonical(policy)
        entries = [dict(difficulty='Oni', song_id=str(i), sha256=sha, resource_version=sha,
                        url=schema.asset_url(base, sha), width=816, height=1648) for i in range(1, count+1)]
        payload = dict(schema=1, policy_sha256=schema.digest(policy_bytes), entries=entries,
                       checked_at=now, valid_until=now+900)
        payload['resource_version'] = schema.digest(schema.canonical(dict(policy_sha256=payload['policy_sha256'], entries=entries)))
        (root/'songs'/schema.POLICY).write_bytes(policy_bytes)
        (root/'songs'/schema.MANIFEST).write_bytes(schema.canonical(payload))
        del policy, policy_bytes, entries, payload
        gc.collect()
        before = memory()
        cold, warm, verify = [], [], []
        for _ in range(30):
            store = schema.StaticFumenStore()
            async def lookup():
                assert store.lookup(root, base, 'Oni', '1') is not None
            cold.append(await trial(lookup))
            warm.append(await trial(lookup))
            store._checked_at = 0  # Exercise the unchanged-byte 30s branch.
            verify.append(await trial(lookup))
        # Separate allocation pass; tracemalloc overhead is absent above.
        store = None
        gc.collect()
        tracemalloc.start()
        before_alloc = tracemalloc.get_traced_memory()[0]
        store = schema.StaticFumenStore()
        assert store.lookup(root, base, 'Oni', '1')
        gc.collect()
        retained = tracemalloc.get_traced_memory()[0]-before_alloc
        tracemalloc.stop()
        def summarize(samples):
            return dict(latency_ms=stats([v for row in samples for v in row['latency_ms']]),
                        loop_max_lag_ms=stats([row['loop_max_lag_ms'] for row in samples]),
                        cpu_ms=stats([row['cpu_ms'] for row in samples]))
        rows[str(count)] = dict(trials=30, cold=summarize(cold), warm=summarize(warm), verify_30s=summarize(verify),
                               retained_python_bytes=retained, memory_before=before, memory_after=memory())
        store = None
        gc.collect()
    args.output.write_text(json.dumps(dict(cohorts=rows, cgroup=cgroup_resources(),
        qa_run_id=os.environ['QA_RUN_ID'], caveat='Synthetic metadata only; does not prove 13140 resources verified or public. '
        'Cold parse is synchronous and can block the event loop; native client timing is not measured.'), indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    asyncio.run(main(parser.parse_args()))
