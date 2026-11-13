"""Read-only final scope/lifecycle evidence; no secrets, DB, service mutation."""
import argparse
import ast
import hashlib
import json
from importlib.metadata import PackageNotFoundError, version
import os
from pathlib import Path
import platform
import subprocess
import tomllib

BASE = '070442ef19afc1827a79aa542e092c50e27b0994'
PROTECTED = [
    'packages', 'scripts/performance/song_query', 'docs/performance/song-query/phase1',
    'taiko_bot/runtime/public/catalog.py', 'taiko_bot/runtime/public/provider.py',
    'taiko_bot/runtime/public/client_provider.py', 'taiko_bot/runtime/public/resolve.py',
    'taiko_bot/runtime/public/center_messages.py', 'taiko_bot/runtime/public/client_messages.py',
    'taiko_bot/runtime/qq_images.py', 'taiko_bot/runtime/center_markdown_media.py',
    'taiko_bot/runtime/player', 'taiko_bot/runtime/community',
    'tests/test_song_search.py', 'tests/test_song_phonetics.py',
    'tests/test_song_visibility.py', 'tests/test_song_catalog_snapshot.py',
    'deploy/services', 'scripts/deploy.sh',
]
ALLOWED = {
    '.env.example', 'README.md', 'pyproject.toml', 'deploy/runtime-lock.txt',
    'taiko_bot/static_fumens.py', 'taiko_bot/offline/static_fumens.py',
    'taiko_bot/runtime/public/__init__.py', 'taiko_bot/runtime/public/delivery.py',
    'taiko_bot/runtime/public/static_fumens.py', 'taiko_bot/runtime/public/warmup.py',
    'tests/test_static_fumens.py', 'tests/test_static_fumen_delivery.py',
}


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--expected-production-pid', type=int, required=True)
    args = parser.parse_args()
    assert os.environ.get('QA_RUN_ID'), 'Use memory QA runner'
    def git(*arguments):
        return subprocess.check_output(['git', '-C', str(args.source), *arguments], text=True).strip()
    assert not git('diff', BASE, '--name-only', '--', *PROTECTED), 'protected phase/global code changed'
    git('diff', BASE, '--check')
    paths = set(git('diff', BASE, '--name-only').splitlines())
    paths.update(git('ls-files', '--others', '--exclude-standard').splitlines())
    assert paths and all(path in ALLOWED or path.startswith(('docs/performance/song-query/phase2/',
        'scripts/performance/song_query_phase2/')) for path in paths), 'change scope escaped allowlist'
    for path in paths:
        if path.endswith('.py'):
            ast.parse((args.source/path).read_text(), filename=path)
    project = tomllib.loads((args.source/'pyproject.toml').read_text())
    assert project['project']['version'] == '0.24.0'
    assert 'taiko-bot==0.24.0' in (args.source/'deploy/runtime-lock.txt').read_text().splitlines()
    env = (args.source/'.env.example').read_text().splitlines()
    assert 'TAIKO_STATIC_FUMEN_ENABLED=0' in env and 'TAIKO_SONG_QUERY_PREWARM=0' in env
    production = subprocess.check_output(['systemctl', 'show', 'taiko-bot.service',
        '-p', 'MainPID', '-p', 'ExecMainStartTimestamp'], text=True).strip()
    assert f'MainPID={args.expected_production_pid}' in production.splitlines(), 'production PID changed externally'
    publication = Path('/home/sigaer/taiko/output/qq_markdown_cache/qq-delivery-probe/song-query-phase2')
    assert not publication.exists(), 'owned test namespace not removed'
    assert not Path('/var/tmp/taiko-song-query-phase2-private/runtime/songs/static_fumen_manifest.json').exists()
    reports = args.source/'docs/performance/song-query/phase2'
    artifacts = json.loads((reports/'artifacts.json').read_text())
    assert set(artifacts) == {p.name for p in reports.iterdir() if p.is_file() and p.name != 'artifacts.json'}
    for name, metadata in artifacts.items():
        path = reports/name
        assert path.stat().st_size == metadata['bytes'], 'evidence size mismatch'
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == metadata['sha256'], 'evidence hash mismatch'
    versions = {}
    for name in ('nonebot2', 'nonebot-adapter-qq', 'nonebot-adapter-onebot', 'httpx', 'httpcore',
                 'Pillow', 'fuzzywuzzy', 'sakura-taiko-core'):
        try:
            versions[name] = version(name)
        except PackageNotFoundError:
            versions[name] = None
    evidence = dict(schema=1, base_commit=BASE, branch=git('branch', '--show-current'),
        protected_paths=PROTECTED, protected_unchanged=True, changed_paths=sorted(paths),
        ast_parse=True, default_disabled=True, version='0.24.0',
        evidence_hashes=True,
        production_process=production.splitlines(), owned_public_test_namespace_removed=True,
        isolated_manifest_removed=True, qa_run_id=os.environ['QA_RUN_ID'],
        environment=dict(python=platform.python_version(), platform=platform.platform(),
                         logical_cpus=os.cpu_count(), dependencies=versions,
                         core_note='Core 0.1.2 regression explicitly loads repository source; benchmarks use installed 0.1.1'))
    args.output.write_text(json.dumps(evidence, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(scope='PASS', protected_unchanged=True, files=len(paths))))


if __name__ == '__main__':
    main()
