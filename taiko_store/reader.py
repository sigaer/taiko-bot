"""One captured score view, valid only for the kernel lease that created it."""
from __future__ import annotations

import os
import stat
import json
from contextlib import contextmanager

from .publication import PublicationError, PublicationStore, _directory, _history_name


class ScoreReadView:
    def __init__(self, store, manifest, token):
        self.store = store
        self.manifest = manifest
        self.token = token

    def _check(self):
        self.store._require_lock()
        if self.store._lease_token is not self.token:
            raise PublicationError("Score view belongs to an expired lease")

    @property
    def publication(self):
        self._check()
        return None if self.manifest is None else {
            "sequence": self.manifest["sequence"], "commitId": self.manifest["commitId"]}

    def _legacy_bytes(self, key):
        path = self.store._projection_path(key)
        if key.startswith("history/"):
            # Reject ancestor symlinks before opening a legacy history file.
            _directory(path.parent)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.store.max_file_bytes:
                raise PublicationError("Legacy score file is not a bounded plain file")
            raw = source.read(self.store.max_file_bytes + 1)
        if len(raw) > self.store.max_file_bytes:
            raise PublicationError("Legacy score object limit exceeded")
        return raw

    def raw(self, key):
        self._check()
        self.store._projection_path(key)
        if self.manifest is None:
            return self._legacy_bytes(key)
        reference = self.manifest["files"].get(key)
        if reference is None:
            raise FileNotFoundError("Score object absent from committed view")
        return self.store.read_object(reference)

    def current_raw(self):
        return self.raw("current")

    def history_raw(self, name):
        return self.raw("history/" + _history_name(name))

    def file_times(self, key):
        """Filesystem metadata only, never a score time or readiness proof.

        Managed bytes verify before their metadata is used. Captured mtime
        preserves legacy fallback ordering, including equal-content files with
        different original mtimes. Captured ctime preserves the old displayed
        filesystem value across adoption/link/recovery/restore, rather than
        turning storage operations into a new score update.
        """
        self._check()
        path = self.store._projection_path(key)
        if self.manifest is not None:
            reference = self.manifest["files"].get(key)
            if reference is None:
                raise FileNotFoundError("Score object absent from committed view")
            try:
                self.raw(key)
            except OSError:
                raise PublicationError("Canonical score metadata is unavailable") from None
            path = self.store.objects / reference["sha256"]
        elif key.startswith("history/"):
            _directory(path.parent)
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        except OSError:
            if self.manifest is not None:
                raise PublicationError("Canonical score metadata is unavailable") from None
            raise
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > self.store.max_file_bytes:
                raise PublicationError("Score metadata is not a bounded plain file")
            return {"mtime": self.manifest.get("fileMtimes", {}).get(key, info.st_mtime)
                    if self.manifest is not None else info.st_mtime,
                    "ctime": self.manifest.get("fileCtimes", {}).get(key, info.st_ctime)
                    if self.manifest is not None else info.st_ctime}
        finally:
            os.close(fd)

    def history_names(self):
        self._check()
        if self.manifest is not None:
            return [key[len("history/"):] for key in self.manifest["files"] if key.startswith("history/")]
        directory = self.store.root / self.store.identity
        if not directory.exists():
            return []
        _directory(directory)
        result = []
        for path in directory.iterdir():
            if path.name.startswith("data_") and path.name.endswith(".json"):
                result.append(_history_name(path.name))
                if len(result) > self.store.max_history_files:
                    raise PublicationError("Legacy history file limit exceeded")
        return result


@contextmanager
def score_read_view(root, identity):
    store = PublicationStore(root, str(identity))
    with store.shared():
        yield store.reader()


def read_current_json(root, identity):
    """Decode one current object while its canonical publication lease is held.

    Legacy sources retain sequence-zero reading; a managed source never falls
    back to its compatible projection when the immutable object is absent or
    corrupt. The caller owns root configuration and score interpretation.
    """
    with score_read_view(root, identity) as view:
        try:
            return json.loads(view.current_raw().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            if view.manifest is not None and "current" in view.manifest["files"]:
                raise PublicationError("Canonical current is unavailable") from None
            raise
