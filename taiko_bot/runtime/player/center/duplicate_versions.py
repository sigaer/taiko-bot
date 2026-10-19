from __future__ import annotations



from sakura_taiko_core.chart.identity import (
    normalize_song_title,
    normalize_song_title_aggressive,
    _safe_int,
    _safe_float,
    _title_candidates,
    DuplicateSongGroup,
    quality_sort_key_for_record,
)
from sakura_taiko_core.chart import identity as domain_identity


import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

BASE = Path(__import__("os").getenv("TAIKO_CENTER_ROOT", "/home/sigaer/taiko"))
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


def group_for_song_id(song_id: int | str | None, song_data_path: str | Path=SONG_DATA_PATH) -> Optional[DuplicateSongGroup]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.group_for_song_id(song_id, groups_by_id=by_id, groups_by_title=by_title)


def group_for_title(title: str, song_data_path: str | Path=SONG_DATA_PATH) -> Optional[DuplicateSongGroup]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.group_for_title(title, groups_by_id=by_id, groups_by_title=by_title)


def default_song_id_for_query(song_id: int | None=None, *, title: str='', song_data_path: str | Path=SONG_DATA_PATH) -> Optional[int]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.default_song_id_for_query(song_id, title=title, groups_by_id=by_id, groups_by_title=by_title)


def duplicate_identity_key(song_id: int, level: int, *, song_data_path: str | Path=SONG_DATA_PATH) -> Tuple[str, int, int]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.duplicate_identity_key(song_id, level, groups_by_id=by_id, groups_by_title=by_title)


def duplicate_identity_key_by_title(title: str, level: int, *, song_data_path: str | Path=SONG_DATA_PATH) -> Tuple[str, int, int] | Tuple[str, str, int]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.duplicate_identity_key_by_title(title, level, groups_by_id=by_id, groups_by_title=by_title)


def collapse_query_results_by_group(rows: Sequence[Sequence[Any]], *, song_data_path: str | Path=SONG_DATA_PATH) -> List[List[Any]]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.collapse_query_results_by_group(rows, groups_by_id=by_id, groups_by_title=by_title)


def group_ids_for_query(*, song_id: int | None=None, title: str='', song_data_path: str | Path=SONG_DATA_PATH) -> Tuple[int, ...]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.group_ids_for_query(song_id=song_id, title=title, groups_by_id=by_id, groups_by_title=by_title)


def choose_best_record(records, *, note_count_by_key=None, song_data_path=SONG_DATA_PATH, level=None):
    return domain_identity.choose_best_record(records, note_count_by_key=note_count_by_key, level=level)


def choose_best_record_in_group(records: Iterable[Mapping[str, Any]], *, song_id: int | None=None, title: str='', level: Optional[int]=None, note_count_by_key: Optional[Mapping[Tuple[int, int], int]]=None, song_data_path: str | Path=SONG_DATA_PATH) -> Optional[Dict[str, Any]]:
    _, by_id, by_title = _group_cache(song_data_path)
    return domain_identity.choose_best_record_in_group(records, song_id=song_id, title=title, level=level, note_count_by_key=note_count_by_key, groups_by_id=by_id, groups_by_title=by_title)
