#!/usr/bin/env bash
# Serial installed-package checks under the workspace's existing QA cgroup.
set -euo pipefail
[[ -n "${QA_RUN_ID:-}" ]] || { echo 'Use the bounded QA runner' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python=/opt/taiko-bot/releases/0.22.1/bin/python
installed=/opt/taiko-bot/releases/0.22.1/lib/python3.11/site-packages
fixture=/var/tmp/taiko-b30-performance/fixture
work="/var/tmp/taiko-bxx-summary/verification-$QA_RUN_ID"
mkdir -p "$work"
"$python" -I "$root/scripts/performance/run_tests.py" --source "$installed" --fixture "$fixture" \
    --tests "$root/tests/performance" "$root/tests/b30/test_update_diff.py" "$root/tests/test_merged_materialization_bounds.py"
"$python" -I "$root/scripts/performance/host_events.py" --fixture "$fixture" --work "$work/center" --profile center
"$python" -I -c 'import runpy,sys; sys.path.insert(0,"/var/tmp/taiko-b30-performance/core-client"); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name="__main__")' \
    "$root/scripts/performance/host_events.py" --fixture "$fixture" --work "$work/client" --profile client
"$python" -I - "$root" "$work" <<'PY'
import os, sys
from pathlib import Path
sys.path.append('/usr/lib/python3.11/site-packages')
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
import pytest
root, work = map(Path, sys.argv[1:])
tests = ['test_daily_service.py', 'test_snapshot_daily_models.py', 'test_source_service.py', 'test_hiroba_source.py']
raise SystemExit(pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider', '--basetemp', str(work/'service-tests'),
                             *[str(root/'tests/server'/name) for name in tests]]))
PY
"$python" -I - "$root" <<'PY'
import os, sys
from pathlib import Path
sys.path.append('/usr/lib/python3.11/site-packages')
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
import pytest
root = Path(sys.argv[1])
raise SystemExit(pytest.main(['-q', '--tb=short', '-p', 'no:cacheprovider',
    '--basetemp', str(Path(os.environ['QA_RUN_TMPDIR'])/'offline-tests'),
    str(root/'tests/offline/test_backfill.py'), str(root/'tests/offline/test_viewer.py')]))
PY
"$python" -I "$root/scripts/performance/benchmark.py" --source "$installed" --fixture "$fixture" \
    --output "$work/queries.jsonl" --scope query --warmup 1 --repeats 3
"$python" -I - "$work/queries.jsonl" <<'PY'
import json, sys
from pathlib import Path
rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
assert len(rows) == 18 and all(row['output']['kind'] == 'image' for row in rows)
for row in rows:
    for phase in ('B.history._history_snapshot_inputs', 'B.history._reconstruct_user_snapshots',
                  'B.history._build_daily_rating_points_from_view'):
        assert row['stages'].get(phase, {}).get('calls', 0) == 0
print('18 installed full-image queries; zero historical reconstruction calls: PASS')
PY
"$python" -I - "$root" "$installed" <<'PY'
from pathlib import Path
import hashlib, subprocess, sys
root, installed = map(Path, sys.argv[1:])
names = subprocess.check_output(['git', '-C', str(root), 'diff', '3e0ca22', '--name-only'], text=True).splitlines()
names += subprocess.check_output(['git', '-C', str(root), 'ls-files', '--others', '--exclude-standard'], text=True).splitlines()
checked = 0
for name in names:
    if name.startswith(('taiko_bot/', 'taiko_store/')) and name.endswith('.py'):
        relative = name
    elif name.startswith('packages/taiko-application/src/') and name.endswith('.py'):
        relative = name.removeprefix('packages/taiko-application/src/')
    else:
        continue
    assert hashlib.sha256((root/name).read_bytes()).digest() == hashlib.sha256((installed/relative).read_bytes()).digest(), relative
    checked += 1
print(f'{checked} changed source files match the installed wheel: PASS')
PY
echo "Installed BXX verification: $work"
