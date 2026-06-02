from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .snapshot_history import list_snapshot_files, parse_snapshot_time
from taiko_bot.settings import get_settings

ROOT_DIR = Path(__file__).resolve().parents[2]
USERDATA_DIR = get_settings().userdata_dir
SONG_DATA_PATH = ROOT_DIR / "songs" / "song_data.json"

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
    sanitized = re.sub(r"[^0-9A-Za-z._-]+", "_", str(identity_key or "").strip())
    sanitized = sanitized.strip("._-") or "anonymous"
    return f"u0_{sanitized}"


def materialize_merged_bind_userdata(
    identity_key: str,
    entry: Dict[str, Any],
    *,
    userdata_dir: Path = USERDATA_DIR,
) -> MaterializedMergedBind:
    ids = [str(raw or "").strip() for raw in (entry.get("ids") or []) if str(raw or "").strip()]
    if len(ids) < 2:
        raise MergedBindError("当前绑定数量不足，无法生成 u0 合并账户。")

    current_index = int(entry.get("current_index", 0) or 0)
    current_index = max(0, min(current_index, len(ids) - 1))
    profile_source_id = ids[current_index]

    current_payloads: Dict[str, Dict[str, Any]] = {}
    missing: List[MissingBindUserdata] = []
    for slot, taiko_id in enumerate(ids, start=1):
        payload = _load_current_userdata(taiko_id, userdata_dir=userdata_dir)
        if payload is None:
            missing.append(MissingBindUserdata(slot=slot, taiko_id=taiko_id))
            continue
        current_payloads[taiko_id] = payload
    if missing:
        raise MergedBindMissingUserdataError(missing)

    virtual_user_id = build_virtual_user_id(identity_key)
    current_path = userdata_dir / f"{virtual_user_id}data.json"
    history_dir = userdata_dir / virtual_user_id

    merged_current = _merge_payloads(
        [current_payloads[taiko_id] for taiko_id in ids],
        profile_source=current_payloads[profile_source_id],
    )
    _write_json_atomic(current_path, merged_current)

    source_histories = {
        taiko_id: _load_snapshot_history_with_current(taiko_id, userdata_dir=userdata_dir)
        for taiko_id in ids
    }
    merged_history = _merge_snapshot_histories(
        ids,
        source_histories,
        profile_source_id=profile_source_id,
        fallback_profile=current_payloads[profile_source_id],
    )
    _write_full_snapshot_history(history_dir, merged_history)

    return MaterializedMergedBind(
        virtual_user_id=virtual_user_id,
        current_path=current_path,
        history_dir=history_dir,
        source_ids=tuple(ids),
        profile_source_id=profile_source_id,
    )


