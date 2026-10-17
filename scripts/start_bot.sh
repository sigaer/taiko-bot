#!/usr/bin/env bash
set -euo pipefail
exec "${TAIKO_PYTHON:-/opt/taiko-bot/current/bin/python}" -I -m taiko_bot
