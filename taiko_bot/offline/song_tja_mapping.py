"""Load and refresh the Nijiiro song-id to ESE TJA path mapping."""

from __future__ import annotations

from sakura_taiko_core.parser.tja_mapping import (
    _normalize_tja_path,
    normalize_song_tja_mapping,
)


import json
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
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    mapping = normalize_song_tja_mapping(response.json())
    if len(mapping) < minimum_entries:
        raise ValueError(
            f"remote song_id2tjapath has only {len(mapping)} entries; "
            f"expected at least {minimum_entries}"
        )
    write_song_tja_mapping(path, mapping)
    return mapping
