#!/usr/bin/env bash
# Run only inside the existing bounded QA runner; install without activation.
set -euo pipefail
[[ -n "${QA_RUN_ID:-}" ]] || { echo 'Use the bounded QA runner' >&2; exit 2; }
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
work=/var/tmp/taiko-bxx-summary
source_root="$QA_RUN_TMPDIR/source"
wheelhouse="$work/wheelhouse"
mkdir -p "$source_root" "$wheelhouse"
export PIP_CACHE_DIR="$QA_RUN_TMPDIR/pip-cache"
for source in /opt/taiko-bot/artifacts/*.whl /var/tmp/taiko-b30-performance/wheelhouse/*.whl; do
    target="$wheelhouse/$(basename "$source")"
    [[ -e "$target" ]] || ln -s "$source" "$target"
done
git -C "$root" archive HEAD | tar -x -C "$source_root"
while IFS= read -r relative; do
    [[ -f "$root/$relative" ]] || continue
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" diff HEAD --name-only -- taiko_bot taiko_store packages/taiko-application pyproject.toml deploy/runtime-lock.txt)
while IFS= read -r relative; do
    mkdir -p "$source_root/$(dirname "$relative")"
    cp -p "$root/$relative" "$source_root/$relative"
done < <(git -C "$root" ls-files --others --exclude-standard -- taiko_bot taiko_store packages/taiko-application)
python3 -m venv --system-site-packages "$QA_RUN_TMPDIR/build-venv"
"$QA_RUN_TMPDIR/build-venv/bin/pip" install --no-deps --no-index --find-links "$wheelhouse" setuptools==84.0.0 packaging==26.3
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root/packages/taiko-application"
"$QA_RUN_TMPDIR/build-venv/bin/pip" wheel --no-deps --no-build-isolation --no-index --wheel-dir "$wheelhouse" "$source_root"
release=/opt/taiko-bot/releases/0.22.1
[[ "$(readlink -f /opt/taiko-bot/current)" != "$release" ]] || { echo 'Refusing to reinstall active release' >&2; exit 2; }
if [[ -d "$release" ]]; then
    "$release/bin/pip" install --no-index --find-links "$wheelhouse" -r "$source_root/deploy/runtime-lock.txt" "taiko-bot[center]==0.22.1"
    "$release/bin/pip" install --no-index --no-deps --force-reinstall \
        "$wheelhouse/taiko_application-0.9.1-py3-none-any.whl" "$wheelhouse/taiko_bot-0.22.1-py3-none-any.whl"
else
    bash "$source_root/scripts/install_release.sh" 0.22.1 "$wheelhouse"
fi
"$release/bin/pip" check
sha256sum "$wheelhouse/taiko_application-0.9.1-py3-none-any.whl" "$wheelhouse/taiko_bot-0.22.1-py3-none-any.whl"
