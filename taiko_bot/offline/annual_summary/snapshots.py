from __future__ import annotations

import copy
import marshal
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from taiko_bot.runtime.player.center.snapshot_history import list_snapshot_files, parse_snapshot_time
from .cache import read_normalized_snapshot, write_normalized_snapshot
from .constants import FULL_SNAPSHOT_MIN_SONGS, MANUAL_SOURCES, USERDATA_DIR
from .helpers import canonical_json_bytes, file_sha256, load_json, parse_datetime, safe_int, song_key
from .model import RebuiltSnapshot, SnapshotHistory, SnapshotPlanEntry, WindowSelection
from .profiling import mark_profile_stage, observe_profile_objects, profiling_enabled


_FAST_SIGNATURE_MIN_SNAPSHOTS = 50


def _fast_json_signature(payload: Any) -> bytes:
    """Return an exact, process-local fast path for canonical JSON equality.

    Equal tokens guarantee the same supported JSON value graph. A token miss
    still falls back to canonical JSON because mapping order and object sharing
    can change marshal bytes without changing canonical JSON.
    """
    return marshal.dumps(payload, 4)


def is_full_snapshot(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    meta = payload.get("_meta")
    if isinstance(meta, dict) and meta.get("full") is True:
        return True
    if isinstance(meta, dict) and meta.get("full") is False:
        return False
    has_full_shape = (
        isinstance(payload.get("profile"), dict)
        and isinstance(payload.get("achievement"), dict)
        and isinstance(payload.get("songs"), list)
    )
    if not has_full_shape:
        return False
    if not meta:
        return True
    return len(payload.get("songs") or []) >= FULL_SNAPSHOT_MIN_SONGS


def _normalize_source(raw: Any) -> str:
    source = str(raw or "").strip().lower().replace("_", "-")
    aliases = {
        "official": "wahlap",
        "wahlap-cn": "wahlap",
        "web": "web-account",
        "manual": "web-account",
        "merged": "merged-bind",
    }
    return aliases.get(source, source or "unknown")


def _infer_source(payload: Dict[str, Any], path: Path) -> str:
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    explicit = meta.get("source")
    if explicit:
        return _normalize_source(explicit)
    profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
    if profile.get("_source"):
        return _normalize_source(profile.get("_source"))
    lowered = path.name.lower()
    if "web-account" in lowered:
        return "web-account"
    if "hiroba" in lowered:
        return "hiroba"
    if "merged" in lowered:
        return "merged-bind"
    return "unknown"


def _normalize_topology(meta: Dict[str, Any]) -> List[str]:
    raw = (
        meta.get("merge_topology")
        or meta.get("mergeTopology")
        or meta.get("member_ids")
        or meta.get("memberIds")
        or []
    )
    if isinstance(raw, dict):
        raw = raw.get("members") or raw.get("ids") or list(raw.keys())
    if isinstance(raw, str):
        raw = [item.strip() for item in raw.split(",")]
    if not isinstance(raw, (list, tuple, set)):
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def _read_snapshot_plan_entry(path: Path) -> Optional[SnapshotPlanEntry]:
    try:
        content_hash = file_sha256(path)
        size = path.stat().st_size
    except OSError:
        return None
    normalized = read_normalized_snapshot(content_hash)
    payload = normalized.get("payload") if isinstance(normalized, dict) else None
    try:
        if payload is None:
            payload = load_json(path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    observe_profile_objects(raw_payload_count=1, raw_payload_estimated_bytes=size)
    meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
    # Web edits inherit the last sync metadata; their own timestamp is authoritative.
    source = _infer_source(payload, path)
    observed_at = (parse_datetime(meta.get("ts")) if source in MANUAL_SOURCES else
                   parse_datetime(meta.get("observed_at") or meta.get("observedAt") or meta.get("synced_at")))
    if observed_at is None:
        observed_at = parse_snapshot_time(path)
    if observed_at == datetime.min:
        try:
            observed_at = datetime.fromtimestamp(path.stat().st_mtime)
        except OSError:
            return None
    source = _infer_source(payload, path)
    source_account = (
        meta.get("source_account")
        or meta.get("sourceAccount")
        or meta.get("account_id")
        or None
    )
    account_inferred = False
    if not source_account and source in {"unknown", "sakura-bot-sync", "wahlap"}:
        profile = payload.get("profile") if isinstance(payload.get("profile"), dict) else {}
        profile_userid = str(profile.get("userid") or "").strip()
        if profile_userid:
            source_account = profile_userid
            account_inferred = True
    cached_warnings = normalized.get("warnings") if isinstance(normalized, dict) else None
    warnings: List[str] = [str(item) for item in cached_warnings] if isinstance(cached_warnings, list) else []
    if account_inferred:
        warnings.append("lineage_source_account_inferred")
    if not isinstance(cached_warnings, list):
        seen = set()
        for raw_song in payload.get("songs") or []:
            if not isinstance(raw_song, dict):
                continue
            key = song_key(raw_song)
            if key in seen:
                warnings.append(f"duplicate_chart:{key[0]}:{key[1]}")
            seen.add(key)
        write_normalized_snapshot(
            content_hash,
            {
                "payload": payload,
                "warnings": sorted(set(warnings)),
            },
        )
    return SnapshotPlanEntry(
        path=path,
        observed_at=observed_at,
        is_full=is_full_snapshot(payload),
        source=source,
        source_account=str(source_account).strip() if source_account else None,
        merge_topology=_normalize_topology(meta),
        content_hash=content_hash,
        size=size,
        warnings=sorted(set(warnings)),
    )


def _load_snapshot_payload(item: SnapshotPlanEntry) -> Optional[Dict[str, Any]]:
    normalized = read_normalized_snapshot(item.content_hash)
    payload = normalized.get("payload") if isinstance(normalized, dict) else None
    try:
        if payload is None:
            payload = load_json(item.path)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    observe_profile_objects(raw_payload_count=1, raw_payload_estimated_bytes=item.size)
    return payload


def _candidate_paths(taiko_id: str | int, userdata_dir: str | Path) -> List[Path]:
    root = Path(userdata_dir)
    history_dir = root / str(taiko_id)
    paths = list_snapshot_files(history_dir) if history_dir.exists() else []
    current_path = root / f"{taiko_id}data.json"
    if not paths and current_path.exists():
        paths.append(current_path)
    return paths


def load_snapshot_history(
    taiko_id: str | int, *, userdata_dir: str | Path = USERDATA_DIR
) -> SnapshotHistory:
    candidates: List[SnapshotPlanEntry] = []
    warnings: List[str] = []
    ignored_files = 0
    raw_candidates = _candidate_paths(taiko_id, userdata_dir)
    mark_profile_stage("source_discovery_complete", rawSnapshotCount=len(raw_candidates))
    previous_input_time: Optional[datetime] = None
    for path in raw_candidates:
        item = _read_snapshot_plan_entry(path)
        if item is None:
            ignored_files += 1
            warnings.append(f"invalid_snapshot:{path.name}")
            continue
        if previous_input_time and item.observed_at < previous_input_time:
            warnings.append(f"out_of_order_snapshot:{path.name}")
        previous_input_time = item.observed_at
        candidates.append(item)
        observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)

    mark_profile_stage("raw_snapshot_load_complete", rawSnapshotCount=len(candidates))

    root = Path(userdata_dir)
    current_path = root / f"{taiko_id}data.json"
    lineage_hint = None
    lineage_account_hint = None
    if current_path.exists():
        current_input = _read_snapshot_plan_entry(current_path)
        if current_input and current_input.source != "unknown":
            lineage_hint = current_input.source
            if current_input.source_account == str(taiko_id):
                lineage_account_hint = current_input.source_account
        observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)
    known_history_sources = {
        item.source
        for item in candidates
        if item.source not in {"unknown", *MANUAL_SOURCES}
    }
    if lineage_hint == "wahlap" and known_history_sources.issubset({"wahlap", "sakura-bot-sync"}):
        inferred_count = sum(1 for item in candidates if item.source in {"unknown", "sakura-bot-sync"})
        account_inferred_count = sum(
            1
            for item in candidates
            if lineage_account_hint
            and item.source in {"unknown", "sakura-bot-sync", "wahlap"}
            and not item.source_account
        )
        if inferred_count or account_inferred_count:
            normalized_candidates = []
            for item in candidates:
                source_inferred = item.source in {"unknown", "sakura-bot-sync"}
                account_inferred = bool(
                    lineage_account_hint
                    and item.source in {"unknown", "sakura-bot-sync", "wahlap"}
                    and not item.source_account
                )
                item_warnings = list(item.warnings)
                if source_inferred:
                    item_warnings.append("lineage_source_inferred:wahlap")
                if account_inferred:
                    item_warnings.append("lineage_source_account_inferred")
                normalized_candidates.append(
                    replace(
                        item,
                        source="wahlap" if source_inferred else item.source,
                        source_account=lineage_account_hint if account_inferred else item.source_account,
                        warnings=sorted(set(item_warnings)),
                    )
                    if source_inferred or account_inferred
                    else item
                )
            candidates = normalized_candidates
        if inferred_count:
            warnings.append("lineage_source_inferred:wahlap")
        if account_inferred_count:
            warnings.append("lineage_source_account_inferred")

    candidates.sort(
        key=lambda item: (
            item.observed_at,
            0 if item.is_full else 1,
            item.path.name,
            item.content_hash,
        )
    )
    plan: List[SnapshotPlanEntry] = []
    seen_payload_hashes = set()
    for item in candidates:
        if item.content_hash in seen_payload_hashes:
            warnings.append(f"duplicate_snapshot:{item.path.name}")
            continue
        seen_payload_hashes.add(item.content_hash)
        plan.append(item)
    mark_profile_stage(
        "ordering_dedup_lineage_complete",
        rawSnapshotCount=len(candidates),
        plannedSnapshotCount=len(plan),
    )
    del candidates

    snapshots: List[RebuiltSnapshot] = []
    profile: Dict[str, Any] = {}
    achievement: Dict[str, Any] = {}
    dojo: Dict[str, Any] = {}
    songs: Dict[tuple[int, int], Dict[str, Any]] = {}
    current_source = "unknown"
    current_source_account: Optional[str] = None
    current_topology: List[str] = []
    has_base = False
    previous_observed_at: Optional[datetime] = None
    # Signatures are maintained per branch/chart so unchanged detection does
    # not serialize the complete retained state for every snapshot.  The
    # canonical JSON bytes preserve the old hash's distinctions (for example,
    # key order is ignored while JSON number spelling remains significant).
    profile_signature: Optional[bytes] = None
    achievement_signature: Optional[bytes] = None
    dojo_signature: Optional[bytes] = None
    song_signatures: Dict[tuple[int, int], bytes] = {}
    profile_fast_signature: Optional[bytes] = None
    achievement_fast_signature: Optional[bytes] = None
    dojo_fast_signature: Optional[bytes] = None
    song_fast_signatures: Dict[tuple[int, int], bytes] = {}
    has_previous_state = False
    # Short histories rarely repeat enough objects to repay a second, fast
    # serialization pass. The threshold comes from the Phase 4 fixture matrix;
    # it affects only the equality strategy, never replay semantics.
    reuse_fast_signatures = len(plan) >= _FAST_SIGNATURE_MIN_SNAPSHOTS

    for item in plan:
        if previous_observed_at and item.observed_at < previous_observed_at:
            warnings.append(f"out_of_order_snapshot:{item.path.name}")
        previous_observed_at = item.observed_at

        payload = _load_snapshot_payload(item)
        if payload is None:
            ignored_files += 1
            warnings.append(f"invalid_snapshot:{item.path.name}")
            observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)
            continue
        state_changed = not has_previous_state
        changed_keys: set[tuple[int, int]] = set()
        previous_profile_signature = profile_signature
        previous_achievement_signature = achievement_signature
        previous_dojo_signature = dojo_signature
        previous_song_signatures = song_signatures
        previous_profile_fast_signature = profile_fast_signature
        previous_achievement_fast_signature = achievement_fast_signature
        previous_dojo_fast_signature = dojo_fast_signature
        previous_song_fast_signatures = song_fast_signatures
        if item.is_full:
            previous_songs = songs
            raw_profile = payload.get("profile") or {}
            raw_achievement = payload.get("achievement") or {}
            raw_dojo = payload.get("dojo") or {}
            profile_fast_signature = _fast_json_signature(raw_profile) if reuse_fast_signatures else None
            achievement_fast_signature = _fast_json_signature(raw_achievement) if reuse_fast_signatures else None
            dojo_fast_signature = _fast_json_signature(raw_dojo) if reuse_fast_signatures else None
            if (
                reuse_fast_signatures
                and previous_profile_signature is not None
                and profile_fast_signature == previous_profile_fast_signature
            ):
                profile_signature = previous_profile_signature
            else:
                profile_signature = canonical_json_bytes(raw_profile)
            if (
                reuse_fast_signatures
                and previous_achievement_signature is not None
                and achievement_fast_signature == previous_achievement_fast_signature
            ):
                achievement_signature = previous_achievement_signature
            else:
                achievement_signature = canonical_json_bytes(raw_achievement)
            if (
                reuse_fast_signatures
                and previous_dojo_signature is not None
                and dojo_fast_signature == previous_dojo_fast_signature
            ):
                dojo_signature = previous_dojo_signature
            else:
                dojo_signature = canonical_json_bytes(raw_dojo)
            profile = copy.deepcopy(raw_profile)
            achievement = copy.deepcopy(raw_achievement)
            dojo = copy.deepcopy(raw_dojo)
            songs = {}
            song_signatures = {}
            song_fast_signatures = {}
            for raw_song in payload.get("songs") or []:
                if not isinstance(raw_song, dict):
                    continue
                key = song_key(raw_song)
                if key[0] > 0 and key[1] > 0:
                    candidate_fast_signature = (
                        _fast_json_signature(raw_song) if reuse_fast_signatures else None
                    )
                    candidate_signature = previous_song_signatures.get(key)
                    if not (
                        reuse_fast_signatures
                        and candidate_signature is not None
                        and previous_song_fast_signatures.get(key) == candidate_fast_signature
                    ):
                        candidate_signature = canonical_json_bytes(raw_song)
                    if previous_song_signatures.get(key) == candidate_signature and key in previous_songs:
                        song = previous_songs[key]
                    else:
                        song = copy.deepcopy(raw_song)
                        changed_keys.add(key)
                    songs[key] = song
                    song_signatures[key] = candidate_signature
                    if candidate_fast_signature is not None:
                        song_fast_signatures[key] = candidate_fast_signature
            current_source = item.source
            current_source_account = item.source_account
            current_topology = list(item.merge_topology)
            has_base = True
            state_changed = (
                not has_previous_state
                or profile_signature != previous_profile_signature
                or achievement_signature != previous_achievement_signature
                or dojo_signature != previous_dojo_signature
                or song_signatures != previous_song_signatures
            )
            # New and modified keys were recorded while rebuilding the map;
            # only removals still need to be added here.
            changed_keys.update(previous_song_signatures.keys() - song_signatures.keys())
        else:
            if not has_base:
                warnings.append(f"delta_without_base:{item.path.name}")
                del payload
                observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)
                continue
            if isinstance(payload.get("profile"), dict):
                candidate = copy.deepcopy(payload["profile"])
                candidate_fast_signature = (
                    _fast_json_signature(candidate) if reuse_fast_signatures else None
                )
                candidate_signature = profile_signature
                if not reuse_fast_signatures or candidate_fast_signature != profile_fast_signature:
                    candidate_signature = canonical_json_bytes(candidate)
                state_changed = state_changed or candidate_signature != profile_signature
                profile = candidate
                profile_signature = candidate_signature
                profile_fast_signature = candidate_fast_signature
            if isinstance(payload.get("achievement"), dict):
                candidate = copy.deepcopy(payload["achievement"])
                candidate_fast_signature = (
                    _fast_json_signature(candidate) if reuse_fast_signatures else None
                )
                candidate_signature = achievement_signature
                if not reuse_fast_signatures or candidate_fast_signature != achievement_fast_signature:
                    candidate_signature = canonical_json_bytes(candidate)
                state_changed = state_changed or candidate_signature != achievement_signature
                achievement = candidate
                achievement_signature = candidate_signature
                achievement_fast_signature = candidate_fast_signature
            if isinstance(payload.get("dojo"), dict):
                candidate = copy.deepcopy(payload["dojo"])
                candidate_fast_signature = (
                    _fast_json_signature(candidate) if reuse_fast_signatures else None
                )
                candidate_signature = dojo_signature
                if not reuse_fast_signatures or candidate_fast_signature != dojo_fast_signature:
                    candidate_signature = canonical_json_bytes(candidate)
                state_changed = state_changed or candidate_signature != dojo_signature
                dojo = candidate
                dojo_signature = candidate_signature
                dojo_fast_signature = candidate_fast_signature
            for raw_song in payload.get("songs") or []:
                if not isinstance(raw_song, dict):
                    continue
                key = song_key(raw_song)
                if key[0] > 0 and key[1] > 0:
                    candidate_fast_signature = (
                        _fast_json_signature(raw_song) if reuse_fast_signatures else None
                    )
                    candidate_signature = song_signatures.get(key)
                    if (
                        not reuse_fast_signatures
                        or candidate_fast_signature != song_fast_signatures.get(key)
                    ):
                        candidate_signature = canonical_json_bytes(raw_song)
                    if song_signatures.get(key) != candidate_signature:
                        songs[key] = copy.deepcopy(raw_song)
                        song_signatures[key] = candidate_signature
                        changed_keys.add(key)
                        state_changed = True
                    if candidate_fast_signature is not None:
                        song_fast_signatures[key] = candidate_fast_signature
            for raw_key in payload.get("songs_removed") or []:
                if isinstance(raw_key, (list, tuple)) and len(raw_key) >= 2:
                    key = (safe_int(raw_key[0], -1), safe_int(raw_key[1], -1))
                    if key in songs:
                        songs.pop(key, None)
                        song_signatures.pop(key, None)
                        song_fast_signatures.pop(key, None)
                        changed_keys.add(key)
                        state_changed = True
            if item.source != "unknown":
                current_source = item.source
            if item.source_account:
                current_source_account = item.source_account
            if item.merge_topology:
                current_topology = list(item.merge_topology)

        state = {
            "profile": copy.deepcopy(profile),
            "achievement": copy.deepcopy(achievement),
            "dojo": copy.deepcopy(dojo),
            # Song dictionaries are replaced, never mutated, while applying later deltas.
            # Sharing unchanged chart objects avoids copying the entire archive per snapshot.
            "songs": [songs[key] for key in sorted(songs)],
        }
        same_identity = bool(
            snapshots
            and snapshots[-1].source == current_source
            and snapshots[-1].source_account == current_source_account
            and snapshots[-1].merge_topology == current_topology
        )
        if snapshots and not state_changed and same_identity:
            warnings.append(f"unchanged_snapshot:{item.path.name}")
            del payload
            observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)
            continue
        snapshots.append(
            RebuiltSnapshot(
                path=item.path,
                observed_at=item.observed_at,
                state=state,
                source=current_source,
                source_account=current_source_account,
                merge_topology=current_topology,
                content_hash=item.content_hash,
                warnings=item.warnings,
                changed_keys=tuple(sorted(changed_keys)),
            )
        )
        has_previous_state = True
        warnings.extend(item.warnings)
        del payload
        observe_profile_objects(raw_payload_count=0, raw_payload_estimated_bytes=0)
        if profiling_enabled():
            signature_values = [profile_signature, achievement_signature, dojo_signature]
            observe_profile_objects(
                rebuilt_state_count=len(snapshots),
                signature_count=len(song_signatures) + sum(value is not None for value in signature_values),
                signature_bytes=sum(len(value) for value in song_signatures.values())
                + sum(len(value) for value in signature_values if value is not None),
            )

    observe_profile_objects(rebuilt_state_count=len(snapshots))
    mark_profile_stage("history_rebuild_complete", rawSnapshotCount=len(plan))
    observe_profile_objects(
        raw_payload_count=0,
        raw_payload_estimated_bytes=0,
        signature_count=0,
        signature_bytes=0,
    )

    return SnapshotHistory(
        snapshots=snapshots,
        warnings=sorted(set(warnings)),
        ignored_files=ignored_files,
    )


