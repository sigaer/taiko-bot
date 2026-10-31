from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple
import csv
import hashlib
import io
from types import MappingProxyType
from ..models.calculation import V2SongData

IGNORED_SONG_IDS = frozenset({900})
DIFFICULTY_MAP = {'hard': 3, 'oni': 4, 'edit': 5}
REQUIRED_DATASET_FIELDS = ('id', 'title', 'difficulty', 'totalNotes', 'sub_constant_1', 'main_constant', 'sub_constant_2', 'stamina', 'handspeed', 'burst', 'complex', 'rhythm')

class V2DataSourceError(RuntimeError):
    """Raised when the authoritative Rating V2 constants source is unavailable."""

@dataclass(frozen=True)
class V2DataSnapshot:
    song_map: Mapping[Tuple[int, int], V2SongData]
    revision: str
    loaded_at_monotonic: float

def _is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and (not isinstance(value, bool)) and math.isfinite(float(value))

def _parse_numeric_id(value: Any) -> int | None:
    raw = str(value)
    if not re.fullmatch('\\d+', raw):
        return None
    parsed = int(raw)
    return parsed if 0 <= parsed <= 9007199254740991 else None

def _parse_csv_number(value: Any) -> float | None:
    try:
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None

def parse_v2_dataset_csv(content: str, *, loaded_at_monotonic) -> V2DataSnapshot:
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames or not set(REQUIRED_DATASET_FIELDS).issubset(reader.fieldnames):
        raise V2DataSourceError('V2 定数数据集字段不完整')
    song_map: Dict[Tuple[int, int], V2SongData] = {}
    for row in reader:
        song_id = _parse_numeric_id(row.get('id'))
        level = DIFFICULTY_MAP.get(str(row.get('difficulty') or '').strip().lower())
        if song_id is None or song_id in IGNORED_SONG_IDS or level is None:
            continue
        values = {field: _parse_csv_number(row.get(field)) for field in REQUIRED_DATASET_FIELDS if field not in {'id', 'title', 'difficulty'}}
        if not all((_is_finite_number(value) for value in values.values())):
            continue
        song_map[song_id, level] = V2SongData(song_id=song_id, level=level, title=str(row.get('title') or '').strip(), total_notes=int(values['totalNotes']), sub_constant_1=float(values['sub_constant_1']), main_constant=float(values['main_constant']), sub_constant_2=float(values['sub_constant_2']), stamina=float(values['stamina']), handspeed=float(values['handspeed']), burst=float(values['burst']), complex=float(values['complex']), rhythm=float(values['rhythm']))
    if not song_map:
        raise V2DataSourceError('V2 定数数据集中没有可用谱面')
    return V2DataSnapshot(song_map=MappingProxyType(song_map), revision=hashlib.sha256(content.encode('utf-8')).hexdigest(), loaded_at_monotonic=loaded_at_monotonic)
