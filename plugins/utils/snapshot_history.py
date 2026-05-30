from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import List

_COMPACT_SNAPSHOT_RE = re.compile(r"^data_(\d{8}_\d{6}_\d{6})(?:_.+)?$")
_LEGACY_SNAPSHOT_RE = re.compile(r"^data_(\d{4}-\d{2}-\d{2}_\d{2}_\d{2}_\d{2})(?:_.+)?$")


def parse_snapshot_time(path: Path) -> dt.datetime:
    stem = path.stem
    match = _COMPACT_SNAPSHOT_RE.fullmatch(stem)
    if match:
        try:
            return dt.datetime.strptime(match.group(1), "%Y%m%d_%H%M%S_%f")
        except ValueError:
            pass

    match = _LEGACY_SNAPSHOT_RE.fullmatch(stem)
    if match:
        try:
            return dt.datetime.strptime(match.group(1), "%Y-%m-%d_%H_%M_%S")
        except ValueError:
            pass

    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return dt.datetime.min


def list_snapshot_files(history_dir: Path) -> List[Path]:
    return sorted(
        history_dir.glob("data_*.json"),
        key=lambda path: (parse_snapshot_time(path), path.name),
    )
