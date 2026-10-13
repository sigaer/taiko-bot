"""u0 merge policy. Caller owns combo data, payloads and observation clock.

No filesystem, storage, network or host imports. Inputs are never mutated.
Equal records retain first-member precedence; member order is significant.
"""
from __future__ import annotations
import copy
import re
import hashlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Mapping, Callable

SongKey = Tuple[int, int]
SnapshotItem = Tuple[datetime, Dict[str, Any]]

@dataclass(frozen=True)
class MissingBindUserdata:
    slot: int
    taiko_id: str


@dataclass(frozen=True)
class MaterializedMergedBind:
    virtual_user_id: str
    current_path: Path
    history_dir: Path
    source_ids: Tuple[str, ...]
    profile_source_id: str


class MergedBindError(RuntimeError):
    pass


class MergedBindMissingUserdataError(MergedBindError):
    def __init__(self, missing: Iterable[MissingBindUserdata]):
        self.missing = tuple(missing)
        lines = [f"u{item.slot}:{item.taiko_id}" for item in self.missing]
        super().__init__(
            "u0 合并账户缺少以下本地成绩数据，请先分别更新后再试："
            + " / ".join(lines)
        )


def build_virtual_user_id(identity_key: str) -> str:
    value = str(identity_key or "").strip()
    if not re.fullmatch(r"(?:onebot_v11|qq_official):[A-Za-z0-9_-]{1,128}", value):
        raise MergedBindError("合并账户身份无效。")
    virtual_id = "u0_" + value.replace(":", "_")
    if len(virtual_id) > 128:
        virtual_id = "u0_" + hashlib.sha256(value.encode()).hexdigest()
    return virtual_id


def merge_song_records(records: Iterable[Iterable[Dict[str, Any]]], *, combo_map: Mapping[SongKey, int]) -> List[Dict[str, Any]]:
    merged: Dict[SongKey, Dict[str, Any]] = {}
    stage_totals: Dict[SongKey, int] = {}

    for group in records:
        for raw_song in group:
            if not isinstance(raw_song, dict):
                continue
            key = _song_key(raw_song)
            if key is None:
                continue
            song = copy.deepcopy(raw_song)
            stage_totals[key] = stage_totals.get(key, 0) + _safe_int(song.get("stage_cnt"), 0)

            previous = merged.get(key)
            if previous is None or _is_song_record_better(song, previous, combo_map):
                merged[key] = song

    rows: List[Dict[str, Any]] = []
    for key in sorted(merged.keys()):
        row = merged[key]
        row["stage_cnt"] = stage_totals.get(key, 0)
        rows.append(row)
    return rows