def merge_song_records(records: Iterable[Iterable[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    combo_map = _load_song_combo_map()
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
) -> Dict[str, Any]:
    payload_list = [payload for payload in payloads if isinstance(payload, dict)]
    songs = merge_song_records(payload.get("songs", []) or [] for payload in payload_list)
    achievement = build_achievement_from_songs(songs)
    profile = copy.deepcopy(profile_source.get("profile") or {})
    dojo = copy.deepcopy(profile_source.get("dojo") or {})
    merged_payload = {
        "_meta": {
            "full": True,
            "source": "merged-bind",
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
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
) -> List[SnapshotItem]:
    all_points = sorted(
        {
            point_time
            for snapshots in source_histories.values()
            for point_time, _payload in snapshots
        }
    )
    if not all_points:
        current_dt = _current_payload_time(fallback_profile)
        return [(current_dt, _merge_payloads([fallback_profile], profile_source=fallback_profile))]

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
        )
        merged_payload["_meta"]["ts"] = point_time.strftime("%Y-%m-%d %H:%M:%S")
        merged.append((point_time, merged_payload))
    return merged


def _load_current_userdata(
    taiko_id: str,
    *,
    userdata_dir: Path,
) -> Optional[Dict[str, Any]]:
    path = userdata_dir / f"{taiko_id}data.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MergedBindError(f"读取 {taiko_id} 的本地成绩文件失败：{exc}") from exc
    if not isinstance(payload, dict):
        raise MergedBindError(f"{taiko_id} 的本地成绩文件格式无效。")
    payload.setdefault("songs", [])
    return payload


def _load_snapshot_history_with_current(
    taiko_id: str,
    *,
    userdata_dir: Path,
) -> List[SnapshotItem]:
    current_payload = _load_current_userdata(taiko_id, userdata_dir=userdata_dir)
    if current_payload is None:
        return []

    history_dir = userdata_dir / taiko_id
    snapshots = _reconstruct_full_snapshots(history_dir)
    current_path = userdata_dir / f"{taiko_id}data.json"
    current_dt = datetime.fromtimestamp(current_path.stat().st_mtime)
    if not snapshots:
        return [(current_dt, current_payload)]

    latest_dt, latest_payload = snapshots[-1]
    if latest_dt < current_dt or latest_payload != current_payload:
        snapshots.append((current_dt, current_payload))
    return snapshots


def _reconstruct_full_snapshots(history_dir: Path) -> List[SnapshotItem]:
    if not history_dir.exists():
        return []

    snapshots: List[SnapshotItem] = []
    current_profile: Dict[str, Any] = {}
    current_achievement: Dict[str, Any] = {}
    current_dojo: Dict[str, Any] = {}
    song_map: Dict[SongKey, Dict[str, Any]] = {}
    has_base = False

    for path in list_snapshot_files(history_dir):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
        is_full = bool(meta.get("full")) or (
            "songs" in payload and "profile" in payload and "achievement" in payload
        )
        if is_full:
            current_profile = copy.deepcopy(payload.get("profile") or {})
            current_achievement = copy.deepcopy(payload.get("achievement") or {})
            current_dojo = copy.deepcopy(payload.get("dojo") or {})
            song_map = {}
            for song in payload.get("songs") or []:
                key = _song_key(song)
                if key is None or not isinstance(song, dict):
                    continue
                song_map[key] = copy.deepcopy(song)
            has_base = True
        else:
            if not has_base:
                continue
            if "profile" in payload:
                current_profile = copy.deepcopy(payload.get("profile") or {})
            if "achievement" in payload:
                current_achievement = copy.deepcopy(payload.get("achievement") or {})
            if "dojo" in payload:
                current_dojo = copy.deepcopy(payload.get("dojo") or {})
            for song in payload.get("songs") or []:
                key = _song_key(song)
                if key is None or not isinstance(song, dict):
                    continue
                song_map[key] = copy.deepcopy(song)
            for raw_key in payload.get("songs_removed") or []:
                normalized_key = _normalize_removed_key(raw_key)
                if normalized_key is None:
                    continue
                song_map.pop(normalized_key, None)

        snapshots.append(
            (
                parse_snapshot_time(path),
                {
                    "profile": copy.deepcopy(current_profile),
                    "achievement": copy.deepcopy(current_achievement),
                    "dojo": copy.deepcopy(current_dojo),
                    "songs": [copy.deepcopy(song) for song in song_map.values()],
                },
            )
        )

    return snapshots


def _normalize_removed_key(raw_key: Any) -> Optional[SongKey]:
    if isinstance(raw_key, (list, tuple)) and len(raw_key) >= 2:
        try:
            return int(raw_key[0]), int(raw_key[1])
        except Exception:
            return None
    return None


def _write_full_snapshot_history(history_dir: Path, snapshots: List[SnapshotItem]) -> None:
    history_dir.mkdir(parents=True, exist_ok=True)
    for path in history_dir.glob("data_*.json"):
        path.unlink(missing_ok=True)

    for point_time, payload in snapshots:
        snapshot_name = f"data_{point_time.strftime('%Y%m%d_%H%M%S_%f')}_merged-bind.json"
        _write_json_atomic(history_dir / snapshot_name, payload)


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + f".tmp-{datetime.now().timestamp():.0f}")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=4), encoding="utf-8")
    temp_path.replace(path)


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


def _current_payload_time(payload: Dict[str, Any]) -> datetime:
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
    return datetime.now()


_SONG_COMBO_MAP_CACHE: Optional[Dict[SongKey, int]] = None


def _load_song_combo_map() -> Dict[SongKey, int]:
    global _SONG_COMBO_MAP_CACHE
    if _SONG_COMBO_MAP_CACHE is not None:
        return _SONG_COMBO_MAP_CACHE

    combo_map: Dict[SongKey, int] = {}
    try:
        rows = json.loads(SONG_DATA_PATH.read_text(encoding="utf-8"))
    except Exception:
        rows = []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            song_no = _safe_int(row.get("id"), -1)
            if song_no <= 0:
                continue
            max_combo = row.get("max_combo")
            if isinstance(max_combo, list):
                for idx, raw_combo in enumerate(max_combo, start=1):
                    combo = _safe_int(raw_combo, 0)
                    if combo > 0:
                        combo_map[(song_no, idx)] = combo
            elif max_combo not in (None, "", "-"):
                combo = _safe_int(max_combo, 0)
                if combo > 0:
                    combo_map[(song_no, 4)] = combo

    _SONG_COMBO_MAP_CACHE = combo_map
    return combo_map
