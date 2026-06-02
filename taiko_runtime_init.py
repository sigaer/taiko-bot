from __future__ import annotations

from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata

from taiko_bot.public_data import (
    PublicDataSyncError,
    start_background_asset_sync,
    sync_public_datasets_once,
)
from taiko_bot.settings import ensure_runtime_dirs, get_settings
from taiko_bot.sqlite_db import ensure_schema
from taiko_bot.storage import ensure_storage_layout
from taiko_runtime.qq_markdown_media import start_cleanup_task, stop_cleanup_task

__plugin_meta__ = PluginMetadata(
    name="taiko-runtime-init",
    description="Prepare taiko-bot runtime directories, sqlite schema, and public data cache.",
    usage="",
    type="application",
    extra={},
)

driver = get_driver()


@driver.on_startup
async def _prepare_runtime() -> None:
    settings = get_settings()
    ensure_runtime_dirs(settings)
    ensure_storage_layout(settings)
    ensure_schema()
    try:
        result = sync_public_datasets_once(settings)
        downloaded = result.get("downloaded") or []
        if result.get("skipped"):
            logger.info("taiko public data sync skipped: cache already refreshed in this process")
        else:
            logger.info(f"taiko public data sync completed: downloaded={downloaded}")
    except PublicDataSyncError as exc:
        logger.warning(f"taiko public data sync degraded: {exc}")
    start_background_asset_sync(settings)
    logger.info("taiko asset sync manager started in background")
    start_cleanup_task()


@driver.on_shutdown
async def _shutdown_runtime() -> None:
    await stop_cleanup_task()
