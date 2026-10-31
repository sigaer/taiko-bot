from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from pathlib import PurePosixPath

def _normalize_tja_path(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError('TJA mapping values must be strings')
    text = value.strip().replace('\\', '/')
    if not text:
        return ''
    path = PurePosixPath(text)
    if path.is_absolute() or '..' in path.parts:
        raise ValueError(f'unsafe TJA mapping path: {value!r}')
    if path.suffix.lower() != '.tja':
        raise ValueError(f'TJA mapping path does not end in .tja: {value!r}')
    return path.as_posix()

def normalize_song_tja_mapping(payload: Any) -> Dict[int, str]:
    """Validate a JSON mapping and normalize Windows separators for Linux."""
    if not isinstance(payload, Mapping):
        raise ValueError('song_id2tjapath must be a JSON object')
    result: Dict[int, str] = {}
    for raw_song_id, raw_path in payload.items():
        try:
            song_id = int(raw_song_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'invalid song id in TJA mapping: {raw_song_id!r}') from exc
        if song_id <= 0 or str(song_id) != str(raw_song_id).strip():
            raise ValueError(f'invalid song id in TJA mapping: {raw_song_id!r}')
        result[song_id] = _normalize_tja_path(raw_path)
    return result
