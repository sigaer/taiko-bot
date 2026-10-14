from __future__ import annotations
import datetime
from typing import *
from pathlib import Path
from taiko_bot.history_adapter import iter_trend_history
from .b30_support.score_calculator import *
from .b30_support.score_calculator import _compute_results_from_userdata_records
TrendPoint=Tuple[datetime.datetime,Dict[str,float],float]
def _parse_center_snapshot_datetime(raw_value: str) -> datetime.datetime:
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError("empty snapshot timestamp")
    for candidate in (text, text.replace("_", " "), text.replace("Z", "+00:00")):
        try:
            return datetime.datetime.fromisoformat(candidate)
        except ValueError:
            continue
    raise ValueError(f"invalid snapshot timestamp: {text}")

def iter_user_snapshots(user_id, history_snapshots=None):
    if history_snapshots is None:
        raise ValueError("captured history required")
    if not history_snapshots or all(isinstance(item, dict) and item.get("historyFormat") == "raw-v1" for item in history_snapshots):
        yield from iter_trend_history(history_snapshots)
    else:
        # Existing explicit, caller-supplied center DTOs retain their old
        # already-prepared semantics; implicit reads use the versioned format.
        snapshots: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
        for item in history_snapshots:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            captured_at = str(item.get("capturedAt") or "").strip()
            try:
                dt = _parse_center_snapshot_datetime(captured_at)
            except ValueError:
                continue
            snapshots.append((dt, payload))
        snapshots.sort(key=lambda item: item[0])
        yield from snapshots

def _limit_trend_points_to_recent_days(
    points: List[TrendPoint], max_days: Optional[int]
) -> List[TrendPoint]:
    if not points or not max_days:
        return points

    latest_date = points[-1][0].date()
    cutoff_date = latest_date - datetime.timedelta(days=max_days - 1)
    return [point for point in points if point[0].date() >= cutoff_date]

def build_daily_rating_points(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_days: Optional[int] = 30,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> List[TrendPoint]:
    snapshots = iter_user_snapshots(user_id, history_snapshots=history_snapshots)

    cfg = load_rating_config(json_path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)

    points: List[TrendPoint] = []
    for dt, snapshot in snapshots:
        records = snapshot.get("songs", []) if isinstance(snapshot, dict) else snapshot
        if not records:
            continue
        try:
            results = _compute_results_from_userdata_records(records, cfg, const_table)
        except Exception as e:
            print(f"警告：跳过异常历史快照 {user_id} {dt}: {e}")
            continue
        if not results:
            continue
        dim_means = compute_dim_topN_means(results, N)
        overall = aggregate_topN_value(results, "AI_rating", N)
        points.append((dt, dim_means, overall))

    if not points:
        return []

    points.sort(key=lambda x: x[0])
    daily: Dict[datetime.date, TrendPoint] = {}
    for dt, dim_means, overall in points:
        daily[dt.date()] = (dt, dim_means, overall)

    daily_points = sorted(daily.values(), key=lambda x: x[0])
    return _limit_trend_points_to_recent_days(daily_points, max_days)

def observed_time():
    return str(datetime.datetime.now().replace(microsecond=0))
