from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from .visibility import is_song_publicly_visible

MANUAL_PAIR_ID_GROUPS = [(399, 400), (433, 1265), (939, 1263), (450, 1257), (1146, 1264), (750, 1260), (141, 1258), (191, 1266), (527, 1261), (323, 1262), (137, 1259)]

def _normalize_duplicate_song_level_signature(song: Dict[str, Any]) -> Tuple[str, ...]:
    return tuple((str(song.get(f'level_{level}') or '').strip() for level in range(1, 6)))

def build_rating_duplicate_groups(song_data) -> List[Tuple[int, ...]]:
    """
    构建推荐流程的“同曲多 ID”分组。
    - 保留手工维护的已知共谱分组
    - 自动补充：song_data 中曲名完全一致且难度签名一致的多 ID 曲目
    """
    group_candidates: List[Tuple[int, ...]] = [tuple(group) for group in MANUAL_PAIR_ID_GROUPS]
    if isinstance(song_data, list):
        duplicate_ids_by_signature: Dict[Tuple[str, Tuple[str, ...]], Set[int]] = {}
        for item in song_data:
            if not isinstance(item, dict):
                continue
            if not is_song_publicly_visible(item):
                continue
            title = str(item.get('song_name') or '').strip()
            if not title:
                continue
            try:
                song_id = int(item.get('id'))
            except Exception:
                continue
            signature = (title, _normalize_duplicate_song_level_signature(item))
            duplicate_ids_by_signature.setdefault(signature, set()).add(song_id)
        for ids in duplicate_ids_by_signature.values():
            if len(ids) > 1:
                group_candidates.append(tuple(sorted(ids)))
    parent: Dict[int, int] = {}

    def find(song_id: int) -> int:
        root = parent.setdefault(song_id, song_id)
        if root != song_id:
            parent[song_id] = find(root)
        return parent[song_id]

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root
    for group in group_candidates:
        normalized = [int(song_id) for song_id in group]
        if len(normalized) < 2:
            continue
        for song_id in normalized:
            parent.setdefault(song_id, song_id)
        anchor = normalized[0]
        for song_id in normalized[1:]:
            union(anchor, song_id)
    merged: Dict[int, Set[int]] = {}
    for song_id in list(parent):
        merged.setdefault(find(song_id), set()).add(song_id)
    return sorted([tuple(sorted(song_ids)) for song_ids in merged.values() if len(song_ids) > 1])
