from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

def compute_score_from_points(initial_points, good, ok, drumroll=0) -> int:
    """
    计算总分（支持里/表对应 level）：
      - 良基础分值 = initial_points
      - 可基础分值 = (initial_points // 2) 再“舍去个位” => ((initial_points // 2) // 10) * 10
      - 连打分 = drumroll * 100
    """
    good_base = initial_points
    ok_base = initial_points // 2 // 10 * 10
    total = good * good_base + ok * ok_base + drumroll * 100
    return int(total)
