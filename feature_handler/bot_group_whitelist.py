import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, FrozenSet, Optional

from nonebot.adapters import Event
from taiko_bot.settings import get_settings

DEFAULT_WHITELIST_PATH = get_settings().storage_dir / "config" / "bot_group_whitelist.json"
_CACHE_TTL = 5.0

_cache_lock = threading.Lock()
_cached_mtime: float = -1.0
_cached_loaded_at: float = 0.0
_cached_whitelist: Dict[str, FrozenSet[str]] = {}


def _resolve_whitelist_path() -> Path:
    env_path = os.getenv("BOT_GROUP_WHITELIST_PATH", "").strip()
    if env_path:
        return Path(env_path)
    try:
        from nonebot import get_driver

        config_path = get_driver().config.dict().get("bot_group_whitelist_path")
        if config_path:
            return Path(str(config_path))
    except Exception:
        pass
    return DEFAULT_WHITELIST_PATH


def _normalize_bot_id(bot_id: Any) -> str:
    return str(bot_id or "").strip()


def _normalize_group_id(group_id: Any) -> str:
    return str(group_id or "").strip()


def _parse_whitelist_payload(payload: Any) -> Dict[str, FrozenSet[str]]:
    if not isinstance(payload, dict):
        return {}
    parsed: Dict[str, FrozenSet[str]] = {}
    for bot_id, groups in payload.items():
        bot_key = _normalize_bot_id(bot_id)
        if not bot_key:
            continue
        if not isinstance(groups, list):
            continue
        group_set = frozenset(
            _normalize_group_id(group_id)
            for group_id in groups
            if _normalize_group_id(group_id)
        )
        if group_set:
            parsed[bot_key] = group_set
    return parsed


def load_whitelist() -> Dict[str, FrozenSet[str]]:
    global _cached_mtime, _cached_loaded_at, _cached_whitelist

    path = _resolve_whitelist_path()
    now = time.monotonic()
    try:
        stat = path.stat()
        mtime = stat.st_mtime
    except FileNotFoundError:
        with _cache_lock:
            _cached_mtime = -1.0
            _cached_loaded_at = now
            _cached_whitelist = {}
        return {}
    except OSError:
        with _cache_lock:
            if _cached_whitelist and now - _cached_loaded_at <= _CACHE_TTL:
                return _cached_whitelist
        return {}

    with _cache_lock:
        if (
            _cached_whitelist
            and mtime == _cached_mtime
            and now - _cached_loaded_at <= _CACHE_TTL
        ):
            return _cached_whitelist

    try:
        raw = path.read_text(encoding="utf-8")
        payload = json.loads(raw) if raw.strip() else {}
    except (OSError, json.JSONDecodeError):
        with _cache_lock:
            if _cached_whitelist and now - _cached_loaded_at <= _CACHE_TTL:
                return _cached_whitelist
        return {}

    parsed = _parse_whitelist_payload(payload)
    with _cache_lock:
        _cached_mtime = mtime
        _cached_loaded_at = now
        _cached_whitelist = parsed
    return parsed


def is_restricted_bot(bot_id: Any) -> bool:
    bot_key = _normalize_bot_id(bot_id)
    if not bot_key:
        return False
    return bot_key in load_whitelist()


def is_group_allowed(bot_id: Any, group_id: Any) -> bool:
    bot_key = _normalize_bot_id(bot_id)
    group_key = _normalize_group_id(group_id)
    if not bot_key:
        return True
    whitelist = load_whitelist()
    allowed_groups = whitelist.get(bot_key)
    if allowed_groups is None:
        return True
    if not group_key:
        return False
    return group_key in allowed_groups


async def should_block_group_event(event: Event) -> bool:
    group_id = getattr(event, "group_id", None)
    if group_id is None:
        return False
    bot_id = getattr(event, "self_id", None)
    if not is_restricted_bot(bot_id):
        return False
    return not is_group_allowed(bot_id, group_id)
