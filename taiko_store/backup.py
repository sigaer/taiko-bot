"""Verified, independent source backups under the source's kernel fence."""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import stat

from .publication import PublicationError, _atomic_bytes, _directory, _fsync_directory, _json

from .daily import DAILY_NAME, MAX_ARCHIVE_BYTES, archive_lock as _archive_lock

MAX_ARCHIVES = 32


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{32}", value):
        raise PublicationError("Invalid source backup identity")
    return value


def _plain_directory(path):
    if not stat.S_ISDIR(path.lstat().st_mode) or path.is_symlink():
        raise PublicationError("Backup directory is not a plain directory")


def _location(store, key, *, create=False):
    key = _key(key)
    parent = store.root / ".manual_deleted"
    if create:
        _directory(parent)
    else:
        _plain_directory(parent)
    return parent / (store.identity + "-" + key)


def _copy_verified(source, target, limit, expected=None):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    count, digest = 0, hashlib.sha256()
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_size > limit:
            raise PublicationError("Backup input is not a bounded plain file")
        output_fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(output_fd, "wb") as output:
            with os.fdopen(fd, "rb", closefd=False) as incoming:
                while chunk := incoming.read(1024**2):
                    count += len(chunk)
                    if count > limit:
                        raise PublicationError("Source backup byte limit exceeded")
                    digest.update(chunk)
                    output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    finally:
        os.close(fd)
    reference = {"sha256": digest.hexdigest(), "bytes": count}
    if expected is not None and reference != expected:
        raise PublicationError("Source backup input hash mismatch")
    return reference


def _verify_file(path, reference, limit):
    if (not isinstance(reference, dict) or set(reference) != {"sha256", "bytes"}
            or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("sha256", "")))
            or type(reference.get("bytes")) is not int or not 0 <= reference["bytes"] <= limit):
        raise PublicationError("Invalid source backup reference")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    count, digest = 0, hashlib.sha256()
    with os.fdopen(fd, "rb") as incoming:
        if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
            raise PublicationError("Backup object is not a plain file")
        if os.fstat(incoming.fileno()).st_size != reference["bytes"]:
            raise PublicationError("Source backup object size mismatch")
        while chunk := incoming.read(1024**2):
            count += len(chunk)
            if count > limit:
                raise PublicationError("Source backup verification limit exceeded")
            digest.update(chunk)
    if count != reference["bytes"] or digest.hexdigest() != reference["sha256"]:
        raise PublicationError("Source backup object hash mismatch")


def _file_path(store, base, key):
    store._projection_path(key)
    return base / (store.identity + "data.json") if key == "current" else base / store.identity / key[len("history/"):]


def verify_source_backup(store, key):
    """Private backup metadata is not a trusted receipt until every file verifies."""
    store._require_lock()
    base = _location(store, key)
    _plain_directory(base)
    metadata = store._read_json(base / "backup.json")
    if (not isinstance(metadata, dict) or set(metadata) != {"schema", "identity", "backupKey", "source", "archives"}
            or type(metadata.get("schema")) is not int or metadata["schema"] != 1 or metadata.get("identity") != store.identity
            or metadata.get("backupKey") != key or not isinstance(metadata.get("archives"), dict)
            or len(metadata["archives"]) > MAX_ARCHIVES):
        raise PublicationError("Invalid source backup metadata")
    store._validate_manifest(metadata["source"])
    _plain_directory(base / store.identity)
    for file_key, reference in metadata["source"]["files"].items():
        _verify_file(_file_path(store, base, file_key), reference, store.max_file_bytes)
    for name, reference in metadata["archives"].items():
        if not isinstance(name, str) or not DAILY_NAME.fullmatch(name):
            raise PublicationError("Invalid daily backup namespace")
        _verify_file(base / store.identity / name, reference, MAX_ARCHIVE_BYTES)
    return metadata


