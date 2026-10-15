from __future__ import annotations
from taiko_bot.runtime.paths import root as _runtime_root




import datetime as dt

import math

import os

import re

from contextlib import contextmanager

from pathlib import Path

from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")

ROOT = Path(str(_runtime_root() / 'userdata'))

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

def capture_snapshot_v1(user_id, songs, captured, *, userdata_dir=None, publication_store=None):
    """Called by the authoritative snapshot writer, never by a chart render."""
    from . import score_calculator as score
    with archive(user_id, userdata_dir=userdata_dir, publication_store=publication_store) as days:
        if not needs_measurement(days, captured):
            return
        cfg = score.load_rating_config("./songs/rating_structured_with_ids.json")
        table = score.build_const_table(cfg["const_table"]["const_to_score"])
        results = score._compute_results_from_userdata_records(songs, cfg, table, collapse_duplicate_versions=False)
        if results:
            store_measurement(days, captured, score.compute_dim_topN_means(results, 20),
                              score.aggregate_topN_value(results, "AI_rating", 20), len(results))

def capture_snapshot(user_id, songs, captured, *, userdata_dir=None, publication_store=None):
    if publication_store is None:
        from taiko_store import PublicationStore
        root = archive_path(user_id, userdata_dir=userdata_dir).parent.parent
        store = PublicationStore(root, str(user_id))
        with store.shared():
            return capture_snapshot(user_id, songs, captured, userdata_dir=store.root, publication_store=store)
    capture_snapshot_v1(user_id, songs, captured, userdata_dir=userdata_dir, publication_store=publication_store)
    # The bot defaults to v2; keep its distinct dimensions in a separate archive.
    from . import taikob_v2 as v2
    with archive(user_id, "v2-top20", userdata_dir=userdata_dir, publication_store=publication_store) as days:
        if not needs_measurement(days, captured):
            return
        results = v2.compute_all_v2_from_userdata_records(songs)
        if results:
            store_measurement(days, captured, v2.compute_dim_topN_means_v2(results, 20),
                              v2.aggregate_topN_value_v2(results, "AI_rating", 20), len(results))
