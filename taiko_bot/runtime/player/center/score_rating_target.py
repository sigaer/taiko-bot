from __future__ import annotations

from sakura_taiko_core.rating import target as domain_target


from sakura_taiko_core.rating.target import SongRatingTargetResult


from pathlib import Path
from typing import Any, Dict, Optional

from .duplicate_versions import default_song_id_for_query, group_ids_for_query
from sakura_taiko_core.rating.v1 import build_const_table

def load_rating_config(path):
    from .recommendation_support.score_calculator import load_rating_config as load
    return load(path)


from ...public.config import root

RATING_PATH = root() / "songs/rating_structured_with_ids.json"


def get_song_rating_info(
    song_id: int,
    level: int,
    *,
    fallback_title: str = "",
    rating_path: str | Path = RATING_PATH,
) -> Optional[Dict[str, Any]]:
    cfg = load_rating_config(rating_path)
    candidates: Dict[int, Dict[str, Any]] = {}
    for info in cfg.get("songs", {}).values():
        try:
            if int(info.get("level")) == level:
                candidates[int(info.get("id"))] = info
        except (TypeError, ValueError):
            continue

    group_ids = set(group_ids_for_query(song_id=song_id, title=fallback_title))
    default_id = default_song_id_for_query(song_id, title=fallback_title)
    for candidate_id in sorted(group_ids, key=lambda value: (value != default_id, value)):
        if candidate_id in candidates:
            return candidates[candidate_id]
    return candidates.get(song_id)


def compute_song_rating_target(song_info, target_rating, *, rating_path=RATING_PATH):
    cfg = load_rating_config(rating_path)
    table = build_const_table(cfg["const_table"]["const_to_score"])
    return domain_target.compute_song_rating_target(song_info, target_rating, const_table=table)


def format_song_rating_target_message(
    title: str,
    level_label: str,
    result: SongRatingTargetResult,
) -> str:
    header = (
        f"歌曲：{title}（{level_label}）\n"
        f"目标单曲 Rating：{result.target_rating:g}"
    )
    if not result.reachable:
        return f"{header}\n即使全良也无法达到，最高约为 {result.max_rating:.2f}。"
    return (
        f"{header}\n"
        f"最低良数：{result.good_count}\n"
        f"最多可数：{result.ok_count}\n"
        f"良率：{result.accuracy * 100:.2f}%\n"
        f"预计单曲 Rating：{result.achieved_rating:.2f}"
    )
