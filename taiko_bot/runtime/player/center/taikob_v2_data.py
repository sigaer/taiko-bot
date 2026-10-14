from __future__ import annotations

from sakura_taiko_core.parser import v2_dataset as domain_dataset


from sakura_taiko_core.parser.v2_dataset import (
    IGNORED_SONG_IDS,
    DIFFICULTY_MAP,
    REQUIRED_DATASET_FIELDS,
    V2DataSourceError,
    V2DataSnapshot,
    _is_finite_number,
    _parse_numeric_id,
    _parse_csv_number,
)


from sakura_taiko_core.models.calculation import V2SongData


import csv
import hashlib
import io
import math
import os
import re
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Dict, Mapping, Tuple

import requests

ROOT_DIR = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))
V2_DATASET_URL = "https://viewer.sakura-bot.cn/api/taiko/data/constants_id_v2"
V2_DATASET_FALLBACK_PATH = ROOT_DIR / "songs" / "constants_id_v2.csv"
V2_SOURCE_CACHE_TTL_SECONDS = 3600.0
V2_SOURCE_RETRY_DELAY_SECONDS = 300.0
V2_SOURCE_REQUEST_TIMEOUT_SECONDS = 10.0


_snapshot: V2DataSnapshot | None = None
_snapshot_lock = threading.Lock()
_retry_after_monotonic = 0.0
_refresh_in_progress = False


def parse_v2_dataset_csv(content):
    return domain_dataset.parse_v2_dataset_csv(content, loaded_at_monotonic=time.monotonic())


def _fetch_snapshot() -> V2DataSnapshot:
    try:
        response = requests.get(
            V2_DATASET_URL,
            timeout=V2_SOURCE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise V2DataSourceError(f"读取 {V2_DATASET_URL} 失败: {exc}") from exc
    snapshot = parse_v2_dataset_csv(response.text)
    _write_fallback_dataset(response.text)
    return snapshot


def _write_fallback_dataset(content: str) -> None:
    target = V2_DATASET_FALLBACK_PATH
    temporary = target.with_name(
        f".{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(target)
    except OSError:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _load_fallback_snapshot() -> V2DataSnapshot:
    try:
        content = V2_DATASET_FALLBACK_PATH.read_text(encoding="utf-8")
    except OSError as exc:
        raise V2DataSourceError(
            f"读取本地 V2 定数快照 {V2_DATASET_FALLBACK_PATH} 失败: {exc}"
        ) from exc
    snapshot = parse_v2_dataset_csv(content)
    return replace(
        snapshot,
        loaded_at_monotonic=time.monotonic() - V2_SOURCE_CACHE_TTL_SECONDS,
    )


def _run_background_refresh() -> None:
    global _refresh_in_progress, _retry_after_monotonic, _snapshot

    try:
        refreshed = _fetch_snapshot()
    except V2DataSourceError:
        refreshed = None

    with _snapshot_lock:
        if refreshed is None:
            _retry_after_monotonic = (
                time.monotonic() + V2_SOURCE_RETRY_DELAY_SECONDS
            )
        else:
            _snapshot = refreshed
            _retry_after_monotonic = 0.0
        _refresh_in_progress = False


def _start_background_refresh_locked(now: float) -> None:
    global _refresh_in_progress

    if _refresh_in_progress or now < _retry_after_monotonic:
        return
    _refresh_in_progress = True
    threading.Thread(
        target=_run_background_refresh,
        name="taikob-v2-refresh",
        daemon=True,
    ).start()


def load_v2_snapshot(*, force_refresh: bool = False) -> V2DataSnapshot:
    global _retry_after_monotonic, _snapshot

    if force_refresh:
        refreshed = _fetch_snapshot()
        with _snapshot_lock:
            _snapshot = refreshed
            _retry_after_monotonic = 0.0
        return refreshed

    now = time.monotonic()
    cached = _snapshot
    if (
        cached is not None
        and now - cached.loaded_at_monotonic < V2_SOURCE_CACHE_TTL_SECONDS
    ):
        return cached

    with _snapshot_lock:
        now = time.monotonic()
        cached = _snapshot
        if cached is not None and (
            now - cached.loaded_at_monotonic < V2_SOURCE_CACHE_TTL_SECONDS
        ):
            return cached
        if cached is None:
            try:
                cached = _load_fallback_snapshot()
            except V2DataSourceError:
                cached = None
            else:
                _snapshot = cached
        if cached is not None:
            _start_background_refresh_locked(now)
            return cached
        _snapshot = _fetch_snapshot()
        _retry_after_monotonic = 0.0
        return _snapshot


def clear_v2_source_cache() -> None:
    global _refresh_in_progress, _retry_after_monotonic, _snapshot
    with _snapshot_lock:
        _snapshot = None
        _retry_after_monotonic = 0.0
        _refresh_in_progress = False
