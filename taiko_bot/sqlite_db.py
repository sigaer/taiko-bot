from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from typing import Iterable, Sequence

from .settings import get_settings


def _sqlite_path() -> str:
    settings = get_settings()
    settings.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    return str(settings.sqlite_path)


class SQLiteCompatCursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    def execute(self, query: str, params: Sequence[object] | None = None):
        sql = re.sub(r"%s", "?", query)
        if params is None:
            self._cursor.execute(sql)
        else:
            self._cursor.execute(sql, tuple(params))
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        self._cursor.close()


class SQLiteCompatConnection:
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection

    def cursor(self) -> SQLiteCompatCursor:
        return SQLiteCompatCursor(self._connection.cursor())

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def connect_sqlite() -> sqlite3.Connection:
    conn = sqlite3.connect(_sqlite_path())
    conn.row_factory = sqlite3.Row
    return conn


def get_taiko_db_connection() -> SQLiteCompatConnection:
    ensure_schema()
    return SQLiteCompatConnection(connect_sqlite())


def _execute_many(conn: sqlite3.Connection, statements: Iterable[str]) -> None:
    for statement in statements:
        conn.execute(statement)


def ensure_schema() -> None:
    conn = connect_sqlite()
    try:
        _execute_many(
            conn,
            (
                """
                CREATE TABLE IF NOT EXISTS bind (
                    qq TEXT PRIMARY KEY,
                    id TEXT NOT NULL,
                    visible INTEGER NOT NULL DEFAULT 0
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS public_score_tokens (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    taiko_id TEXT NOT NULL UNIQUE,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_mask TEXT NOT NULL,
                    last_used_at TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS web_hiroba_credentials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    taiko_no TEXT NOT NULL UNIQUE,
                    email TEXT NOT NULL,
                    password_enc TEXT NOT NULL,
                    configured_by_qq TEXT DEFAULT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS web_song_locks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    taiko_id TEXT NOT NULL,
                    song_no INTEGER NOT NULL,
                    level INTEGER NOT NULL,
                    is_locked INTEGER NOT NULL DEFAULT 1,
                    UNIQUE (taiko_id, song_no, level)
                )
                """,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def utc_timestamp() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
