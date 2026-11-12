"""Bounded update measurements for BXX. Never accepts or replays history.

The existing daily-ability archive owns this derived input. Keep the previous
update and the first measurement of each of the last 30 calendar days. Top 50 values
per dimension support every accepted N; Top20 keeps the model's compensation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo
import json
import math

FIELD = "bxx"
SCHEMA = 1
MAX_TOP = 50
MAX_BYTES = 1024 * 1024
DIMENSIONS = ("大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理")
COLUMNS = (*DIMENSIONS, "AI_rating")
ATTRIBUTES = ("big_song", "stamina", "speed", "accuracy_power", "rhythm", "complex_proc", "AI_rating")


def timestamp(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    return value.replace(tzinfo=ZoneInfo('Asia/Shanghai')) if value.tzinfo is None else value


def score_digest(records):
    return sha256(json.dumps(records, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def measurement(results, top_entries, aggregate, *, attributes=None, top20=None):
    """Retain numerical measurements and chart identities, never raw scores."""
    columns = {}
    attributes = attributes or dict(zip(COLUMNS, ATTRIBUTES))
    for column, attribute in attributes.items():
        values = sorted((float(getattr(row, attribute)) for row in results
                         if getattr(row, attribute, None) is not None), reverse=True)[:MAX_TOP]
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Nonfinite BXX measurement")
        columns[column] = values
    return {
        "columns": columns,
        "top20": top20 if top20 is not None else {
            column: float(aggregate(results, column, 20)) for column in columns},
        "top": [[int(entry["song_no"]), int(entry["level"]), float(rating)]
                for rating, entry in top_entries[:MAX_TOP]],
    }


def statistics(model, count):
    if not 1 <= count <= MAX_TOP:
        raise ValueError("Invalid BXX count")
    if count == 20:
        values = model["top20"]
    else:
        values = {}
        for column in model['columns']:
            top = model["columns"][column][:count]
            values[column] = sum(top) / len(top) if top else 0.0
    return {"rating": values["AI_rating"],
            "dimensions": {column: value for column, value in values.items() if column != 'AI_rating'},
            "top": model["top"][:count]}


def snapshot(row):
    if row is None:
        return None
    return {"capturedAt": row["capturedAt"], "rating": row["rating"],
            "dimensions": row["dimensions"], "model": row.get(FIELD, {}).get("model"),
            "context": row.get(FIELD, {}).get("context")}


def latest(days, captured):
    candidates = [row for row in days.values() if timestamp(row["capturedAt"]) <= timestamp(captured)]
    return max(candidates, key=lambda row: timestamp(row["capturedAt"])) if candidates else None


def attach(days, row, *, previous, first, records, model, context=None, source_ref=None):
    """Add only missing per-update/TopN information to the existing daily row."""
    row[FIELD] = {"schema": SCHEMA, "scores": score_digest(records), "model": model,
                  "previous": snapshot(previous), "context": context, "source": source_ref}
    row[FIELD]['first'] = first if first and first.get('context') == context else snapshot(row)
    # Numerical long-term daily archives remain intact. Bound only the extra
    # BXX detail; both previous and first are flat snapshots without recursion.
    cutoff = (datetime.fromisoformat(row["capturedAt"]).date() - timedelta(days=29)).isoformat()
    for day, old in days.items():
        if day < cutoff:
            old.pop(FIELD, None)
    if len(json.dumps(row[FIELD], ensure_ascii=False, allow_nan=False).encode()) > MAX_BYTES:
        raise ValueError("BXX summary byte limit exceeded")


def comparison(days, *, records, version, count, captured, context=None, source_ref=None):
    """Read existing measurements; missing detail never triggers reconstruction.

    Legacy v2 Top20 rows already contain precisely the requested numbers.
    Legacy v1 daily rows used a different duplicate policy, so only their new
    explicitly measured merged model is suitable for BXX.
    """
    captured = timestamp(captured)
    cutoff = (captured.date() - timedelta(days=29)).isoformat()
    end = captured.date().isoformat()
    def select(row):
        if not isinstance(row, dict):
            return None
        saved_context = row.get('context', row.get(FIELD, {}).get('context'))
        if saved_context != context:
            return None
        model = row.get("model") or row.get(FIELD, {}).get("model")
        if model is not None and version == 'v1-unmerged':
            model = model.get('unmerged')
        if model is not None:
            return statistics(model, count)
        if version in ('v2', 'v1-unmerged') and count == 20:
            return {"rating": row["rating"], "dimensions": row["dimensions"], "top": None}
        return None
    baseline = None
    for day, row in sorted(days.items()):
        if cutoff <= day <= end and timestamp(row["capturedAt"]) <= captured:
            first = row.get(FIELD, {}).get("first") or row
            baseline = select(first) or select(row)
            if baseline is not None:
                break
    current = latest(days, captured)
    detail = current.get(FIELD, {}) if current else {}
    previous = None
    if (detail.get("schema") == SCHEMA and detail.get("scores") == score_digest(records)
            and (source_ref is None or detail.get('source') == source_ref)):
        previous = select(detail.get("previous"))
    return {"previous": previous, "baseline": baseline}


def update_diff(current_top, current_dimensions, current_rating, prepared, *, epsilon=1e-9):
    previous = prepared.get("previous") if prepared else None
    if previous is None:
        return set(), {}, {}, 0.0
    old_top = {(int(sid), int(level)): float(value) for sid, level, value in (previous["top"] or [])}
    new_top = {(int(entry["song_no"]), int(entry["level"])): float(value) for value, entry in current_top}
    new_keys = new_top.keys() - old_top.keys() if previous["top"] is not None else set()
    improved = {key: value - old_top[key] for key, value in new_top.items()
                if key in old_top and value - old_top[key] > epsilon}
    dimensions = {key: value - previous["dimensions"].get(key, 0.0)
                  for key, value in current_dimensions.items()
                  if abs(value - previous["dimensions"].get(key, 0.0)) > epsilon}
    delta = current_rating - previous["rating"]
    return set(new_keys), improved, dimensions, delta if abs(delta) > epsilon else 0.0


def growth(current_dimensions, current_rating, prepared):
    baseline = prepared.get("baseline") if prepared else None
    if baseline is None:
        return None
    values = {key: value - baseline["dimensions"].get(key, 0.0)
              for key, value in current_dimensions.items()}
    values["综合Rating"] = current_rating - baseline["rating"]
    return values
