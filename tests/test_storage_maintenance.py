from pathlib import Path

from taiko_bot.cli import storage_maintenance as storage


def test_pressure_levels():
    assert storage.pressure_level(31 * storage.GIB) == "normal"
    assert storage.pressure_level(25 * storage.GIB) == "warning"
    assert storage.pressure_level(15 * storage.GIB) == "critical"
    assert storage.pressure_level(5 * storage.GIB) == "emergency"


def test_vsix_dry_run_does_not_delete(tmp_path: Path, monkeypatch):
    cache = tmp_path / "vsix"
    cache.mkdir()
    old = cache / "old.vsix"
    old.write_bytes(b"x" * 128)
    old.touch()
    monkeypatch.setattr(storage, "VSIX_CACHE", cache)
    monkeypatch.setattr(storage, "VSIX_TTL_SECONDS", -1)
    result = storage.maintain_vsix_cache("normal", True)
    assert old.exists()
    assert result["releasedBytes"] == 128
    assert result["removed"] == ["old.vsix"]
