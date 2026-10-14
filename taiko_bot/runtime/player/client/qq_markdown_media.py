from __future__ import annotations

import asyncio
import logging
import os
import time
from io import BytesIO
from pathlib import Path
from typing import IO, Optional, Union
from urllib.parse import quote
from uuid import uuid4

from PIL import Image
from taiko_bot.settings import get_settings

_logger = logging.getLogger(__name__)
_SETTINGS = get_settings()

QQ_MARKDOWN_IMAGE_CACHE_DIR = Path(
    os.getenv(
        "QQ_MARKDOWN_IMAGE_CACHE_DIR",
        _SETTINGS.qq_markdown_cache_dir,
    )
)
QQ_MARKDOWN_IMAGE_BASE_URL = os.getenv(
    "QQ_MARKDOWN_IMAGE_BASE_URL",
    _SETTINGS.qq_markdown_image_base_url,
).rstrip("/")
QQ_MARKDOWN_IMAGE_TTL_SECONDS = max(
    int(os.getenv("QQ_MARKDOWN_IMAGE_TTL_SECONDS", "1800") or 1800),
    300,
)
QQ_MARKDOWN_IMAGE_CLEANUP_INTERVAL_SECONDS = max(
    int(os.getenv("QQ_MARKDOWN_IMAGE_CLEANUP_INTERVAL_SECONDS", "300") or 300),
    60,
)

_cleanup_task: Optional[asyncio.Task] = None


def _ensure_cache_dir() -> Path:
    QQ_MARKDOWN_IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return QQ_MARKDOWN_IMAGE_CACHE_DIR


def _read_image_bytes(
    image: Union[bytes, IO[bytes], BytesIO, Path],
) -> tuple[bytes, str]:
    if isinstance(image, Path):
        return image.read_bytes(), image.suffix.lower()
    if isinstance(image, bytes):
        return image, ""
    if hasattr(image, "seek"):
        image.seek(0)
    data = image.read()
    return data, ""


def _infer_suffix(data: bytes, fallback_suffix: str = "") -> str:
    normalized_fallback = str(fallback_suffix or "").strip().lower()
    if normalized_fallback in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return normalized_fallback
    try:
        with Image.open(BytesIO(data)) as img:
            fmt = str(img.format or "").upper()
    except Exception:
        return ".png"
    return {
        "JPEG": ".jpg",
        "JPG": ".jpg",
        "PNG": ".png",
        "WEBP": ".webp",
        "GIF": ".gif",
    }.get(fmt, ".png")


def cache_markdown_image_url(
    image: Union[bytes, IO[bytes], BytesIO, Path],
    *,
    prefix: str = "taiko",
) -> str:
    if not QQ_MARKDOWN_IMAGE_BASE_URL:
        raise RuntimeError("QQ markdown image base URL is not configured")
    raw_bytes, fallback_suffix = _read_image_bytes(image)
    if not raw_bytes:
        raise ValueError("empty image payload")
    suffix = _infer_suffix(raw_bytes, fallback_suffix)
    cache_dir = _ensure_cache_dir()
    filename = f"{prefix}-{int(time.time())}-{uuid4().hex}{suffix}"
    target = cache_dir / filename
    target.write_bytes(raw_bytes)
    return f"{QQ_MARKDOWN_IMAGE_BASE_URL}/{quote(filename)}"


def cleanup_expired_markdown_images(*, now: Optional[float] = None) -> int:
    cache_dir = _ensure_cache_dir()
    current_time = float(time.time() if now is None else now)
    deleted = 0
    for path in cache_dir.iterdir():
        if not path.is_file():
            continue
        try:
            age = current_time - path.stat().st_mtime
        except FileNotFoundError:
            continue
        if age < QQ_MARKDOWN_IMAGE_TTL_SECONDS:
            continue
        try:
            path.unlink()
            deleted += 1
        except FileNotFoundError:
            continue
    return deleted


async def _cleanup_loop() -> None:
    while True:
        try:
            deleted = cleanup_expired_markdown_images()
            if deleted:
                _logger.info("cleaned %s expired QQ markdown cache images", deleted)
        except Exception:
            _logger.exception("failed to clean QQ markdown cache images")
        await asyncio.sleep(QQ_MARKDOWN_IMAGE_CLEANUP_INTERVAL_SECONDS)


def start_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task is not None and not _cleanup_task.done():
        return
    _ensure_cache_dir()
    _cleanup_task = asyncio.create_task(_cleanup_loop())


async def stop_cleanup_task() -> None:
    global _cleanup_task
    if _cleanup_task is None:
        return
    _cleanup_task.cancel()
    try:
        await _cleanup_task
    except asyncio.CancelledError:
        pass
    finally:
        _cleanup_task = None
