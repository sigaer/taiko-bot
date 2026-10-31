from __future__ import annotations
import math
import re
from dataclasses import dataclass, replace, field
from datetime import date, datetime
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Set, Tuple

def normalize_song_title(text: Any) -> str:
    normalized = str(text or '').strip()
    normalized = normalized.replace('〜', '～')
    normalized = normalized.replace('~', '～')
    normalized = normalized.replace('（', '(')
    normalized = normalized.replace('）', ')')
    normalized = normalized.replace('＆', '&')
    normalized = normalized.replace('＠', '@')
    normalized = normalized.replace('！', '!')
    normalized = normalized.replace('？', '?')
    for src in ('‐', '‑', '‒', '–', '—', '―', '－', 'ｰ'):
        normalized = normalized.replace(src, '-')
    normalized = normalized.replace('【限定】', '')
    normalized = normalized.replace('(裏)', '')
    normalized = normalized.replace('(裏譜面)', '')
    normalized = re.sub('\\s+', '', normalized)
    return normalized.lower()

def normalize_song_title_aggressive(text: Any) -> str:
    normalized = normalize_song_title(text)
    normalized = re.sub('\\([^)]*\\)', '', normalized)
    return normalized

def _safe_int(value: Any, default: int=-1) -> int:
    try:
        return int(value)
    except Exception:
        return default

