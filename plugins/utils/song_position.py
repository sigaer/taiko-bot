from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT_DIR = Path(__file__).resolve().parents[2]
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

_MISSING_SORT = 10**9


@dataclass(frozen=True)
class PositionResult:
    song_id: int
    title: str
    song_type: str
    rank: Optional[int]
    total_on_shelf: int
    sort: int
    is_on_shelf: bool


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_on_shelf(item: Dict[str, Any]) -> bool:
    status = item.get("shelf_status", 0)
    if status is None or status == "":
        return True
    try:
        return int(status) == 0
    except (TypeError, ValueError):
        return str(status).strip() in {"0", "未下架"}


def _song_title(item: Dict[str, Any]) -> str:
    song_id = _to_int(item.get("id"), 0)
    return str(
        item.get("song_name") or item.get("song_name_jp") or f"ID{song_id}"
    ).strip()


def _sort_key(item: Dict[str, Any]) -> Tuple[int, int]:
    return (_to_int(item.get("sort"), _MISSING_SORT), _to_int(item.get("id"), 0))


@lru_cache(maxsize=4)
def _load_song_catalog(song_data_path: str) -> Tuple[
    Dict[int, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, int],
]:
    path = Path(song_data_path)
    with path.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    if not isinstance(raw, list):
        return {}, {}, {}

    id_index: Dict[int, Dict[str, Any]] = {}
    type_buckets: Dict[str, List[Dict[str, Any]]] = {}

    for item in raw:
        if not isinstance(item, dict):
            continue
        song_id = _to_int(item.get("id"), -1)
        if song_id < 0:
            continue
        id_index[song_id] = item
        song_type = str(item.get("type") or "-").strip() or "-"
        if _is_on_shelf(item):
            type_buckets.setdefault(song_type, []).append(item)

    type_on_shelf_lists: Dict[str, List[Dict[str, Any]]] = {}
    type_totals: Dict[str, int] = {}
    for song_type, items in type_buckets.items():
        ordered = sorted(items, key=_sort_key)
        type_on_shelf_lists[song_type] = ordered
        type_totals[song_type] = len(ordered)

    return id_index, type_on_shelf_lists, type_totals


def _get_catalog() -> Tuple[
    Dict[int, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, int],
]:
    return _load_song_catalog(str(SONG_DATA_PATH))


def get_song_position_by_id(song_id: int) -> Optional[PositionResult]:
    id_index, type_lists, type_totals = _get_catalog()
    item = id_index.get(int(song_id))
    if not item:
        return None

    song_type = str(item.get("type") or "-").strip() or "-"
    on_shelf = _is_on_shelf(item)
    total_on_shelf = type_totals.get(song_type, 0)
    rank: Optional[int] = None

    if on_shelf:
        ordered = type_lists.get(song_type, [])
        for idx, candidate in enumerate(ordered):
            if _to_int(candidate.get("id")) == int(song_id):
                rank = idx + 1
                break

    return PositionResult(
        song_id=int(song_id),
        title=_song_title(item),
        song_type=song_type,
        rank=rank,
        total_on_shelf=total_on_shelf,
        sort=_to_int(item.get("sort"), 0),
        is_on_shelf=on_shelf,
    )


def format_position_reply(result: PositionResult) -> str:
    lines = [
        f"【{result.title}】id{result.song_id}",
        f"分类：{result.song_type}",
    ]
    if result.is_on_shelf and result.rank is not None:
        lines.append(f"位序：第 {result.rank} / {result.total_on_shelf}（在架）")
    else:
        lines.append("状态：已下架（在架曲库中不计位序）")
        lines.append(f"该分类在架：共 {result.total_on_shelf} 首")
    lines.append(f"排序号 sort：{result.sort}")
    return "\n".join(lines)
