from __future__ import annotations

import copy
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from taiko_application import merged_bind as _kernel
from taiko_application.merged_bind import (
    MissingBindUserdata, MaterializedMergedBind, MergedBindError,
    MergedBindMissingUserdataError, build_virtual_user_id,
    build_achievement_from_songs, _normalize_removed_key, _song_key,
    _is_song_record_better, _song_accuracy, _song_update_key, _safe_int,
)
from taiko_store.merge_reference import _load_song_combo_map


def merge_song_records(records):
    return _kernel.merge_song_records(records, combo_map=_load_song_combo_map())


def _merge_payloads(payloads, *, profile_source, merge_topology=None):
    return _kernel._merge_payloads(payloads, profile_source=profile_source,
        merge_topology=merge_topology, combo_map=_load_song_combo_map(), clock=datetime.now)


def _merge_snapshot_histories(ids, source_histories, *, profile_source_id, fallback_profile):
    return _kernel._merge_snapshot_histories(ids, source_histories,
        profile_source_id=profile_source_id, fallback_profile=fallback_profile,
        combo_map=_load_song_combo_map(), clock=datetime.now)


def _current_payload_time(payload):
    return _kernel._current_payload_time(payload, clock=datetime.now)


from taiko_bot.runtime.player.center.snapshot_history import list_snapshot_files, parse_snapshot_time

from taiko_bot.offline.paths import root
ROOT_DIR = root()
USERDATA_DIR = ROOT_DIR / "userdata"

SongKey = Tuple[int, int]
SnapshotItem = Tuple[datetime, Dict[str, Any]]


def materialize_merged_bind_userdata(
    identity_key: str,
    entry: Dict[str, Any],
    *,
    userdata_dir: Optional[Path] = None,
) -> MaterializedMergedBind:
    from taiko_store.merged_materialization import materialize
    from taiko_store.publication import PublicationError

    if not isinstance(entry, dict) or not isinstance(entry.get("ids"), (list, tuple)):
        raise MergedBindError("合并账户绑定无效。")
    ids = entry["ids"]
    if (not 2 <= len(ids) <= 128 or any(not isinstance(item, str) for item in ids)
            or len(set(ids)) != len(ids)):
        raise MergedBindError("当前绑定数量或账号无效，无法生成 u0 合并账户。")
    index = entry.get("current_index", 0) or 0
    if type(index) is not int:
        raise MergedBindError("合并账户资料来源无效。")
    index = max(0, min(index, len(ids) - 1))
    virtual_id = build_virtual_user_id(identity_key)
    root = Path(userdata_dir) if userdata_dir is not None else Path(os.getenv("TAIKO_USERDATA_DIR") or USERDATA_DIR)
    try:
        return materialize(root, identity_key, ids, ids[index], virtual_id)
    except (PublicationError, OSError, ValueError):
        raise MergedBindError("合并账户数据暂不可用，请更新真实账号后重试。") from None


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
            "songs" in payload
            and "profile" in payload
            and "achievement" in payload
            and not meta
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
