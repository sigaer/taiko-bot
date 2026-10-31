from __future__ import annotations
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Set, Tuple
from ..models.calculation import V2SongData
from ..rating.v2 import _safe_int
from ..score.scoreline import _safe_float

DOUBLE_PLAY_TITLE_PREFIX = '【双打】'
DIFFICULTY_MAP = {'hard': 3, 'oni': 4, 'edit': 5}

def v2_client_song_map(rows) -> Dict[Tuple[int, int], V2SongData]:
    song_map: Dict[Tuple[int, int], V2SongData] = {}
    for row in rows:
        difficulty = DIFFICULTY_MAP.get(str(row.get('difficulty') or '').strip().lower())
        if difficulty is None:
            continue
        song = V2SongData(song_id=_safe_int(row.get('id')), level=difficulty, title=str(row.get('title') or '').strip(), total_notes=_safe_int(row.get('totalNotes')), sub_constant_1=_safe_float(row.get('sub_constant_1')), main_constant=_safe_float(row.get('main_constant')), sub_constant_2=_safe_float(row.get('sub_constant_2')), stamina=_safe_float(row.get('stamina')), handspeed=_safe_float(row.get('handspeed')), burst=_safe_float(row.get('burst')), complex=_safe_float(row.get('complex')), rhythm=_safe_float(row.get('rhythm')))
        if song.song_id <= 0 or song.total_notes <= 0:
            continue
        if song.title.startswith(DOUBLE_PLAY_TITLE_PREFIX):
            continue
        song_map[song.song_id, song.level] = song
    return song_map