def _safe_float(value: Any, default: float=0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default

def _title_candidates(song: Mapping[str, Any]) -> List[str]:
    candidates = [song.get('song_name'), song.get('song_name_jp'), song.get('title_cn'), song.get('title_jp'), song.get('title')]
    out: List[str] = []
    seen: set[str] = set()
    for value in candidates:
        normalized = normalize_song_title(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(str(value or '').strip())
    return out

@dataclass(frozen=True)
class DuplicateSongGroup:
    key: str
    ids: Tuple[int, ...]
    default_id: int
    display_title: str

def build_group_maps(song_rows) -> Tuple[Dict[str, DuplicateSongGroup], Dict[int, DuplicateSongGroup], Dict[str, DuplicateSongGroup]]:
    ids_by_group: Dict[str, set[int]] = {}
    title_by_group: Dict[str, str] = {}
    for row in song_rows:
        if not isinstance(row, dict):
            continue
        song_id = _safe_int(row.get('id'))
        if song_id < 0:
            continue
        titles = _title_candidates(row)
        if not titles:
            continue
        primary_title = titles[0]
        normalized_key = normalize_song_title(primary_title)
        ids_by_group.setdefault(normalized_key, set()).add(song_id)
        title_by_group.setdefault(normalized_key, primary_title)
        for candidate in titles[1:]:
            alias_key = normalize_song_title(candidate)
            if alias_key and alias_key != normalized_key:
                ids_by_group.setdefault(normalized_key, set()).add(song_id)
    groups_by_key: Dict[str, DuplicateSongGroup] = {}
    groups_by_id: Dict[int, DuplicateSongGroup] = {}
    groups_by_title: Dict[str, DuplicateSongGroup] = {}
    for key, ids in ids_by_group.items():
        if not ids:
            continue
        sorted_ids = tuple(sorted(ids))
        group = DuplicateSongGroup(key=key, ids=sorted_ids, default_id=sorted_ids[0], display_title=title_by_group.get(key, str(sorted_ids[0])))
        groups_by_key[key] = group
        for song_id in sorted_ids:
            groups_by_id[song_id] = group
        groups_by_title[key] = group
        aggressive_key = normalize_song_title_aggressive(group.display_title)
        if aggressive_key:
            groups_by_title.setdefault(aggressive_key, group)
    return (groups_by_key, groups_by_id, groups_by_title)

def group_for_song_id(song_id: int | str | None, *, groups_by_id, groups_by_title) -> Optional[DuplicateSongGroup]:
    try:
        target_id = int(song_id)
    except Exception:
        return None
    return groups_by_id.get(target_id)

def group_for_title(title: str, *, groups_by_id, groups_by_title) -> Optional[DuplicateSongGroup]:
    normalized = normalize_song_title(title)
    if normalized and normalized in groups_by_title:
        return groups_by_title[normalized]
    aggressive = normalize_song_title_aggressive(title)
    if aggressive and aggressive in groups_by_title:
        return groups_by_title[aggressive]
    return None

def default_song_id_for_query(song_id: int | None=None, *, title: str='', groups_by_id, groups_by_title) -> Optional[int]:
    group = group_for_song_id(song_id, groups_by_id=groups_by_id, groups_by_title=groups_by_title) if song_id is not None else None
    if group is None and title:
        group = group_for_title(title, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
    if group is None:
        return song_id
    return group.default_id

def duplicate_identity_key(song_id: int, level: int, *, groups_by_id, groups_by_title) -> Tuple[str, int, int]:
    group = group_for_song_id(song_id, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
    if group is None:
        return ('song', song_id, level)
    return ('title', group.default_id, level)

def duplicate_identity_key_by_title(title: str, level: int, *, groups_by_id, groups_by_title) -> Tuple[str, int, int] | Tuple[str, str, int]:
    group = group_for_title(title, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
    if group is None:
        normalized = normalize_song_title_aggressive(title) or normalize_song_title(title) or str(title)
        return ('title_name', normalized, level)
    return ('title', group.default_id, level)

def collapse_query_results_by_group(rows: Sequence[Sequence[Any]], *, groups_by_id, groups_by_title) -> List[List[Any]]:
    grouped: Dict[Tuple[str, int], List[Any]] = {}
    ordered: List[Tuple[str, int]] = []
    for row in rows:
        if not row:
            continue
        try:
            song_id = int(row[0])
        except Exception:
            key = ('unknown', len(ordered))
            grouped[key] = list(row)
            ordered.append(key)
            continue
        group = group_for_song_id(song_id, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
        normalized_key = ('title', group.default_id) if group is not None else ('song', song_id)
        existing = grouped.get(normalized_key)
        if existing is None:
            grouped[normalized_key] = list(row)
            ordered.append(normalized_key)
            continue
        candidate = list(row)
        if group is not None:
            current_id = _safe_int(existing[0], 10 ** 9)
            candidate_id = _safe_int(candidate[0], 10 ** 9)
            if candidate_id < current_id:
                grouped[normalized_key] = candidate
    return [grouped[key] for key in ordered]

def group_ids_for_query(*, song_id: int | None=None, title: str='', groups_by_id, groups_by_title) -> Tuple[int, ...]:
    group = group_for_song_id(song_id, groups_by_id=groups_by_id, groups_by_title=groups_by_title) if song_id is not None else None
    if group is None and title:
        group = group_for_title(title, groups_by_id=groups_by_id, groups_by_title=groups_by_title)
    if group is None:
        return (song_id,) if song_id is not None else tuple()
    return group.ids

def quality_sort_key_for_record(record: Mapping[str, Any], *, note_count: int=0) -> Tuple[float, int, int, int, int]:
    total_notes = max(int(note_count), 0)
    great = _safe_int(record.get('good_cnt'), 0)
    good = _safe_int(record.get('ok_cnt'), 0)
    score = _safe_int(record.get('high_score'), 0)
    dondaful = _safe_int(record.get('dondaful_combo_cnt'), 0)
    full_combo = _safe_int(record.get('full_combo_cnt'), 0)
    clear = _safe_int(record.get('clear_cnt'), 0)
    crown_score = (1 if clear > 0 else 0) + (1 if full_combo > 0 else 0) + (1 if dondaful > 0 else 0)
    accuracy = 0.0
    if dondaful > 0:
        accuracy = 1.0
    elif total_notes > 0:
        accuracy = (great + 0.5 * good) / total_notes
    return (accuracy, score, crown_score, dondaful + full_combo + clear, -_safe_int(record.get('song_no'), 10 ** 9))

def choose_best_record(records: Iterable[Mapping[str, Any]], *, note_count_by_key: Optional[Mapping[Tuple[int, int], int]]=None, level: Optional[int]=None) -> Optional[Dict[str, Any]]:
    best: Optional[Dict[str, Any]] = None
    best_key: Optional[Tuple[float, int, int, int, int]] = None
    for record in records:
        if not isinstance(record, Mapping):
            continue
        song_id = _safe_int(record.get('song_no'), -1)
        record_level = _safe_int(record.get('level'), -1)
        if song_id < 0 or record_level < 0:
            continue
        if level is not None and record_level != level:
            continue
        note_count = 0
        if note_count_by_key:
            note_count = int(note_count_by_key.get((song_id, record_level), 0) or 0)
        sort_key = quality_sort_key_for_record(record, note_count=note_count)
        if best is None or sort_key > best_key:
            best = dict(record)
            best_key = sort_key
    return best

def choose_best_record_in_group(records: Iterable[Mapping[str, Any]], *, song_id: int | None=None, title: str='', level: Optional[int]=None, note_count_by_key: Optional[Mapping[Tuple[int, int], int]]=None, groups_by_id, groups_by_title) -> Optional[Dict[str, Any]]:
    ids = set(group_ids_for_query(song_id=song_id, title=title, groups_by_id=groups_by_id, groups_by_title=groups_by_title))
    candidates = []
    for record in records:
        if not isinstance(record, Mapping):
            continue
        record_song_id = _safe_int(record.get('song_no'), -1)
        if ids and record_song_id not in ids:
            continue
        candidates.append(record)
    return choose_best_record(candidates, note_count_by_key=note_count_by_key, level=level)
