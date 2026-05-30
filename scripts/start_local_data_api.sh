#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-${ROOT_DIR}/.venv/bin/python}"
API_HOST="${TAIKO_LOCAL_DATA_API_HOST:-127.0.0.1}"
API_PORT="${TAIKO_LOCAL_DATA_API_PORT:-37565}"

cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m uvicorn taiko_data_api:app --host "$API_HOST" --port "$API_PORT"
