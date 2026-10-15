from __future__ import annotations

import gc
import json
import os
import time
from pathlib import Path
from typing import Any


_STARTED_AT = time.monotonic()
_PROFILE_PATH = str(os.getenv("TAIKO_ANNUAL_PROFILE_PATH") or "").strip()
_TRACE_MEMORY = os.getenv("TAIKO_ANNUAL_PROFILE_TRACEMALLOC") == "1"
_GC_COUNTS = os.getenv("TAIKO_ANNUAL_PROFILE_GC") == "1"
_CURRENT: dict[str, int] = {
    "rawPayloadRetainedCount": 0,
    "rawPayloadEstimatedBytes": 0,
    "rebuiltStateCount": 0,
    "eventCount": 0,
    "signatureCount": 0,
    "signatureBytes": 0,
}
_PEAKS: dict[str, int] = {
    "peakRawPayloadsAlive": 0,
    "peakRawPayloadEstimatedBytes": 0,
    "peakHistoryEntriesAlive": 0,
    "peakEventCount": 0,
    "peakSignatureCount": 0,
    "peakSignatureBytes": 0,
}

if _PROFILE_PATH and _TRACE_MEMORY:
    import tracemalloc

    tracemalloc.start(1)


def profiling_enabled() -> bool:
    return bool(_PROFILE_PATH)


def observe_profile_objects(
    *,
    raw_payload_count: int | None = None,
    raw_payload_estimated_bytes: int | None = None,
    rebuilt_state_count: int | None = None,
    event_count: int | None = None,
    signature_count: int | None = None,
    signature_bytes: int | None = None,
) -> None:
    if not _PROFILE_PATH:
        return
    updates = {
        "rawPayloadRetainedCount": raw_payload_count,
        "rawPayloadEstimatedBytes": raw_payload_estimated_bytes,
        "rebuiltStateCount": rebuilt_state_count,
        "eventCount": event_count,
        "signatureCount": signature_count,
        "signatureBytes": signature_bytes,
    }
    for key, value in updates.items():
        if value is not None:
            _CURRENT[key] = max(0, int(value))
    _PEAKS["peakRawPayloadsAlive"] = max(
        _PEAKS["peakRawPayloadsAlive"], _CURRENT["rawPayloadRetainedCount"]
    )
    _PEAKS["peakRawPayloadEstimatedBytes"] = max(
        _PEAKS["peakRawPayloadEstimatedBytes"], _CURRENT["rawPayloadEstimatedBytes"]
    )
    _PEAKS["peakHistoryEntriesAlive"] = max(
        _PEAKS["peakHistoryEntriesAlive"], _CURRENT["rebuiltStateCount"]
    )
    _PEAKS["peakEventCount"] = max(_PEAKS["peakEventCount"], _CURRENT["eventCount"])
    _PEAKS["peakSignatureCount"] = max(
        _PEAKS["peakSignatureCount"], _CURRENT["signatureCount"]
    )
    _PEAKS["peakSignatureBytes"] = max(
        _PEAKS["peakSignatureBytes"], _CURRENT["signatureBytes"]
    )


def _proc_fields(path: Path) -> dict[str, int]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, int] = {}
    for line in lines:
        if ":" not in line:
            continue
        key, raw = line.split(":", 1)
        first = raw.strip().split(maxsplit=1)[0] if raw.strip() else ""
        try:
            values[key] = int(first)
        except ValueError:
            continue
    return values


def mark_profile_stage(stage: str, **detail: Any) -> None:
    if not _PROFILE_PATH:
        return
    status = _proc_fields(Path("/proc/self/status"))
    rollup = _proc_fields(Path("/proc/self/smaps_rollup"))
    traced_current = traced_peak = None
    if _TRACE_MEMORY:
        import tracemalloc

        traced_current, traced_peak = tracemalloc.get_traced_memory()
    record: dict[str, Any] = {
        "stage": stage,
        "elapsedSeconds": round(time.monotonic() - _STARTED_AT, 6),
        "rssKiB": status.get("VmRSS", 0),
        "pssKiB": rollup.get("Pss", 0),
        "rssAnonKiB": status.get("RssAnon", 0),
        "vmSwapKiB": status.get("VmSwap", 0),
        "tracemallocCurrentBytes": traced_current,
        "tracemallocPeakBytes": traced_peak,
        **_CURRENT,
        **_PEAKS,
        **detail,
    }
    if _GC_COUNTS:
        record["gcTrackedObjectCount"] = len(gc.get_objects())
    path = Path(_PROFILE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.chmod(path, 0o600)


mark_profile_stage("process_start")