def build_achievement_from_songs(songs: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rank_counts = [0] * 7
    crown_counts = [0] * 3

    for raw_song in songs:
        if not isinstance(raw_song, dict):
            continue
        rank_value = _safe_int(raw_song.get("best_score_rank"), 0)
        if 2 <= rank_value <= 8:
            rank_counts[rank_value - 2] += 1

        clear_cnt = _safe_int(raw_song.get("clear_cnt"), 0)
        full_combo_cnt = _safe_int(raw_song.get("full_combo_cnt"), 0)
        dondaful_cnt = _safe_int(raw_song.get("dondaful_combo_cnt"), 0)
        if clear_cnt > 0 or full_combo_cnt > 0 or dondaful_cnt > 0:
            crown_counts[0] += 1
        if full_combo_cnt > 0 or dondaful_cnt > 0:
            crown_counts[1] += 1
        if dondaful_cnt > 0:
            crown_counts[2] += 1

    if rank_counts[6] > 0:
        count_level = 5
    elif rank_counts[5] > 0:
        count_level = 4
    elif rank_counts[4] > 0:
        count_level = 3
    elif rank_counts[3] > 0:
        count_level = 2
    else:
        count_level = 1

    return {
        "count_level": count_level,
        "ary_crown_count": crown_counts,
        "ary_score_rank_count": rank_counts,
    }


def _merge_payloads(
    payloads: Iterable[Dict[str, Any]],
    *,
    profile_source: Dict[str, Any],
    merge_topology: Optional[Iterable[str]] = None,
    combo_map: Mapping[SongKey, int],
    clock: Callable[[], datetime],
) -> Dict[str, Any]:
    payload_list = [payload for payload in payloads if isinstance(payload, dict)]
    songs = merge_song_records((payload.get("songs", []) or [] for payload in payload_list), combo_map=combo_map)
    achievement = build_achievement_from_songs(songs)
    profile = copy.deepcopy(profile_source.get("profile") or {})
    dojo = copy.deepcopy(profile_source.get("dojo") or {})
    merged_payload = {
        "_meta": {
            "full": True,
            "source": "merged-bind",
            "merge_topology": sorted({str(item) for item in (merge_topology or [])}),
            "schema_version": 2,
            "ts": clock().strftime("%Y-%m-%d %H:%M:%S"),
        },
        "profile": profile,
        "songs": songs,
        "achievement": achievement,
        "dojo": dojo,
    }
    return merged_payload


def _merge_snapshot_histories(
    ids: List[str],
    source_histories: Dict[str, List[SnapshotItem]],
    *,
    profile_source_id: str,
    fallback_profile: Dict[str, Any],
    combo_map: Mapping[SongKey, int],
    clock: Callable[[], datetime],
) -> List[SnapshotItem]:
    all_points = sorted(
        {
            point_time
            for snapshots in source_histories.values()
            for point_time, _payload in snapshots
        }
    )
    if not all_points:
        current_dt = _current_payload_time(fallback_profile, clock=clock)
        return [(current_dt, _merge_payloads([fallback_profile], profile_source=fallback_profile, merge_topology=ids, combo_map=combo_map, clock=clock))]

    positions = {taiko_id: -1 for taiko_id in ids}
    merged: List[SnapshotItem] = []

    for point_time in all_points:
        active_payloads: List[Dict[str, Any]] = []
        profile_payload: Optional[Dict[str, Any]] = None
        for taiko_id in ids:
            snapshots = source_histories.get(taiko_id) or []
            next_pos = positions[taiko_id]
            while next_pos + 1 < len(snapshots) and snapshots[next_pos + 1][0] <= point_time:
                next_pos += 1
            positions[taiko_id] = next_pos
            if next_pos < 0:
                continue
            payload = snapshots[next_pos][1]
            active_payloads.append(payload)
            if taiko_id == profile_source_id:
                profile_payload = payload
        if not active_payloads:
            continue
        merged_payload = _merge_payloads(
            active_payloads,
            profile_source=profile_payload or fallback_profile,
            merge_topology=ids, combo_map=combo_map, clock=clock,
        )
        merged_payload["_meta"]["ts"] = point_time.strftime("%Y-%m-%d %H:%M:%S")
        merged.append((point_time, merged_payload))
    return merged


def _normalize_removed_key(raw_key: Any) -> Optional[SongKey]:
    if isinstance(raw_key, (list, tuple)) and len(raw_key) >= 2:
        try:
            return int(raw_key[0]), int(raw_key[1])
        except Exception:
            return None
    return None


def _song_key(song: Any) -> Optional[SongKey]:
    if not isinstance(song, dict):
        return None
    try:
        return int(song.get("song_no")), int(song.get("level"))
    except Exception:
        return None


def _is_song_record_better(
    candidate: Dict[str, Any],
    current: Dict[str, Any],
    combo_map: Dict[SongKey, int],
) -> bool:
    candidate_dondaful = _safe_int(candidate.get("dondaful_combo_cnt"), 0) > 0
    current_dondaful = _safe_int(current.get("dondaful_combo_cnt"), 0) > 0
    if candidate_dondaful != current_dondaful:
        return candidate_dondaful

    candidate_acc = _song_accuracy(candidate, combo_map)
    current_acc = _song_accuracy(current, combo_map)
    if candidate_acc != current_acc:
        return candidate_acc > current_acc

    candidate_full = _safe_int(candidate.get("full_combo_cnt"), 0)
    current_full = _safe_int(current.get("full_combo_cnt"), 0)
    if candidate_full != current_full:
        return candidate_full > current_full

    candidate_score = _safe_int(candidate.get("high_score"), 0)
    current_score = _safe_int(current.get("high_score"), 0)
    if candidate_score != current_score:
        return candidate_score > current_score

    candidate_rank = _safe_int(candidate.get("best_score_rank"), 0)
    current_rank = _safe_int(current.get("best_score_rank"), 0)
    if candidate_rank != current_rank:
        return candidate_rank > current_rank

    return _song_update_key(candidate) > _song_update_key(current)


def _song_accuracy(song: Dict[str, Any], combo_map: Dict[SongKey, int]) -> float:
    if _safe_int(song.get("dondaful_combo_cnt"), 0) > 0:
        return 1.0
    key = _song_key(song)
    total_notes = combo_map.get(key or (-1, -1), 0)
    if total_notes <= 0:
        total_notes = (
            _safe_int(song.get("good_cnt"), 0)
            + _safe_int(song.get("ok_cnt"), 0)
            + _safe_int(song.get("ng_cnt", song.get("bad_cnt")), 0)
        )
    if total_notes <= 0:
        return 0.0
    return (
        _safe_int(song.get("good_cnt"), 0) + _safe_int(song.get("ok_cnt"), 0) * 0.5
    ) / float(total_notes)


def _song_update_key(song: Dict[str, Any]) -> str:
    return str(song.get("update_datetime") or song.get("highscore_datetime") or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _current_payload_time(payload: Dict[str, Any], *, clock: Callable[[], datetime]) -> datetime:
    update_candidates = [
        _song_update_key(song)
        for song in (payload.get("songs") or [])
        if isinstance(song, dict) and _song_update_key(song)
    ]
    for raw_value in sorted(update_candidates, reverse=True):
        try:
            return datetime.strptime(raw_value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return clock()
