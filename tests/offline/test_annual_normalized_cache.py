from __future__ import annotations

import shutil
from pathlib import Path

from taiko_bot.offline.annual_summary import cache


def test_normalized_cache_skips_write_below_free_space_floor(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TAIKO_ANNUAL_CACHE_DIR", str(tmp_path / "cache"))
    gib = 1024 ** 3
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(315 * gib, 300 * gib, 15 * gib))
    cache.reset_normalized_cache_stats()
    content_hash = "a" * 64
    cache.write_normalized_snapshot(content_hash, {"payload": {"songs": []}})
    assert not (tmp_path / "cache" / "normalized").exists()
    assert cache.get_normalized_cache_stats()["disabled"] == 1


def test_normalized_cache_write_io_error_is_non_fatal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TAIKO_ANNUAL_CACHE_DIR", str(tmp_path / "cache"))
    gib = 1024 ** 3
    monkeypatch.setattr(shutil, "disk_usage", lambda _path: shutil._ntuple_diskusage(315 * gib, 200 * gib, 115 * gib))
    monkeypatch.setattr(cache, "_ensure_private_dir", lambda _path: (_ for _ in ()).throw(OSError("disk error")))
    cache.reset_normalized_cache_stats()
    cache.write_normalized_snapshot("b" * 64, {"payload": {}})
    assert cache.get_normalized_cache_stats()["disabled"] == 1
