#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${TAIKO_SOURCE_ROOT:-/home/sigaer/taiko}"
ASSETS_DIR="${SOURCE_ROOT}/assets"
OUTPUT_DIR="${TAIKO_OPEN_RESOURCE_DIR:-/home/sigaer/taiko-open-resources}"

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR"/taiko-bot*.zip

cd "$ASSETS_DIR"
zip -qr "$OUTPUT_DIR/taiko-bot-assets.zip" .

du -sh "$OUTPUT_DIR"/taiko-bot-assets.zip
