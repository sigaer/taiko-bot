"""Bounded, offline public-song replay. No messages, DBs or private userdata.

Use the repository memory QA runner. `prepare` freezes only the two public
catalogs; baseline and candidate run in separate processes with the same input.
"""
from __future__ import annotations

import argparse
import atexit
from contextlib import contextmanager, nullcontext
import gc
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import resource
import shutil
import sys
import time
from types import ModuleType


def initialize(source, fixture, profile):
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(source), str(source / 'packages/taiko-application/src')]
    # Keep the same Core 0.1.1 runtime for before/after center comparison.
    import taiko_bot
    public = Path(taiko_bot.__file__).parent / 'runtime/public'
    name = '_song_replay_public'
    package = ModuleType(name)
    package.__path__ = [str(public)]
    config = ModuleType(name + '.config')
    config.root = lambda: fixture
    config.profile = lambda: profile
    sys.modules[name] = package
    sys.modules[config.__name__] = config
    provider = importlib.import_module(name + '.provider')
    return provider


def cases():
    return [
        ('id', 'id649'), ('exact', '千本桜'), ('alias', '毒糖'),
        ('normalized', '毒locandy♡'), ('partial', 'waruloo'),
        ('homophone', '幽宣'), ('fuzzy', 'warulooo'),
        ('fuzzy_long', 'night of knigts'), ('low_score', 'zxqvjkzz'),
        ('prefix_exact', '里千本桜'), ('prefix_fuzzy', '里warulooo'),
    ]


def command(provider, query, profile):
    from taiko_application.commands import CommandContext, SongPorts, execute_song
    scope = provider.catalog_request() if hasattr(provider, 'catalog_request') else nullcontext()
    with scope:
        result = execute_song(CommandContext(profile=profile, text=query+'是什么歌'), SongPorts(
            _extract_what_song_query=lambda text: text.removesuffix('是什么歌'),
            _is_rejected_fuzzy_query_result=provider.rejected_fuzzy,
            _resolve_what_song_query=provider.resolve))
        brief = ''
        if profile == 'center' and result.kind in ('fumen', 'fuzzy_fumen'):
            sid = result.payload[1] if result.kind == 'fumen' else result.payload[0][0]
            brief = provider.brief(sid)
        return dict(kind=result.kind, payload=result.payload, difficulty=result.difficulty, brief=brief)


def summary(values):
    ordered = sorted(values)
    return dict(p50=ordered[math.ceil(len(ordered)*.50)-1],
                p95=ordered[math.ceil(len(ordered)*.95)-1])


class Detail:
    def __init__(self):
        self.rows = {}
        self.stack = []
        self.originals = []
        self.queries = []

    @contextmanager
    def phase(self, label):
        start = time.perf_counter_ns()
        frame = [0]
        self.stack.append(frame)
        try:
            yield
        finally:
            elapsed = time.perf_counter_ns() - start
            self.stack.pop()
            if self.stack:
                self.stack[-1][0] += elapsed
            row = self.rows.setdefault(label, dict(calls=0, inclusive_ns=0, exclusive_ns=0))
            row['calls'] += 1
            row['inclusive_ns'] += elapsed
            row['exclusive_ns'] += elapsed - frame[0]

    def wrap(self, obj, name, label):
        original = getattr(obj, name)
        def measured(*args, **kwargs):
            with self.phase(label):
                result = original(*args, **kwargs)
            if label == 'query_with_mode':
                self.queries.append(dict(query=args[0], options=kwargs, mode=result[1], rows=len(result[0])))
            return result
        self.originals.append((obj, name, original))
        setattr(obj, name, measured)

    def restore(self):
        for obj, name, original in reversed(self.originals):
            setattr(obj, name, original)


