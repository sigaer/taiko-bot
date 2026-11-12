#!/usr/bin/env bash
# One bounded, offline build and verification session. Never activate current.
set -euo pipefail
[[ -n "${QA_RUN_ID:-}" ]] || { echo 'Use the existing bounded QA runner' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work=/var/tmp/taiko-b30-latency
wheelhouse=/var/tmp/taiko-b30-performance/wheelhouse
source_root="$QA_RUN_TMPDIR/source"
release=/opt/taiko-bot/releases/0.21.3
mkdir -p "$work" "$source_root"
export PIP_CACHE_DIR="$QA_RUN_TMPDIR/pip-cache"
git -C "$root" archive HEAD | tar -x -C "$source_root"
while IFS= read -r relative; do
    [[ -f "$root/$relative" ]] || continue
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" diff HEAD --name-only -- taiko_bot onebot_runtime pyproject.toml deploy/runtime-lock.txt)
while IFS= read -r relative; do
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" ls-files --others --exclude-standard -- taiko_bot)
python3 -m venv --system-site-packages "$QA_RUN_TMPDIR/build-venv"
"$QA_RUN_TMPDIR/build-venv/bin/pip" install --no-deps --no-index --find-links "$wheelhouse" setuptools==84.0.0 packaging==26.3
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root"
[[ "$(readlink -f /opt/taiko-bot/current)" != "$release" ]] || { echo 'Refusing to reinstall active release' >&2; exit 2; }
if [[ -d "$release" ]]; then
    "$release/bin/pip" install --no-index --no-deps --force-reinstall "$wheelhouse/taiko_bot-0.21.3-py3-none-any.whl"
else
    bash "$source_root/scripts/install_release.sh" 0.21.3 "$wheelhouse"
fi
"$release/bin/pip" check
"$release/bin/python" -I "$root/scripts/performance/verify_dependencies.py" \
    --before /opt/taiko-bot/releases/0.21.2/lib/python3.11/site-packages \
    --after "$release/lib/python3.11/site-packages" --output "$work/dependency-parity.json"
"$release/bin/python" -I "$root/scripts/performance/run_tests.py" \
    --source "$release/lib/python3.11/site-packages" --fixture /var/tmp/taiko-b30-performance/fixture \
    --tests "$root/tests/performance" "$root/tests/b30/test_update_diff.py"
"$release/bin/python" -I "$root/scripts/performance/host_events.py" \
    --fixture /var/tmp/taiko-b30-performance/fixture --work "$work/host-center-$QA_RUN_ID" --profile center
"$release/bin/python" -I -c 'import runpy,sys; sys.path.insert(0,"/var/tmp/taiko-b30-performance/core-client"); sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0],run_name="__main__")' \
    "$root/scripts/performance/host_events.py" --fixture /var/tmp/taiko-b30-performance/fixture \
    --work "$work/host-client-$QA_RUN_ID" --profile client
"$release/bin/python" -I "$root/scripts/performance/benchmark.py" \
    --source "$release/lib/python3.11/site-packages" --fixture /var/tmp/taiko-b30-performance/fixture \
    --output "$work/query-$QA_RUN_ID.jsonl" --scope query --warmup 0 --repeats 1
"$release/bin/python" -I - "$work/query-$QA_RUN_ID.jsonl" <<'PY'
import json, pathlib, sys
old = [json.loads(x) for x in pathlib.Path('/var/tmp/taiko-b30-performance/results/before-confirmed-warm-query.jsonl').read_text().splitlines()]
expected = {(x['user'], x['command']): x['output'] for x in old}
new = [json.loads(x) for x in pathlib.Path(sys.argv[1]).read_text().splitlines()]
assert len(new) == 6
assert all(x['output'] == expected[x['user'], x['command']] for x in new)
print('Six fixed query JPEGs match original baseline byte-for-byte: PASS')
PY
sha256sum "$wheelhouse/taiko_bot-0.21.3-py3-none-any.whl"
