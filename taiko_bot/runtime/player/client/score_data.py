from __future__ import annotations

from sakura_taiko_core.score import scoreline as _scoreline, client_scoreline as _client_scoreline

import json
import math
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from taiko_bot.settings import get_settings


BASE = get_settings().root_dir
SCORE_PATH = BASE / "songs" / "song_score.json"
ROLL_PATH = BASE / "songs" / "song_data_with_roll.json"
SONG_DATA_PATH = BASE / "songs" / "song_data.json"
UNIFIED_PATH = BASE / "songs" / "taiko_goku_onis.json"

RATING_CONFIG = _scoreline.RATING_CONFIG

_RATING_ALIAS_TO_KEY = _scoreline._RATING_ALIAS_TO_KEY

_SORTED_RATING_ALIASES = _scoreline._SORTED_RATING_ALIASES

_DIFF_PREFIXES = _client_scoreline._DIFF_PREFIXES


ScoreLineRequest = _client_scoreline.ScoreLineRequest


_safe_int = _scoreline._safe_int


_safe_float = _scoreline._safe_float


_round_up_to_10 = _scoreline._round_up_to_10


_normalize_title = _client_scoreline._normalize_title


_score_target_map = _scoreline._score_target_map


_extract_roll_times = _scoreline._extract_roll_times


_extract_balloons = _scoreline._extract_balloons


def rebuild_scoreline_dataset(output_path=UNIFIED_PATH):
    merged, matched = _client_scoreline.build_scoreline_dataset(
        json.loads(SCORE_PATH.read_text(encoding="utf-8")),
        json.loads(ROLL_PATH.read_text(encoding="utf-8")),
        json.loads(SONG_DATA_PATH.read_text(encoding="utf-8")))
    output_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _load_scoreline_data.cache_clear()
    return len(merged), matched


@lru_cache(maxsize=1)
def _load_scoreline_data() -> List[Dict[str, Any]]:
    source_mtime = max(
        SCORE_PATH.stat().st_mtime,
        ROLL_PATH.stat().st_mtime,
        SONG_DATA_PATH.stat().st_mtime,
    )
    if not UNIFIED_PATH.exists() or UNIFIED_PATH.stat().st_mtime < source_mtime:
        rebuild_scoreline_dataset()
    return json.loads(UNIFIED_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _build_chart_index():
    return _client_scoreline.build_chart_index(_load_scoreline_data())


def get_scoreline_entry(song_id, level, fallback_title=""):
    by_id, by_title = _build_chart_index()
    return _client_scoreline.get_scoreline_entry(song_id, level, fallback_title,
        by_id=by_id, by_title=by_title)


def available_levels_for_song(song_id, fallback_title=""):
    by_id, by_title = _build_chart_index()
    return _client_scoreline.available_levels_for_song(song_id, fallback_title,
        by_id=by_id, by_title=by_title)


compute_roll_hits = _scoreline.compute_roll_hits


compute_scoreline_result = _scoreline.compute_scoreline_result


parse_scoreline_request = _client_scoreline.parse_scoreline_request


def format_scoreline_message(
    entry: Dict[str, Any],
    result: Dict[str, Any],
    request: ScoreLineRequest,
) -> str:
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


JSON_PATH = UNIFIED_PATH


@lru_cache(maxsize=1)
def _load_score_json() -> Dict[str, Any]:
    """
    读取并缓存统一后的 taiko_goku_onis.json。
    期望结构：列表，每项至少包含 id / level / initial_points。
    """

    source_mtime = max(
        SCORE_PATH.stat().st_mtime,
        ROLL_PATH.stat().st_mtime,
        SONG_DATA_PATH.stat().st_mtime,
    )
    if not JSON_PATH.exists() or JSON_PATH.stat().st_mtime < source_mtime:
        rebuild_scoreline_dataset(JSON_PATH)
    if not JSON_PATH.exists():
        raise FileNotFoundError(f"未找到分值配置文件: {JSON_PATH}")
    with JSON_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data

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

def compute_score(
    song_id: int, good: int, ok: int, drumroll: int = 0, level: int = 4
) -> int:
    """
    计算总分（支持里/表对应 level）：
      - 良基础分值 = initial_points
      - 可基础分值 = (initial_points // 2) 再“舍去个位” => ((initial_points // 2) // 10) * 10
      - 连打分 = drumroll * 100
    """
    initial_points = _get_initial_points(song_id, level=level)
    good_base = initial_points
    # “除以2后舍去个位”（例如 390 -> 190, 391 -> 190）
    ok_base = (initial_points // 2) // 10 * 10
    total = good * good_base + ok * ok_base + drumroll * 100
    return int(total)
