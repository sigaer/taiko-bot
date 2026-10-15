"""Host input boundary for the pinned Taiko Domain implementation.

Storage, clocks and cache lifetimes remain in Sakura; the Core consumes values.
"""
from importlib.metadata import version
from datetime import date
from functools import wraps
from pathlib import Path
from taiko_bot.runtime.player.center.duplicate_versions import SONG_DATA_PATH, _group_cache

CORE_VERSION = "0.1.1"
CONTRACT_VERSION = "0.1.0"

def assert_domain_versions():
    for package, expected in (("sakura-taiko-core", CORE_VERSION), ("sakura-taiko-contract", CONTRACT_VERSION)):
        actual = version(package)
        if actual != expected:
            raise RuntimeError(f"{package} version mismatch: expected {expected}, got {actual}")

def identity_inputs(song_data_path: str | Path = SONG_DATA_PATH):
    groups, by_id, _ = _group_cache(song_data_path)
    return {song_id: group.default_id for song_id, group in by_id.items()}, sorted(
        group.ids for group in groups.values() if len(group.ids) > 1)

def with_host_clock(function):
    @wraps(function)
    def delegate(*args, **kwargs):
        kwargs.setdefault("today", date.today())
        return function(*args, **kwargs)
    return delegate

assert_domain_versions()
