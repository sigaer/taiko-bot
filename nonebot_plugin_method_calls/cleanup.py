from __future__ import annotations

from datetime import datetime, timedelta

import aiomysql
from nonebot import get_driver, logger, require

from .config import CONFIG


async def cleanup_old_method_calls() -> None:
    if not CONFIG.enabled:
        return

    cutoff = datetime.now() - timedelta(hours=CONFIG.retention_hours)
    try:
        conn = await aiomysql.connect(**CONFIG.db_config)
        async with conn.cursor() as cursor:
            await cursor.execute(
                "DELETE FROM method_calls WHERE timestamp < %s",
                (cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
            )
            deleted = cursor.rowcount
        conn.close()
        logger.info(
            f"method_calls cleanup completed: deleted={deleted} before={cutoff.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    except Exception:
        logger.exception("method_calls cleanup failed")


def register_cleanup_job() -> None:
    # Load APScheduler through NoneBot's plugin manager to avoid import-order crashes.
    require("nonebot_plugin_apscheduler")
    from nonebot_plugin_apscheduler import scheduler

    @scheduler.scheduled_job("interval", hours=12, id="method_calls_cleanup")
    async def _cleanup_old_method_calls() -> None:
        await cleanup_old_method_calls()

    driver = get_driver()

    @driver.on_startup
    async def _ensure_cleanup_job() -> None:
        if not CONFIG.enabled:
            return
        logger.info(
            "method_calls cleanup scheduled every 12h, retention=%s h",
            CONFIG.retention_hours,
        )
