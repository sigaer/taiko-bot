"""Host-owned public combo reference; retains legacy lazy process cache."""
import json
from pathlib import Path
import os
from typing import Dict, Optional
from taiko_application.merged_bind import SongKey, _safe_int

SONG_DATA_PATH = Path(os.getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko")) / "songs" / "song_data.json"
_SONG_COMBO_MAP_CACHE: Optional[Dict[SongKey, int]] = None

def _load_song_combo_map() -> Dict[SongKey, int]:
    global _SONG_COMBO_MAP_CACHE
    if _SONG_COMBO_MAP_CACHE is not None:
        return _SONG_COMBO_MAP_CACHE

    combo_map: Dict[SongKey, int] = {}
    try:
        rows = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        rows = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            song_no = _safe_int(row.get("id"), -1)
            if song_no <= 0:
                continue
            max_combo = row.get("max_combo")
            if isinstance(max_combo, list):
                for idx, raw_combo in enumerate(max_combo, start=1):
                    combo = _safe_int(raw_combo, 0)
                    if combo > 0:
                        combo_map[(song_no, idx)] = combo
            elif max_combo not in (None, "", "-"):
                combo = _safe_int(max_combo, 0)
                if combo > 0:
                    combo_map[(song_no, 4)] = combo

    _SONG_COMBO_MAP_CACHE = combo_map
    return combo_map
