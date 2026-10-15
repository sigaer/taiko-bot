from __future__ import annotations
from functools import lru_cache
from typing import Any, Dict, List, Optional
from .recommendation_support.score_line import (UNIFIED_PATH, load_scoreline_data, _build_chart_index, _ensure_scoreline_dataset_current)
from .duplicate_versions import default_song_id_for_query, group_ids_for_query
from sakura_taiko_core.chart import scoreline_dataset as domain_scoreline_dataset
from sakura_taiko_core.score.scoreline import DIFFICULTY_LEVEL_LABELS, ScoreLineRequest, parse_scoreline_request, compute_scoreline_result
from sakura_taiko_core.score.points import compute_score_from_points
JSON_PATH = UNIFIED_PATH
def get_scoreline_entry(song_id: Optional[int], level: int, fallback_title: str='') -> Optional[Dict[str, Any]]:
    by_id, by_title = _build_chart_index(_ensure_scoreline_dataset_current())
    return domain_scoreline_dataset.get_scoreline_entry(song_id, level, fallback_title, by_id=by_id, by_title=by_title, group_ids=group_ids_for_query(song_id=song_id, title=fallback_title), default_id=default_song_id_for_query(song_id, title=fallback_title))

def available_levels_for_song(song_id: Optional[int], fallback_title: str='') -> List[int]:
    by_id, by_title = _build_chart_index(_ensure_scoreline_dataset_current())
    return domain_scoreline_dataset.available_levels_for_song(song_id, fallback_title, by_id=by_id, by_title=by_title, group_ids=group_ids_for_query(song_id=song_id, title=fallback_title), default_id=default_song_id_for_query(song_id, title=fallback_title))

def format_scoreline_message(
    entry: Dict[str, Any],
    result: Dict[str, Any],
    request: ScoreLineRequest,
) -> str:
    if request.rating_display is None:
        raise ValueError("评价分数线缺少评价名。")
    title = str(entry.get("title_jp") or entry.get("title_cn") or entry.get("title") or "未知歌曲")
    target_score = int(result["target_score"])
    roll_hits = int(result["roll_hits"])
    balloon_hits = int(result.get("balloon_hits", 0))
    roll_score = int(result["roll_score"])
    speed_text = str(int(request.speed_ips))
    roll_times = entry.get("roll_times") or []
    roll_adjusted = bool(result.get("roll_adjusted"))
    preserved_balloon_hits = int(result.get("preserved_balloon_hits", balloon_hits))
    replaced_balloon_hits = int(result.get("replaced_balloon_hits", 0))
    special_balloon_seconds = float(result.get("special_balloon_seconds", 0.0))
    if not roll_times and balloon_hits <= 0:
        roll_note = "无连打，秒速不影响结果"
    elif roll_adjusted:
        preserved_note = (
            f"，另保留常规气球 {preserved_balloon_hits} 打"
            if preserved_balloon_hits > 0
            else ""
        )
        roll_note = (
            f"预计连打得分：{roll_score}（{roll_hits} 打，"
            f"特殊气球按 {special_balloon_seconds:.1f} 秒连打处理，"
            f"替代原 {replaced_balloon_hits} 打{preserved_note}）"
        )
    elif balloon_hits > 0:
        roll_note = f"预计连打得分：{roll_score}（{roll_hits} 打，含气球 {balloon_hits} 打）"
    else:
        roll_note = f"预计连打得分：{roll_score}（{roll_hits} 打）"

    if not result["reachable"]:
        return (
            f"歌曲：{title}（{request.level_label}）\n"
            f"评价：{request.rating_display}\n"
            f"目标分：{target_score}\n"
            f"连打秒速：{speed_text}\n"
            f"{roll_note}\n"
            f"该秒速下即使全良也无法达成，最高分约为 {int(result['max_score'])}。"
        )

    return (
        f"歌曲：{title}（{request.level_label}）\n"
        f"评价：{request.rating_display}\n"
        f"目标分：{target_score}\n"
        f"连打秒速：{speed_text}\n"
        f"{roll_note}\n"
        f"最多可数：{int(result['max_ok'])}"
    )

@lru_cache(maxsize=1)
def _load_score_json() -> List[Dict[str, Any]]:
    """
    读取并缓存统一后的极分数据列表。
    每项至少包含 id / level / initial_points。
    """

    return load_scoreline_data(JSON_PATH)

def _get_initial_points(song_id: int, level: int) -> int:
    """
    在列表型 JSON 中，遍历查找 id==song_id 且 level==level 的项，返回 initial_points（良的基础分值）。
    若存在多条匹配，取第一条；若不存在匹配则报错。
    """
    data_list = _load_score_json()

    for item in data_list:
        # 允许 id 为字符串/数字，做一次安全解析
        try:
            item_id = int(item.get("id"))
        except Exception:
            continue
        item_level = item.get("level")

        if item_id == song_id and item_level == level:
            if "initial_points" not in item:
                raise KeyError(
                    f"id={song_id}, level={level} 的记录缺少 'initial_points'"
                )
            ip = item["initial_points"]
            return ip

    raise KeyError(f"未在 {JSON_PATH} 中找到 id={song_id}, level={level} 的分值记录。")

def compute_score(song_id: int, good: int, ok: int, drumroll: int=0, level: int=4) -> int:
    return compute_score_from_points(_get_initial_points(song_id, level=level), good, ok, drumroll)
