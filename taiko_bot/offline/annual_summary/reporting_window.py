from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any, Dict

from .helpers import parse_date


@dataclass(frozen=True)
class ReportingWindow:
    start_date: date
    end_inclusive_date: date
    start_at: datetime
    end_exclusive_at: datetime
    calendar_days: int
    timezone: str
    revision: str

    def fingerprint_payload(self) -> Dict[str, Any]:
        return {
            "start": self.start_date.isoformat(),
            "endInclusive": self.end_inclusive_date.isoformat(),
            "endExclusive": self.end_exclusive_at.date().isoformat(),
            "calendarDays": self.calendar_days,
            "timezone": self.timezone,
            "revision": self.revision,
        }


def resolve_reporting_window(version: Dict[str, Any]) -> ReportingWindow:
    """Validate the reporting contract supplied by the Viewer.

    Annual timestamps are normalized to naive Asia/Shanghai wall-clock values by
    ``parse_datetime``. The window therefore uses naive wall-clock boundaries too.
    The generator intentionally owns no fallback dates: the Viewer contract is the
    single production source of truth.
    """
    timezone = str(version.get("timezone") or "").strip()
    if timezone != "Asia/Shanghai":
        raise ValueError("annual reporting timezone must be Asia/Shanghai")
    start_date = parse_date(version.get("startDate"))
    end_inclusive_date = parse_date(version.get("endDate"))
    if end_inclusive_date < start_date:
        raise ValueError("annual reporting end date precedes start date")
    start_at = datetime.combine(start_date, time.min)
    end_exclusive_at = datetime.combine(end_inclusive_date + timedelta(days=1), time.min)
    calendar_days = (end_inclusive_date - start_date).days + 1
    declared_end_exclusive = str(version.get("endExclusive") or "").strip()
    if declared_end_exclusive and declared_end_exclusive != end_exclusive_at.date().isoformat():
        raise ValueError("annual reporting endExclusive does not match endDate")
    declared_days = version.get("calendarDays")
    if declared_days is not None and int(declared_days) != calendar_days:
        raise ValueError("annual reporting calendarDays does not match date range")
    revision = str(version.get("reportRevision") or "").strip()
    if not revision:
        raise ValueError("annual report revision is required")
    return ReportingWindow(
        start_date=start_date,
        end_inclusive_date=end_inclusive_date,
        start_at=start_at,
        end_exclusive_at=end_exclusive_at,
        calendar_days=calendar_days,
        timezone=timezone,
        revision=revision,
    )
