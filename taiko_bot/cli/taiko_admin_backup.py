#!/usr/bin/env python3
from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

REPO_ROOT = Path(str(_runtime_root()))
BACKUP_ROOT = Path(str(_runtime_root() / 'data/admin_backups'))

from taiko_bot.runtime.player.center.admin_audit import write_system_backup_log
from taiko_bot.runtime.player.center.taiko_db import get_taiko_db_connection

DEFAULT_LABEL = "daily"
ARCHIVE_NAME = "taiko_admin_bundle.tar.gz"
CHECKSUM_NAME = f"{ARCHIVE_NAME}.sha256"
MANAGED_FILES = [REPO_ROOT / "songs" / "song_data.json", REPO_ROOT / "songs" / "song_alias.json"]
MANAGED_DIRS = [REPO_ROOT / "assets" / "cover"]
MANAGED_TABLES = ["web_admin_action_logs", "web_admin_access_rollups", "web_admin_ingest_state"]


def build_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def ensure_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def dump_table_rows(table_name: str) -> List[Dict[str, Any]]:
    db = get_taiko_db_connection()
    cursor = db.cursor()
    try:
        cursor.execute(f"SELECT * FROM {table_name}")
        columns = [column[0] for column in cursor.description or []]
        return [{key: (value.isoformat() if hasattr(value, "isoformat") else value) for key, value in zip(columns, values)} for values in cursor.fetchall()]
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        db.close()


def copy_managed_sources(target_dir: Path) -> Dict[str, Any]:
    copied_files = []
    for file_path in MANAGED_FILES:
        if not file_path.exists():
            continue
        target_path = target_dir / file_path.name
        shutil.copy2(file_path, target_path)
        copied_files.append(str(target_path))
    copied_dirs = []
    for dir_path in MANAGED_DIRS:
        if not dir_path.exists():
            continue
        target_path = target_dir / dir_path.name
        if target_path.exists():
            shutil.rmtree(target_path)
        shutil.copytree(dir_path, target_path)
        copied_dirs.append(str(target_path))
    dumped_tables = []
    db_dump_dir = target_dir / "db"
    ensure_directory(db_dump_dir)
    for table_name in MANAGED_TABLES:
        dump_path = db_dump_dir / f"{table_name}.json"
        dump_path.write_text(json.dumps(dump_table_rows(table_name), ensure_ascii=False, indent=2), encoding="utf-8")
        dumped_tables.append(str(dump_path))
    return {"files": copied_files, "dirs": copied_dirs, "dbDumps": dumped_tables}


def create_archive(backup_dir: Path, archive_path: Path) -> None:
    payload_dir = backup_dir / "payload"
    manifest_path = backup_dir / "manifest.json"
    if not payload_dir.is_dir() or not manifest_path.is_file():
        raise RuntimeError(f"backup source is incomplete: {backup_dir}")
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(manifest_path, arcname="manifest.json", recursive=False)
        archive.add(payload_dir, arcname="payload", recursive=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_archive_name(name: str) -> bool:
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and ".." not in path.parts


def verify_archive(archive_path: Path) -> Dict[str, Any]:
    names: Set[str] = set()
    regular_files = 0
    expanded_bytes = 0
    required = {"manifest.json", "payload/song_data.json", "payload/song_alias.json", *(f"payload/db/{table}.json" for table in MANAGED_TABLES)}
    has_cover = False
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive.getmembers():
            if not _safe_archive_name(member.name):
                raise RuntimeError(f"unsafe archive member: {member.name}")
            if member.name in names:
                raise RuntimeError(f"duplicate archive member: {member.name}")
            names.add(member.name)
            if member.isfile():
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"cannot read archive member: {member.name}")
                read_bytes = 0
                for chunk in iter(lambda: extracted.read(1024 * 1024), b""):
                    read_bytes += len(chunk)
                if read_bytes != member.size:
                    raise RuntimeError(f"truncated archive member: {member.name}")
                regular_files += 1
                expanded_bytes += read_bytes
                has_cover = has_cover or member.name.startswith("payload/cover/")
    missing = sorted(required - names)
    if missing or not has_cover or regular_files == 0 or expanded_bytes == 0:
        raise RuntimeError(f"archive verification failed: missing={missing}, hasCover={has_cover}, files={regular_files}")
    return {"members": len(names), "regularFiles": regular_files, "expandedBytes": expanded_bytes}


def write_checksum(archive_path: Path, checksum_path: Path) -> str:
    checksum = sha256_file(archive_path)
    temporary = checksum_path.with_name(f".{checksum_path.name}.{os.getpid()}.tmp")
    temporary.write_text(f"{checksum}  {ARCHIVE_NAME}\n", encoding="ascii")
    os.replace(temporary, checksum_path)
    return checksum


