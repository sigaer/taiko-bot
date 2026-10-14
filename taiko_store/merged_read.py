"""Bounded u0 derivation from simultaneously leased center score views.

Identity and SQL grants belong to the caller. This module never opens SQL,
materializes private projections, or treats filesystem times as play events.
The existing center merge rule remains the score/profile oracle.
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from pathlib import Path

from taiko_application.merged_bind import _merge_payloads, _song_key, _normalize_removed_key
from .snapshot_history import parse_snapshot_time
from .merge_reference import _load_song_combo_map
from .publication import PublicationError

MAX_BYTES = 32 * 1024 * 1024


def merge_rule_revision():
    # Loading also pins the legacy kernel's process-local reference map before
    # SQL proof. A table change between current/history requests changes the
    # combined observation even when all private Source heads are unchanged.
    combos = _load_song_combo_map()
    policy = {"profile": "center-merged-bind-v1", "historyAdapter": 1, "currentClock": "max-file-mtime-v1",
              "combos": [(song, level, combo) for (song, level), combo in sorted(combos.items())]}
    return hashlib.sha256(json.dumps(policy, separators=(",", ":")).encode()).hexdigest()


def _object(view, key):
    raw = view.raw(key)
    try:
        payload = json.loads(raw)
    except (ValueError, UnicodeError):
        if key == "current":
            raise PublicationError("Merged current is invalid") from None
        return None
    return payload if isinstance(payload, dict) else None


def _history(view, names):
    profile, achievement, dojo, songs = {}, {}, {}, {}
    has_base = False
    for stamp, name in names:
        payload = _object(view, "history/" + name)
        if payload is None:
            continue
        meta = payload.get("_meta") if isinstance(payload.get("_meta"), dict) else {}
        full = bool(meta.get("full")) or ("songs" in payload and "profile" in payload and "achievement" in payload and not meta)
        if full:
            profile = copy.deepcopy(payload.get("profile") or {})
            achievement = copy.deepcopy(payload.get("achievement") or {})
            dojo = copy.deepcopy(payload.get("dojo") or {})
            songs = {}
            has_base = True
        elif not has_base:
            continue
        else:
            if "profile" in payload:
                profile = copy.deepcopy(payload.get("profile") or {})
            if "achievement" in payload:
                achievement = copy.deepcopy(payload.get("achievement") or {})
            if "dojo" in payload:
                dojo = copy.deepcopy(payload.get("dojo") or {})
        for song in payload.get("songs") or []:
            key = _song_key(song)
            if key is not None:
                songs[key] = copy.deepcopy(song)
        if not full:
            for removed in payload.get("songs_removed") or []:
                key = _normalize_removed_key(removed)
                if key is not None:
                    songs.pop(key, None)
        yield stamp, {"profile": copy.deepcopy(profile), "achievement": copy.deepcopy(achievement),
                      "dojo": copy.deepcopy(dojo), "songs": [copy.deepcopy(song) for song in songs.values()]}


def derive_merged_read(views, ids, profile_source_id, kind, *, max_output_bytes=MAX_BYTES, raw_history=False):
    if kind not in ("current", "history") or not 2 <= len(ids) <= 128 or len(set(ids)) != len(ids) or set(views) != set(ids) or profile_source_id not in ids:
        raise PublicationError("Merged request is invalid")
    # Canonical publication is required. Legacy in-place files cannot prove a
    # multi-member current/history vector, even while our kernel SH is held.
    total = 0
    for view in views.values():
        view._check()
        if view.manifest is None:
            raise PublicationError("Merged source has no publication")
        total += sum(item["bytes"] for key, item in view.manifest["files"].items() if key == "current" or (kind == "history" and key.startswith("history/")))
        if total > MAX_BYTES:
            raise PublicationError("Merged input limit exceeded")
    currents = {identity: _object(views[identity], "current") for identity in ids}
    if any(payload is None for payload in currents.values()):
        raise PublicationError("Merged current is invalid")
    times = {identity: datetime.fromtimestamp(views[identity].file_times("current")["mtime"]) for identity in ids}
    if kind == "current":
        payload = _merge_payloads(currents.values(), profile_source=currents[profile_source_id], merge_topology=ids,
                    combo_map=_load_song_combo_map(), clock=datetime.now)
        # Preserve the incremental materializer's observation clock. Request
        # time must not manufacture a different current representation.
        payload["_meta"]["ts"] = max(times.values()).strftime("%Y-%m-%d %H:%M:%S")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode()) > max_output_bytes:
            raise PublicationError("Merged output limit exceeded")
        return payload

    indices, append_current, points = {}, {}, set()
    for identity in ids:
        view = views[identity]
        names = []
        for name in view.history_names():
            stamp = parse_snapshot_time(Path(name), fallback_mtime=lambda name=name: view.file_times("history/" + name)["mtime"])
            names.append((stamp, name))
        names.sort(key=lambda item: (item[0], item[1]))
        indices[identity] = names
        latest = None
        # First pass retains only the latest reconstructed state and compact
        # timestamps; the second pass supplies one cursor per source.
        for latest in _history(view, names):
            points.add(latest[0])
        append_current[identity] = latest is None or latest[0] < times[identity] or latest[1] != currents[identity]
        if append_current[identity]:
            points.add(times[identity])
        latest = None

    def stream(identity):
        yield from _history(views[identity], indices[identity])
        if append_current[identity]:
            # Keep the legacy final append order even if current mtime is
            # earlier than the last history filename; do not silently sort it.
            yield times[identity], currents[identity]

    cursors = {identity: iter(stream(identity)) for identity in ids}
    pending = {identity: next(cursors[identity], None) for identity in ids}
    active = {}
    snapshots, encoded_bytes = [], 128
    for stamp in sorted(points):
        for identity in ids:
            while pending[identity] is not None and pending[identity][0] <= stamp:
                active[identity] = pending[identity][1]
                pending[identity] = next(cursors[identity], None)
        if not active:
            continue
        payload = _merge_payloads((active[identity] for identity in ids if identity in active),
                                 profile_source=active.get(profile_source_id) or currents[profile_source_id], merge_topology=ids,
                    combo_map=_load_song_combo_map(), clock=datetime.now)
        payload["_meta"]["ts"] = stamp.strftime("%Y-%m-%d %H:%M:%S")
        item = {"capturedAt": payload["_meta"]["ts"], "payload": payload}
        if raw_history:
            # An explicitly derived recipe name, not a claimed filesystem
            # timestamp. It preserves the old materializer's microsecond key.
            item["fileName"] = "data_" + stamp.strftime("%Y%m%d_%H%M%S_%f") + "_merged-bind.json"
        encoded_bytes += len(json.dumps(item, ensure_ascii=False, separators=(",", ":")).encode()) + 1
        if encoded_bytes > max_output_bytes:
            raise PublicationError("Merged output limit exceeded")
        snapshots.append(item)
    return {"snapshots": snapshots, **({"historyFormat": "raw-v1"} if raw_history else {})}
