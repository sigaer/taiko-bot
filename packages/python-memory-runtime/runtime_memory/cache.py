"""LRU with incremental eviction and accounting at insertion, never JSON dumps."""
import sys
import time
import threading
from collections import OrderedDict
from collections.abc import MutableMapping


def estimated_size(value, max_nodes=4096):
    """Bounded traversal; extrapolate unvisited nodes conservatively for admission.

    An estimate, not a PSS measurement. Prefer known decoded sizes for images.
    """
    # Fixed work budget, including cyclic or adversarially deep containers.
    from itertools import islice
    stack = [(value, 1.0)]
    seen = set()
    size = 0.0
    visited = 0
    while stack and visited < max_nodes:
        item, multiplier = stack.pop()
        visited += 1
        if id(item) in seen:
            continue
        seen.add(id(item))
        size += sys.getsizeof(item) * multiplier
        if isinstance(item, dict):
            count = min(len(item), 32, max(0, (max_nodes - visited - len(stack)) // 2))
            if count:
                factor = multiplier * len(item) / count
                for key, child in islice(item.items(), count):
                    stack.extend(((key, factor), (child, factor)))
            elif item:
                size += len(item) * 1024 * multiplier
        elif isinstance(item, (tuple, list, set, frozenset)):
            count = min(len(item), 64, max(0, max_nodes - visited - len(stack)))
            if count:
                factor = multiplier * len(item) / count
                stack.extend((child, factor) for child in islice(item, count))
            elif item:
                size += len(item) * 1024 * multiplier
    return int(size + sum(multiplier * 1024 for _, multiplier in stack))


def image_bytes(image):
    channels = max(1, len(image.getbands()))
    if image.mode in ('I', 'F'):
        channels = 4
    elif image.mode.startswith('I;16'):
        channels = 2
    return int(image.width) * int(image.height) * channels


class BoundedLRU(MutableMapping):
    def __init__(self, name, max_entries, max_bytes, weight=estimated_size, ttl=None, low_watermark=1.0):
        if max_entries < 1 or max_bytes < 1 or not 0 < low_watermark <= 1:
            raise ValueError('cache budgets must be positive')
        self.name, self.max_entries, self.max_bytes = name, int(max_entries), int(max_bytes)
        self.weight, self.ttl, self.low_watermark = weight, ttl, low_watermark
        self._rows = OrderedDict()
        self._bytes = self.hits = self.misses = self.evictions = self.evicted_bytes = self.rejected = 0
        self._lock = threading.RLock()

    def _remove(self, key, eviction=False):
        value, weight, created = self._rows.pop(key)
        self._bytes -= weight
        if eviction:
            self.evictions += 1
            self.evicted_bytes += weight
        # Caller-owned/shared PIL images are never closed on eviction.
        return value

    def __getitem__(self, key):
        with self._lock:
            item = self._rows.get(key)
            if item is None or (self.ttl is not None and time.monotonic() - item[2] > self.ttl):
                if item is not None:
                    self._remove(key, True)
                self.misses += 1
                raise KeyError(key)
            self.hits += 1
            self._rows.move_to_end(key)
            return item[0]

    def __setitem__(self, key, value):
        weight = max(1, int(self.weight(value))) + min(4096, estimated_size(key, 128))
        with self._lock:
            if key in self._rows:
                self._remove(key)
            if weight > self.max_bytes:
                self.rejected += 1
                return
            over = len(self._rows) + 1 > self.max_entries or self._bytes + weight > self.max_bytes
            entry_limit = max(1, int(self.max_entries * self.low_watermark)) if over else self.max_entries
            byte_limit = max(weight, int(self.max_bytes * self.low_watermark)) if over else self.max_bytes
            while self._rows and (len(self._rows) + 1 > entry_limit or self._bytes + weight > byte_limit):
                self._remove(next(iter(self._rows)), True)
            self._rows[key] = (value, weight, time.monotonic())
            self._bytes += weight

    def __delitem__(self, key):
        with self._lock:
            self._remove(key)

    def __iter__(self):
        with self._lock:
            return iter(tuple(self._rows))

    def __len__(self):
        with self._lock:
            return len(self._rows)

    def clear(self):
        with self._lock:
            self._rows.clear()
            self._bytes = 0

    def snapshot(self):
        with self._lock:
            ages = [time.monotonic() - item[2] for item in self._rows.values()]
            return dict(name=self.name, entries=len(self._rows), estimated_bytes=self._bytes,
                        hits=self.hits, misses=self.misses, evictions=self.evictions,
                        evicted_bytes=self.evicted_bytes, rejected=self.rejected,
                        max_entries=self.max_entries, max_bytes=self.max_bytes,
                        oldest_age=max(ages, default=0), ttl=self.ttl)


def font_bytes(font):
    """Conservative admission estimate including face/glyph workspace, not PSS."""
    import os
    try:
        source_bytes = os.stat(font.path).st_size
    except (OSError, TypeError, AttributeError):
        source_bytes = 0
    size = max(1, int(getattr(font, 'size', 16)))
    return 2 * 1024**2 + min(source_bytes, 32 * 1024**2) // 4 + size * size * 512


def bounded_memoize(name, max_entries, max_bytes, weight=estimated_size, ttl=None):
    """Small synchronous memoizer retaining cache_info/cache_clear call sites.

    Clear is explicit invalidation only. Counters remain cumulative for telemetry.
    As with functools.lru_cache, concurrent misses may compute the same key.
    """
    from collections import namedtuple
    from functools import wraps
    from .metrics import register_cache
    info_type = namedtuple('CacheInfo', 'hits misses maxsize currsize')
    def decorate(function):
        cache = register_cache(BoundedLRU(name, max_entries, max_bytes, weight=weight, ttl=ttl))
        @wraps(function)
        def wrapped(*args, **kwargs):
            key = (args, tuple(kwargs.items()))
            try:
                return cache[key]
            except KeyError:
                value = function(*args, **kwargs)
                cache[key] = value
                return value
        wrapped.cache_info = lambda: info_type(cache.hits, cache.misses, cache.max_entries, len(cache))
        wrapped.cache_clear = cache.clear
        wrapped.cache_snapshot = cache.snapshot
        wrapped.memory_cache = cache
        return wrapped
    return decorate
