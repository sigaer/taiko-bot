from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from sakura_taiko_core.rating import target as domain_target
from sakura_taiko_core.rating.target import SongRatingTargetResult
from sakura_taiko_core.rating.v1 import build_const_table
from taiko_bot.rating_targets import compute_v2_rating_target, format_rating_targets
from ...paths import root
from .duplicate_versions import default_song_id_for_query, group_ids_for_query
from .taikob_v2_data import load_v2_snapshot, V2DataSourceError

logger = logging.getLogger(__name__)

RATING_PATH = root() / "songs/rating_structured_with_ids.json"


def load_rating_config(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def get_song_rating_info(
    song_id: int,
    level: int,
    *,
    fallback_title: str = "",
    rating_path: str | Path = RATING_PATH,
    config: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    cfg = load_rating_config(rating_path) if config is None else config
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


def compute_song_rating_target(song_info, target_rating, *, rating_path=RATING_PATH, config=None):
    cfg = load_rating_config(rating_path) if config is None else config
    table = build_const_table(cfg["const_table"]["const_to_score"])
    return domain_target.compute_song_rating_target(song_info, target_rating, const_table=table)


def build_song_rating_target_message(
    song_id: int, level: int, title: str, level_label: str, target_rating: float,
) -> str:
    results: Dict[str, SongRatingTargetResult | str] = {}
    try:
        config = load_rating_config(RATING_PATH)
        song_info = get_song_rating_info(song_id, level, fallback_title=title, config=config)
        results["v1"] = (
            compute_song_rating_target(song_info, target_rating, config=config) if song_info is not None
            else "该歌曲暂无该难度的 Rating 数据。"
        )
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Rating v1 target unavailable: %s", type(exc).__name__)
        results["v1"] = "Rating 数据暂时不可用，请稍后再试。"
    try:
        song_map = load_v2_snapshot().song_map
        group_ids = set(group_ids_for_query(song_id=song_id, title=title)) | {song_id}
        default_id = default_song_id_for_query(song_id, title=title)
        chart = next((song_map[(candidate_id, level)]
            for candidate_id in sorted(group_ids, key=lambda value: (value != default_id, value))
            if (candidate_id, level) in song_map), None)
        results["v2"] = (
            compute_v2_rating_target(chart, target_rating) if chart is not None
            else "该歌曲暂无该难度的 Rating 数据。"
        )
    except (V2DataSourceError, OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Rating v2 target unavailable: %s", type(exc).__name__)
        results["v2"] = "Rating 数据暂时不可用，请稍后再试。"
    return format_rating_targets(title, level_label, target_rating, results)
