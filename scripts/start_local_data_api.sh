#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_VENV_PYTHON="${ROOT_DIR}/.venv/bin/python"
if [[ -n "${PYTHON_BIN:-}" ]]; then
  :
elif [[ -x "$DEFAULT_VENV_PYTHON" ]]; then
  PYTHON_BIN="$DEFAULT_VENV_PYTHON"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "missing command: python3/python" >&2
  exit 1
fi
API_HOST="${TAIKO_LOCAL_DATA_API_HOST:-127.0.0.1}"
API_PORT="${TAIKO_LOCAL_DATA_API_PORT:-37565}"

cd "$ROOT_DIR"
exec "$PYTHON_BIN" -m uvicorn taiko_data_api:app --host "$API_HOST" --port "$API_PORT"