def select_window(
    snapshots: Iterable[RebuiltSnapshot],
    *,
    start_date: date,
    generated_at: datetime,
    end_date: Optional[date],
    start_at: Optional[datetime] = None,
    end_exclusive_at: Optional[datetime] = None,
) -> WindowSelection:
    ordered = list(snapshots)
    effective_end_date = min(end_date or generated_at.date(), generated_at.date())
    start_dt = start_at or datetime.combine(start_date, time.min)
    declared_end_exclusive = end_exclusive_at or datetime.combine(
        effective_end_date + timedelta(days=1), time.min
    )
    generated_end_exclusive = datetime.combine(generated_at.date() + timedelta(days=1), time.min)
    effective_end_exclusive = min(declared_end_exclusive, generated_end_exclusive)
    window = [item for item in ordered if start_dt <= item.observed_at < effective_end_exclusive]
    if not window:
        raise ValueError("no snapshots in annual window")
    first_index = ordered.index(window[0])
    preceding = [item for item in ordered[:first_index] if item.observed_at < start_dt]
    partial_start = not preceding
    baseline = preceding[-1] if preceding else window[0]
    last_index = ordered.index(window[-1])
    baseline_index = ordered.index(baseline)
    selected = ordered[baseline_index : last_index + 1]
    return WindowSelection(
        snapshots=selected,
        window_snapshots=window,
        baseline=baseline,
        start_state=baseline.state,
        end_state=window[-1].state,
        partial_start=partial_start,
        effective_end_date=effective_end_date,
    )
