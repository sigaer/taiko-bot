#!/usr/bin/env python3
"""Execute the unchanged 28 synthetic fact-test cases against installed modules.

This is a small function/parameter runner, not pytest. The adapter implements only
parametrize and raises used by that test file; it never imports source packages.
Run with a fresh role interpreter -I through the Viewer memory QA wrapper.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.metadata
import importlib.util
import itertools
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types

parser = argparse.ArgumentParser()
parser.add_argument('--tests', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assert sys.flags.isolated == 1
assert not args.output.exists()
assert importlib.metadata.version('taiko-bot') == '0.14.2'

with tempfile.TemporaryDirectory(prefix='taiko-0142-facts-', dir=os.environ['QA_RUN_TMPDIR']) as directory:
    root = Path(directory)
    (root / 'songs').mkdir()
    (root / 'userdata').mkdir()
    (root / 'songs/song_data.json').write_text('[]')
    for name in ('TAIKO_OFFLINE_ROOT', 'TAIKO_CENTER_ROOT', 'TAIKO_RUNTIME_ROOT'):
        os.environ[name] = str(root)
    os.environ['TAIKO_USERDATA_DIR'] = str(root / 'userdata')
    os.environ['TAIKO_RUNTIME_ENV_FILE'] = str(root / 'absent.env')
    os.environ['TAIKO_COMPUTE_ONLY'] = '1'
    def qa_owned_path(path):
        resolved = Path(path).resolve()
        roots = [Path(os.environ['QA_RUN_DIR']).resolve(), Path(sys.prefix).resolve(), Path(__file__).resolve().parents[2]]
        tooling = os.environ.get('QA_TEST_TOOLS_ROOT')
        if tooling:
            tools = Path(tooling).resolve()
            assert tools.is_relative_to('/home/sigaer/taiko/qa-vault/tooling')
            roots.append(tools)
        frozen = os.environ.get('TAIKO_FROZEN_BASELINE_ROOT')
        if frozen:
            baseline = Path(frozen).resolve()
            assert baseline.is_relative_to('/home/sigaer/taiko/qa-vault/sources')
            roots.append(baseline)
        return any(resolved.is_relative_to(root) for root in roots)
    violations = []
    def guard(event, values):
        if event in ('socket.connect', 'socket.getaddrinfo', 'subprocess.Popen'):
            violations.append(event)
            raise AssertionError('network/process forbidden in synthetic replay')
        if event == 'open' and isinstance(values[0], (str, bytes)):
            path = os.fsdecode(values[0])
            if (path.startswith(('/home/sigaer/taiko/', '/home/sigaer/git/', '/etc/taiko', '/root/.ossutil')) and not qa_owned_path(path)):
                violations.append(path)
                raise AssertionError('production path forbidden')
    sys.addaudithook(guard)
    import pymysql
    def deny_sql(*args, **kwargs):
        raise AssertionError('SQL forbidden in synthetic replay')
    pymysql.connect = deny_sql
    def parametrize(name, values, **kwargs):
        assert ',' not in name
        def decorate(function):
            function.parameters = getattr(function, 'parameters', []) + [(name, values)]
            return function
        return decorate
    @contextlib.contextmanager
    def raises(kind):
        try:
            yield
        except kind:
            return
        raise AssertionError('expected exception not raised')
    adapter = types.ModuleType('pytest')
    adapter.mark = types.SimpleNamespace(parametrize=parametrize)
    adapter.raises = raises
    sys.modules['pytest'] = adapter
    spec = importlib.util.spec_from_file_location('installed_fact_matrix', args.tests)
    matrix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(matrix)
    outcomes = []
    for name, function in vars(matrix).items():
        if not name.startswith('test_') or not callable(function):
            continue
        parameters = getattr(function, 'parameters', [])
        for values in itertools.product(*(items for _, items in parameters)):
            case = root / ('case-' + str(len(outcomes)))
            case.mkdir()
            arguments = dict(zip((key for key, _ in parameters), copy.deepcopy(values)))
            function(tmp_path=case, **arguments)
            outcomes.append({'test': name, 'parameterIndex': len(outcomes), 'status': 'PASS'})
    assert len(outcomes) == 28
    origins = {}
    prefixes = ('taiko_bot', 'taiko_store', 'taiko_application', 'sakura_taiko_core', 'sakura_taiko_contract')
    for name, module in tuple(sys.modules.items()):
        if name.split('.')[0] in prefixes and module is not None:
            origin = getattr(module, '__file__', None)
            assert origin and Path(origin).resolve().is_relative_to(Path(sys.prefix).resolve()), name
            origins[name] = origin
    assert origins and not violations
    report = {'status': 'PASS_INSTALLED_ORIGINAL_FACT_MATRIX', 'pass': len(outcomes),
              'interpreter': sys.executable, 'packageVersion': importlib.metadata.version('taiko-bot'),
              'testSource': str(args.tests), 'testSha256': hashlib.sha256(args.tests.read_bytes()).hexdigest(),
              'runner': 'Original test functions and parameter values; minimal parametrize/raises adapter, no pytest installation',
              'outcomes': outcomes, 'moduleOrigins': origins, 'sysPath': sys.path,
              'cgroup': Path('/proc/self/cgroup').read_text().strip()}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'status': report['status'], 'pass': len(outcomes), 'moduleCount': len(origins)}))
