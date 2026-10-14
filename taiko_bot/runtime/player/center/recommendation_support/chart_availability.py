from __future__ import annotations
from .paths import ROOT as _ROOT


from sakura_taiko_core.chart import availability as domain_availability

import json

from pathlib import Path

from typing import Any, Optional

def _load_song_data(
    song_data_path: str | Path,
) -> Optional[list[dict[str, Any]]]:
    try:
        with Path(song_data_path).open("r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    return [item for item in payload if isinstance(item, dict)]

def load_on_shelf_song_ids(song_data_path=str(_ROOT / 'songs/song_data.json')):
    return domain_availability.on_shelf_song_ids(_load_song_data(song_data_path) or [])

def load_cn_available_chart_keys(song_data_path=str(_ROOT / 'songs/song_data.json'), raw_song_data_path=None):
    path=Path(song_data_path)
    merged=_load_song_data(path) or []
    raw_path=Path(raw_song_data_path) if raw_song_data_path is not None else path.with_name("song_data_raw.json")
    raw=_load_song_data(raw_path) if raw_path.exists() else None
    return domain_availability.cn_available_chart_keys(merged, raw)
