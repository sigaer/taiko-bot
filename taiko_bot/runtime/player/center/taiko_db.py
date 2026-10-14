from __future__ import annotations

import os
from typing import Any, Dict

import pymysql
from .runtime_env import load_runtime_environment

load_runtime_environment()


def _db_config() -> Dict[str, Any]:
    user = os.getenv("TAIKO_DB_USER", "").strip()
    password = os.getenv("TAIKO_DB_PASSWORD", "")
    if not user or not password:
        raise RuntimeError("TAIKO_DB_USER and TAIKO_DB_PASSWORD are required")
    return {
        "host": os.getenv("TAIKO_DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("TAIKO_DB_PORT", "3306")),
        "user": user,
        "password": password,
        "database": os.getenv("TAIKO_DB_NAME", "taiko"),
        "charset": "utf8mb4",
        "autocommit": False,
    }


def get_taiko_db_connection():
    return pymysql.connect(**_db_config())
