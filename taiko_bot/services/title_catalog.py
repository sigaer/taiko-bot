"""One official catalog for Bot queries, display hosts and the public API."""
from __future__ import annotations

import fcntl
import json
import logging
import os
import tempfile
import threading
import time
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import requests
from sakura_taiko_core.parser.title_catalog import (
    _normalize_title_catalog_item as _normalize_core_item,
    build_title_rarity_lookup,
    normalize_title_display,
)

from taiko_bot.runtime.paths import root

ROOT_DIR = root()
TITLE_API_CONFIG_PATH = ROOT_DIR / "config.json"
TITLE_API_CACHE_PATH = ROOT_DIR / "data" / "title_catalog_cache.json"
TITLE_API_URL = "https://wl-taiko.wahlap.net/api/user/all/title"
TITLE_API_PAGE_SIZE = 1000
MAX_TITLE_PAGES = 20
TITLE_REFRESH_SECONDS = 300
_logger = logging.getLogger(__name__)
_refresh_lock = threading.RLock()
_next_refresh_attempt = 0.0


def normalize_title_authorization(value: str) -> str:
    token = str(value or "").strip()
    return token if not token or token.lower().startswith("bearer ") else f"Bearer {token}"


def _normalize_title_catalog_item(item: Dict[str, Any]) -> Dict[str, Any] | None:
    normalized = _normalize_core_item(item)
    if normalized is not None and item.get("id") is not None:
        try:
            normalized["id"] = int(item["id"])
        except (TypeError, ValueError):
            pass
    return normalized


def _deserialize_title_catalog(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = payload.get("titles")
    if not isinstance(rows, list):
        return []
    return [item for row in rows if (item := _normalize_title_catalog_item(row)) is not None]


def _serialize_title_catalog(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"titles": _deserialize_title_catalog({"titles": list(items)})}


def fetch_title_catalog_items(*, config_path: Path = TITLE_API_CONFIG_PATH) -> List[Dict[str, Any]]:
    """Fetch every page; incomplete/unauthorized results never replace the file."""
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        authorization = normalize_title_authorization(config.get("cookie") or "")
        if not authorization:
            raise ValueError("missing credential")
        rows: List[Dict[str, Any]] = []
        seen: set[tuple] = set()
        total = None
        deadline = time.monotonic() + 25
        for page in range(1, MAX_TITLE_PAGES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("title pagination deadline exceeded")
            response = requests.post(
                TITLE_API_URL,
                headers={"Authorization": authorization, "Content-Type": "application/json"},
                json={"page": page, "pageSize": TITLE_API_PAGE_SIZE, "unlock": 0},
                timeout=(min(5, remaining), min(10, remaining)),
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("statusCode", 200) not in (0, 200) or payload.get("code", 0) not in (0, 200):
                raise ValueError("upstream rejected title request")
            data = payload.get("data")
            if not isinstance(data, dict) or not isinstance(data.get("list"), list):
                raise ValueError("invalid title page")
            batch = data["list"]
            reported_total = data.get("total")
            if reported_total is not None:
                reported_total = int(reported_total)
                if reported_total < 0 or (total is not None and reported_total != total):
                    raise ValueError("title total changed during pagination")
                total = reported_total
            for raw in batch:
                item = _normalize_title_catalog_item(raw)
                if item is None:
                    raise ValueError("invalid title item")
                key = (item.get("id"), item["uid"], item["sort_no"], item["name"], item["rarity"])
                if key in seen:
                    raise ValueError("repeated title page/item")
                seen.add(key)
                rows.append(item)
            if total is not None and len(rows) == total:
                return rows
            if not batch:
                if total is None:
                    return rows
                raise ValueError("incomplete title catalog")
            if total is not None and len(rows) > total:
                raise ValueError("title total exceeded")
        raise ValueError("title pagination limit exceeded")
    except Exception as error:
        # Headers and response bodies can contain credentials; never log them.
        status = getattr(getattr(error, "response", None), "status_code", None)
        _logger.warning("Official title refresh failed (%s, HTTP %s)", type(error).__name__, status)
        return []


def write_title_catalog_cache(items: Iterable[Dict[str, Any]], *, cache_path: Path = TITLE_API_CACHE_PATH) -> None:
    payload = _serialize_title_catalog(items)
    if not payload["titles"]:
        raise ValueError("Refusing to replace a title catalog with an empty result")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".title-catalog-", dir=cache_path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, cache_path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def refresh_title_catalog_cache(*, config_path: Path = TITLE_API_CONFIG_PATH, cache_path: Path = TITLE_API_CACHE_PATH) -> List[Dict[str, Any]]:
    items = fetch_title_catalog_items(config_path=config_path)
    if items:
        try:
            write_title_catalog_cache(items, cache_path=cache_path)
        except OSError as error:
            _logger.warning("Official title cache publication failed (%s)", type(error).__name__)
            return []
        load_title_catalog_items.cache_clear()
    return items


def load_title_catalog_cache(*, cache_path: Path = TITLE_API_CACHE_PATH) -> List[Dict[str, Any]]:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        return _deserialize_title_catalog(payload) if isinstance(payload, dict) else []
    except (OSError, ValueError, TypeError):
        return []


def _catalog_version() -> tuple:
    try:
        stat = TITLE_API_CACHE_PATH.stat()
        return (stat.st_ino, stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ()


@lru_cache(maxsize=1)
def _load_catalog_generation(version: tuple) -> Tuple[Dict[str, Any], ...]:
    return tuple(load_title_catalog_cache(cache_path=TITLE_API_CACHE_PATH))


def load_title_catalog_items() -> Tuple[Dict[str, Any], ...]:
    global _next_refresh_attempt
    with _refresh_lock:
        now = time.monotonic()
        version = _catalog_version()
        stale = not version or time.time() - version[1] / 1_000_000_000 >= TITLE_REFRESH_SECONDS
        if stale and now >= _next_refresh_attempt:
            _next_refresh_attempt = now + TITLE_REFRESH_SECONDS
            TITLE_API_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TITLE_API_CACHE_PATH.with_suffix(".lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    pass  # Another process refreshes; keep serving the last good file.
                else:
                    version = _catalog_version()
                    if not version or time.time() - version[1] / 1_000_000_000 >= TITLE_REFRESH_SECONDS:
                        refresh_title_catalog_cache(config_path=TITLE_API_CONFIG_PATH, cache_path=TITLE_API_CACHE_PATH)
                    fcntl.flock(lock, fcntl.LOCK_UN)
            version = _catalog_version()
        return _load_catalog_generation(version)


load_title_catalog_items.cache_clear = _load_catalog_generation.cache_clear


def title_catalog_cache(function):
    """Invalidate existing query derivations when another process refreshes."""
    cached = lru_cache(maxsize=1)(function)
    version = None
    lock = threading.RLock()

    @wraps(function)
    def wrapped(*args, **kwargs):
        nonlocal version
        load_title_catalog_items()
        current = _catalog_version()
        with lock:
            if current != version:
                cached.cache_clear()
                version = current
            return cached(*args, **kwargs)

    wrapped.cache_clear = cached.cache_clear
    wrapped.cache_info = cached.cache_info
    return wrapped
