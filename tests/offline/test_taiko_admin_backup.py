from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
from datetime import datetime
from pathlib import Path


from taiko_bot.cli import taiko_admin_backup as backup


def _make_backup(root: Path, name: str) -> Path:
    target = root / "scheduled" / name
    payload = target / "payload"
    (payload / "cover").mkdir(parents=True)
    (payload / "db").mkdir()
    (payload / "song_data.json").write_text("{}", encoding="utf-8")
    (payload / "song_alias.json").write_text("{}", encoding="utf-8")
    (payload / "cover" / "1.png").write_bytes(b"cover")
    for table in backup.MANAGED_TABLES:
        (payload / "db" / f"{table}.json").write_text("[]", encoding="utf-8")
    (target / "manifest.json").write_text(json.dumps({"createdAt": name[:8]}), encoding="utf-8")
    return target


def test_archive_has_unique_safe_members_and_removes_payload(tmp_path: Path):
    target = _make_backup(tmp_path, "20260822_041502_daily")
    result = backup.archive_and_prune_payload(target)
    assert result["repacked"] is True
    assert not (target / "payload").exists()
    archive_path = target / backup.ARCHIVE_NAME
    with tarfile.open(archive_path, "r:gz") as archive:
        names = archive.getnames()
    assert len(names) == len(set(names))
    assert "manifest.json" in names
    assert "payload/song_data.json" in names
    expected = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    assert (target / backup.CHECKSUM_NAME).read_text().split()[0] == expected


def test_verification_failure_preserves_payload(tmp_path: Path):
    target = _make_backup(tmp_path, "20260822_041502_daily")
    (target / "payload" / "song_data.json").unlink()
    try:
        backup.archive_and_prune_payload(target)
    except RuntimeError:
        pass
    else:
        raise AssertionError("invalid archive unexpectedly passed verification")
    assert (target / "payload").is_dir()


def test_retention_union_across_days_weeks_and_months(tmp_path: Path):
    dates = [datetime(2026, 8, 22, 4), datetime(2026, 8, 21, 4), datetime(2026, 8, 20, 4), datetime(2026, 8, 15, 4), datetime(2026, 8, 8, 4), datetime(2026, 7, 31, 4), datetime(2026, 6, 30, 4), datetime(2026, 5, 31, 4)]
    items = [(value, tmp_path / value.strftime("%Y%m%d_%H%M%S_daily")) for value in dates]
    names = {path.name for path in backup.select_retained_backups(items, 2, 3, 4)}
    assert {"20260822_040000_daily", "20260821_040000_daily", "20260731_040000_daily", "20260630_040000_daily", "20260531_040000_daily"} <= names


def test_dry_run_does_not_modify_backups(tmp_path: Path):
    older = _make_backup(tmp_path, "20260701_041502_daily")
    newer = _make_backup(tmp_path, "20260822_041502_daily")
    before = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    result = backup.maintain_scheduled_backups(tmp_path, daily_retention=1, weekly_retention=1, monthly_retention=1, dry_run=True)
    after = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*"))
    assert before == after
    assert older.name in result["delete"]
    assert newer.name in result["keep"]
