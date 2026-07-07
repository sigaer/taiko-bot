from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from taiko_bot.settings import get_settings

SONG_DATA_PATH = get_settings().root_dir / "songs" / "song_data.json"
SONG_ALIAS_PATH = get_settings().root_dir / "songs" / "song_alias.json"


def normalize_song_title(text: Any) -> str:
    normalized = str(text or "").strip()
    normalized = normalized.replace("〜", "～")
    normalized = normalized.replace("~", "～")
    normalized = normalized.replace("（", "(")
    normalized = normalized.replace("）", ")")
    normalized = normalized.replace("＆", "&")
    normalized = normalized.replace("＠", "@")
    normalized = normalized.replace("！", "!")
    normalized = normalized.replace("？", "?")
    for src in ("‐", "‑", "‒", "–", "—", "―", "－", "ｰ"):
        normalized = normalized.replace(src, "-")
    normalized = normalized.replace("【限定】", "")
    normalized = normalized.replace("(裏)", "")
    normalized = normalized.replace("(裏譜面)", "")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.lower()


def normalize_song_title_aggressive(text: Any) -> str:
    normalized = normalize_song_title(text)
    normalized = re.sub(r"\([^)]*\)", "", normalized)
    return normalized


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _title_candidates(song: Mapping[str, Any]) -> List[str]:
    candidates = [
        song.get("song_name"),
        song.get("song_name_jp"),
        song.get("title_cn"),
        song.get("title_jp"),
        song.get("title"),
    ]
    out: List[str] = []
    seen: set[str] = set()
    for value in candidates:
        normalized = normalize_song_title(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(str(value or "").strip())
    return out


@dataclass(frozen=True)
class DuplicateSongGroup:
    key: str
    ids: Tuple[int, ...]
    default_id: int
    display_title: str


@lru_cache(maxsize=4)
def _load_song_data_mtime(path_str: str) -> Tuple[int, List[Dict[str, Any]]]:
    path = Path(path_str)
    mtime_ns = path.stat().st_mtime_ns
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        return mtime_ns, []
    return mtime_ns, payload


@lru_cache(maxsize=4)
def _build_group_cache(path_str: str, mtime_ns: int) -> Tuple[
    Dict[str, DuplicateSongGroup],
    Dict[int, DuplicateSongGroup],
    Dict[str, DuplicateSongGroup],
]:
    _ = mtime_ns
    _, song_rows = _load_song_data_mtime(path_str)
    ids_by_group: Dict[str, set[int]] = {}
    title_by_group: Dict[str, str] = {}
    for row in song_rows:
        if not isinstance(row, dict):
            continue
        song_id = _safe_int(row.get("id"))
        if song_id < 0:
            continue
        titles = _title_candidates(row)
        if not titles:
            continue
        primary_title = titles[0]
        normalized_key = normalize_song_title(primary_title)
        ids_by_group.setdefault(normalized_key, set()).add(song_id)
        title_by_group.setdefault(normalized_key, primary_title)
        for candidate in titles[1:]:
            alias_key = normalize_song_title(candidate)
            if alias_key and alias_key != normalized_key:
                ids_by_group.setdefault(normalized_key, set()).add(song_id)
    groups_by_key: Dict[str, DuplicateSongGroup] = {}
    groups_by_id: Dict[int, DuplicateSongGroup] = {}
    groups_by_title: Dict[str, DuplicateSongGroup] = {}
    for key, ids in ids_by_group.items():
        if not ids:
            continue
        sorted_ids = tuple(sorted(ids))
        group = DuplicateSongGroup(
            key=key,
            ids=sorted_ids,
            default_id=sorted_ids[0],
            display_title=title_by_group.get(key, str(sorted_ids[0])),
        )
        groups_by_key[key] = group
        for song_id in sorted_ids:
            groups_by_id[song_id] = group
        groups_by_title[key] = group
        aggressive_key = normalize_song_title_aggressive(group.display_title)
        if aggressive_key:
            groups_by_title.setdefault(aggressive_key, group)
    return groups_by_key, groups_by_id, groups_by_title


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


def group_for_song_id(
    song_id: int | str | None,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Optional[DuplicateSongGroup]:
    try:
        target_id = int(song_id)  # type: ignore[arg-type]
    except Exception:
        return None
    _, groups_by_id, _ = _group_cache(song_data_path)
    return groups_by_id.get(target_id)


def group_for_title(
    title: str,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Optional[DuplicateSongGroup]:
    _, _, groups_by_title = _group_cache(song_data_path)
    normalized = normalize_song_title(title)
    if normalized and normalized in groups_by_title:
        return groups_by_title[normalized]
    aggressive = normalize_song_title_aggressive(title)
    if aggressive and aggressive in groups_by_title:
        return groups_by_title[aggressive]
    return None


def default_song_id_for_query(
    song_id: int | None = None,
    *,
    title: str = "",
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Optional[int]:
    group = group_for_song_id(song_id, song_data_path) if song_id is not None else None
    if group is None and title:
        group = group_for_title(title, song_data_path)
    if group is None:
        return song_id
    return group.default_id


def duplicate_identity_key(
    song_id: int,
    level: int,
    *,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Tuple[str, int, int]:
    group = group_for_song_id(song_id, song_data_path)
    if group is None:
        return ("song", song_id, level)
    return ("title", group.default_id, level)


def duplicate_identity_key_by_title(
    title: str,
    level: int,
    *,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> Tuple[str, int, int] | Tuple[str, str, int]:
    group = group_for_title(title, song_data_path)
    if group is None:
        normalized = (
            normalize_song_title_aggressive(title)
            or normalize_song_title(title)
            or str(title)
        )
        return ("title_name", normalized, level)
    return ("title", group.default_id, level)


def collapse_query_results_by_group(
    rows: Sequence[Sequence[Any]],
    *,
    song_data_path: str | Path = SONG_DATA_PATH,
) -> List[List[Any]]:
    grouped: Dict[Tuple[str, int], List[Any]] = {}
    ordered: List[Tuple[str, int]] = []
    for row in rows:
        if not row:
            continue
        try:
            song_id = int(row[0])
        except Exception:
            key = ("unknown", len(ordered))
            grouped[key] = list(row)
            ordered.append(key)
            continue
        group = group_for_song_id(song_id, song_data_path)
        normalized_key = (
            ("title", group.default_id) if group is not None else ("song", song_id)
        )
        existing = grouped.get(normalized_key)
        if existing is None:
            grouped[normalized_key] = list(row)
            ordered.append(normalized_key)
            continue
        candidate = list(row)
        if group is not None:
            current_id = _safe_int(existing[0], 10**9)
            candidate_id = _safe_int(candidate[0], 10**9)
            if candidate_id < current_id:
                grouped[normalized_key] = candidate
    return [grouped[key] for key in ordered]


def group_ids_for_query(
    song_id: int | None = None,
    *,
    title: str = "",
    song_data_path: str | Path = SONG_DATA_PATH,
) -> List[int]:
    group = group_for_song_id(song_id, song_data_path) if song_id is not None else None
    if group is None and title:
        group = group_for_title(title, song_data_path)
    if group is None:
        return [song_id] if song_id is not None else []
    return list(group.ids)


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
