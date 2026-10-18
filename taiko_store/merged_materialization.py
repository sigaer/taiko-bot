"""Publish native u0 from one simultaneously leased member vector.

Authorization stays with the native reader. Legacy sources must be adopted by
the coordinated writer migration, never by a read request. No file time proves
freshness. The frozen merge kernel still defines payloads and observation time.
"""
from contextlib import ExitStack
from datetime import datetime
import copy
import hashlib
import json
import re
import threading

from .merge_reference import _load_song_combo_map
from .publication import PublicationError, PublicationStore
from .merged_read import MAX_BYTES, derive_merged_read, merge_rule_revision

_ADMISSION = threading.BoundedSemaphore(2)


def _encode(payload):
    raw = json.dumps(payload, ensure_ascii=False, indent=4).encode()
    if len(raw) > MAX_BYTES:
        raise PublicationError("Merged output limit exceeded")
    return raw


def _comparable(payload):
    value = copy.deepcopy(payload)
    meta = value.get("_meta")
    if isinstance(meta, dict):
        meta.pop("ts", None)
    return value


def materialize(root, identity_key, ids, profile_id, virtual_id):
    from taiko_application.merged_bind import (
        MaterializedMergedBind, MissingBindUserdata, MergedBindMissingUserdataError,
        _merge_payloads,
    )
    if (not 2 <= len(ids) <= 128 or len(set(ids)) != len(ids)
            or any(not re.fullmatch(r"[0-9]{1,25}", identity) for identity in ids)
            or profile_id not in ids or virtual_id in ids):
        raise PublicationError("Merged members are invalid")
    if not _ADMISSION.acquire(timeout=30):
        raise PublicationError("Merged admission deadline exceeded")
    try:
        with ExitStack() as stack:
            views = {}
            for identity in sorted(ids):
                source = PublicationStore(root, identity, max_file_bytes=MAX_BYTES)
                stack.enter_context(source.shared())
                views[identity] = source.reader()
            missing, currents, total = [], {}, 0
            for slot, identity in enumerate(ids, 1):
                view = views[identity]
                if view.manifest is not None:
                    # Incremental materialization reads current objects only.
                    # A cold history rebuild applies its own aggregate bound in
                    # derive_merged_read; retained history is not current input.
                    total += view.manifest["files"].get("current", {}).get("bytes", 0)
                    if total > MAX_BYTES:
                        raise PublicationError("Merged input limit exceeded")
                try:
                    raw = view.current_raw()
                except FileNotFoundError:
                    missing.append(MissingBindUserdata(slot, identity))
                    continue
                payload = json.loads(raw)
                if not isinstance(payload, dict):
                    raise PublicationError("Merged current is invalid")
                currents[identity] = payload
            if missing:
                raise MergedBindMissingUserdataError(missing)
            if any(view.manifest is None for view in views.values()):
                raise PublicationError("Merged source has no publication")
            dependency = {"recipe": "native-u0-incremental-v1", "principal": identity_key,
                          "members": [(identity, views[identity].publication) for identity in ids],
                          "profile": profile_id, "rule": merge_rule_revision()}
            dependency_hash = hashlib.sha256(json.dumps(dependency, sort_keys=True,
                separators=(",", ":")).encode()).hexdigest()
            store = PublicationStore(root, virtual_id, max_file_bytes=MAX_BYTES)
            with store.exclusive():
                previous = store.view()
                if previous is None and (root / (virtual_id + "data.json")).exists():
                    raise PublicationError("Existing merged output must be adopted before activation")
                old = None
                if previous and "current" in previous["files"]:
                    old = json.loads(store.reader().current_raw())
                if (isinstance(old, dict) and previous.get("dependencyHash") == dependency_hash):
                    # Consumers use canonical SH readers; repair is not needed
                    # to make a missing/tampered compatibility projection valid.
                    return MaterializedMergedBind(virtual_id, root / (virtual_id + "data.json"),
                                                  root / virtual_id, tuple(ids), profile_id)
                merged = _merge_payloads((currents[identity] for identity in ids),
                    profile_source=currents[profile_id], merge_topology=ids,
                    combo_map=_load_song_combo_map(), clock=datetime.now)
                incremental = (isinstance(old, dict)
                    and isinstance(old.get("_meta"), dict)
                    and sorted(old["_meta"].get("merge_topology") or []) == sorted(ids)
                    and any(key.startswith("history/") for key in previous["files"]))
                staged = {}
                if incremental:
                    if _comparable(old) != _comparable(merged):
                        stamp = max(datetime.fromtimestamp(views[identity].file_times("current")["mtime"])
                                    for identity in ids)
                        merged["_meta"]["ts"] = stamp.strftime("%Y-%m-%d %H:%M:%S")
                        ref = store.stage(_encode(merged))
                        staged = {"current": ref, "history/data_" + stamp.strftime("%Y%m%d_%H%M%S_%f")
                                  + "_merged-bind.json": ref}
                    # An unchanged current still commits its new dependency
                    # receipt, without manufacturing a score observation.
                else:
                    staged["current"] = store.stage(_encode(merged))
                    history = derive_merged_read(views, ids, profile_id, "history", raw_history=True)
                    for item in history["snapshots"]:
                        staged["history/" + item["fileName"]] = store.stage(_encode(item["payload"]))
                store.publish(staged, replace_history=not incremental, dependency_hash=dependency_hash)
            return MaterializedMergedBind(virtual_id, root / (virtual_id + "data.json"),
                                          root / virtual_id, tuple(ids), profile_id)
    finally:
        _ADMISSION.release()
