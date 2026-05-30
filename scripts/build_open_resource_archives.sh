#!/usr/bin/env bash
set -euo pipefail

SOURCE_ROOT="${TAIKO_SOURCE_ROOT:-/home/sigaer/taiko}"
ASSETS_DIR="${SOURCE_ROOT}/assets"
OUTPUT_DIR="${TAIKO_OPEN_RESOURCE_DIR:-/home/sigaer/taiko-open-resources}"

mkdir -p "$OUTPUT_DIR"
rm -f "$OUTPUT_DIR"/taiko-bot-*.zip

cd "$ASSETS_DIR"
zip -qr "$OUTPUT_DIR/taiko-bot-core-assets.zip" fonts templates icons
zip -qr "$OUTPUT_DIR/taiko-bot-dress-assets.zip" dress
zip -qr "$OUTPUT_DIR/taiko-bot-nameplate-assets.zip" name_plate name_plate_dani
zip -qr "$OUTPUT_DIR/taiko-bot-cover-assets.zip" cover
zip -qr "$OUTPUT_DIR/taiko-bot-fumens-renamed.zip" fumens_renamed

du -sh "$OUTPUT_DIR"/taiko-bot-*.zip
