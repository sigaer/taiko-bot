from __future__ import annotations


from sakura_taiko_core.chart.identity import DuplicateSongGroup

from sakura_taiko_core.chart import identity as domain_identity

import json

from functools import lru_cache

from pathlib import Path

from typing import Any, Dict, List, Tuple

BASE = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

SONG_DATA_PATH = BASE / "songs" / "song_data.json"

def _load_song_data_mtime(path_str: str) -> Tuple[int, List[Dict[str, Any]]]:
    path = Path(path_str)
    return _load_song_data_revision(path_str, path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _load_song_data_revision(path_str, mtime_ns):
    path = Path(path_str)
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

def build_duplicate_song_groups(
    song_data_path: str | Path = SONG_DATA_PATH,
) -> List[Tuple[int, ...]]:
    groups_by_key, _, _ = _group_cache(song_data_path)
    return sorted(group.ids for group in groups_by_key.values() if len(group.ids) > 1)

def duplicate_identity_key(song_id: int, level: int, *, song_data_path: str | Path=SONG_DATA_PATH) -> Tuple[str, int, int]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.duplicate_identity_key(song_id, level, groups_by_id=by_id, groups_by_title=by_title)
