"""Recoverable score publication with immutable inputs and kernel locking.

Only this infrastructure writes the compatible current/history projections.
Callers own score interpretation, authorization, source metadata and time.
Read-modify-write must run inside ``exclusive``; readers keep ``shared`` open
until they have consumed a view. No score timestamps, DB, framework or global paths.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import stat
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class PublicationError(RuntimeError):
    pass


def _identity(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise PublicationError("Invalid score identity")
    return value


def _history_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"data_[^/\\\x00]+\.json", value):
        raise PublicationError("Invalid history name")
    return value


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _filesystem_time(value):
    return type(value) in (int, float) and -1e12 < value < 1e12 and math.isfinite(value)


def _directory(path):
    try:
        path.lstat()
    except FileNotFoundError:
        _directory(path.parent)
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        _fsync_directory(path.parent)
    if not stat.S_ISDIR(path.lstat().st_mode) or path.is_symlink():
        raise PublicationError("Storage directory is not a plain directory")


def _fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_bytes(path, payload, *, stage_identity=None):
    prefix = ".stage-" if stage_identity is None else ".stage-" + _identity(stage_identity) + "-"
    temporary = path.parent / (prefix + uuid.uuid4().hex)
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


class PublicationStore:
    schema = 1

    def __init__(self, root, identity, *, max_file_bytes=64 * 1024**2,
                 max_history_files=50_000, max_history_bytes=2 * 1024**3,
                 lock_timeout=30, fault=None):
        self.root = Path(root).absolute()
        self.identity = _identity(identity)
        self.base = self.root / ".taiko-publications" / self.identity
        self.objects = self.base / "objects"
        self.commits = self.base / "commits"
        self.max_file_bytes = max_file_bytes
        self.max_history_files = max_history_files
        self.max_history_bytes = max_history_bytes
        self.lock_timeout = lock_timeout
        self.fault = fault or (lambda point: None)
        self._mode = None
        self._lease_token = None
        for path in (self.root, self.root / ".taiko-publications", self.base, self.objects, self.commits):
            _directory(path)

    @contextmanager
    def _lock(self, mode):
        if self._mode is not None:
            raise PublicationError("Nested publication lock")
        fd = os.open(self.base / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
        deadline = time.monotonic() + self.lock_timeout
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise PublicationError("Publication lock is not a plain file")
            requested = fcntl.LOCK_SH if mode == "shared" else fcntl.LOCK_EX
            while True:
                try:
                    fcntl.flock(fd, requested | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise PublicationError("Publication lock deadline exceeded")
                    time.sleep(0.01)
            self._mode = mode
            self._lease_token = object()
            if mode == "shared" and (self.base / "pending.json").exists():
                # A dead writer may have left intent. Release the read lease;
                # obtain exclusive recovery ownership with the same deadline.
                fcntl.flock(fd, fcntl.LOCK_UN)
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise PublicationError("Publication recovery deadline exceeded")
                        time.sleep(0.01)
                self._mode = "exclusive"
                self._recover()
                fcntl.flock(fd, fcntl.LOCK_SH)
                self._mode = "shared"
            elif mode == "exclusive":
                self._recover()
            yield self
        finally:
            self._mode = None
            self._lease_token = None
            os.close(fd)

    def exclusive(self):
        return self._lock("exclusive")

    def shared(self):
        return self._lock("shared")

    def reader(self):
        self._require_lock()
        from .reader import ScoreReadView
        return ScoreReadView(self, self.view(), self._lease_token)

    def _require_lock(self, *, write=False):
        if self._mode is None or (write and self._mode != "exclusive"):
            raise PublicationError("Publication operation requires its kernel lock")

    def _read_json(self, path, limit=32 * 1024**2):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise PublicationError("Publication metadata is not a plain file")
            if os.fstat(source.fileno()).st_size > limit:
                raise PublicationError("Publication metadata limit exceeded")
            payload = source.read(limit + 1)
        if len(payload) > limit:
            raise PublicationError("Publication metadata limit exceeded")
        return json.loads(payload)

    def view(self):
        self._require_lock()
        try:
            value = self._read_json(self.base / "committed.json")
        except FileNotFoundError:
            return None
        self._validate_manifest(value)
        try:
            committed = self._read_json(self.commits / (value["commitId"] + ".json"))
        except FileNotFoundError as error:
            raise PublicationError("Committed publication record is missing") from error
        if _json(committed) != _json(value):
            raise PublicationError("Committed publication record mismatch")
        return value

    def _validate_manifest(self, value):
        if (not isinstance(value, dict) or value.get("schema") != self.schema
                or value.get("identity") != self.identity
                or type(value.get("sequence")) is not int
                or value["sequence"] < 0
                or not re.fullmatch(r"[a-f0-9]{32}", str(value.get("commitId", "")))
                or not isinstance(value.get("files"), dict)):
            raise PublicationError("Invalid publication manifest")
        if value.get("previousCommitId") is not None and not re.fullmatch(r"[a-f0-9]{32}", str(value["previousCommitId"])):
            raise PublicationError("Invalid previous publication identity")
        if value.get("requestHash") is not None and not re.fullmatch(r"[a-f0-9]{64}", str(value["requestHash"])):
            raise PublicationError("Invalid publication request hash")
        if "dependencyHash" in value and (not isinstance(value["dependencyHash"], str)
                or not re.fullmatch(r"[a-f0-9]{64}", value["dependencyHash"])):
            raise PublicationError("Invalid publication dependency hash")
        for field in ("fileMtimes", "fileCtimes"):
            times = value.get(field, {})
            if (not isinstance(times, dict) or times.keys() - value["files"].keys()
                    or any(not _filesystem_time(timestamp) for timestamp in times.values())):
                raise PublicationError("Invalid publication filesystem times")
        history_count = 0
        history_bytes = 0
        for key, reference in value["files"].items():
            self._projection_path(key)
            if (not isinstance(reference, dict)
                    or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("sha256", "")))
                    or type(reference.get("bytes")) is not int
                    or not 0 <= reference["bytes"] <= self.max_file_bytes):
                raise PublicationError("Invalid publication object reference")
            if key.startswith("history/"):
                history_count += 1
                history_bytes += reference["bytes"]
        if history_count > self.max_history_files or history_bytes > self.max_history_bytes:
            raise PublicationError("History publication limit exceeded")
        if len(_json(value)) > 32 * 1024**2:
            raise PublicationError("Publication metadata limit exceeded")

    def _projection_path(self, key):
        if key == "current":
            return self.root / (self.identity + "data.json")
        if isinstance(key, str) and key.startswith("history/"):
            return self.root / self.identity / _history_name(key[len("history/"):])
        raise PublicationError("Invalid publication projection key")

    def _put_stream(self, source):
        temporary = self.objects / (".stage-" + uuid.uuid4().hex)
        digest = hashlib.sha256()
        count = 0
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
        try:
            with os.fdopen(fd, "wb") as output:
                while chunk := source.read(1024 * 1024):
                    count += len(chunk)
                    if count > self.max_file_bytes:
                        raise PublicationError("Score object limit exceeded")
                    digest.update(chunk)
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            object_hash = digest.hexdigest()
            target = self.objects / object_hash
            if target.exists():
                reference = {"sha256": object_hash, "bytes": count}
                self.read_object(reference)
            else:
                os.replace(temporary, target)
                _fsync_directory(self.objects)
            return {"sha256": object_hash, "bytes": count}
        finally:
            temporary.unlink(missing_ok=True)

    def _put_bytes(self, payload):
        import io
        if not isinstance(payload, bytes) or len(payload) > self.max_file_bytes:
            raise PublicationError("Score object requires bounded bytes")
        return self._put_stream(io.BytesIO(payload))

    def read_object(self, reference):
        self._require_lock()
        if (not isinstance(reference, dict)
                or not re.fullmatch(r"[a-f0-9]{64}", str(reference.get("sha256", "")))
                or type(reference.get("bytes")) is not int
                or not 0 <= reference["bytes"] <= self.max_file_bytes):
            raise PublicationError("Invalid score object reference")
        fd = os.open(self.objects / reference["sha256"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                raise PublicationError("Score object is not a plain file")
            if os.fstat(source.fileno()).st_size != reference["bytes"]:
                raise PublicationError("Score object size mismatch")
            raw = source.read(self.max_file_bytes + 1)
        if len(raw) != reference["bytes"] or hashlib.sha256(raw).hexdigest() != reference["sha256"]:
            raise PublicationError("Score object hash mismatch")
        return raw

    def _adopt(self):
        self._require_lock(write=True)
        files = {}
        mtimes = {}
        ctimes = {}
        current = self._projection_path("current")
        history = self.root / self.identity
        paths = [("current", current)] if current.exists() else []
        if history.exists():
            _directory(history)
            for path in history.iterdir():
                if path.name.startswith("data_") and path.name.endswith(".json"):
                    paths.append(("history/" + _history_name(path.name), path))
                    if len(paths) > self.max_history_files + 1:
                        raise PublicationError("History file limit exceeded")
        total = 0
        for key, path in sorted(paths):
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode):
                    raise PublicationError("Legacy score is not a plain file")
                files[key] = self._put_stream(source)
                mtimes[key] = info.st_mtime
                ctimes[key] = info.st_ctime
            if key.startswith("history/"):
                total += files[key]["bytes"]
                if total > self.max_history_bytes:
                    raise PublicationError("History byte limit exceeded")
        value = {"schema": self.schema, "identity": self.identity, "sequence": 0,
                 "commitId": uuid.uuid4().hex, "files": files, "fileMtimes": mtimes, "fileCtimes": ctimes}
        self._validate_manifest(value)
        _atomic_bytes(self.commits / (value["commitId"] + ".json"), _json(value))
        _atomic_bytes(self.base / "committed.json", _json(value))
        return value

    def commit(self, changes, *, replace_history=False, transaction_id=None):
        """Publish bounded raw bytes; ``None`` removes a projection.

        Storage never infers score differences, source, time or evidence level.
        A replace-history batch preserves non-history files (daily archives).
        """
        self._require_lock(write=True)
        if not isinstance(changes, dict):
            raise PublicationError("Publication changes require a mapping")
        for key, value in changes.items():
            self._projection_path(key)
            if value is not None and (not isinstance(value, bytes) or len(value) > self.max_file_bytes):
                raise PublicationError("Score object requires bounded bytes")
        staged = {key: None if raw is None else self.stage(raw) for key, raw in changes.items()}
        return self.publish(staged, replace_history=replace_history, transaction_id=transaction_id)

    def stage(self, payload):
        """Stage one object at a time; a batch need not retain all raw bodies."""
        self._require_lock(write=True)
        return self._put_bytes(payload)

    def publish(self, changes, *, replace_history=False, transaction_id=None, filesystem_times=None, dependency_hash=None):
        """Commit staged references while retaining the original write lease."""
        self._require_lock(write=True)
        if not isinstance(changes, dict):
            raise PublicationError("Publication changes require a mapping")
        for key, reference in changes.items():
            self._projection_path(key)
            if reference is not None:
                self.read_object(reference)
        operation = {"replaceHistory": bool(replace_history), "changes": {
            key: None if reference is None else reference["sha256"] for key, reference in changes.items()}}
        if dependency_hash is not None:
            if not isinstance(dependency_hash, str) or not re.fullmatch(r"[a-f0-9]{64}", dependency_hash):
                raise PublicationError("Invalid publication dependency hash")
            operation["dependencyHash"] = dependency_hash
        if filesystem_times:
            if not isinstance(filesystem_times, dict) or filesystem_times.keys() - {"fileMtimes", "fileCtimes"}:
                raise PublicationError("Invalid restored filesystem times")
            for times in filesystem_times.values():
                if (not isinstance(times, dict) or any(key not in changes or changes[key] is None for key in times)
                        or any(not _filesystem_time(timestamp) for timestamp in times.values())):
                    raise PublicationError("Invalid restored filesystem times")
            operation["filesystemTimes"] = filesystem_times
        elif filesystem_times is not None and not isinstance(filesystem_times, dict):
            raise PublicationError("Invalid restored filesystem times")
        request_hash = hashlib.sha256(_json(operation)).hexdigest()
        commit_id = transaction_id or uuid.uuid4().hex
        if not re.fullmatch(r"[a-f0-9]{32}", commit_id):
            raise PublicationError("Invalid transaction identity")
        receipt_path = self.commits / (commit_id + ".json")
        if receipt_path.exists():
            receipt = self._read_json(receipt_path)
            self._validate_manifest(receipt)
            if receipt.get("requestHash") != request_hash:
                raise PublicationError("Transaction identity reused with different input")
            # An uncommitted staged manifest is not an idempotency receipt.
            current = self.view()
            if current and current["commitId"] == commit_id:
                return current
            # Death after objects-staged can precede pending.json. Only the
            # exact matching input on its unchanged parent may resume; a later
            # committed generation must never be rewound by an old nonce.
            if (current and receipt.get("previousCommitId") == current["commitId"]
                    and receipt["sequence"] == current["sequence"] + 1):
                receipt_path.unlink()
                _fsync_directory(self.commits)
            else:
                raise PublicationError("Transaction receipt is no longer the current publication")
        previous = self.view() or self._adopt()
        files = {key: value for key, value in previous["files"].items()
                 if not (replace_history and key.startswith("history/"))}
        for key, reference in changes.items():
            if reference is None:
                files.pop(key, None)
            else:
                files[key] = reference
        next_view = {"schema": self.schema, "identity": self.identity,
                     "sequence": previous["sequence"] + 1, "commitId": commit_id,
                     "previousCommitId": previous["commitId"], "requestHash": request_hash,
                     "files": files}
        if dependency_hash is not None:
            next_view["dependencyHash"] = dependency_hash
        # Filesystem mtime is an old malformed-filename sorting fallback, not
        # score/event time or readiness. Retain it across projection loss,
        # backup/restore and equal-content object deduplication.
        mtimes = previous.get("fileMtimes", {})
        ctimes = previous.get("fileCtimes", {})
        next_view["fileMtimes"] = {}
        next_view["fileCtimes"] = {}
        for key, reference in files.items():
            if reference == previous["files"].get(key) and key in mtimes and key in ctimes:
                next_view["fileMtimes"][key] = mtimes[key]
                next_view["fileCtimes"][key] = ctimes[key]
            else:
                fd = os.open(self.objects / reference["sha256"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                try:
                    info = os.fstat(fd)
                    if not stat.S_ISREG(info.st_mode) or info.st_size != reference["bytes"]:
                        raise PublicationError("Score metadata is not a bounded plain file")
                    next_view["fileMtimes"][key] = info.st_mtime
                    next_view["fileCtimes"][key] = info.st_ctime
                finally:
                    os.close(fd)
        for field, times in (filesystem_times or {}).items():
            next_view[field].update(times)
        self._validate_manifest(next_view)
        changed = sorted(key for key in previous["files"].keys() | files.keys()
                         if previous["files"].get(key) != files.get(key))
        _atomic_bytes(receipt_path, _json(next_view))
        self.fault("objects-staged")
        pending = {"schema": self.schema, "identity": self.identity,
                   "previousCommitId": previous["commitId"], "nextCommitId": commit_id,
                   "changedKeys": changed}
        _atomic_bytes(self.base / "pending.json", _json(pending))
        self.fault("intent-durable")
        try:
            for index, key in enumerate(changed):
                self._install(key, files.get(key))
                self.fault("projection-" + str(index))
            self.fault("projections-durable")
            _atomic_bytes(self.base / "committed.json", _json(next_view))
            self.fault("commit-durable")
            self._recover()
            return next_view
        except BaseException:
            self._recover()
            raise

    def _install(self, key, reference):
        target = self._projection_path(key)
        _directory(target.parent)
        if target.is_symlink():
            raise PublicationError("Projection target is a symlink")
        if reference is None:
            target.unlink(missing_ok=True)
            _fsync_directory(target.parent)
            return
        # Verify the immutable input before linking its compatible projection.
        self.read_object(reference)
        temporary = target.parent / (".stage-" + self.identity + "-" + uuid.uuid4().hex)
        try:
            os.link(self.objects / reference["sha256"], temporary, follow_symlinks=False)
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    def _recover(self):
        self._require_lock(write=True)
        try:
            pending = self._read_json(self.base / "pending.json")
        except FileNotFoundError:
            return
        if (pending.get("schema") != self.schema or pending.get("identity") != self.identity
                or not isinstance(pending.get("changedKeys"), list)):
            raise PublicationError("Invalid pending publication")
        for field in ("previousCommitId", "nextCommitId"):
            if not re.fullmatch(r"[a-f0-9]{32}", str(pending.get(field, ""))):
                raise PublicationError("Invalid recovery identity")
        previous = self._read_json(self.commits / (pending["previousCommitId"] + ".json"))
        following = self._read_json(self.commits / (pending["nextCommitId"] + ".json"))
        self._validate_manifest(previous)
        self._validate_manifest(following)
        current = self.view()
        if current is None or current["commitId"] not in (previous["commitId"], following["commitId"]):
            raise PublicationError("Recovery cannot identify committed publication")
        restoring = pending.get("restoreProjections") is True
        if restoring and previous["commitId"] != following["commitId"]:
            raise PublicationError("Invalid projection restore generation")
        expected = sorted(current["files"]) if restoring else sorted(
            key for key in previous["files"].keys() | following["files"].keys()
            if previous["files"].get(key) != following["files"].get(key))
        if pending["changedKeys"] != expected:
            raise PublicationError("Recovery projection list mismatch")
        for key in expected:
            self._install(key, current["files"].get(key))
        (self.base / "pending.json").unlink()
        _fsync_directory(self.base)
        if not restoring and current["commitId"] == previous["commitId"]:
            (self.commits / (following["commitId"] + ".json")).unlink()
            _fsync_directory(self.commits)

    def restore_projections(self):
        """Materialize a verified backup's canonical generation in a fresh root.

        Restoring DB identities/measurements and daily archives is owned by the
        backup coordinator. This method does not infer or recreate those data.
        """
        self._require_lock(write=True)
        current = self.view()
        if current is None:
            raise PublicationError("No committed generation to restore")
        for reference in current["files"].values():
            self.read_object(reference)
        pending = {"schema": self.schema, "identity": self.identity,
                   "previousCommitId": current["commitId"], "nextCommitId": current["commitId"],
                   "restoreProjections": True, "changedKeys": sorted(current["files"])}
        _atomic_bytes(self.base / "pending.json", _json(pending))
        self._recover()
        return current

    def collect(self):
        """Reclaim orphan stages and older objects under the exclusive fence.

        Keep current + previous committed generations. Readers must hold the
        shared lease, so collection cannot delete an object being consumed.
        This is explicit maintenance, never a timer or a cache purge.
        """
        self._require_lock(write=True)
        self._recover()
        current = self.view()
        keep_commits = set()
        keep_objects = set()
        if current is not None:
            generations = [current]
            if current.get("previousCommitId"):
                previous = self._read_json(self.commits / (current["previousCommitId"] + ".json"))
                self._validate_manifest(previous)
                generations.append(previous)
            for generation in generations:
                keep_commits.add(generation["commitId"] + ".json")
                keep_objects.update(value["sha256"] for value in generation["files"].values())
        removed = {"commits": 0, "objects": 0, "stages": 0, "bytes": 0}
        for directory in (self.commits, self.objects, self.base, self.root, self.root / self.identity):
            if not directory.exists():
                continue
            _directory(directory)
            for path in directory.iterdir():
                own_stage = re.fullmatch(r"\.stage-" + re.escape(self.identity) + r"-[a-f0-9]{32}", path.name)
                private_stage = directory in (self.commits, self.objects, self.base) and re.fullmatch(r"\.stage-[a-f0-9]{32}", path.name)
                stage = own_stage or private_stage
                commit = directory == self.commits and re.fullmatch(r"[a-f0-9]{32}\.json", path.name)
                obj = directory == self.objects and re.fullmatch(r"[a-f0-9]{64}", path.name)
                if stage or (commit and path.name not in keep_commits) or (obj and path.name not in keep_objects):
                    if not stat.S_ISREG(path.lstat().st_mode):
                        raise PublicationError("Collection target is not a plain file")
                    removed["bytes"] += path.stat().st_size
                    path.unlink()
                    removed["stages" if stage else "commits" if commit else "objects"] += 1
            _fsync_directory(directory)
        return removed
