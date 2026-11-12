#!/usr/bin/env bash
# Run under the existing workspace QA wrapper. Install without switching current.
set -euo pipefail
[[ -n "${QA_RUN_ID:-}" ]] || { echo 'Use the bounded QA runner' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work=/var/tmp/taiko-b30-performance
export PIP_CACHE_DIR="$QA_RUN_TMPDIR/pip-cache"
wheelhouse="$work/wheelhouse"
mkdir -p "$wheelhouse"
for source in /opt/taiko-bot/artifacts/*.whl /home/sigaer/taiko/qa-vault/wheelhouse/*.whl; do
    target="$wheelhouse/$(basename "$source")"
    [[ -e "$target" ]] || ln -s "$source" "$target"
done
source_root="$QA_RUN_TMPDIR/source"
mkdir -p "$source_root"
git -C "$root" archive HEAD | tar -x -C "$source_root"
while IFS= read -r relative; do
    [[ -f "$root/$relative" ]] || continue
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" diff HEAD --name-only -- taiko_bot packages/taiko-application pyproject.toml deploy/runtime-lock.txt)
while IFS= read -r relative; do
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" ls-files --others --exclude-standard -- taiko_bot packages/taiko-application)
python3 -m venv --system-site-packages "$QA_RUN_TMPDIR/build-venv"
"$QA_RUN_TMPDIR/build-venv/bin/pip" install --no-deps --no-index --find-links "$wheelhouse" setuptools==84.0.0 packaging==26.3
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root/packages/taiko-application"
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root"
if [[ -d /opt/taiko-bot/releases/0.21.2 ]]; then
    [[ "$(readlink -f /opt/taiko-bot/current)" != /opt/taiko-bot/releases/0.21.2 ]] || { echo 'Refusing to reinstall the active release' >&2; exit 2; }
    /opt/taiko-bot/releases/0.21.2/bin/pip install --no-index --no-deps --force-reinstall \
        "$wheelhouse/taiko_application-0.8.3-py3-none-any.whl" "$wheelhouse/taiko_bot-0.21.2-py3-none-any.whl"
    /opt/taiko-bot/releases/0.21.2/bin/pip check
else
    bash "$root/scripts/install_release.sh" 0.21.2 "$wheelhouse"
fi
/opt/taiko-bot/releases/0.21.2/bin/python -I -c 'from taiko_bot.runtime.package_inventory import runtime_inventory; print(runtime_inventory())'
/opt/taiko-bot/releases/0.21.2/bin/python -I "$root/scripts/performance/verify_dependencies.py" --output "$work/results/dependency-parity.json"
sha256sum "$wheelhouse/taiko_application-0.8.3-py3-none-any.whl" "$wheelhouse/taiko_bot-0.21.2-py3-none-any.whl"