def detail(provider, query, profile):
    from sakura_taiko_core.chart import identity
    import taiko_application.query.song as song
    measurement = Detail()
    # Attribution only; this instrumentation is absent from latency samples.
    measurement.wrap(Path, 'open', 'file_open')
    measurement.wrap(Path, 'stat', 'file_stat')
    measurement.wrap(Path, 'read_text', 'read_text')
    measurement.wrap(Path, 'read_bytes', 'read_bytes')
    measurement.wrap(json, 'load', 'json_load')
    measurement.wrap(json, 'loads', 'json_loads')
    measurement.wrap(identity, 'build_group_maps', 'center_groups')
    measurement.wrap(song, 'query_music', 'matching')
    if hasattr(provider, 'query_music'):
        measurement.wrap(provider, 'query_music', 'matching')
    if hasattr(provider, 'get_snapshot'):
        catalog = importlib.import_module(provider.__package__+'.catalog')
        measurement.wrap(catalog, 'query_music', 'matching')
        measurement.wrap(catalog, '_read', 'catalog_read_hash')
        measurement.wrap(catalog, 'build_song_index', 'index_prepare')
    if profile == 'client':
        client = importlib.import_module(provider.__package__+'.client_provider')
        if hasattr(client, 'query_music'):
            measurement.wrap(client, 'query_music', 'matching')
    measurement.wrap(provider, 'query_with_mode', 'query_with_mode')
    measurement.wrap(provider, 'brief', 'brief')
    try:
        with measurement.phase('command'):
            command(provider, query, profile)
    finally:
        measurement.restore()
    return dict(phases=measurement.rows, queries=measurement.queries)


def memory():
    result = {}
    for line in Path('/proc/self/smaps_rollup').read_text().splitlines():
        if line.startswith(('Rss:', 'Pss:')):
            name, value, _ = line.split()
            result[name[:-1].lower()+'_kib'] = int(value)
    return result


def cgroup_resources():
    group = Path('/proc/self/cgroup').read_text().strip().split('::', 1)[1]
    directory = Path('/sys/fs/cgroup')/group.lstrip('/')
    result = dict(cgroup=group)
    for name in ('memory.current', 'memory.peak', 'memory.events', 'memory.max', 'memory.high', 'cpu.max'):
        path = directory/name
        result[name] = path.read_text().strip() if path.exists() else None
    return result


def benchmark(args):
    provider = initialize(args.source, args.fixture, args.profile)
    gc.collect()
    before = memory()
    started = time.perf_counter_ns()
    first = command(provider, 'id649', args.profile)
    cold_ns = time.perf_counter_ns() - started
    gc.collect()
    resident = memory()
    # Fixed schedule, warm filesystem/phonetic caches; no dropped OS caches.
    expected = {}
    selected = [('partial_name', 'ワルルーさまの歌を')] if args.partial_only else cases()
    for label, query in selected:
        expected[label] = command(provider, query, args.profile)
    rows = {label: dict(wall_ns=[], cpu_ns=[]) for label, _ in selected}
    for _ in range(args.repetitions):
        for label, query in selected:
            start_cpu, start = time.process_time_ns(), time.perf_counter_ns()
            result = command(provider, query, args.profile)
            elapsed = time.perf_counter_ns()-start
            cpu = time.process_time_ns()-start_cpu
            assert result == expected[label], 'unstable replay: '+label
            rows[label]['wall_ns'].append(elapsed)
            rows[label]['cpu_ns'].append(cpu)
    details = {label: detail(provider, query, args.profile) for label, query in selected}
    stats = {label: {key: summary(value) for key, value in row.items()} for label, row in rows.items()}
    payload = dict(profile=args.profile, source=str(args.source), python=sys.version,
                   platform=platform.platform(), cpu_count=os.cpu_count(),
                   affinity=sorted(os.sched_getaffinity(0)), repetitions=args.repetitions,
                   cases=selected, fixture=json.loads((args.fixture/'manifest.json').read_text()),
                   cold_first_command_ns=cold_ns, memory_before=before, memory_after_first=resident,
                   memory_after_replay=memory(), max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                   qa_run_id=os.environ['QA_RUN_ID'], raw=rows, summary=stats,
                   details=details, results=expected, first_result=first)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(output=str(args.output), samples=args.repetitions*len(selected),
                          cold_ms=cold_ns/1e6, memory_after_first=resident)))


def prepare(args):
    args.fixture.mkdir(parents=True, exist_ok=False)
    (args.fixture/'songs').mkdir()
    manifest = {}
    for name in ('song_data.json', 'song_alias.json'):
        source = args.public / name
        target = args.fixture/'songs'/name
        shutil.copyfile(source, target)
        payload = target.read_bytes()
        data = json.loads(payload)
        assert isinstance(data, list)
        manifest[name] = dict(sha256=hashlib.sha256(payload).hexdigest(), bytes=len(payload), rows=len(data))
    (args.fixture/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(manifest))


