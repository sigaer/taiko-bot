import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Optional

from nonebot.rule import Rule
from taiko_bot.settings import get_settings

from .bot_group_whitelist import is_group_allowed

_DATA_DIR: Optional[Path] = None
_DB_PATH: Optional[Path] = None


def _get_data_dir() -> Path:
    global _DATA_DIR
    if _DATA_DIR is None:
        from nonebot import get_driver

        driver = get_driver()
        data_dir = Path(
            driver.config.dict().get(
                "feature_switch_data_dir",
                get_settings().runtime_data_dir / "feature_handler",
            )
        )
        data_dir.mkdir(parents=True, exist_ok=True)
        _DATA_DIR = data_dir
    return _DATA_DIR


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = _get_data_dir() / "switch.db"
    return _DB_PATH

ONEBOT_V11_PLATFORM = "onebot_v11"
QQ_OFFICIAL_PLATFORM = "qq_official"

_FEATURE_CACHE_TTL = 5.0
_HANDLED_MESSAGE_RETENTION = 48 * 3600
_CLEANUP_INTERVAL = 3600

_thread_local = threading.local()
_cache_lock = threading.Lock()
_cleanup_lock = threading.Lock()
_feature_cache = {}
_last_cleanup_at = 0.0


def _get_conn() -> sqlite3.Connection:
    conn = getattr(_thread_local, "conn", None)
    if conn is None:
        conn = sqlite3.connect(_get_db_path(), timeout=1, isolation_level=None)
        _thread_local.conn = conn
    return conn


def _clear_feature_cache() -> None:
    with _cache_lock:
        _feature_cache.clear()


def _invalidate_feature_cache(group_id: str, feature: str) -> None:
    with _cache_lock:
        _feature_cache.pop((group_id, feature), None)


def _set_feature_cache(group_id: str, feature: str, value: Optional[bool]) -> None:
    with _cache_lock:
        _feature_cache[(group_id, feature)] = (value, time.monotonic())


def _get_feature_cache(group_id: str, feature: str):
    now = time.monotonic()
    with _cache_lock:
        cache_key = (group_id, feature)
        cached = _feature_cache.get(cache_key)
        if cached is None:
            return False, None
        value, cached_at = cached
        if now - cached_at > _FEATURE_CACHE_TTL:
            _feature_cache.pop(cache_key, None)
            return False, None
        return True, value


def _cleanup_old_rows(now: Optional[int] = None) -> None:
    current = int(time.time()) if now is None else int(now)
    cutoff = current - _HANDLED_MESSAGE_RETENTION
    conn = _get_conn()
    conn.execute("DELETE FROM handled_message WHERE created_at < ?", (cutoff,))


def _maybe_cleanup(now: Optional[int] = None) -> None:
    global _last_cleanup_at
    current = int(time.time()) if now is None else int(now)
    if current - _last_cleanup_at < _CLEANUP_INTERVAL:
        return
    with _cleanup_lock:
        if current - _last_cleanup_at < _CLEANUP_INTERVAL:
            return
        _cleanup_old_rows(current)
        _last_cleanup_at = current


def _normalize_group_key(group_id: str) -> str:
    normalized = str(group_id or "").strip()
    if not normalized or ":" in normalized:
        return normalized
    if normalized.isdigit():
        return f"{ONEBOT_V11_PLATFORM}:{normalized}"
    return normalized


