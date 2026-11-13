"""One revisioned search snapshot per process; request pins outlive replacement.

The cache owns one finite catalog, not unbounded roots/profiles or query keys.
Each unpinned acquisition stats both inputs (including inode/ctime), with a
30-second hash backstop for same-tick in-place rewrites. Build under a writer
lock and publish one frozen object only after a stable read. Corruption retains
last-good in memory, not on disk.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import logging
from pathlib import Path
from threading import Lock
from time import monotonic

from taiko_application.query import SongQueryContext, query_music
from taiko_application.query.song_index import SongIndex, build_song_index

_logger = logging.getLogger(__name__)


class CatalogChangedError(ValueError):
    """Retry on the next request, even if the writer has now stopped."""


@dataclass(frozen=True)
class CatalogSnapshot:
    key: tuple
    revision: str
    signatures: tuple
    index: SongIndex

    def query(self, text, similarity, **options):
        return query_music(SongQueryContext(songs=(), aliases=(), groups_by_id={},
            groups_by_title={}, similarity=similarity, query=text, index=self.index, **options))


def _signature(path):
    st = path.stat()
    return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns


def _read(path):
    # Keep only the two public JSON payloads temporarily, never private files.
    data = path.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def _validate(songs, aliases):
    if not isinstance(songs, list) or not isinstance(aliases, list):
        raise ValueError('song catalogs must be arrays')
    for row in songs:
        if not isinstance(row, dict):
            raise ValueError('invalid song row')
        try:
            int(row.get('id'))
        except (TypeError, ValueError, OverflowError):
            raise ValueError('invalid song ID') from None
        if any(row.get(key) is not None and not isinstance(row[key], str)
               for key in ('song_name', 'song_name_jp', 'type')):
            raise ValueError('invalid song metadata')
    for row in aliases:
        if not isinstance(row, dict) or (row.get('aliases') is not None and not isinstance(row['aliases'], list)):
            raise ValueError('invalid alias row')
        if any(not isinstance(value, str) for value in row.get('aliases') or []):
            raise ValueError('invalid alias value')
        if row.get('song_name_jp') is not None and not isinstance(row['song_name_jp'], str):
            raise ValueError('invalid alias title')


class CatalogStore:
    def __init__(self):
        self._snapshot = None
        self._failed = None
        self._lock = Lock()
        self.loads = 0
        self.failures = 0
        self._verify_after = 0.0

    def get(self, songs_path, aliases_path, profile):
        paths = Path(songs_path), Path(aliases_path)
        key = (*paths, profile)
        # Serialize reads/rebuilds; no reader can observe half of a replacement.
        with self._lock:
            now = monotonic()
            old = self._snapshot if self._snapshot and self._snapshot.key == key else None
            signature = None
            try:
                signature = tuple(_signature(path) for path in paths)
                if old and old.signatures == signature and now < self._verify_after:
                    return old
                if old and self._failed == (key, signature) and now < self._verify_after:
                    return old
                for _ in range(2):
                    song_bytes, songs_hash = _read(paths[0])
                    alias_bytes, aliases_hash = _read(paths[1])
                    revision = hashlib.sha256(f'{profile}:{songs_hash}:{aliases_hash}'.encode()).hexdigest()
                    if old and old.revision == revision:
                        after = tuple(_signature(path) for path in paths)
                        if after == signature:
                            snapshot = old if old.signatures == after else CatalogSnapshot(key, revision, after, old.index)
                            self._snapshot = snapshot
                            self._verify_after = now + 30.0
                            self._failed = None
                            return snapshot
                        signature = after
                        continue
                    songs, aliases = json.loads(song_bytes), json.loads(alias_bytes)
                    del song_bytes, alias_bytes
                    _validate(songs, aliases)
                    if profile == 'client':
                        from sakura_taiko_core.chart.visibility import is_song_publicly_visible, normalize_song_id
                        songs = [row for row in songs if is_song_publicly_visible(row)]
                        visible_ids = {normalize_song_id(row.get('id')) for row in songs}
                        visible_ids.discard(None)
                        aliases = [row for row in aliases if normalize_song_id(row.get('id')) in visible_ids]
                    index = build_song_index(songs, aliases, collapse_versions=profile == 'center')
                    after = tuple(_signature(path) for path in paths)
                    if after == signature:
                        snapshot = CatalogSnapshot(key, revision, after, index)
                        self._snapshot = snapshot
                        self._failed = None
                        self._verify_after = now + 30.0
                        self.loads += 1
                        return snapshot
                    signature = after
                raise CatalogChangedError('song catalogs changed during preparation')
            except Exception as error:
                # Preparation can fail as well as file IO/JSON decoding. Never
                # replace last-good with a partially prepared generation.
                self.failures += 1
                failed = key, signature
                if self._failed != failed:
                    _logger.warning('Song catalog reload failed (%s); last-good=%s', type(error).__name__, old is not None)
                self._failed = None if isinstance(error, CatalogChangedError) else failed
                self._verify_after = now + 30.0
                if old is not None:
                    return old
                raise


_store = CatalogStore()
_pinned: ContextVar[CatalogSnapshot | None] = ContextVar('public_song_catalog', default=None)
_in_request: ContextVar[bool] = ContextVar('public_song_request', default=False)


def get_snapshot(*, profile=None):
    from . import config
    mode = profile or config.profile()
    base = config.root() / 'songs'
    key = (base/'song_data.json', base/'song_alias.json', mode)
    current = _pinned.get()
    if current is not None and current.key == key:
        return current
    snapshot = _store.get(*key)
    if _in_request.get():
        _pinned.set(snapshot)
    return snapshot


@contextmanager
def catalog_request():
    # Acquire lazily inside execute_song's existing query-error handling. Nested
    # prefix resolution shares the enclosing command's pin, including brief().
    if _in_request.get():
        yield
        return
    token = _pinned.set(None)
    request_token = _in_request.set(True)
    try:
        yield
    finally:
        _pinned.reset(token)
        _in_request.reset(request_token)
