"""One bounded daily namespace protocol under an existing Source lease.

The caller owns measurement semantics. These files intentionally survive model
changes independently of C/H generations; Source SH fences EX deletion/backup,
and the shared namespace lock also serializes portable restoration.
"""
from contextlib import contextmanager
import fcntl
import json
import os
import re
import stat
import time

from .publication import PublicationError, _atomic_bytes, _directory

DAILY_NAME = re.compile(r"daily-ability-[a-z0-9-]{1,64}\.json")
MAX_ARCHIVE_BYTES = 8 * 1024**2


@contextmanager
def archive_lock(store, path, *, write=True):
    store._require_lock()
    fd = os.open(path.with_suffix(".lock"), os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise PublicationError("Daily lock is not a plain file")
        deadline = time.monotonic() + store.lock_timeout
        mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
        while True:
            try:
                fcntl.flock(fd, mode | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise PublicationError("Daily lock deadline exceeded")
                time.sleep(.01)
        yield
    finally:
        os.close(fd)


@contextmanager
def daily_archive(store, namespace="v1-top20", *, writable=True):
    store._require_lock()
    if not isinstance(namespace, str) or not re.fullmatch(r"[a-z0-9-]{1,64}", namespace):
        raise PublicationError("Invalid daily namespace")
    directory = store.root / store.identity
    _directory(directory)
    path = directory / ("daily-ability-" + namespace + ".json")
    with archive_lock(store, path, write=writable):
        try:
            payload = store._read_json(path, MAX_ARCHIVE_BYTES)
            exists = True
        except FileNotFoundError:
            payload = {"version": 1, "namespace": namespace, "days": {}}
            exists = False
        if (not isinstance(payload, dict) or payload.get("version") != 1
                or payload.get("namespace") != namespace or not isinstance(payload.get("days"), dict)):
            raise PublicationError("Invalid daily archive")
        before = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        yield payload["days"]
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        if encoded == before and (exists or not payload["days"]):
            return
        if not writable:
            raise PublicationError("Daily reader cannot write")
        view = store.view()
        if view is None or not any(key == "current" or key.startswith("history/") for key in view["files"]):
            raise PublicationError("Daily mutation requires an active canonical Source")
        raw = encoded.encode()
        if len(raw) > MAX_ARCHIVE_BYTES:
            raise PublicationError("Daily archive limit exceeded")
        # Existing Source EX collection recognizes only this identity's stage;
        # a daily SH writer cannot race that collector or a different Source.
        _atomic_bytes(path, raw, stage_identity=store.identity)
        store.fault("daily-archive-durable")
