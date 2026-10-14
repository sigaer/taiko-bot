from __future__ import annotations


from pathlib import Path

from .duplicate_versions import SONG_DATA_PATH, _group_cache

def identity_inputs(song_data_path: str | Path = SONG_DATA_PATH):
    groups, by_id, _ = _group_cache(song_data_path)
    return {song_id: group.default_id for song_id, group in by_id.items()}, sorted(
        group.ids for group in groups.values() if len(group.ids) > 1)
