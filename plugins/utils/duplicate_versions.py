from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.chart import identity as _identity

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from taiko_bot.settings import get_settings

SONG_DATA_PATH = get_settings().root_dir / "songs" / "song_data.json"
SONG_ALIAS_PATH = get_settings().root_dir / "songs" / "song_alias.json"


normalize_song_title = _identity.normalize_song_title


normalize_song_title_aggressive = _identity.normalize_song_title_aggressive


_safe_int = _identity._safe_int


_title_candidates = _identity._title_candidates


DuplicateSongGroup = _identity.DuplicateSongGroup


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


def build_duplicate_song_groups(
    song_data_path: str | Path = SONG_DATA_PATH,
) -> List[Tuple[int, ...]]:
    groups_by_key, _, _ = _group_cache(song_data_path)
    return sorted(group.ids for group in groups_by_key.values() if len(group.ids) > 1)


def group_for_song_id(song_id, song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.group_for_song_id(song_id, groups_by_id=by_id, groups_by_title=by_title)


def group_for_title(title, song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.group_for_title(title, groups_by_id=by_id, groups_by_title=by_title)


def default_song_id_for_query(song_id=None, *, title="", song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.default_song_id_for_query(song_id, title=title, groups_by_id=by_id, groups_by_title=by_title)


def duplicate_identity_key(song_id, level, *, song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.duplicate_identity_key(song_id, level, groups_by_id=by_id, groups_by_title=by_title)


def duplicate_identity_key_by_title(title, level, *, song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.duplicate_identity_key_by_title(title, level, groups_by_id=by_id, groups_by_title=by_title)


def collapse_query_results_by_group(rows, *, song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return _identity.collapse_query_results_by_group(rows, groups_by_id=by_id, groups_by_title=by_title)


def group_ids_for_query(song_id=None, *, title="", song_data_path=SONG_DATA_PATH):
    _, by_id, by_title = _group_cache(song_data_path)
    return list(_identity.group_ids_for_query(song_id=song_id, title=title, groups_by_id=by_id, groups_by_title=by_title))


def alias_entry_for_song_id(
    song_id: int | str,
    song_alias_path: str | Path = SONG_ALIAS_PATH,
    *,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Optional[Dict[str, Any]]:
    group = group_for_song_id(song_id, song_data_path)
    if group is None:
        target_ids = {_safe_int(song_id)}
    else:
        target_ids = set(group.ids)
    try:
        payload = json.loads(Path(song_alias_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, list):
        return None
    candidates: List[Dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        current_id = _safe_int(item.get("id"))
        if current_id in target_ids:
            candidates.append(item)
    if not candidates:
        return None
    candidates.sort(key=lambda item: (_safe_int(item.get("id"), 10**9), len(item.get("aliases") or [])))
    return candidates[0]