def archive_and_prune_payload(backup_dir: Path) -> Dict[str, Any]:
    payload_dir = backup_dir / "payload"
    archive_path = backup_dir / ARCHIVE_NAME
    checksum_path = backup_dir / CHECKSUM_NAME
    if not payload_dir.exists():
        verification = verify_archive(archive_path)
        checksum = sha256_file(archive_path)
        expected = checksum_path.read_text(encoding="ascii").split()[0] if checksum_path.exists() else ""
        if expected and expected != checksum:
            raise RuntimeError(f"checksum mismatch: {archive_path}")
        if not expected:
            write_checksum(archive_path, checksum_path)
        return {**verification, "sha256": checksum, "repacked": False}
    temporary = backup_dir / f".{ARCHIVE_NAME}.{os.getpid()}.tmp"
    try:
        create_archive(backup_dir, temporary)
        verification = verify_archive(temporary)
        checksum = sha256_file(temporary)
        os.replace(temporary, archive_path)
        write_checksum(archive_path, checksum_path)
        shutil.rmtree(payload_dir)
        return {**verification, "sha256": checksum, "repacked": True}
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def parse_backup_timestamp(name: str) -> Optional[datetime]:
    try:
        return datetime.strptime(name[:15], "%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        return None


def select_retained_backups(backups: Sequence[Tuple[datetime, Path]], daily_retention: int, weekly_retention: int, monthly_retention: int) -> Set[Path]:
    ordered = sorted(backups, key=lambda item: item[0], reverse=True)
    keep: Set[Path] = set()
    seen_days: Set[Tuple[int, int]] = set()
    seen_weeks: Set[Tuple[int, int]] = set()
    seen_months: Set[Tuple[int, int]] = set()
    for created_at, path in ordered:
        day_key = (created_at.year, created_at.timetuple().tm_yday)
        if len(seen_days) < daily_retention and day_key not in seen_days:
            seen_days.add(day_key)
            keep.add(path)
        iso = created_at.isocalendar()
        week_key = (iso[0], iso[1])
        if len(seen_weeks) < weekly_retention and week_key not in seen_weeks:
            seen_weeks.add(week_key)
            keep.add(path)
        month_key = (created_at.year, created_at.month)
        if len(seen_months) < monthly_retention and month_key not in seen_months:
            seen_months.add(month_key)
            keep.add(path)
    return keep


def maintain_scheduled_backups(backup_root: Path, *, daily_retention: int, weekly_retention: int, monthly_retention: int, dry_run: bool) -> Dict[str, Any]:
    scheduled_root = backup_root / "scheduled"
    ensure_directory(scheduled_root)
    parsed: List[Tuple[datetime, Path]] = []
    ignored: List[str] = []
    for path in scheduled_root.iterdir():
        created_at = parse_backup_timestamp(path.name) if path.is_dir() else None
        if created_at is None:
            ignored.append(path.name)
        else:
            parsed.append((created_at, path))
    keep = select_retained_backups(parsed, daily_retention, weekly_retention, monthly_retention)
    delete = sorted((path for _, path in parsed if path not in keep), key=lambda path: path.name)
    kept = sorted(keep, key=lambda path: path.name)
    result: Dict[str, Any] = {"dryRun": dry_run, "keep": [path.name for path in kept], "delete": [path.name for path in delete], "ignored": sorted(ignored), "estimatedReclaimBytes": sum(directory_size(path) for path in delete), "repacked": [], "deleted": []}
    if dry_run:
        return result
    for path in kept:
        verification = archive_and_prune_payload(path)
        if verification["repacked"]:
            result["repacked"].append(path.name)
    for path in delete:
        shutil.rmtree(path)
        result["deleted"].append(path.name)
    return result


def positive_retention(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("retention must be at least 1")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and maintain taiko admin backups.")
    parser.add_argument("--label", default=DEFAULT_LABEL)
    parser.add_argument("--summary", default="daily scheduled backup")
    parser.add_argument("--maintenance-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--daily-retention", type=positive_retention, default=7)
    parser.add_argument("--weekly-retention", type=positive_retention, default=4)
    parser.add_argument("--monthly-retention", type=positive_retention, default=6)
    args = parser.parse_args()
    created_manifest: Optional[Dict[str, Any]] = None
    if not args.maintenance_only:
        if args.dry_run:
            parser.error("--dry-run requires --maintenance-only")
        backup_dir = BACKUP_ROOT / "scheduled" / f"{build_timestamp()}_{args.label}"
        payload_dir = backup_dir / "payload"
        ensure_directory(payload_dir)
        copied = copy_managed_sources(payload_dir)
        created_manifest = {"label": args.label, "summary": args.summary, "createdAt": datetime.now().isoformat(), "backupDir": str(backup_dir), "archivePath": str(backup_dir / ARCHIVE_NAME), **copied}
        (backup_dir / "manifest.json").write_text(json.dumps(created_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        verification = archive_and_prune_payload(backup_dir)
        created_manifest["archiveSha256"] = verification["sha256"]
        (backup_dir / "manifest.json").write_text(json.dumps(created_manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        write_system_backup_log(args.label, created_manifest)
    maintenance = maintain_scheduled_backups(BACKUP_ROOT, daily_retention=args.daily_retention, weekly_retention=args.weekly_retention, monthly_retention=args.monthly_retention, dry_run=args.dry_run)
    print(json.dumps({"backup": created_manifest, "maintenance": maintenance}, ensure_ascii=False))


if __name__ == "__main__":
    main()
