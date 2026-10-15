from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import datetime
from typing import Any

import aiomysql
from nonebot import get_driver, logger

from .config import CONFIG

TAIKO_COMMAND_TOTAL_SOURCE = "taiko_commands_v2:total"
TAIKO_COMMAND_PLATFORM_SOURCE_PREFIX = "taiko_commands_v2:platform:"
TAIKO_COMMAND_COMMAND_SOURCE_PREFIX = "taiko_commands_v2:command:"
TAIKO_COMMAND_META_STATE_KEY = "taiko_commands_v2_meta"

ROLLUP_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS web_admin_access_rollups (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    source_key VARCHAR(64) NOT NULL,
    granularity VARCHAR(16) NOT NULL,
    bucket_start DATETIME NOT NULL,
    metric_count INT UNSIGNED NOT NULL DEFAULT 0,
    pv_count INT UNSIGNED NOT NULL DEFAULT 0,
    uv_count INT UNSIGNED NOT NULL DEFAULT 0,
    home_pv_count INT UNSIGNED NOT NULL DEFAULT 0,
    extra_json LONGTEXT DEFAULT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_web_admin_access_rollups_bucket (source_key, granularity, bucket_start),
    KEY idx_web_admin_access_rollups_bucket_start (granularity, bucket_start)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

INGEST_STATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS web_admin_ingest_state (
    source_key VARCHAR(64) NOT NULL PRIMARY KEY,
    state_json LONGTEXT NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

_queue: asyncio.Queue[dict[str, Any]] | None = None
_worker_task: asyncio.Task | None = None
_started = False
_schema_ready = False


def _bucket_start(timestamp: datetime, granularity: str) -> datetime:
    bucket = timestamp.replace(minute=0, second=0, microsecond=0)
    if granularity == "day":
        bucket = bucket.replace(hour=0)
    return bucket


def _format_bucket(timestamp: datetime) -> str:
    return timestamp.strftime("%Y-%m-%d %H:%M:%S")


def _safe_group_id(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _build_rollup_rows(records: list[dict[str, Any]]) -> list[tuple[str, str, str, int]]:
    counts: defaultdict[tuple[str, str, str], int] = defaultdict(int)
    for record in records:
        canonical = str(record.get("normalized_command") or "").strip()
        platform = str(record.get("platform") or "").strip()
        timestamp = record.get("timestamp")
        if not canonical or not platform or not isinstance(timestamp, datetime):
            continue
        for granularity in ("hour", "day"):
            bucket = _format_bucket(_bucket_start(timestamp, granularity))
            counts[(TAIKO_COMMAND_TOTAL_SOURCE, granularity, bucket)] += 1
            counts[(f"{TAIKO_COMMAND_PLATFORM_SOURCE_PREFIX}{platform}", granularity, bucket)] += 1
            counts[(f"{TAIKO_COMMAND_COMMAND_SOURCE_PREFIX}{canonical}", granularity, bucket)] += 1
    return [
        (source_key, granularity, bucket_start, metric_count)
        for (source_key, granularity, bucket_start), metric_count in counts.items()
    ]


async def ensure_method_call_schema() -> None:
    global _schema_ready
    if _schema_ready:
        return

    bot_conn = await aiomysql.connect(**CONFIG.db_config)
    taiko_conn = await aiomysql.connect(**CONFIG.taiko_db_config)
    try:
        async with bot_conn.cursor() as cursor:
            await cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS method_calls (
                    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
                    method_name VARCHAR(255) NOT NULL,
                    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    group_id VARCHAR(191) DEFAULT NULL,
                    platform VARCHAR(32) DEFAULT NULL,
                    normalized_command VARCHAR(64) DEFAULT NULL,
                    KEY idx_method_calls_timestamp (timestamp),
                    KEY idx_method_calls_normalized_command (normalized_command),
                    KEY idx_method_calls_platform (platform)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            await cursor.execute("SHOW COLUMNS FROM method_calls")
            columns = {
                str(row[0]).strip(): {
                    "type": str(row[1]).strip().lower(),
                    "null": str(row[2]).strip().upper(),
                }
                for row in (await cursor.fetchall())
            }
            if "group_id" not in columns:
                await cursor.execute(
                    "ALTER TABLE method_calls ADD COLUMN group_id VARCHAR(191) DEFAULT NULL AFTER timestamp"
                )
            elif "varchar" not in columns["group_id"]["type"]:
                await cursor.execute(
                    "ALTER TABLE method_calls MODIFY COLUMN group_id VARCHAR(191) DEFAULT NULL"
                )
            if "platform" not in columns:
                await cursor.execute(
                    "ALTER TABLE method_calls ADD COLUMN platform VARCHAR(32) DEFAULT NULL AFTER group_id"
                )
            if "normalized_command" not in columns:
                await cursor.execute(
                    "ALTER TABLE method_calls ADD COLUMN normalized_command VARCHAR(64) DEFAULT NULL AFTER platform"
                )

        async with taiko_conn.cursor() as cursor:
            await cursor.execute(ROLLUP_TABLE_SQL)
            await cursor.execute(INGEST_STATE_TABLE_SQL)
            await cursor.execute(
                """
                INSERT INTO web_admin_ingest_state (source_key, state_json)
                VALUES (%s, %s)
                ON DUPLICATE KEY UPDATE
                  state_json = CASE
                    WHEN JSON_VALID(state_json)
                         AND JSON_EXTRACT(state_json, '$.statsStartedAt') IS NOT NULL
                    THEN JSON_SET(state_json, '$.version', 2)
                    ELSE VALUES(state_json)
                  END,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    TAIKO_COMMAND_META_STATE_KEY,
                    json.dumps(
                        {
                            "version": 2,
                            "statsStartedAt": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
        _schema_ready = True
    finally:
        bot_conn.close()
        taiko_conn.close()


async def _insert_batch(records: list[dict[str, Any]]) -> None:
    if not records:
        return

    await ensure_method_call_schema()
    timestamp = datetime.now()
    materialized: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        row["timestamp"] = timestamp
        materialized.append(row)

    bot_conn = await aiomysql.connect(**CONFIG.db_config)
    taiko_conn = await aiomysql.connect(**CONFIG.taiko_db_config)
    try:
        async with bot_conn.cursor() as cursor:
            await cursor.executemany(
                """
                INSERT INTO method_calls (method_name, timestamp, group_id, platform, normalized_command)
                VALUES (%s, %s, %s, %s, %s)
                """,
                [
                    (
                        item["method_name"],
                        item["timestamp"],
                        _safe_group_id(item.get("group_id")),
                        str(item.get("platform") or "").strip() or None,
                        str(item.get("normalized_command") or "").strip() or None,
                    )
                    for item in materialized
                ],
            )

        rollup_rows = _build_rollup_rows(materialized)
        if rollup_rows:
            async with taiko_conn.cursor() as cursor:
                await cursor.executemany(
                    """
                    INSERT INTO web_admin_access_rollups
                      (source_key, granularity, bucket_start, metric_count, pv_count, uv_count, home_pv_count, extra_json)
                    VALUES (%s, %s, %s, %s, 0, 0, 0, NULL)
                    ON DUPLICATE KEY UPDATE
                      metric_count = metric_count + VALUES(metric_count),
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    rollup_rows,
                )
                await cursor.execute(
                    """
                    INSERT INTO web_admin_ingest_state (source_key, state_json)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE
                      state_json = CASE
                        WHEN JSON_VALID(state_json)
                             AND JSON_EXTRACT(state_json, '$.statsStartedAt') IS NOT NULL
                        THEN JSON_SET(
                          state_json,
                          '$.version', 2,
                          '$.lastUpdatedAt', %s
                        )
                        ELSE VALUES(state_json)
                      END,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        TAIKO_COMMAND_META_STATE_KEY,
                        json.dumps(
                            {
                                "version": 2,
                                "statsStartedAt": timestamp.isoformat(timespec="seconds") + "Z",
                                "lastUpdatedAt": timestamp.isoformat(timespec="seconds") + "Z",
                            },
                            ensure_ascii=False,
                        ),
                        timestamp.isoformat(timespec="seconds") + "Z",
                    ),
                )
    finally:
        bot_conn.close()
        taiko_conn.close()


async def enqueue_record(record: dict[str, Any]) -> None:
    if _queue is None:
        return
    await _queue.put(record)


async def _worker() -> None:
    pending: list[dict[str, Any]] = []
    while True:
        try:
            if pending:
                wait_task = asyncio.create_task(_queue.get())  # type: ignore[union-attr]
                done, _ = await asyncio.wait(
                    {wait_task},
                    timeout=CONFIG.flush_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if done:
                    pending.append(wait_task.result())
                else:
                    wait_task.cancel()
                    try:
                        await wait_task
                    except asyncio.CancelledError:
                        pass
            else:
                pending.append(await _queue.get())  # type: ignore[union-attr]

            while len(pending) < CONFIG.batch_size and not _queue.empty():  # type: ignore[union-attr]
                pending.append(_queue.get_nowait())  # type: ignore[union-attr]

            batch = pending[: CONFIG.batch_size]
            pending = pending[CONFIG.batch_size :]
            try:
                await _insert_batch(batch)
            except Exception:
                logger.exception("method_calls batch insert failed, dropped=%s", len(batch))
        except asyncio.CancelledError:
            if pending:
                try:
                    await _insert_batch(pending)
                except Exception:
                    logger.exception("method_calls final flush failed, dropped=%s", len(pending))
            raise
        except Exception:
            logger.exception("method_calls worker loop error")


async def start_store() -> None:
    global _queue, _worker_task, _started
    if _started or not CONFIG.enabled:
        return
    await ensure_method_call_schema()
    _queue = asyncio.Queue()
    _worker_task = asyncio.create_task(_worker())
    _started = True
    logger.info("method_calls store worker started")


async def stop_store() -> None:
    global _worker_task, _started
    if not _started or _worker_task is None:
        return
    _worker_task.cancel()
    try:
        await _worker_task
    except asyncio.CancelledError:
        pass
    _worker_task = None
    _started = False


def register_store_lifecycle() -> None:
    driver = get_driver()

    @driver.on_startup
    async def _start_method_calls_store() -> None:
        await start_store()

    @driver.on_shutdown
    async def _stop_method_calls_store() -> None:
        await stop_store()
