#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
from pathlib import Path

import nonebot
from nonebot.adapters.qq import Adapter as QQAdapter
from nonebot.log import logger

from onebot_runtime.adapter import Adapter as ONEBOT_V11Adapter
from taiko_bot.public_data import PublicDataSyncError, sync_public_datasets_once
from taiko_bot.settings import ensure_runtime_dirs, get_settings
from taiko_bot.sqlite_db import ensure_schema
from taiko_bot.storage import ensure_storage_layout

os.environ.setdefault("TAIKO_BOT_ROOT", str(Path(__file__).resolve().parent))
os.environ.setdefault("DRIVER", "~fastapi+~httpx+~websockets")
_SETTINGS = get_settings()
ensure_runtime_dirs(_SETTINGS)
ensure_storage_layout(_SETTINGS)
ensure_schema()
try:
    sync_public_datasets_once(_SETTINGS)
except PublicDataSyncError as exc:
    logger.warning(f"initial taiko public data sync degraded: {exc}")

nonebot.init()
app = nonebot.get_asgi()

driver = nonebot.get_driver()
driver.register_adapter(ONEBOT_V11Adapter)
driver.register_adapter(QQAdapter)

nonebot.load_from_toml("pyproject.toml")


if __name__ == "__main__":
    nonebot.logger.warning(
        "Always use `nb run` or the project start script instead of manually running!"
    )
    nonebot.run(app="__mp_main__:app")
