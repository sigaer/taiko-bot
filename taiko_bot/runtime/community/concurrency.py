"""Serialize in-flight mutations per group/song, retaining no idle keys."""
import asyncio
from contextlib import asynccontextmanager

_pending = {}


@asynccontextmanager
async def serialized(key):
    # Admission and reference accounting contain no await; one event loop owns
    # the same in-memory sessions as the handlers.
    entry = _pending.setdefault(key, [asyncio.Lock(), 0])
    entry[1] += 1
    try:
        async with entry[0]:
            yield
    finally:
        entry[1] -= 1
        if not entry[1]:
            _pending.pop(key, None)