def export_source_backup(store, key):
    """C/H come from immutable objects; independent daily archives keep their lock.

    Archive files are copied at each namespace's freeze boundary. They are a
    separate authority: this does not claim a common SQL/daily/score transaction.
    """
    store._require_lock(write=True)
    key = _key(key)
    destination = _location(store, key, create=True)
    if destination.exists() or destination.is_symlink():
        return verify_source_backup(store, key)
    collect_source_backup_stages(store)
    source = store.view() or store._adopt()
    history = store.root / store.identity
    _directory(history)
    names = sorted(path.name for path in history.iterdir() if DAILY_NAME.fullmatch(path.name))
    if len(names) > MAX_ARCHIVES:
        raise PublicationError("Source daily namespace limit exceeded")
    required = sum(reference["bytes"] for reference in source["files"].values()) + len(names) * MAX_ARCHIVE_BYTES
    if shutil.disk_usage(destination.parent).free < required + 64 * 1024**2:
        raise PublicationError("Insufficient source backup disk headroom")
    # One retry removes only this operation's private staging tree under EX.
    staging = destination.parent / (".stage-" + store.identity + "-" + key)
    if staging.exists() or staging.is_symlink():
        _directory(staging)
        shutil.rmtree(staging)
    _directory(staging)
    _directory(staging / store.identity)
    promoted = False
    try:
        store.fault("backup.created")
        for file_key, reference in source["files"].items():
            _copy_verified(store.objects / reference["sha256"], _file_path(store, staging, file_key), store.max_file_bytes, reference)
        store.fault("backup.source-complete")
        archives = {}
        for name in names:
            path = history / name
            with _archive_lock(store, path):
                archives[name] = _copy_verified(path, staging / store.identity / name, MAX_ARCHIVE_BYTES)
        store.fault("backup.archives-complete")
        metadata = {"schema": 1, "identity": store.identity, "backupKey": key, "source": source, "archives": archives}
        _atomic_bytes(staging / "backup.json", _json(metadata))
        _fsync_directory(staging / store.identity)
        _fsync_directory(staging)
        store.fault("backup.metadata-commit")
        os.replace(staging, destination)
        promoted = True
        _fsync_directory(destination.parent)
        store.fault("backup.promoted")
        return metadata
    finally:
        if not promoted and staging.exists():
            shutil.rmtree(staging)
            _fsync_directory(staging.parent)


def collect_source_backup_stages(store):
    """Only unpromoted trees of this identity; EX proves no live backup owner."""
    store._require_lock(write=True)
    parent = store.root / ".manual_deleted"
    if not parent.exists() and not parent.is_symlink():
        return 0
    _plain_directory(parent)
    removed = 0
    for path in parent.iterdir():
        if not re.fullmatch(r"\.stage-" + re.escape(store.identity) + r"-[a-f0-9]{32}", path.name):
            continue
        _plain_directory(path)
        shutil.rmtree(path)
        removed += 1
    if removed:
        _fsync_directory(parent)
    return removed


def purge_backup_archives(store, key):
    """Forward cleanup after the coordinator durably revokes SQL grants.

    This deliberately has no SQL access. Every archive must still match its
    independent verified backup; a changed/new namespace stops cleanup.
    Missing files are an idempotent completed step, never a new measurement.
    """
    store._require_lock(write=True)
    metadata = verify_source_backup(store, key)
    current = store.view()
    if current is None or not (current["commitId"] == metadata["source"]["commitId"] or (
            not current["files"] and current["sequence"] > metadata["source"]["sequence"])):
        raise PublicationError("Source changed after lifecycle backup")
    history = store.root / store.identity
    _plain_directory(history)
    names = sorted(path.name for path in history.iterdir() if DAILY_NAME.fullmatch(path.name))
    if any(name not in metadata["archives"] for name in names):
        raise PublicationError("Daily namespace changed after lifecycle backup")
    # Preflight all present measurements before the first destructive step.
    for name in names:
        with _archive_lock(store, history / name):
            _verify_file(history / name, metadata["archives"][name], MAX_ARCHIVE_BYTES)
    removed = 0
    for name, reference in metadata["archives"].items():
        path = history / name
        with _archive_lock(store, path):
            if path.exists() or path.is_symlink():
                _verify_file(path, reference, MAX_ARCHIVE_BYTES)
                path.unlink()
                _fsync_directory(history)
                removed += 1
                store.fault("delete.archive-removed")
    return {"removed": removed}


