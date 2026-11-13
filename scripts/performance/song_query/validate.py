"""Check archived replays, source ownership, QA exit/resource evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--test-runs', nargs='+', required=True)
    args = parser.parse_args()
    assert os.environ.get('QA_RUN_ID'), 'Use the bounded QA runner'
    read = lambda path: json.loads(path.read_text())
    protected = [
        'taiko_bot/runtime/qq_images.py', 'taiko_bot/runtime/center_markdown_media.py',
        'taiko_runtime/qq_markdown_media.py', 'taiko_runtime/platform_adapter.py',
        'taiko_bot/runtime/public/delivery.py', 'taiko_bot/runtime/public/center_messages.py',
        'scripts/deploy_taiko.sh', 'packages/taiko-application/src/taiko_application/commands/song.py',
    ]
    diff = subprocess.check_output(['git', '-C', str(args.source), 'diff', 'origin/main', '--name-only', '--', *protected], text=True)
    assert not diff.strip(), 'out-of-scope path changed'
    runs = set(args.test_runs)
    artifacts = {}
    for path in sorted(args.work.glob('*.json')):
        if path.name == 'validation.json':
            continue
        data = read(path)
        if data.get('qa_run_id'):
            runs.add(data['qa_run_id'])
        artifacts[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for role in ('center', 'client'):
        old, new = (read(args.work/f'{state}-{role}.json') for state in ('before', 'after'))
        assert old['fixture'] == new['fixture']
        assert old['results'] == new['results'], 'command drift'
        assert len(old['raw']) == len(new['raw']) == 11
        for cohort in (old, new):
            assert all(len(row['wall_ns']) == len(row['cpu_ns']) == 40 for row in cohort['raw'].values())
        old_trace, new_trace = (read(args.work/f'{state}-trace-{role}.json') for state in ('before', 'after'))
        assert old_trace['core_version'] == new_trace['core_version'] == ('0.1.1' if role == 'center' else '0.1.2')
        for label, _ in old['cases']:
            assert old_trace[label]['queries'] == new_trace[label]['queries'], 'attempt/mode drift'
        assert old_trace['partial_name']['queries'] == new_trace['partial_name']['queries']
        assert new_trace['partial_name']['queries'][-1]['mode'] == 'partial_name'
        for name, digest in new_trace['source_files'].items():
            assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, 'candidate changed after trace'
        for basename in ('song_matching.py', 'song_phonetics.py', 'resolve.py', 'delivery.py'):
            old_hash = next(value for name, value in old_trace['source_files'].items() if Path(name).name == basename)
            new_hash = next(value for name, value in new_trace['source_files'].items() if Path(name).name == basename)
            assert old_hash == new_hash, 'protected matching/delivery implementation changed'
    evidence = []
    tests = []
    for run in sorted(runs):
        assert re.fullmatch(r'qa-[a-f0-9]{12}', run)
        directory = Path('/home/sigaer/taiko/qa-vault/runs')/run/'evidence'
        manifest = read(directory/'manifest.json')
        assert manifest['exitCode'] == manifest['wrapperExitCode'] == 0
        assert manifest['childrenStopped'] is True
        entry = dict(qa_run_id=run, exit_code=manifest['exitCode'], children_stopped=True,
                     manifest_sha256=hashlib.sha256((directory/'manifest.json').read_bytes()).hexdigest())
        resources = directory/'song-query-resources.json'
        if resources.exists():
            entry['resources'] = read(resources)
            events = entry['resources']['after']['memory.events']
            assert re.search(r'^oom_kill 0$', events, re.M)
            assert re.search(r'^oom 0$', events, re.M)
        else:
            entry['resources'] = None
        evidence.append(entry)
        if run in args.test_runs:
            output = (directory/'output.log').read_text()
            match = re.search(r'\d+ passed[^\n]*', output)
            assert match, 'missing successful test summary'
            tests.append(dict(qa_run_id=run, summary=match[0]))
    songs = read(args.work/'catalog/songs/song_data.json')
    aliases = read(args.work/'catalog/songs/song_alias.json')
    queries = []
    for row in songs:
        queries.extend(str(row[key]) for key in ('song_name_jp', 'song_name') if row.get(key))
        queries.extend((str(row['id']), 'id'+str(row['id'])))
    queries.extend(alias for row in aliases for alias in row.get('aliases') or [] if isinstance(alias, str))
    output = dict(status='PASS', base_commit=subprocess.check_output(
        ['git', '-C', str(args.source), 'rev-parse', 'origin/main'], text=True).strip(),
        literal_queries_per_profile=len(set(queries)), literal_comparisons_total=2*len(set(queries)),
        additional_stage_matrix_comparisons=120, timing_samples=1920, tests=tests,
        protected_paths_unchanged=protected, qa_evidence=evidence, artifacts=artifacts,
        limitations=['offline query and brief only; no QQ end-to-end claim',
                     'memory.peak unavailable on this kernel; use process max RSS',
                     'early baseline runs have no cgroup OOM/event samples'])
    (args.work/'validation.json').write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({key: value for key, value in output.items() if key in
                      ('status', 'literal_queries_per_profile', 'literal_comparisons_total', 'timing_samples', 'tests')}))


if __name__ == '__main__':
    main()
