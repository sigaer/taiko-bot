from __future__ import annotations

from pathlib import Path

from nonebot import get_driver, logger
from nonebot.plugin import PluginMetadata

from taiko_bot.runtime.center_markdown_media import start_cleanup_task, stop_cleanup_task
from taiko_bot.runtime.center_startup_migration import (
    DEFAULT_FEATURE_SWITCH_DB_PATH,
    migrate_feature_switch_db,
)
from taiko_bot.runtime.player.center.hiroba.credentials import ensure_hiroba_credentials_table

__plugin_meta__ = PluginMetadata(
    name="taiko-runtime-init",
    description="Initialize taiko runtime and feature-switch storage.",
    usage="",
    type="application",
    extra={},
)

driver = get_driver()


@driver.on_startup
async def _run_taiko_startup_migrations() -> None:
    from taiko_bot.offline.memory import start_telemetry
    start_telemetry("taikobot")
    config = driver.config
    feature_switch_dir = Path(
        config.dict().get(
            "feature_switch_data_dir",
            str(DEFAULT_FEATURE_SWITCH_DB_PATH.parent),
        )
    )
    feature_switch_db = feature_switch_dir / DEFAULT_FEATURE_SWITCH_DB_PATH.name

    feature_switch_stats = migrate_feature_switch_db(feature_switch_db)
    try:
        ensure_hiroba_credentials_table()
    except Exception as exc:
        logger.warning("ensure_hiroba_credentials_table failed: %s", exc)
    logger.info(
        "taiko startup feature-switch migration completed: %s",
        feature_switch_stats,
    )
    start_cleanup_task()


@driver.on_shutdown
async def _shutdown_qq_markdown_cleanup_task() -> None:
    await stop_cleanup_task()
