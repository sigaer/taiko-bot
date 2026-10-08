"""Single-host source commit protocol, stdlib only. P1a: isolated roots only.

The legacy files are a compatibility projection. Only a verified manifest is a
committed input; pending/revoked/unregistered sources never report ready.
Copies in other repositories must have the same SHA-256 (checked by QA).
"""
from __future__ import annotations

import contextvars
import fcntl
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from contextlib import contextmanager, ExitStack
from pathlib import Path

SCHEMA = 1
MAX_FILE = 64 * 1024 * 1024
MAX_BYTES = 300 * 1024 * 1024
MAX_FILES = 10_000
WRITERS = frozenset({"wahlap", "hiroba", "sakura-bot-sync", "viewer", "kinoko-history",
                     "merged-bind", "maintenance", "manual-lifecycle", "viewer-cache"})
_active = contextvars.ContextVar("source_transactions", default={})


class CommitError(RuntimeError):
    pass


def isolated_root(root):
    root = Path(root).resolve()
    # No production reads/writes, even if an opt-in is accidentally inherited.
    if (os.environ.get("TAIKO_SOURCE_COMMIT_ISOLATED") != "1"
            or not root.is_relative_to(Path("/var/tmp"))
            or not (root / ".source-commit-isolated").is_file()):
        raise CommitError("isolated_root_required")
    return root


