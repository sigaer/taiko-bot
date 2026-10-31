from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
from ..rating.v1 import calc_y, compute_AI, compute_P, compute_Q, lookup_const_score, build_const_table
from ..rating.v1 import _calc_accuracy_for_record
from ..dimension.v1 import compute_AD_AE_AF_AG

def _compute_rating_for_entry(entry: Dict[str, Any], rating_index: Dict[Tuple[int, int], dict], const_table: List[tuple], *, duplicate_groups=()) -> Optional[float]:
    PAIR_ID_GROUPS = duplicate_groups
    PAIR_ID_MAP = {sid: index for index, group in enumerate(duplicate_groups) for sid in group}
    try:
        song_no = int(entry.get('song_no', 0))
        level = int(entry.get('level', 0))
    except Exception:
        return None
    song_info = rating_index.get((song_no, level))
    if not song_info:
        pair_id = PAIR_ID_MAP.get(song_no)
        if pair_id is not None:
            for candidate_song_no in PAIR_ID_GROUPS[pair_id]:
                if candidate_song_no == song_no:
                    continue
                song_info = rating_index.get((candidate_song_no, level))
                if song_info:
                    break
    if not song_info:
        return None
    good_cnt = int(entry.get('good_cnt', 0) or 0)
    ok_cnt = int(entry.get('ok_cnt', 0) or 0)
    total_notes = int(song_info.get('combo', 0) or 0)
    dondaful_cnt = int(entry.get('dondaful_combo_cnt', 0) or 0)
    accuracy = _calc_accuracy_for_record(total_notes=total_notes, great_cnt=good_cnt, good_cnt=ok_cnt, dondaful_combo_cnt=dondaful_cnt, algorithm='comprehensive')
    if accuracy == 0.0:
        return 0.0
    metrics = compute_AD_AE_AF_AG(song_info)
    const_value = song_info.get('score', 0)
    M = lookup_const_score(const_value, const_table)
    N = calc_y(accuracy=accuracy, normalization_factor=15.5, algorithm='comprehensive')
    P = compute_P(M, N)
    Q = compute_Q(M, N)
    return compute_AI(M, N, P, Q)
