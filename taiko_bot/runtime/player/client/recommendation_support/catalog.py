"""Public catalog inputs for recommendations; no legacy plugin imports."""
from __future__ import annotations
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple
from taiko_bot.settings import get_settings
from sakura_taiko_core.chart import identity as _identity, visibility as _visibility

SONG_DATA_PATH = get_settings().root_dir / 'songs/song_data.json'
DuplicateSongGroup = _identity.DuplicateSongGroup
normalize_song_id = _visibility.normalize_song_id

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
    return _identity.build_group_maps(rows)

def _group_cache(
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Tuple[
    Dict[str, DuplicateSongGroup],
    Dict[int, DuplicateSongGroup],
    Dict[str, DuplicateSongGroup],
]:
    path = Path(song_data_path)
    mtime_ns, _ = _load_song_data_mtime(str(path))
    return _build_group_cache(str(path), mtime_ns)

def load_song_index() -> Dict[int, Dict[str, Any]]:
    path = Path(SONG_DATA_PATH)
    if not path.exists():
        return {}
    return _load_song_index_revision(str(path), path.stat().st_mtime_ns)


@lru_cache(maxsize=4)
def _load_song_index_revision(path_str, mtime_ns):
    _, payload = _load_song_data_revision(path_str, mtime_ns)
    result: Dict[int, Dict[str, Any]] = {}
    for item in payload:
        if not isinstance(item, dict):
            continue
        normalized_id = normalize_song_id(item.get("id"))
        if normalized_id is None:
            continue
        result[normalized_id] = item
    return result

def identity_inputs():
    _, by_id, by_title = _group_cache()
    return {sid: group.default_id for sid, group in by_id.items()}, by_id, by_title

def visibility_inputs(records=(), songs=None):
    from sakura_taiko_core.chart.visibility import is_song_id_publicly_visible
    index = load_song_index()
    ids = set(index)
    for record in records:
        try: ids.add(int(record.get('song_no')))
        except (TypeError, ValueError): pass
    for row in (songs or {}).values():
        try: ids.add(int(row.get('id')))
        except (TypeError, ValueError): pass
    return {sid for sid in ids if is_song_id_publicly_visible(sid, song_index=index)}


def rating_identity_inputs():
    """Capture the current client pair namespace without retaining import-time IDs."""
    from sakura_taiko_core.chart.client_groups import build_rating_duplicate_groups
    groups = build_rating_duplicate_groups(list(load_song_index().values()))
    return groups, {song_id: index for index, group in enumerate(groups) for song_id in group}