def identity(value):
    value = str(value)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", value):
        raise CommitError("invalid_source_identity")
    return value


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def fsync_dir(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic(path, data):
    path = Path(path)
    if path.is_symlink():
        raise CommitError("symlink_rejected")
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temp.open("xb") as handle:
            os.chmod(temp, 0o600)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def read_json(path, default=None):
    if not path.exists():
        return default
    if path.is_symlink() or path.stat().st_size > MAX_FILE:
        raise CommitError("unsafe_file")
    try:
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise CommitError("metadata_byte_budget")
        return json.loads(data)
    except (ValueError, OSError) as exc:
        raise CommitError("corrupt_metadata") from exc


class Source:
    def __init__(self, root, source_id):
        self.root = isolated_root(root)
        self.id = identity(source_id)
        self.store = self.root / ".source-commits" / hashlib.sha256(self.id.encode()).hexdigest()
        self.current_path = self.root / (self.id + "data.json")
        self.history_path = self.root / self.id
        for path in (self.root / ".source-commits", self.store, self.store / "objects",
                     self.store / "generations", self.history_path):
            if path.is_symlink():
                raise CommitError("symlink_rejected")
            path.mkdir(mode=0o700, exist_ok=True)
        self.pending_path = self.store / "pending.json"
        self.head_path = self.store / "head.json"

    @contextmanager
    def lock(self, shared=False, timeout=30):
        lock_path = self.store / "lock"
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        deadline = time.monotonic() + timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, (fcntl.LOCK_SH if shared else fcntl.LOCK_EX) | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise CommitError("lock_timeout")
                    time.sleep(0.01)
            yield
        finally:
            os.close(fd)

    def object_path(self, ref):
        digest = ref["sha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise CommitError("invalid_object_identity")
        return self.store / "objects" / (digest + ".json")

    def object_bytes(self, ref):
        path = self.object_path(ref)
        if path.is_symlink() or ref["bytes"] < 0 or ref["bytes"] > MAX_FILE:
            raise CommitError("unsafe_object")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as handle:
            if os.fstat(handle.fileno()).st_size != ref["bytes"]:
                raise CommitError("corrupt_object")
            data = handle.read(ref["bytes"] + 1)
        if len(data) != ref["bytes"] or hashlib.sha256(data).hexdigest() != ref["sha256"]:
            raise CommitError("corrupt_object")
        return data

    def store_bytes(self, data):
        if isinstance(data, str):
            data = data.encode()
        if len(data) > MAX_FILE:
            raise CommitError("file_budget")
        digest = hashlib.sha256(data).hexdigest()
        try:
            parsed = json.loads(data)
            valid = isinstance(parsed, dict) and isinstance(parsed.get("songs"), list)
            meta = parsed.get("_meta", {}) if isinstance(parsed, dict) else {}
            source = meta.get("writer_source") or meta.get("source") if isinstance(meta, dict) else None
            source = source if isinstance(source, str) and len(source) <= 128 else None
        except (ValueError, UnicodeError):
            valid, source = False, None
        ref = {"sha256": digest, "bytes": len(data), "valid": valid, "source": source}
        path = self.object_path(ref)
        if not path.exists():
            atomic(path, data)
        else:
            self.object_bytes(ref)
        return ref

    def manifest(self, head=None):
        head = head or read_json(self.head_path)
        if head is None:
            return None
        generation = head["generation"]
        if not re.fullmatch(r"[0-9]+-[0-9a-f]{32}", generation):
            raise CommitError("invalid_generation")
        path = self.store / "generations" / (generation + ".json")
        if path.is_symlink() or path.stat().st_size > MAX_FILE:
            raise CommitError("unsafe_manifest")
        with path.open("rb") as handle:
            data = handle.read(MAX_FILE + 1)
        if len(data) > MAX_FILE:
            raise CommitError("manifest_byte_budget")
        if hashlib.sha256(data).hexdigest() != head["sha256"]:
            raise CommitError("corrupt_manifest")
        value = json.loads(data)
        if value["schema"] != SCHEMA or value["source_id"] != self.id:
            raise CommitError("manifest_identity_mismatch")
        for key in ("schema", "source_id", "sequence", "managed", "revoked", "fingerprint", "generation", "dependencies"):
            if head.get(key) != value.get(key):
                raise CommitError("head_manifest_mismatch")
        return value

    def status(self):
        # May be polled without a lock: double check pending/head to avoid a
        # false ready across an entire commit. Consumers hold a shared lease.
        if self.pending_path.exists():
            return {"status": "dirty"}
        if (self.store / "unsafe.json").exists():
            return {"status": "unavailable", "reason": "reconciliation_required"}
        head = read_json(self.head_path)
        if head is None:
            return {"status": "unavailable", "reason": "legacy_unregistered"}
        if head.get("schema") != SCHEMA or head.get("source_id") != self.id:
            raise CommitError("head_identity_mismatch")
        for value, dependency in head.get("dependencies", {}).items():
            dependency_store = self.root / ".source-commits" / hashlib.sha256(identity(value).encode()).hexdigest()
            if (dependency_store / "pending.json").exists() or (dependency_store / "unsafe.json").exists():
                return {"status": "dirty"}
            if dependency != read_json(dependency_store / "head.json"):
                return {"status": "dirty"}
        if self.pending_path.exists() or head != read_json(self.head_path):
            return {"status": "dirty"}
        status = "revoked" if head["revoked"] else "ready" if head["managed"] else "unavailable"
        return {"status": status, "generation": head["generation"], "sequence": head["sequence"],
                "fingerprint": head["fingerprint"]}

    @contextmanager
    def lease(self):
        observed = read_json(self.head_path)
        ids = sorted({self.id, *(observed or {}).get("dependencies", {})})
        with ExitStack() as stack:
            for value in ids:
                source = self if value == self.id else Source(self.root, value)
                stack.enter_context(source.lock(shared=True))
            if observed != read_json(self.head_path) or self.status()["status"] != "ready":
                raise CommitError("source_not_ready")
            yield self.manifest(observed)

    def gc(self):
        # Maintenance-only. A shared reader lease pins the generation by
        # preventing this exclusive sweep. Keep current + preceding commit.
        with self.lock():
            if self.pending_path.exists():
                raise CommitError("pending_gc_rejected")
            current = read_json(self.head_path)
            if current is None:
                return
            paths = sorted((self.store / "generations").glob("*.json"), key=lambda p: int(p.stem.split("-")[0]))
            keep = {p for p in paths if p.stem in {current["generation"], current.get("previous")}}
            objects = set()
            for path in keep:
                value = read_json(path)
                for ref in [value["current"], *value["history"].values()]:
                    if ref is not None:
                        objects.add(self.object_path(ref).name)
            for path in (self.store / "generations").iterdir():
                if path not in keep:
                    path.unlink()
            for path in (self.store / "objects").iterdir():
                if path.name not in objects:
                    path.unlink()
            fsync_dir(self.store / "generations")
            fsync_dir(self.store / "objects")

    def project(self, manifest):
        # Shadow objects and journal are durable before any compatibility write.
        history = manifest["history"]
        for name in manifest["projection"]["write"]:
            ref = history[name]
            check_history_name(name)
            path = self.history_path / name
            atomic(path, self.object_bytes(ref))
        current = manifest["current"]
        if current is not None:
            atomic(self.current_path, self.object_bytes(current))
        else:
            self.current_path.unlink(missing_ok=True)
            fsync_dir(self.root)
        for name in manifest["projection"]["delete"]:
            check_history_name(name)
            (self.history_path / name).unlink(missing_ok=True)
        fsync_dir(self.history_path)

    def recover(self):
        pending = read_json(self.pending_path)
        if pending is None:
            return
        if pending["phase"] == "prepared":
            manifest = self.manifest(pending["head"])
            self.project(manifest)
            atomic(self.head_path, encoded(pending["head"]))
        elif pending["phase"] != "building":
            raise CommitError("invalid_journal")
        # building never changes legacy files; prepared always finishes forward.
        self.pending_path.unlink()
        fsync_dir(self.store)

    def reconcile(self):
        manifest = self.manifest()
        if manifest is None:
            raise CommitError("legacy_unregistered")
        expected = manifest["history"]
        actual = {p.name for p in self.history_path.glob("data_*.json")}
        if actual != set(expected):
            raise CommitError("unmanaged_history_change")
        refs = [(self.history_path / name, ref) for name, ref in expected.items()]
        refs.append((self.current_path, manifest["current"]))
        total = 0
        for path, ref in refs:
            if ref is None:
                if path.exists():
                    raise CommitError("unmanaged_current_change")
                continue
            if path.is_symlink() or not path.is_file() or path.stat().st_size != ref["bytes"]:
                raise CommitError("unmanaged_content_change")
            total += ref["bytes"]
            if total > MAX_BYTES:
                raise CommitError("reconcile_budget")
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for block in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != ref["sha256"]:
                raise CommitError("unmanaged_content_change")
        return True


def check_history_name(name):
    if not re.fullmatch(r"data_[A-Za-z0-9_.-]+\.json", name) or len(name) > 240:
        raise CommitError("invalid_history_name")


class Transaction:
    def __init__(self, source, actor):
        if actor not in WRITERS:
            raise CommitError("unregistered_writer")
        self.source, self.actor = source, actor
        source.recover()
        previous = source.manifest()
        if previous and previous["revoked"] and actor != "manual-lifecycle":
            raise CommitError("source_revoked")
        epoch_path = source.store / "epoch.json"
        self.epoch = read_json(epoch_path, 0) + 1
        atomic(epoch_path, encoded(self.epoch))
        atomic(source.pending_path, encoded({"phase": "building", "epoch": self.epoch, "actor": actor}))
        self.current = previous["current"] if previous else None
        self.previous_head = read_json(source.head_path)
        self.history = dict(previous["history"]) if previous else {}
        self.previous_history = dict(self.history)
        self.sequence = previous["sequence"] if previous else 0
        self.managed = previous["managed"] if previous else False
        self.revoked = previous["revoked"] if previous else False
        self.dependencies = previous.get("dependencies", {}) if previous else {}
        self.previous_view_identity = previous.get("view_identity") if previous else None
        self.view_identity = self.previous_view_identity
        self.changed = False
        self.replaced = False
        if previous is None:
            total = 0
            paths = sorted(source.history_path.glob("data_*.json"))
            if len(paths) > MAX_FILES:
                raise CommitError("file_count_budget")
            for path in [source.current_path, *paths]:
                if not path.exists():
                    continue
                if path.is_symlink() or path.stat().st_size > MAX_FILE:
                    raise CommitError("unsafe_legacy_file")
                total += path.stat().st_size
                if total > MAX_BYTES:
                    raise CommitError("legacy_byte_budget")
                ref = source.store_bytes(path.read_bytes())
                if path == source.current_path:
                    self.current = ref
                else:
                    check_history_name(path.name)
                    self.history[path.name] = ref
            self.previous_history = dict(self.history)

    def put_current(self, data):
        if self.revoked:
            raise CommitError("source_revoked")
        self.current = self.source.store_bytes(data)
        self.changed = True

    def history_name(self, timestamp, source=""):
        suffix = "_" + source if source else ""
        return f"data_{timestamp}_{self.sequence + 1:020d}{suffix}.json"

    def put_history(self, name, data, overwrite=False):
        if self.revoked:
            raise CommitError("source_revoked")
        check_history_name(name)
        ref = self.source.store_bytes(data)
        if name in self.history and self.history[name] != ref and not overwrite:
            raise CommitError("history_identity_collision")
        if name in self.history and self.history[name] != ref:
            self.replaced = True
        self.history[name] = ref
        self.changed = True

    def replace_history(self):
        self.history = {}
        self.replaced = self.changed = True

    def enroll(self, writers):
        if set(writers) != WRITERS:
            raise CommitError("writer_inventory_incomplete")
        self.managed = self.changed = True

    def revoke(self):
        self.revoked = self.changed = True
        self.current = None
        self.history = {}

    def commit(self):
        source = self.source
        if not self.changed:
            source.pending_path.unlink(missing_ok=True)
            fsync_dir(source.store)
            return source.status()
        if len(self.history) > MAX_FILES:
            raise CommitError("file_count_budget")
        total = sum(ref["bytes"] for ref in self.history.values()) + (self.current or {}).get("bytes", 0)
        if total > MAX_BYTES:
            raise CommitError("generation_byte_budget")
        self.sequence += 1
        generation = f"{self.sequence}-{uuid.uuid4().hex}"
        inputs = {"current": self.current, "history": self.history, "dependencies": self.dependencies,
                  "view_identity": self.view_identity}
        manifest = {"schema": SCHEMA, "source_id": source.id, "sequence": self.sequence,
                    "epoch": self.epoch, "actor": self.actor, "generation": generation,
                    "managed": self.managed, "revoked": self.revoked, "replace": self.replaced,
                    "projection": {
                        "write": [name for name, ref in self.history.items() if self.previous_history.get(name) != ref],
                        "delete": sorted(set(self.previous_history) - set(self.history))},
                    **inputs, "fingerprint": hashlib.sha256(encoded(inputs)).hexdigest()}
        data = encoded(manifest)
        atomic(source.store / "generations" / (generation + ".json"), data)
        head = {"generation": generation, "sha256": hashlib.sha256(data).hexdigest(),
                "schema": SCHEMA, "source_id": source.id, "sequence": self.sequence,
                "previous": (self.previous_head or {}).get("generation"),
                "dependencies": self.dependencies,
                "managed": self.managed, "revoked": self.revoked, "fingerprint": manifest["fingerprint"]}
        atomic(source.pending_path, encoded({"phase": "prepared", "epoch": self.epoch, "actor": self.actor, "head": head}))
        source.project(manifest)
        atomic(source.head_path, encoded(head))
        source.pending_path.unlink()
        fsync_dir(source.store)
        self.previous_head = head
        return source.status()


@contextmanager
def source_transaction(root, source_id, actor):
    key = (str(Path(root).resolve()), identity(source_id))
    active = _active.get()
    if key in active:
        yield active[key]
        return
    source = Source(root, source_id)
    with source.lock():
        tx = Transaction(source, actor)
        token = _active.set({**active, key: tx})
        try:
            yield tx
            tx.commit()
        except BaseException:
            # Keep a prepared journal for recovery; discard only staging intent.
            pending = read_json(source.pending_path)
            if pending and pending["phase"] == "building":
                source.pending_path.unlink()
                fsync_dir(source.store)
            raise
        finally:
            _active.reset(token)


@contextmanager
def source_group_transaction(root, target_id, source_ids):
    """One ordered lock set for merged read-all-inputs -> shadow publication."""
    target_id = identity(target_id)
    ids = sorted({target_id, *(identity(value) for value in source_ids)})
    if target_id in source_ids:
        raise CommitError("recursive_source_dependency")
    with ExitStack() as stack:
        sources = {value: Source(root, value) for value in ids}
        for value in ids:
            stack.enter_context(sources[value].lock())
            sources[value].recover()
        tx = Transaction(sources[target_id], "merged-bind")
        key = (str(Path(root).resolve()), target_id)
        token = _active.set({**_active.get(), key: tx})
        dependencies = {value: read_json(sources[value].head_path) for value in ids if value != target_id}
        try:
            for value in dependencies:
                if sources[value].status()["status"] == "revoked":
                    raise CommitError("source_dependency_revoked")
            if any(sources[value].status()["status"] != "ready" for value in dependencies):
                tx.managed = False
            tx.previous_dependencies = tx.dependencies
            tx.dependencies = dependencies
            # A zero-score-change input still advances source identity. Publish
            # the validated dependency fence without inventing a history point.
            if tx.previous_dependencies != dependencies:
                tx.changed = True
            yield tx
            tx.commit()
        except BaseException:
            pending = read_json(tx.source.pending_path)
            if pending and pending["phase"] == "building":
                tx.source.pending_path.unlink()
                fsync_dir(tx.source.store)
            raise
        finally:
            _active.reset(token)


def maintenance_reconcile(root, source_id):
    source = Source(root, source_id)
    with source.lock():
        source.recover()
        try:
            source.reconcile()
        except CommitError:
            atomic(source.store / "unsafe.json", encoded({"reason": "unmanaged_change"}))
            raise
        (source.store / "unsafe.json").unlink(missing_ok=True)
        fsync_dir(source.store)
    return source.status()


def rpc(root, source_id, actor="viewer"):
    """Hold the same kernel lock for a Node callback, including its pre-state read."""
    def reply(value):
        print(json.dumps(value, separators=(",", ":")), flush=True)
    with source_transaction(root, source_id, actor) as tx:
        reply({"ok": True, "sequence": tx.sequence + 1})
        for _ in range(MAX_FILES + 16):
            line = sys.stdin.buffer.readline(MAX_FILE * 2 + 1024)
            if not line:
                raise CommitError("writer_disconnected")
            if len(line) >= MAX_FILE * 2 + 1024:
                raise CommitError("request_budget")
            command = json.loads(line)
            op = command["op"]
            if op == "current":
                tx.put_current(command["data"])
            elif op == "history":
                tx.put_history(command["name"], command["data"])
            elif op == "fence":
                tx.revoke()
                tx.commit()  # Durable revocation before independent DB cleanup.
                tx.changed = False
            elif op == "abort":
                raise CommitError("writer_aborted")
            elif op == "finish":
                # Context publishes only after the final command. Ack on exit.
                break
            else:
                raise CommitError("invalid_command")
            reply({"ok": True})
        else:
            raise CommitError("request_count_budget")
    reply({"ok": True, **tx.source.status()})


if __name__ == "__main__":
    try:
        signal.alarm(60)
        rpc(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "viewer")
    except Exception:
        # Never echo payloads, paths, credentials or arbitrary exception text.
        print('{"ok":false,"reason":"source_commit_failed"}', flush=True)
        sys.exit(1)
