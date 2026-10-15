"""Read-only retirement/protected-scope audit against this batch's exact baselines."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys

bot, sakura = map(Path, sys.argv[1:])
refs = {bot: '16d118d', sakura: '084d13d'}
for root, prefix in ((bot, ''), (sakura, 'taiko/')):
    assert not (root / prefix / 'plugins/taiko.py').exists()
    changed = subprocess.check_output(['git', 'diff', refs[root], '--name-only'], cwd=root, text=True).splitlines()
    protected = ('taiko_viewer/', 'taiko/taiko_viewer/', 'packages/sakura-taiko-core/', 'packages/sakura-taiko-contract/', 'packages/taiko-application/src/', 'taiko_store/', 'taiko/taiko_store/')
    assert not any(path.startswith(protected) or path.endswith('.sql') for path in changed), changed
    for directory in ('plugins', 'taiko_bot', 'taiko_runtime', 'feature_handler'):
        for path in (root/prefix/directory).rglob('*.py'):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom): assert node.module != 'plugins.taiko', path
                if isinstance(node, ast.Import): assert all(a.name != 'plugins.taiko' for a in node.names), path
    assert all(not path.startswith(('nonebot_plugin_method_calls/', 'miku_bot/')) for path in changed) if root==sakura else True
for name in ('store.py', 'cleanup.py', 'recorder.py'):
    old = subprocess.check_output(['git', 'show', f'084d13d:taiko/nonebot_plugin_method_calls/{name}'], cwd=sakura)
    assert old == (bot/'nonebot_plugin_method_calls'/name).read_bytes(), name
assert not (sakura/'taiko/nonebot_plugin_method_calls').exists()
assert not (sakura/'taiko/plugins/utils/annual_report_command.py').exists()
# Exact annual computation/limits/delivery body, ignoring relocated imports.
def body(text):
    return [ast.dump(n) for n in ast.parse(text).body if not isinstance(n,(ast.Import, ast.ImportFrom))]
old = subprocess.check_output(['git','show','084d13d:taiko/plugins/utils/annual_report_command.py'],cwd=sakura,text=True)
assert body(old)==body((bot/'taiko_bot/runtime/community/center/annual_report_command.py').read_text())
removed = subprocess.check_output(['git','diff','--numstat','084d13d'],cwd=sakura,text=True).splitlines()
removed_files = {line.split('\t')[2]: int(line.split('\t')[1]) for line in removed if line.split('\t')[0]=='0' and not (sakura/line.split('\t')[2]).exists()}
print(json.dumps({'status':'PASS','sakura_removed_files':removed_files,'sakura_removed_lines':sum(removed_files.values()),'protected_protocol_and_schema_changes':0,'stats_storage_body':'byte identical','annual_body':'AST identical'},ensure_ascii=False,indent=2))