def _migrate_legacy_group_keys(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT group_id, feature, enabled, updated_at
        FROM feature_switch
        WHERE instr(group_id, ':') = 0
        """
    ).fetchall()
    migrated = 0
    for old_group_id, feature, enabled, updated_at in rows:
        normalized_group_id = _normalize_group_key(str(old_group_id))
        if not normalized_group_id or normalized_group_id == old_group_id:
            continue
        current = conn.execute(
            """
            SELECT enabled, updated_at
            FROM feature_switch
            WHERE group_id=? AND feature=?
            """,
            (normalized_group_id, feature),
        ).fetchone()
        if current is None or int(updated_at) >= int(current[1]):
            conn.execute(
                """
                INSERT INTO feature_switch (group_id, feature, enabled, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id, feature)
                DO UPDATE SET enabled=excluded.enabled,
                              updated_at=excluded.updated_at
                """,
                (normalized_group_id, feature, enabled, updated_at),
            )
        conn.execute(
            "DELETE FROM feature_switch WHERE group_id=? AND feature=?",
            (old_group_id, feature),
        )
        migrated += 1
    if migrated:
        _clear_feature_cache()
    return migrated


def resolve_feature_group_key(event: Any) -> Optional[str]:
    group_id = getattr(event, "group_id", None)
    if group_id is not None:
        return f"{ONEBOT_V11_PLATFORM}:{group_id}"
    group_openid = getattr(event, "group_openid", None)
    if group_openid is not None:
        return f"{QQ_OFFICIAL_PLATFORM}:{group_openid}"
    return None


def is_first_handler(msg_id: str) -> bool:
    _maybe_cleanup()
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        conn.execute(
            "INSERT INTO handled_message (msg_id, created_at) VALUES (?, ?)",
            (msg_id, int(time.time())),
        )
        conn.execute("COMMIT;")
        return True
    except sqlite3.IntegrityError:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        return False
    except sqlite3.OperationalError:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        return False


def init_db() -> None:
    conn = sqlite3.connect(_get_db_path(), timeout=1, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS feature_switch (
              group_id   TEXT NOT NULL,
              feature    TEXT NOT NULL,
              enabled    INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              PRIMARY KEY(group_id, feature)
            );
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS handled_message (
              msg_id     TEXT PRIMARY KEY,
              created_at INTEGER NOT NULL
            );
            """
        )
        _migrate_legacy_group_keys(conn)
    finally:
        conn.close()
    _maybe_cleanup(int(time.time()))


def get_feature(group_id: str, feature: str) -> Optional[bool]:
    normalized_group_id = _normalize_group_key(group_id)
    has_cached, cached = _get_feature_cache(normalized_group_id, feature)
    if has_cached:
        return cached

    conn = _get_conn()
    cur = conn.execute(
        "SELECT enabled FROM feature_switch WHERE group_id=? AND feature=?",
        (normalized_group_id, feature),
    )
    row = cur.fetchone()
    value = None if row is None else bool(row[0])
    _set_feature_cache(normalized_group_id, feature, value)
    return value


def is_feature_enabled(group_id: str, feature: str, default: bool = True) -> bool:
    value = get_feature(group_id, feature)
    return default if value is None else value


def apply_switch(group_id: str, feature: str, enabled: bool) -> bool:
    normalized_group_id = _normalize_group_key(group_id)
    conn = _get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE;")
        cur = conn.execute(
            "SELECT enabled FROM feature_switch WHERE group_id=? AND feature=?",
            (normalized_group_id, feature),
        )
        row = cur.fetchone()
        if row is not None and bool(row[0]) == enabled:
            conn.execute("COMMIT;")
            _set_feature_cache(normalized_group_id, feature, enabled)
            return False

        conn.execute(
            """
            INSERT INTO feature_switch (group_id, feature, enabled, updated_at)
            VALUES (?, ?, ?, strftime('%s','now'))
            ON CONFLICT(group_id, feature)
            DO UPDATE SET enabled=excluded.enabled,
                          updated_at=excluded.updated_at
            """,
            (normalized_group_id, feature, int(enabled)),
        )
        conn.execute("COMMIT;")
        _set_feature_cache(normalized_group_id, feature, enabled)
        return True
    except sqlite3.OperationalError:
        try:
            conn.execute("ROLLBACK;")
        except Exception:
            pass
        _invalidate_feature_cache(normalized_group_id, feature)
        return False


def feature_on(feature: str, default: bool = True) -> Rule:
    async def _checker(event) -> bool:
        group_id = resolve_feature_group_key(event)
        if group_id is None:
            return True
        bot_id = str(getattr(event, "self_id", "") or "")
        raw_group = str(getattr(event, "group_id", "") or "")
        if not is_group_allowed(bot_id, raw_group):
            return False
        return is_feature_enabled(group_id, feature, default=default)

    return Rule(_checker)
