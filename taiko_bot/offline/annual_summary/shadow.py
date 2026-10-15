from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .cache import get_normalized_cache_stats, reset_normalized_cache_stats
from .constants import DEFAULT_VERSION, USERDATA_DIR
from .events import build_observation_events
from .helpers import iso_datetime
from .service import _time_coverage, resolve_version
from .snapshots import load_snapshot_history, select_window
from .reporting_window import resolve_reporting_window


def _failure_reason(current_file: Path, error: Exception) -> str:
    message = str(error).strip().lower()
    if message == "no snapshots in annual window":
        return "no_snapshots_in_window"
    if message != "no_snapshots":
        return "unexpected"
    try:
        payload = json.loads(current_file.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return "invalid_snapshot_json"
    if not isinstance(payload, dict):
        return "invalid_snapshot_shape"
    if not isinstance(payload.get("songs"), list):
        return "invalid_songs_shape"
    return "no_snapshots"


def build_shadow_report(
    userdata_dir: str | Path = USERDATA_DIR,
    version: str | Dict[str, Any] = DEFAULT_VERSION["key"],
    *,
    generated_at: Optional[datetime] = None,
) -> Dict[str, Any]:
    reset_normalized_cache_stats()
    generated_at = generated_at or datetime.now()
    version_payload = resolve_version(version)
    reporting_window = resolve_reporting_window(version_payload)
    start_date = reporting_window.start_date
    end_date = reporting_window.end_inclusive_date
    root = Path(userdata_dir)
    current_files = sorted(
        path for path in root.glob("*data.json") if path.is_file() and not path.name.startswith("data_")
    )
    modes: Counter[str] = Counter()
    time_status: Counter[str] = Counter()
    sources: Counter[str] = Counter()
    warnings: Counter[str] = Counter()
    failures: Counter[str] = Counter()
    built_count = 0

    for current_file in current_files:
        taiko_id = current_file.name[: -len("data.json")]
        try:
            history = load_snapshot_history(taiko_id, userdata_dir=root)
            if not history.snapshots:
                raise ValueError("no_snapshots")
            selection = select_window(
                history.snapshots,
                start_date=start_date,
                generated_at=generated_at,
                end_date=end_date,
                start_at=reporting_window.start_at,
                end_exclusive_at=reporting_window.end_exclusive_at,
            )
            events, event_stats = build_observation_events(
                selection,
                start_date=start_date,
                effective_end_date=selection.effective_end_date,
                start_at=reporting_window.start_at,
                end_exclusive_at=reporting_window.end_exclusive_at,
            )
            mode = "version_observed" if event_stats["comparableTransitionCount"] > 0 else "current_archive"
            coverage = _time_coverage(events)
            modes[mode] += 1
            time_status["eligible" if coverage["eligible"] else "hidden"] += 1
            for item in selection.window_snapshots:
                sources[item.source] += 1
            for warning in history.warnings:
                warnings[str(warning).split(":", 1)[0]] += 1
            built_count += 1
        except Exception as error:  # one malformed account must not stop the audit batch
            failures[type(error).__name__] += 1
            failures[f"reason:{_failure_reason(current_file, error)}"] += 1

    return {
        "schemaVersion": 4,
        "versionKey": version_payload["key"],
        "generatedAt": iso_datetime(generated_at),
        "scannedCount": len(current_files),
        "builtCount": built_count,
        "failedCount": len(current_files) - built_count,
        "modeCounts": dict(sorted(modes.items())),
        "timePageCounts": dict(sorted(time_status.items())),
        "sourceSnapshotCounts": dict(sorted(sources.items())),
        "warningCounts": dict(sorted(warnings.items())),
        "failureTypeCounts": dict(sorted(failures.items())),
        "cacheStats": get_normalized_cache_stats(),
    }
