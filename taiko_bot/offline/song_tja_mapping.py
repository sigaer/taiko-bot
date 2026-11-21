"""Load and refresh the Nijiiro song-id to ESE TJA path mapping."""

from __future__ import annotations

from sakura_taiko_core.parser.tja_mapping import (
    _normalize_tja_path,
    normalize_song_tja_mapping,
)


import json
import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, Mapping

import requests


from taiko_bot.offline.paths import root as _runtime_root
ROOT_DIR = _runtime_root()
DEFAULT_MAPPING_URL = (
    "https://raw.githubusercontent.com/OurTaiko/"
    "ese-mapping-to-nijiiroid/main/data.json"
)
DEFAULT_MAPPING_PATH = ROOT_DIR / "songs/song_id2tjapath.json"
MIN_EXPECTED_MAPPING_COUNT = 1000
logger = logging.getLogger(__name__)


def _download_mapping(url: str, timeout: float):
    proxy = os.environ.get("MIHOMO_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    direct = {"http": "", "https": "", "all": ""}
    routes = [("direct", direct), ("mihomo", {"http": proxy, "https": proxy})] if proxy else [("direct", direct), ("direct-retry", direct)]
    request_timeout = (min(5.0, timeout), min(15.0, timeout))
    for index, (name, proxies) in enumerate(routes):
        try:
            response = requests.get(url, timeout=request_timeout, proxies=proxies)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status is not None and status < 500 and status not in (408, 429):
                raise
            if index == len(routes) - 1:
                raise
            logger.warning("TJA mapping %s request failed (%s); trying %s", name, type(exc).__name__, routes[index + 1][0])


def load_song_tja_mapping(path: Path = DEFAULT_MAPPING_PATH) -> Dict[int, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return normalize_song_tja_mapping(payload)


def write_song_tja_mapping(path: Path, mapping: Mapping[int, str]) -> None:
    """Atomically persist a normalized mapping for offline daily-update fallback."""
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {str(song_id): mapping[song_id] for song_id in sorted(mapping)}
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def refresh_song_tja_mapping(
    *,
    url: str = DEFAULT_MAPPING_URL,
    path: Path = DEFAULT_MAPPING_PATH,
    timeout: float = 30.0,
    minimum_entries: int = MIN_EXPECTED_MAPPING_COUNT,
) -> Dict[int, str]:
    mapping = normalize_song_tja_mapping(_download_mapping(url, timeout))
    if len(mapping) < minimum_entries:
        raise ValueError(
            f"remote song_id2tjapath has only {len(mapping)} entries; "
            f"expected at least {minimum_entries}"
        )
    write_song_tja_mapping(path, mapping)
    return mapping
