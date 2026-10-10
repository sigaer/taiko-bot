from __future__ import annotations

from taiko_bot import domain as _domain
from sakura_taiko_core.chart import position as _position

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from .song_visibility import is_song_publicly_visible

ROOT_DIR = Path(__file__).resolve().parents[2]
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

_MISSING_SORT = 10**9


PositionResult = _position.PositionResult


_to_int = _position._to_int


def _is_on_shelf(item: Dict[str, Any]) -> bool:
    return is_song_publicly_visible(item)


_song_title = _position._song_title


_sort_key = _position._sort_key


@lru_cache(maxsize=4)
def _load_song_catalog(song_data_path):
    with Path(song_data_path).open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return _position.build_song_catalog(raw, profile="position-client-20261010")


def _get_catalog() -> Tuple[
    Dict[int, Dict[str, Any]],
    Dict[str, List[Dict[str, Any]]],
    Dict[str, int],
]:
    return _load_song_catalog(str(SONG_DATA_PATH))


def get_song_position_by_id(song_id):
    return _position.get_song_position_by_id(song_id, catalog=_get_catalog(),
        profile="position-client-20261010")


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
