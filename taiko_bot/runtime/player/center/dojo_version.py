from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from .dojo_score import normalize_dojo_scores

DOJO_VERSIONS = {"2025", "2026"}
DOJO_TIMEZONE = ZoneInfo("Asia/Shanghai")
DOJO_2026_OPENED_AT = datetime(2026, 10, 14, tzinfo=DOJO_TIMEZONE)


def _version_at(value: Any) -> Optional[str]:
    try:
        stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=DOJO_TIMEZONE)
    return "2026" if stamp >= DOJO_2026_OPENED_AT else "2025"


def dojo_payload_version(dojo: Any) -> Optional[str]:
    """Resolve version before normalization, which discards source metadata."""
    if not isinstance(dojo, dict):
        return None
    if "version" in dojo:
        version = str(dojo["version"])
        return version if version in DOJO_VERSIONS else None

    # Legacy records predate version tagging. Use the actual rollout boundary,
    # not the calendar year or snapshot save time (which can contain old scores).
    rows = dojo.get("scores") or []
    if not rows:
        return "2025"
    versions = {
        _version_at(row.get("highscore_datetime"))
        for row in rows if isinstance(row, dict)
    }
    if versions == {None}:
        return "2025"
    return next(iter(versions)) if len(versions) == 1 else None


def normalize_wahlap_dojo_scores(payload: Any, *, fetched_at: Optional[datetime] = None) -> dict:
    """Tag a fresh current-version response, including an empty reset response."""
    dojo = normalize_dojo_scores(payload)
    dojo["version"] = _version_at(fetched_at or datetime.now(DOJO_TIMEZONE))
    return dojo


def normalize_versioned_dojo_scores(payload: Any) -> dict:
    dojo = normalize_dojo_scores(payload)
    dojo["version"] = dojo_payload_version(payload)
    return dojo
