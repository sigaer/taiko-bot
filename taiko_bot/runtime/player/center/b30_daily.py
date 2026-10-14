"""Durable daily values, independent of later model/config revisions.

A newer snapshot can replace today's representative. Past days and an already
measured snapshot are immutable. Namespaces separate v1/v2, top-N and merging.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
from contextlib import contextmanager
from pathlib import Path
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")
ROOT = Path("/home/sigaer/taiko/userdata")
MAX_BYTES = 8 * 1024 * 1024


def archive_path(user_id, namespace="v1-top20", *, userdata_dir=None):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(user_id)) or not re.fullmatch(r"[a-z0-9-]+", namespace):
        raise ValueError("Invalid daily ability identity")
    root = Path(userdata_dir) if userdata_dir is not None else Path(os.environ.get("TAIKO_USERDATA_DIR", ROOT))
    return root / str(user_id) / f"daily-ability-{namespace}.json"


@contextmanager
def archive(user_id, namespace="v1-top20", *, userdata_dir=None, publication_store=None, writable=True):
    from taiko_store import PublicationStore, PublicationError
    from taiko_store.daily import daily_archive
    path = archive_path(user_id, namespace, userdata_dir=userdata_dir)
    if publication_store is not None:
        publication_store._require_lock()
        if publication_store.identity != str(user_id) or publication_store.root != path.parent.parent.absolute():
            raise PublicationError("Daily Source does not match its lease")
        with daily_archive(publication_store, namespace, writable=writable) as days:
            yield days
    else:
        store = PublicationStore(path.parent.parent, str(user_id))
        with store.shared():
            with daily_archive(store, namespace, writable=writable) as days:
                yield days


def local_time(captured):
    return captured.replace(tzinfo=SHANGHAI) if captured.tzinfo is None else captured.astimezone(SHANGHAI)


def needs_measurement(days, captured, today=None):
    captured = local_time(captured)
    day = captured.date().isoformat()
    old = days.get(day)
    today = today or dt.datetime.now(SHANGHAI).date()
    if old is None:
        return True
    return captured.date() == today and captured.isoformat() > old["capturedAt"]


def store_measurement(days, captured, dimensions, rating, sample_count, *, origin="snapshot", today=None):
    if not needs_measurement(days, captured, today):
        return days[local_time(captured).date().isoformat()]
    if not dimensions or not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in [rating, *dimensions.values()]):
        raise ValueError("Invalid daily ability values")
    captured = local_time(captured)
    row = {"capturedAt": captured.isoformat(), "dimensions": dimensions, "rating": rating,
           "sampleCount": sample_count, "origin": origin,
           "computedAt": dt.datetime.now(SHANGHAI).isoformat()}
    days[captured.date().isoformat()] = row
    return row
