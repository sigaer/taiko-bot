from __future__ import annotations


from sakura_taiko_core.chart.identity import DuplicateSongGroup

from sakura_taiko_core.chart import identity as domain_identity

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, List, Optional, Tuple

BASE = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

SONG_DATA_PATH = BASE / "songs" / "song_data.json"

@lru_cache(maxsize=4)
def _load_song_data_mtime(path_str: str) -> Tuple[int, List[Dict[str, Any]]]:
    path = Path(path_str)
    mtime_ns = path.stat().st_mtime_ns
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return mtime_ns, []
    return mtime_ns, payload

@lru_cache(maxsize=4)
def _build_group_cache(path_str, mtime_ns):
    _, rows = _load_song_data_mtime(path_str)
    return domain_identity.build_group_maps(rows)

def _group_cache(
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Tuple[Dict[str, DuplicateSongGroup], Dict[int, DuplicateSongGroup], Dict[str, DuplicateSongGroup]]:
    path = Path(song_data_path)
    mtime_ns, _ = _load_song_data_mtime(str(path))
    return _build_group_cache(str(path), mtime_ns)

def default_song_id_for_query(song_id: int | None=None, *, title: str='', song_data_path: str | Path=SONG_DATA_PATH) -> Optional[int]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.default_song_id_for_query(song_id, title=title, groups_by_id=by_id, groups_by_title=by_title)
