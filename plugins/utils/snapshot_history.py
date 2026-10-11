from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import List
from taiko_bot.history_adapter import snapshot_name_time

def parse_snapshot_time(path: Path) -> dt.datetime:
    stamp = snapshot_name_time(path.name)
    if stamp is not None:
        return stamp

    try:
        return dt.datetime.fromtimestamp(path.stat().st_mtime)
    except OSError:
        return dt.datetime.min


def list_snapshot_files(history_dir: Path) -> List[Path]:
    return sorted(
        history_dir.glob("data_*.json"),
        key=lambda path: (parse_snapshot_time(path), path.name),
    )
