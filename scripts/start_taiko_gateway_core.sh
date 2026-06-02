#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=clear_nb_inherited_proxy_env.sh
source "${SCRIPT_DIR}/clear_nb_inherited_proxy_env.sh"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

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
CORE_HOST="${TAIKO_CORE_HOST:-127.0.0.1}"
CORE_PORT="${TAIKO_CORE_PORT:-37563}"
CORE_WORKERS="${TAIKO_CORE_WORKERS:-1}"
GATEWAY_HOST="${TAIKO_GATEWAY_HOST:-0.0.0.0}"
GATEWAY_PORT="${TAIKO_GATEWAY_PORT:-37564}"
GATEWAY_WORKERS="${TAIKO_GATEWAY_WORKERS:-1}"
BOT_POOL_METRICS_SERVICE_NAME="${BOT_POOL_METRICS_SERVICE_NAME:-taiko}"

RUNTIME_DIR="${ROOT_DIR}/runtime/gateway-core"
LOG_DIR="${RUNTIME_DIR}/logs"
PID_DIR="${RUNTIME_DIR}/pids"
CORE_PID_FILE="${PID_DIR}/core.pid"
GATEWAY_PID_FILE="${PID_DIR}/gateway.pid"
CORE_LOG_FILE="${LOG_DIR}/core.log"
GATEWAY_LOG_FILE="${LOG_DIR}/gateway.log"
CORE_PID=""
GATEWAY_PID=""

if [[ -d "${ROOT_DIR}/.venv" ]]; then
  export VIRTUAL_ENV="${ROOT_DIR}/.venv"
  export PATH="${VIRTUAL_ENV}/bin:${PATH}"
fi

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "missing command: $1" >&2
    exit 1
  }
}

read_pidfile() {
  [[ -f "$1" ]] && tr -d '[:space:]' <"$1"
}

is_pid_alive() {
  [[ -n "$1" ]] && kill -0 "$1" 2>/dev/null
}

port_busy() {
  ss -ltnp | rg -q "[:.]$1[[:space:]]"
}

wait_port() {
  local host="$1"
  local port="$2"
  local timeout="${3:-30}"
  for _ in $(seq 1 "$timeout"); do
    "$PYTHON_BIN" - "$host" "$port" <<'PY' >/dev/null 2>&1 && return 0
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect((host, port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
    sleep 1
  done
  return 1
}

stop_pid_tree() {
  local pid="$1"
  if is_pid_alive "$pid"; then
    pkill -TERM -P "$pid" 2>/dev/null || true
    kill -TERM "$pid" 2>/dev/null || true
  fi
}

cleanup() {
  local code=$?
  trap - EXIT INT TERM
  stop_pid_tree "$GATEWAY_PID"
  stop_pid_tree "$CORE_PID"
  rm -f "$CORE_PID_FILE" "$GATEWAY_PID_FILE"
  exit "$code"
}

require_cmd "$PYTHON_BIN"
require_cmd rg
require_cmd ss
mkdir -p "$LOG_DIR" "$PID_DIR"

for file in "$CORE_PID_FILE" "$GATEWAY_PID_FILE"; do
  pid="$(read_pidfile "$file" || true)"
  if [[ -n "$pid" ]] && ! is_pid_alive "$pid"; then
    rm -f "$file"
  fi
done

existing_core="$(read_pidfile "$CORE_PID_FILE" || true)"
existing_gateway="$(read_pidfile "$GATEWAY_PID_FILE" || true)"
if is_pid_alive "$existing_core"; then
  echo "taiko core already running: pid=${existing_core}" >&2
  exit 1
fi
if is_pid_alive "$existing_gateway"; then
  echo "taiko gateway already running: pid=${existing_gateway}" >&2
  exit 1
fi
if port_busy "$CORE_PORT"; then
  echo "taiko core port busy: ${CORE_HOST}:${CORE_PORT}" >&2
  exit 1
fi
if port_busy "$GATEWAY_PORT"; then
  echo "taiko gateway port busy: ${GATEWAY_HOST}:${GATEWAY_PORT}" >&2
  exit 1
fi

trap cleanup EXIT INT TERM

BOT_POOL_METRICS_SERVICE_NAME="$BOT_POOL_METRICS_SERVICE_NAME" \
"$PYTHON_BIN" -m uvicorn bot_core:app \
  --host "$CORE_HOST" \
  --port "$CORE_PORT" \
  --workers "$CORE_WORKERS" \
  >>"$CORE_LOG_FILE" 2>&1 &
CORE_PID=$!
echo "$CORE_PID" >"$CORE_PID_FILE"

if ! wait_port "$CORE_HOST" "$CORE_PORT" 60; then
  echo "taiko core failed to listen on ${CORE_HOST}:${CORE_PORT}" >&2
  exit 1
fi

ONEBOT_GATEWAY_SERVICE_NAME="taiko" \
ONEBOT_GATEWAY_CORE_WS_URL="ws://${CORE_HOST}:${CORE_PORT}/onebot/v11/ws" \
ONEBOT_GATEWAY_CORE_HTTP_URL="http://${CORE_HOST}:${CORE_PORT}" \
ONEBOT_GATEWAY_ALLOW_CROSS_HOST_TAKEOVER="${ONEBOT_GATEWAY_ALLOW_CROSS_HOST_TAKEOVER:-1}" \
ONEBOT_GATEWAY_DUPLICATE_TAKEOVER_IDLE="${ONEBOT_GATEWAY_DUPLICATE_TAKEOVER_IDLE:-0}" \
"$PYTHON_BIN" -m uvicorn bot_gateway:app \
  --host "$GATEWAY_HOST" \
  --port "$GATEWAY_PORT" \
  --workers "$GATEWAY_WORKERS" \
  >>"$GATEWAY_LOG_FILE" 2>&1 &
GATEWAY_PID=$!
echo "$GATEWAY_PID" >"$GATEWAY_PID_FILE"

if ! wait_port "127.0.0.1" "$GATEWAY_PORT" 30; then
  echo "taiko gateway failed to listen on ${GATEWAY_HOST}:${GATEWAY_PORT}" >&2
  exit 1
fi

echo "taiko gateway/core started"
echo "core_pid=${CORE_PID}"
echo "gateway_pid=${GATEWAY_PID}"
echo "core_url=ws://${CORE_HOST}:${CORE_PORT}/onebot/v11/ws"
echo "gateway_url=ws://${GATEWAY_HOST}:${GATEWAY_PORT}/onebot/v11/ws"
echo "core_log=${CORE_LOG_FILE}"
echo "gateway_log=${GATEWAY_LOG_FILE}"

while true; do
  if ! is_pid_alive "$CORE_PID"; then
    wait "$CORE_PID"
    exit $?
  fi
  if ! is_pid_alive "$GATEWAY_PID"; then
    wait "$GATEWAY_PID"
    exit $?
  fi
  sleep 2
done