def allocation(args):
    import tracemalloc
    provider = initialize(args.source, args.fixture, args.profile)
    import taiko_application.commands  # Exclude unrelated command-module imports.
    gc.collect()
    before = memory()
    tracemalloc.start()
    command(provider, 'id649', args.profile)
    gc.collect()
    current, peak = tracemalloc.get_traced_memory()
    after = memory()
    tracemalloc.stop()
    payload = dict(profile=args.profile, retained_python_bytes=current, peak_python_bytes=peak,
                   before=before, after=after, qa_run_id=os.environ['QA_RUN_ID'],
                   note='Fresh process; net retained allocations include index and its pinyin preparation. '
                        'RSS/PSS include tracemalloc bookkeeping; use benchmark for untraced RSS/PSS.')
    args.output.write_text(json.dumps(payload, indent=2)+'\n')
    print(json.dumps(payload))


def trace(args):
    provider = initialize(args.source, args.fixture, args.profile)
    selected = cases() + [('partial_name', 'ワルルーさまの歌を')]
    cold = detail(provider, 'id649', args.profile)
    traces = {label: detail(provider, query, args.profile) for label, query in selected}
    import taiko_application.query.song as song
    import sakura_taiko_core
    files = [Path(provider.__file__).with_name(name+'.py')
             for name in ('__init__', 'provider', 'client_provider', 'resolve', 'delivery', 'catalog')]
    files += [Path(song.__file__).with_name(name+'.py')
              for name in ('song', 'context', 'song_index', 'song_matching', 'song_phonetics')]
    fingerprints = {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in files if path.exists()}
    args.output.write_text(json.dumps(dict(cold=cold, source_files=fingerprints,
        core_version=sakura_taiko_core.__version__, qa_run_id=os.environ['QA_RUN_ID'], **traces),
        ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({label: row['queries'] for label, row in traces.items()}, ensure_ascii=False))


def main():
    sys.dont_write_bytecode = True
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('action', choices=['prepare', 'benchmark', 'allocation', 'trace', 'tests'])
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--public', type=Path)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--profile', choices=['center', 'client'], default='center')
    parser.add_argument('--repetitions', type=int, default=40)
    parser.add_argument('--tests', nargs='+', default=[])
    parser.add_argument('--keyword', default='')
    parser.add_argument('--partial-only', action='store_true')
    parser.add_argument('--core-source', type=Path,
                        help='Optional pinned Core package directory (client needs Core 0.1.2)')
    args = parser.parse_args()
    assert os.environ.get('QA_RUN_ID'), 'Use scripts/memory/run_qa.sh'
    initial_resources = cgroup_resources()
    def save_resources():
        destination = Path(os.environ['QA_EVIDENCE_DIR'])/'song-query-resources.json'
        destination.write_text(json.dumps(dict(before=initial_resources, after=cgroup_resources(),
            max_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            cpu_seconds=resource.getrusage(resource.RUSAGE_SELF).ru_utime + resource.getrusage(resource.RUSAGE_SELF).ru_stime),
            indent=2)+'\n')
    atexit.register(save_resources)
    if args.core_source:
        spec = importlib.util.spec_from_file_location('sakura_taiko_core', args.core_source/'__init__.py',
                                                     submodule_search_locations=[str(args.core_source)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
    if args.action == 'prepare':
        prepare(args)
    elif args.action == 'benchmark':
        benchmark(args)
    elif args.action == 'allocation':
        allocation(args)
    elif args.action == 'trace':
        trace(args)
    else:
        sys.path[:0] = [str(args.source), str(args.source/'packages/taiko-application/src')]
        sys.path.append('/usr/lib/python3.11/site-packages')
        os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
        os.environ['TAIKO_SONG_TEST_CATALOG'] = str(args.fixture/'songs')
        import pytest
        raise SystemExit(pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider',
                                     '--basetemp', os.environ['QA_RUN_TMPDIR']+'/pytest',
                                     '-k', args.keyword, *args.tests]))


if __name__ == '__main__':
    main()
