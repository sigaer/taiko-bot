from __future__ import annotations

import os
from dataclasses import dataclass
from taiko_bot.runtime.player.center.runtime_env import load_runtime_environment

load_runtime_environment()


def _env_bool(name: str, default: bool = True) -> bool:
    raw = _env_or_driver(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = _env_or_driver(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_or_driver(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is not None and raw != "":
        return raw

    driver_key = name.lower()
    try:
        from nonebot import get_driver

        config_val = get_driver().config.dict().get(driver_key)
    except Exception:
        return None

    if config_val is None:
        return None
    text = str(config_val).strip()
    return text or None


@dataclass(frozen=True)
class MethodCallsConfig:
    enabled: bool
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    batch_size: int
    flush_interval: float
    retention_hours: int
    method_name_max_len: int
    taiko_db_host: str
    taiko_db_port: int
    taiko_db_user: str
    taiko_db_password: str
    taiko_db_name: str

    @classmethod
    def from_env(cls) -> "MethodCallsConfig":
        return cls(
            enabled=_env_bool("METHOD_CALLS_ENABLED", True),
            db_host=_env_or_driver("METHOD_CALLS_DB_HOST") or "localhost",
            db_port=_env_int("METHOD_CALLS_DB_PORT", 3306),
            db_user=_env_or_driver("METHOD_CALLS_DB_USER") or "",
            db_password=_env_or_driver("METHOD_CALLS_DB_PASSWORD") or "",
            db_name=_env_or_driver("METHOD_CALLS_DB_NAME") or "bot",
            batch_size=_env_int("METHOD_CALLS_BATCH_SIZE", 50),
            flush_interval=float(
                _env_or_driver("METHOD_CALLS_FLUSH_INTERVAL") or "0.5"
            ),
            retention_hours=_env_int("METHOD_CALLS_RETENTION_HOURS", 72),
            method_name_max_len=_env_int("METHOD_CALLS_METHOD_NAME_MAX_LEN", 64),
            taiko_db_host=_env_or_driver("TAIKO_DB_HOST") or "127.0.0.1",
            taiko_db_port=_env_int("TAIKO_DB_PORT", 3306),
            taiko_db_user=_env_or_driver("TAIKO_DB_USER") or "",
            taiko_db_password=_env_or_driver("TAIKO_DB_PASSWORD") or "",
            taiko_db_name=_env_or_driver("TAIKO_DB_NAME") or "taiko",
        )

    @property
    def db_config(self) -> dict:
        return {
            "host": self.db_host,
            "port": self.db_port,
            "user": self.db_user,
            "password": self.db_password,
            "db": self.db_name,
            "autocommit": True,
        }

    @property
    def taiko_db_config(self) -> dict:
        return {
            "host": self.taiko_db_host,
            "port": self.taiko_db_port,
            "user": self.taiko_db_user,
            "password": self.taiko_db_password,
            "db": self.taiko_db_name,
            "autocommit": True,
        }


class _LazyConfig:
    def __getattr__(self, name: str):
        return getattr(MethodCallsConfig.from_env(), name)


CONFIG = _LazyConfig()