def restore_source_backup(store, key, *, transaction_id):
    """Restore only into an empty or already matching identity under EX.

    The coordinator keeps SQL grants unavailable until this returns. C/H publish
    together; daily namespaces restore independently and a retry verifies each
    completed file. This cannot overwrite a different active source or archive.
    A portable recovery first copies the verified private backup to the fresh
    root's .manual_deleted directory; it does not require the old object store.
    """
    store._require_lock(write=True)
    transaction_id = _key(transaction_id)
    metadata = verify_source_backup(store, key)
    base = _location(store, key)
    current = store.view()
    files = metadata["source"]["files"]
    if current and current["files"] and current["files"] != files:
        raise PublicationError("Cannot restore over a different active source")
    history = store.root / store.identity
    _directory(history)
    # A managed empty head must not conceal writes by an old, unfenced writer.
    if not current or not current["files"]:
        legacy_current = store.root / (store.identity + "data.json")
        if legacy_current.exists() or legacy_current.is_symlink() or any(
                path.name.startswith("data_") and path.name.endswith(".json") for path in history.iterdir()):
            raise PublicationError("Cannot restore over legacy source files")
    names = sorted(path.name for path in history.iterdir() if DAILY_NAME.fullmatch(path.name))
    if any(name not in metadata["archives"] for name in names):
        raise PublicationError("Cannot restore over a different daily namespace")
    for name in names:
        with _archive_lock(store, history / name):
            _verify_file(history / name, metadata["archives"][name], MAX_ARCHIVE_BYTES)
    required = sum(reference["bytes"] for reference in files.values()) + sum(
        reference["bytes"] for name, reference in metadata["archives"].items() if name not in names)
    if shutil.disk_usage(store.root).free < required + 64 * 1024**2:
        raise PublicationError("Insufficient source restore disk headroom")
    if not current or current["files"] != files:
        staged = {"current": None}
        for file_key, reference in files.items():
            fd = os.open(_file_path(store, base, file_key), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as incoming:
                if not stat.S_ISREG(os.fstat(incoming.fileno()).st_mode):
                    raise PublicationError("Restore object is not a plain file")
                staged[file_key] = store._put_stream(incoming)
            if staged[file_key] != reference:
                raise PublicationError("Source restore object hash mismatch")
        times = {field: metadata["source"][field] for field in ("fileMtimes", "fileCtimes") if field in metadata["source"]}
        current = store.publish(staged, replace_history=True, transaction_id=transaction_id, filesystem_times=times)
    store.restore_projections()
    store.fault("restore.source-committed")
    for name, reference in metadata["archives"].items():
        path = history / name
        with _archive_lock(store, path):
            if path.exists() or path.is_symlink():
                _verify_file(path, reference, MAX_ARCHIVE_BYTES)
            else:
                temporary = history / (".restore-" + transaction_id + "-" + name)
                if temporary.exists() or temporary.is_symlink():
                    if not stat.S_ISREG(temporary.lstat().st_mode):
                        raise PublicationError("Restore stage is not a plain file")
                    temporary.unlink()
                try:
                    _copy_verified(base / store.identity / name, temporary, MAX_ARCHIVE_BYTES, reference)
                    os.replace(temporary, path)
                    _fsync_directory(history)
                finally:
                    temporary.unlink(missing_ok=True)
            store.fault("restore.archive-installed")
    return {"source": current, "archives": metadata["archives"], "backupKey": key}
