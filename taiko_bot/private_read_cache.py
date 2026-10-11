"""Serialized LRU snapshots: reusable only after a fresh matching center 304."""
from collections import OrderedDict
from dataclasses import dataclass
import hashlib
import json
import threading
import time

from .settings import Settings


@dataclass(frozen=True)
class CacheEntry:
    etag: str
    raw: bytes
    expires_at: float

    def payload(self):
        return json.loads(self.raw)


def private_cache_key(kind: str, source: str, settings: Settings):
    digest = lambda value: hashlib.sha256(value.encode("utf-8")).hexdigest()
    return kind, digest(settings.viewer_base_url.strip().rstrip("/")), digest(settings.viewer_developer_token.strip()), source


class PrivateReadCache:
    def __init__(self, *, max_entries=64, max_bytes=32 * 1024 * 1024, max_entry_bytes=4 * 1024 * 1024, ttl_seconds=30, now=time.monotonic):
        if any(value <= 0 for value in (max_entries, max_bytes, max_entry_bytes, ttl_seconds)):
            raise ValueError("Private cache budgets must be positive")
        self.max_entries, self.max_bytes, self.max_entry_bytes = max_entries, max_bytes, max_entry_bytes
        self.ttl_seconds, self.now = ttl_seconds, now
        self.entries = OrderedDict()
        self.bytes = self.hits = self.misses = self.evictions = 0
        self.lock = threading.RLock()

    def _remove(self, key, *, eviction=False):
        entry = self.entries.pop(key, None)
        if entry:
            self.bytes -= len(entry.raw)
            if eviction:
                self.evictions += 1

    def get(self, key):
        with self.lock:
            entry = self.entries.get(key)
            if entry and entry.expires_at <= self.now():
                self._remove(key, eviction=True)
                entry = None
            if entry:
                self.entries.move_to_end(key)
                self.hits += 1
            else:
                self.misses += 1
            return entry

    def put(self, key, etag, payload):
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with self.lock:
            self._remove(key)
            if len(raw) > min(self.max_entry_bytes, self.max_bytes):
                return
            while self.entries and (len(self.entries) >= self.max_entries or self.bytes + len(raw) > self.max_bytes):
                self._remove(next(iter(self.entries)), eviction=True)
            self.entries[key] = CacheEntry(etag, raw, self.now() + self.ttl_seconds)
            self.bytes += len(raw)

    def discard(self, key):
        with self.lock:
            self._remove(key)

    def diagnostics(self):
        with self.lock:
            return {"entries": len(self.entries), "bytes": self.bytes, "hits": self.hits, "misses": self.misses, "evictions": self.evictions}
