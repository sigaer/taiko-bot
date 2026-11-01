"""Exclude future evidence from read projections without rewriting stored history."""
from __future__ import annotations

import datetime as dt
import re
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
FUTURE_SKEW = dt.timedelta(minutes=5)


def history_time_ceiling(now=None):
    now = now or dt.datetime.now(SHANGHAI)
    return local_history_time(now) + FUTURE_SKEW


def local_history_time(value):
    if isinstance(value, str):
        compact = re.fullmatch(r"(\d{8})_(\d{6})(?:_(\d{1,6}))?", value)
        if compact:
            value = dt.datetime.strptime(value, "%Y%m%d_%H%M%S" + ("_%f" if compact[3] else ""))
        else:
            value = dt.datetime.fromisoformat(value)
    return value.replace(tzinfo=SHANGHAI) if value.tzinfo is None else value.astimezone(SHANGHAI)


def is_future_history_time(value, ceiling):
    if not value:
        return False
    try:
        return local_history_time(value) > ceiling
    except (ValueError, TypeError, AttributeError, OverflowError):
        # Missing/legacy non-date values keep their existing interpretation.
        return False


def admit_history_snapshot(timestamp, payload, ceiling):
    if is_future_history_time(timestamp, ceiling):
        return None
    meta = payload.get("_meta") or {}
    if any(is_future_history_time(meta.get(field), ceiling)
           for field in ("observed_at", "observedAt", "synced_at", "ts")):
        return None
    songs = payload.get("songs") or []
    admitted = [song for song in songs if not any(
        is_future_history_time(song.get(field), ceiling)
        for field in ("update_datetime", "highscore_datetime")
    )]
    return payload if len(admitted) == len(songs) else {**payload, "songs": admitted}
