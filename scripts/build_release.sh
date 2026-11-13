#!/usr/bin/env bash
# Build and install a candidate under the existing bounded QA runner.
set -euo pipefail
[[ -n "${QA_RUN_ID:-}" ]] || { echo 'Use the bounded QA runner' >&2; exit 2; }
[[ $# == 2 && "$1" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'Usage: build_release.sh VERSION WHEELHOUSE' >&2; exit 2; }
version="$1"
wheelhouse="$2"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release="/opt/taiko-bot/releases/$version"
[[ "$(readlink -f /opt/taiko-bot/current)" != "$release" ]] || { echo 'Refusing to rebuild active release' >&2; exit 2; }
mkdir -p "$wheelhouse"
wheelhouse="$(realpath "$wheelhouse")"
for source in /opt/taiko-bot/artifacts/*.whl /var/tmp/taiko-bxx-summary/wheelhouse/*.whl; do
    [[ -f "$source" ]] || continue
    target="$wheelhouse/$(basename "$source")"
    [[ -e "$target" ]] || ln -s "$source" "$target"
done
source_root="$QA_RUN_TMPDIR/source"
mkdir -p "$source_root"
git -C "$root" archive HEAD | tar -x -C "$source_root"
paths=(taiko_bot taiko_runtime taiko_store onebot_runtime feature_handler pyproject.toml README.md deploy/runtime-lock.txt)
while IFS= read -r relative; do
    if [[ ! -f "$root/$relative" ]]; then rm -f "$source_root/$relative"; continue; fi
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" diff HEAD --name-only -- "${paths[@]}"; git -C "$root" ls-files --others --exclude-standard -- "${paths[@]}")
export PIP_CACHE_DIR="$QA_RUN_TMPDIR/pip-cache"
python3 -m venv --system-site-packages "$QA_RUN_TMPDIR/build-venv"
"$QA_RUN_TMPDIR/build-venv/bin/pip" install --no-deps --no-index --find-links "$wheelhouse" setuptools==84.0.0 packaging==26.3
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root"
if [[ -d "$release" ]]; then
    "$release/bin/pip" install --no-index --no-deps --force-reinstall "$wheelhouse/taiko_bot-${version}-py3-none-any.whl"
    "$release/bin/pip" check
else
    bash "$source_root/scripts/install_release.sh" "$version" "$wheelhouse"
fi
sha256sum "$wheelhouse/taiko_bot-${version}-py3-none-any.whl"
