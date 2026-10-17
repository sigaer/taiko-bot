#!/usr/bin/env bash
# Run under the repository's bounded build runner. Wheels include private dependencies.
set -euo pipefail
[[ $# == 2 ]] || { echo 'Usage: install_release.sh VERSION WHEELHOUSE' >&2; exit 2; }
version="$1"
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 2
wheelhouse="$(realpath "$2")"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
release="/opt/taiko-bot/releases/$version"
[[ ! -e "$release" ]] || { echo 'Release already exists; choose a new version' >&2; exit 1; }
python3 -m venv "$release"
"$release/bin/pip" install --no-index --find-links "$wheelhouse" -c "$root/deploy/runtime-lock.txt" "taiko-bot[center,hdu]==$version"
"$release/bin/pip" check
