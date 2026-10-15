"""从 TJA 谱面计算各 COURSE / 分歧路径的连打与气球元数据。

核心原则：
1. 逗号 `,` 才是小节结束；换行不是小节结束。
2. 保留音符片段之间的命令位置，支持小节内部 #BPMCHANGE / #DELAY。
3. #MEASURE 决定小节拍数；整小节所有音符字符共同决定 subdivision。
4. #BRANCHSTART 的 N/E/M 分别展开成独立时间轴计算。
5. BALLOON 按 TJA 源文件中的 7/9 出现顺序消费，并映射到对应分歧。
6. 气球记录持续时间、要求打速与给定 RPS 下的统计容量；容量统一向下取整。
7. 即使 BALLOON 头缺值，仍保留谱面中的 7/9 事件，并将 required_hits 记为 None。

默认 branch="M"，因此带分歧的 COURSE 顶层 roll_times / balloons 使用 M 路；
完整 N/E/M 结果位于 entry["branches"]。
"""

from __future__ import annotations

from sakura_taiko_core.parser.tja import (
    _DRUMROLL,
    _BALLOON,
    _END,
    _BRANCHES,
    _COURSE_KEY,
    _NOTE_RE,
    _Component,
)

from sakura_taiko_core.parser.tja import (
    _NoteChunk,
    _Command,
    _Measure,
    _CourseBlock,
    _strip_comment,
    _parse_float,
    _parse_measure_ratio,
    _parse_balloons,
    _find_global_bpm,
    _split_courses,
    _expand_branches,
    _map_balloons_to_branches,
    _parse_command,
    _build_measures,
    _normalize_capacity_rates,
    _rate_key,
    _balloon_capacity,
    _summarize_events,
    _extract_chart_events,
    parse_tja_roll_metadata,
)


import math
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple, Union


def read_tja_text(path: str) -> str:
    """兼容常见 TJA 编码：UTF-8 BOM/UTF-8 -> CP932。"""
    with open(path, "rb") as f:
        raw = f.read()
    for encoding in ("utf-8-sig", "utf-8", "cp932"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            pass
    # 最后给出明确错误，而不是静默替换乱码。
    raise UnicodeDecodeError("tja", raw, 0, len(raw), "unsupported TJA encoding")
