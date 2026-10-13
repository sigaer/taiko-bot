"""Public presentation helpers, without host IO or platform dependencies."""
from typing import Dict, List, Tuple, Any
from sakura_taiko_core.chart.position import PositionResult

def find_by_volume(
    data: Dict[str, Dict[str, Dict[str, int]]],
    target: int | Tuple[int, int],
    stat_key: str = "total",
) -> List[Tuple[str, str]]:
    """
    按物量查找歌曲与难度。

    参数:
      - data: 由 load_note_counts 读出的字典
      - target: 目标物量。可以是整数(精确匹配)或 (lo, hi) 区间(闭区间)
      - stat_key: 统计项，默认 'total'；也可用 '1'/'2'/'3'/'4' 之一

    返回:
      - [(title, "Course|Level"), ...]，已按标题、难度名排序
    """
    if stat_key not in {"1", "2", "3", "4", "total"}:
        raise ValueError("stat_key 必须是 '1','2','3','4' 或 'total'")
    courseMap = {
        "Edit": "里谱",
        "Oni": "魔王",
        "Hard": "困难",
        "Normal": "一般",
        "Easy": "简单",
    }
    is_range = isinstance(target, tuple)
    lo, hi = target if is_range else (target, target)

    hits: List[Tuple[str, str]] = []
    for title, courses in data.items():
        for course_level, counts in courses.items():
            course_level = courseMap.get(course_level.split("|")[0])
            val = int(counts.get(stat_key, None))
            if val is None:
                continue
            if lo <= val <= hi:
                hits.append((title, course_level))

    # 按曲名、难度字符串排序，便于展示稳定
    hits.sort(key=lambda x: (x[0], x[1]))
    return hits

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

def _strip_song_query_diff_prefix(raw_q: str) -> str:
    if raw_q.startswith("简单"):
        return raw_q[2:].strip()
    if raw_q.startswith("普通"):
        return raw_q[2:].strip()
    if raw_q.startswith("困难"):
        return raw_q[2:].strip()
    if raw_q.startswith("魔王"):
        return raw_q[2:].strip()
    if raw_q.startswith(("梅", "竹", "松", "鬼", "里")):
        return raw_q[1:].strip()
    return raw_q

def _build_fuzzy_query_hint(results: List[List[Any]]) -> str:
    title = results[0][1]
    ratio = float(results[0][2]) / 100.0
    return f"你要找的可能是：{title}\n匹配度：{ratio:.2f}"
