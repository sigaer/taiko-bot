"""Versioned disk last-good JSON and a read-only, ordered ID-query SQLite pilot."""
import contextlib
import fcntl
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping
from pathlib import Path

from .cache import BoundedLRU
from .metrics import register_cache


def revision(path):
    s = os.stat(path)
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns]


def _folder(root, key):
    path = Path(root) / hashlib.sha256(str(key).encode()).hexdigest()
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


@contextlib.contextmanager
def _lock(path, timeout=120):
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('master publication lock deadline exceeded')
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def _manifest(path):
    try:
        value = json.loads(path.read_text())
        return [entry for entry in value if isinstance(entry, dict)
                and isinstance(entry.get('file'), str)
                and Path(entry['file']).name == entry['file']
                and entry['file'].startswith('v-')] if isinstance(value, list) else []
    except (OSError, ValueError):
        return []


def _valid_generation(folder, entry):
    path = folder / entry['file']
    try:
        if path.suffix == '.json':
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            return digest.hexdigest() == entry.get('sha256')
        with contextlib.closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
            db.execute('PRAGMA mmap_size=0')
            db.execute('PRAGMA cache_size=-2048')
            return db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    except (OSError, sqlite3.Error):
        return False


def _publish(folder, manifest, entry):
    old = _manifest(folder / manifest)
    entries = [entry] + [item for item in old if item['file'] != entry['file'] and _valid_generation(folder, item)][:1]
    fd, tmp = tempfile.mkstemp(dir=folder, prefix='.manifest-')
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(entries, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, folder / manifest)
        directory_fd = os.open(folder, os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        Path(tmp).unlink(missing_ok=True)
    suffix = Path(entry['file']).suffix
    keep = {item['file'] for item in entries}
    for path in folder.glob('v-*' + suffix):
        if path.name not in keep:
            path.unlink(missing_ok=True)


class LastGoodJSON:
    """Stores no row trees; fallback returns a fresh decode, preserving ownership."""
    def __init__(self, root, name='master.last_good'):
        self.root, self.name = Path(root), name
        self._recent = BoundedLRU(name + '.metadata', 512, 512 * 1024)
        self.hits = self.misses = self.writes = self.errors = 0
        register_cache(self)

    def remember(self, key, data, source_revision=None):
        folder = _folder(self.root, key)
        token = tuple(source_revision) if source_revision else None
        if token is not None and self._recent.get(key) == token:
            return
        with _lock(folder / 'json.lock'):
            entries = _manifest(folder / 'json-current.json')
            if token is not None and entries and entries[0].get('source') == list(token) and (folder / entries[0]['file']).exists():
                self._recent[key] = token
                return
            fd, temporary = tempfile.mkstemp(dir=folder, prefix='.json-')
            digest = hashlib.sha256()
            try:
                with os.fdopen(fd, 'wb') as stream:
                    for chunk in json.JSONEncoder(ensure_ascii=False, separators=(',', ':')).iterencode(data):
                        encoded = chunk.encode('utf8')
                        stream.write(encoded)
                        digest.update(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                filename = 'v-' + digest.hexdigest() + '.json'
                os.replace(temporary, folder / filename)
                _publish(folder, 'json-current.json', dict(file=filename, sha256=digest.hexdigest(), source=source_revision))
                self.writes += 1
                if token is not None:
                    self._recent[key] = token
            except Exception:
                self.errors += 1
                raise
            finally:
                Path(temporary).unlink(missing_ok=True)

    def get(self, key, default=None):
        folder = _folder(self.root, key)
        # Pin the manifest and its generations while opening/decoding fallback.
        # Publication GC cannot unlink both generations under a reader.
        with _lock(folder / 'json.lock'):
            for entry in _manifest(folder / 'json-current.json'):
                try:
                    path = folder / entry['file']
                    digest = hashlib.sha256()
                    with path.open('rb') as f:
                        while chunk := f.read(1024 * 1024):
                            digest.update(chunk)
                        if digest.hexdigest() != entry['sha256']:
                            continue
                        f.seek(0)
                        result = json.load(f)
                    self.hits += 1
                    return result
                except (OSError, ValueError):
                    continue
            self.misses += 1
            return default

    def snapshot(self):
        return dict(name=self.name, entries=len(self._recent), estimated_bytes=self._recent.snapshot()['estimated_bytes'],
                    hits=self.hits, misses=self.misses, evictions=self._recent.evictions,
                    max_entries=512, max_bytes=512*1024, oldest_age=self._recent.snapshot()['oldest_age'],
                    successful_publications=self.writes, publication_errors=self.errors,
                    representation='disk_json; metadata_only_in_memory')


class SQLiteRows(Mapping):
    """Read-only dict-like ID index. Duplicate IDs: last row wins, first-key order."""
    def __init__(self, path, source_revision=None, name='master.sqlite'):
        self.path = Path(path)
        self.name = name
        self.source_revision = source_revision
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path.as_uri() + '?mode=ro&immutable=1', uri=True, check_same_thread=False)
        self._db.execute('PRAGMA mmap_size=0')
        self._db.execute('PRAGMA cache_size=-2048')
        if self._db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
            self._db.close()
            raise sqlite3.DatabaseError('master SQLite validation failed')
        self._count = self._db.execute('SELECT COUNT(*) FROM ids').fetchone()[0]
        self.hits = self.misses = 0
        register_cache(self)

    @classmethod
    def load(cls, source, root, key, name='master.sqlite'):
        folder = _folder(root, key)
        with _lock(folder / 'sqlite.lock'):
            entries = _manifest(folder / 'sqlite-current.json')
            try:
                current_revision = revision(source)
            except OSError:
                current_revision = None
            if entries and current_revision == entries[0].get('source'):
                try:
                    return cls(folder / entries[0]['file'], current_revision, name)
                except (OSError, sqlite3.Error):
                    pass
            try:
                fd, temporary = tempfile.mkstemp(dir=folder, prefix='.sqlite-')
                os.close(fd)
                try:
                    # Serial across services; builder sets AS/CPU limits before loading JSON.
                    lock_path = Path(os.environ.get('PYTHON_MEMORY_BUILD_LOCK', '/var/lock/python-memory-master-build.lock'))
                    with _lock(lock_path):
                        completed = subprocess.run([sys.executable, str(Path(__file__).with_name('_build_sqlite.py')), str(source), temporary],
                                                   capture_output=True, text=True, timeout=90, check=True)
                    info = json.loads(completed.stdout)
                    filename = 'v-' + info['sha256'] + '.sqlite'
                    os.replace(temporary, folder / filename)
                    _publish(folder, 'sqlite-current.json', dict(file=filename, source=info['source'], sha256=info['sha256']))
                    return cls(folder / filename, info['source'], name)
                finally:
                    Path(temporary).unlink(missing_ok=True)
            except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError):
                # Failed refresh never replaces an existing valid published generation.
                for entry in entries:
                    try:
                        return cls(folder / entry['file'], entry.get('source'), name)
                    except (OSError, sqlite3.Error):
                        continue
                raise

    def __getitem__(self, key):
        if not isinstance(key, (int, float)) or (isinstance(key, float) and not __import__("math").isfinite(key)) or key != int(key):
            raise KeyError(key)
        with self._lock:
            row = self._db.execute('SELECT rows.payload FROM ids JOIN rows ON rows.position=ids.last_position WHERE ids.id=?', (str(int(key)),)).fetchone()
            if row is None:
                self.misses += 1
                raise KeyError(key)
            self.hits += 1
            return json.loads(row[0])

    def __iter__(self):
        with self._lock:
            cursor = self._db.execute('SELECT id FROM ids ORDER BY first_position')
        try:
            while True:
                with self._lock:
                    row = cursor.fetchone()
                if row is None:
                    break
                yield int(row[0])
        finally:
            with self._lock:
                cursor.close()

    def __len__(self):
        return self._count

    def ordered_rows(self):
        with self._lock:
            cursor = self._db.execute('SELECT payload FROM rows ORDER BY position')
        try:
            while True:
                with self._lock:
                    row = cursor.fetchone()
                if row is None:
                    break
                yield json.loads(row[0])
        finally:
            with self._lock:
                cursor.close()

    def close(self):
        with self._lock:
            self._db.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def snapshot(self):
        return dict(name=self.name, entries=0, dataset_rows=self._count, loaded_datasets=1,
                    estimated_bytes=2*1024**2, max_entries=0, max_bytes=2*1024**2,
                    hits=self.hits, misses=self.misses, evictions=0, oldest_age=None,
                    representation='sqlite_readonly; page_cache_budget_estimate; no_mmap')
