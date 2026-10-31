#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${TAIKO_SOURCE_ROOT:-/home/sigaer/taiko}"
ASSETS_DIR="${SOURCE_ROOT}/assets"
OUTPUT_DIR="${TAIKO_OPEN_RESOURCE_DIR:-/home/sigaer/taiko-open-resources}"
SCOPE="${1:-all}"
[[ "$SCOPE" == all || "$SCOPE" == dress || "$SCOPE" == nameplate ]] || { echo 'Usage: build_open_resource_archives.sh [all|dress|nameplate]' >&2; exit 2; }

mkdir -p "$OUTPUT_DIR"
STAGING_DIR="$(mktemp -d "$OUTPUT_DIR/.resource-build.XXXXXX")"
trap 'rm -rf "$STAGING_DIR"' EXIT

require_paths() {
  local missing=0
  for rel_path in "$@"; do
    if [[ ! -e "$ASSETS_DIR/$rel_path" ]]; then
      echo "missing asset path: $ASSETS_DIR/$rel_path" >&2
      missing=1
    fi
  done
  if [[ "$missing" -ne 0 ]]; then
    exit 1
  fi
}

build_zip() {
  local output_name="$1"
  shift
  (
    cd "$ASSETS_DIR"
    zip -qr "$STAGING_DIR/$output_name" "$@"
  )
  unzip -tq "$STAGING_DIR/$output_name" >/dev/null
  mv -f "$STAGING_DIR/$output_name" "$OUTPUT_DIR/$output_name"
}

CORE_ITEMS=(fonts templates icons)
COVER_ITEMS=(cover)
DRESS_ITEMS=(dress)
NAMEPLATE_ITEMS=(name_plate name_plate_dani)
FUMENS_ITEMS=(fumens)
ALL_ITEMS=(
  "${CORE_ITEMS[@]}"
  "${COVER_ITEMS[@]}"
  "${DRESS_ITEMS[@]}"
  "${NAMEPLATE_ITEMS[@]}"
  "${FUMENS_ITEMS[@]}"
)

require_paths "${ALL_ITEMS[@]}"

if [[ "$SCOPE" == all || "$SCOPE" == dress ]]; then
  build_zip "taiko-bot-dress-assets.zip" "${DRESS_ITEMS[@]}"
fi
if [[ "$SCOPE" == all ]]; then
  build_zip "taiko-bot-core-assets.zip" "${CORE_ITEMS[@]}"
  build_zip "taiko-bot-cover-assets.zip" "${COVER_ITEMS[@]}"
  build_zip "taiko-bot-fumens-assets.zip" "${FUMENS_ITEMS[@]}"
  build_zip "taiko-bot-fumens-renamed.zip" "${FUMENS_ITEMS[@]}"
fi
if [[ "$SCOPE" == all || "$SCOPE" == nameplate ]]; then
  build_zip "taiko-bot-nameplate-assets.zip" "${NAMEPLATE_ITEMS[@]}"
fi
build_zip "taiko-bot-assets.zip" "${ALL_ITEMS[@]}"

du -sh "$OUTPUT_DIR"/taiko-bot*.zip
