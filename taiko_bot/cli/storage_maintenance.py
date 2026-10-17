#!/usr/bin/env python3
from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT_FILESYSTEM = Path("/")
VSIX_CACHE = Path("/root/.vscode-server/data/CachedExtensionVSIXs")
QOOAPP_DOWNLOADS = Path("/home/sigaer/sekai/runtime/qooapp_update/downloads")
SEKAI_PICCACHE = Path("/home/sigaer/sekai/piccache")
PJSK_CACHE = Path("/home/sigaer/miku-bot/data/pjsk/cache")
MINECRAFT_BACKUPS = Path("/www/backup/path")
LOCK_PATH = Path("/run/lock/taiko-storage-maintenance.lock")
LOG_PATH = Path("/home/sigaer/taiko/logs/storage_maintenance.jsonl")

GIB = 1024 ** 3
WARNING_FREE = 30 * GIB
CRITICAL_FREE = 20 * GIB
EMERGENCY_FREE = 10 * GIB
VSIX_HIGH = 1 * GIB
VSIX_TARGET = 512 * 1024 ** 2
VSIX_TTL_SECONDS = 14 * 24 * 60 * 60


def tree_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file() and not item.is_symlink():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def disk_snapshot() -> Dict[str, int]:
    usage = shutil.disk_usage(ROOT_FILESYSTEM)
    return {"totalBytes": usage.total, "usedBytes": usage.used, "freeBytes": usage.free}


def pressure_level(free_bytes: int) -> str:
    if free_bytes < EMERGENCY_FREE:
        return "emergency"
    if free_bytes < CRITICAL_FREE:
        return "critical"
    if free_bytes < WARNING_FREE:
        return "warning"
    return "normal"


def remove_path(path: Path, dry_run: bool) -> int:
    size = tree_size(path) if path.is_dir() else path.stat().st_size
    if not dry_run:
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
    return size


def maintain_vsix_cache(level: str, dry_run: bool) -> Dict[str, Any]:
    result: Dict[str, Any] = {"path": str(VSIX_CACHE), "scanned": 0, "removed": [], "releasedBytes": 0, "errors": []}
    if not VSIX_CACHE.is_dir():
        return result
    now = datetime.now(timezone.utc).timestamp()
    entries = []
    for path in VSIX_CACHE.iterdir():
        try:
            info = path.stat(follow_symlinks=False)
            entries.append((info.st_mtime, path, tree_size(path) if path.is_dir() else info.st_size))
            result["scanned"] += 1
        except OSError as error:
            result["errors"].append(f"{path.name}: {error}")
    entries.sort(key=lambda item: item[0])
    total = sum(item[2] for item in entries)
    candidates: List[tuple[float, Path, int]] = []
    if level in {"critical", "emergency"}:
        candidates = entries
    else:
        candidates.extend(item for item in entries if now - item[0] > VSIX_TTL_SECONDS)
        projected = total - sum(item[2] for item in candidates)
        if projected > VSIX_HIGH:
            selected = {item[1] for item in candidates}
            for item in entries:
                if projected <= VSIX_TARGET:
                    break
                if item[1] in selected:
                    continue
                candidates.append(item)
                selected.add(item[1])
                projected -= item[2]
    for _, path, _ in candidates:
        try:
            result["releasedBytes"] += remove_path(path, dry_run)
            result["removed"].append(path.name)
        except OSError as error:
            result["errors"].append(f"{path.name}: {error}")
    result["beforeBytes"] = total
    result["afterBytes"] = max(0, total - result["releasedBytes"])
    return result


def count_files(path: Path) -> Dict[str, int]:
    count = 0
    size = 0
    if path.exists():
        for item in path.rglob("*"):
            try:
                if item.is_file() and not item.is_symlink():
                    count += 1
                    size += item.stat().st_size
            except OSError:
                continue
    return {"files": count, "bytes": size}


def build_report(dry_run: bool) -> Dict[str, Any]:
    before = disk_snapshot()
    level = pressure_level(before["freeBytes"])
    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dryRun": dry_run,
        "level": level,
        "before": before,
        "rules": {"vscodeVsix": maintain_vsix_cache(level, dry_run)},
        "observations": {
            "qooappDownloads": count_files(QOOAPP_DOWNLOADS),
            "sekaiPiccache": count_files(SEKAI_PICCACHE),
            "mikuPjskCache": count_files(PJSK_CACHE),
            "minecraftBackupFiles": count_files(MINECRAFT_BACKUPS),
        },
        "protected": [
            "/home/sigaer/git/ESE_autosync",
            "/opt/mcsmanager/daemon/data",
            "/home/sigaer/taiko/userdata",
            "/home/sigaer/sekai/assets",
            "/home/sigaer/sekai/masterdata",
        ],
    }
    report["after"] = disk_snapshot()
    report["releasedBytes"] = max(0, report["after"]["freeBytes"] - before["freeBytes"])
    report["alert"] = level in {"warning", "critical", "emergency"}
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain explicitly allowlisted rebuildable storage.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="json_only")
    args = parser.parse_args()
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({"error": "storage maintenance is already running"}))
            return 75
        report = build_report(args.dry_run)
        serialized = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
        if not args.dry_run:
            LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with LOG_PATH.open("a", encoding="utf-8") as log:
                log.write(serialized + "\n")
        print(serialized if args.json_only else json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
