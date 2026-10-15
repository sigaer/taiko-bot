from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from .constants import ALGORITHM_VERSION

SNAPSHOT_SCHEMA_VERSION = "snapshot-schema-v2"
SOURCE_LINEAGE_INFERENCE_VERSION = "source-lineage-v3"
NORMALIZER_ALGORITHM_VERSION = f"{ALGORITHM_VERSION}:snapshot-normalizer-v2"
NORMALIZED_CACHE_VERSION = (
    f"{SNAPSHOT_SCHEMA_VERSION}:{SOURCE_LINEAGE_INFERENCE_VERSION}:{NORMALIZER_ALGORITHM_VERSION}"
)

_CACHE_STATS: Counter[str] = Counter()
MIN_CACHE_FREE_BYTES = 20 * 1024 * 1024 * 1024
MIN_CACHE_FREE_RATIO = 0.10
MIN_CACHE_FREE_FLOOR_BYTES = 512 * 1024 * 1024


def reset_normalized_cache_stats() -> None:
    _CACHE_STATS.clear()


def get_normalized_cache_stats() -> Dict[str, int]:
    return {
        "hit": _CACHE_STATS["hit"],
        "miss": _CACHE_STATS["miss"],
        "write": _CACHE_STATS["write"],
        "corrupt": _CACHE_STATS["corrupt"],
        "disabled": _CACHE_STATS["disabled"],
    }


def normalized_cache_object_key(content_hash: str) -> Optional[str]:
    if len(content_hash) != 64:
        return None
    material = "\0".join(
        (
            content_hash,
            SNAPSHOT_SCHEMA_VERSION,
            SOURCE_LINEAGE_INFERENCE_VERSION,
            NORMALIZER_ALGORITHM_VERSION,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _cache_root() -> Optional[Path]:
    raw = str(os.getenv("TAIKO_ANNUAL_CACHE_DIR") or "").strip()
    return Path(raw).resolve() if raw else None


def _cache_path(content_hash: str) -> Optional[Path]:
    root = _cache_root()
    object_key = normalized_cache_object_key(content_hash)
    if root is None or object_key is None:
        return None
    return root / "normalized" / object_key[:2] / f"{object_key}.json"


def _lock_path(content_hash: str) -> Optional[Path]:
    root = _cache_root()
    object_key = normalized_cache_object_key(content_hash)
    if root is None or object_key is None:
        return None
    return root / "locks" / "normalized" / f"{object_key}.lock"


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    current = path
    root = _cache_root()
    while root is not None and (current == root or root in current.parents):
        os.chmod(current, 0o700)
        if current == root:
            break
        current = current.parent


@contextmanager
def _cache_lock(content_hash: str, *, exclusive: bool) -> Iterator[None]:
    lock_path = _lock_path(content_hash)
    if lock_path is None:
        yield
        return
    _ensure_private_dir(lock_path.parent)
    descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_cache_file(path: Path, content_hash: str) -> Optional[Dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if (
        not isinstance(payload, dict)
        or payload.get("cacheVersion") != NORMALIZED_CACHE_VERSION
        or payload.get("contentHash") != content_hash
    ):
        return None
    normalized = payload.get("normalized")
    return normalized if isinstance(normalized, dict) else None


def read_normalized_snapshot(content_hash: str) -> Optional[Dict[str, Any]]:
    path = _cache_path(content_hash)
    if path is None:
        _CACHE_STATS["disabled"] += 1
        return None
    _ensure_private_dir(path.parent)
    with _cache_lock(content_hash, exclusive=False):
        normalized = _read_cache_file(path, content_hash)
    if normalized is None:
        _CACHE_STATS["miss"] += 1
        if path.exists():
            _CACHE_STATS["corrupt"] += 1
        return None
    _CACHE_STATS["hit"] += 1
    return normalized


def write_normalized_snapshot(content_hash: str, normalized: Dict[str, Any]) -> None:
    path = _cache_path(content_hash)
    if path is None:
        return
    try:
        probe = path.parent
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
        disk = shutil.disk_usage(probe)
        free_floor = min(
            MIN_CACHE_FREE_BYTES,
            max(MIN_CACHE_FREE_FLOOR_BYTES, int(disk.total * MIN_CACHE_FREE_RATIO)),
        )
        if disk.free < free_floor:
            _CACHE_STATS["disabled"] += 1
            return
        _ensure_private_dir(path.parent)
        with _cache_lock(content_hash, exclusive=True):
            if _read_cache_file(path, content_hash) is not None:
                return
            descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                    json.dump(
                        {
                            "cacheVersion": NORMALIZED_CACHE_VERSION,
                            "contentHash": content_hash,
                            "normalized": normalized,
                        },
                        file,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    file.flush()
                    os.fsync(file.fileno())
                os.replace(temporary, path)
                os.chmod(path, 0o600)
                _CACHE_STATS["write"] += 1
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
    except OSError:
        # Cache failures must never prevent annual report generation.
        _CACHE_STATS["disabled"] += 1
