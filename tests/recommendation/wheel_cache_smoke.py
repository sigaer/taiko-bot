"""Dependency-free packaging/loader units; full command tests run separately.

Extract only the installed JSON cache loaders, without importing a Bot driver or
substituting the business algorithms. This catches the old path-only cache on CI.
"""
import ast
from functools import lru_cache
import importlib.metadata
import json
import os
from pathlib import Path
import tempfile

distribution = importlib.metadata.distribution('taiko-bot')
assert not json.loads(distribution.read_text('direct_url.json') or '{}').get('dir_info', {}).get('editable')
modules = ('center/duplicate_versions.py', 'center/b30_support/duplicate_versions.py',
           'center/recommendation_support/duplicate_versions.py', 'client/recommendation_support/catalog.py')
with tempfile.TemporaryDirectory(dir=os.environ.get('QA_RUN_TMPDIR', os.environ.get('RUNNER_TEMP', '/var/tmp'))) as directory:
    path = Path(directory)/'catalog.json'
    for module in modules:
        file = distribution.locate_file('taiko_bot/runtime/player/'+module)
        tree = ast.parse(file.read_text())
        functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('_load_song_data_mtime', '_load_song_data_revision')]
        namespace = dict(json=json, Path=Path, lru_cache=lru_cache)
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *functions], type_ignores=[])), str(file), 'exec'), namespace)
        load = namespace['_load_song_data_mtime']
        path.write_text('[{"id":1,"song_name":"A"}]')
        first = load(str(path));assert first[1][0]['song_name'] == 'A'
        path.write_text('[{"id":1,"song_name":"B"}]')
        os.utime(path, ns=(first[0]+1_000_000, first[0]+1_000_000))
        second = load(str(path));assert second[1][0]['song_name'] == 'B', module+' retained stale catalog'
        assert second[0] != first[0]
        assert load(str(path)) is second
print('Four installed wheel catalog revision loader units: PASS')
