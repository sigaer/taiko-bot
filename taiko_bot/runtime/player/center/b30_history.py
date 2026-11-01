"""Host preparation under the captured publication lease; no renderer I/O."""
from __future__ import annotations
import datetime, json
from functools import partial
from pathlib import Path
from typing import *
from taiko_store import PublicationError
from .b30_support.score_calculator import *
from .b30_support.score_calculator import _compute_results_from_userdata_records
from .b30_support import taikob_v2 as v2
from .snapshot_history import parse_snapshot_time
from .history_time import admit_history_snapshot, history_time_ceiling, is_future_history_time
TrendPoint = Tuple[datetime.datetime, Dict[str,float], float]
TrendImageStatus = str
def _song_key(song: Dict[str, Any]) -> tuple:
    return (song.get("song_no"), song.get("level"))

def _history_snapshot_inputs(view):
    ceiling = history_time_ceiling()
    timed = [(parse_snapshot_time(Path(name), fallback_mtime=lambda name=name: view.file_times("history/" + name)["mtime"]), name)
             for name in view.history_names()]
    for timestamp, name in sorted(timed):
        if is_future_history_time(timestamp, ceiling):
            continue
        try:
            snapshot = json.loads(view.history_raw(name).decode("utf-8"))
        except (OSError, UnicodeError):
            if view.manifest is not None:
                raise PublicationError("Canonical history is unavailable") from None
            continue
        except ValueError:
            # Invalid historical JSON remains excluded as in the old rebuild.
            continue
        snapshot = admit_history_snapshot(timestamp, snapshot, ceiling)
        if snapshot is not None:
            yield timestamp, snapshot

def _reconstruct_user_snapshots(inputs):
    snapshots: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
    current_profile: Dict[str, Any] = {}
    current_achievement: Dict[str, Any] = {}
    song_map: Dict[tuple, Dict[str, Any]] = {}
    has_base = False

    for dt, snapshot in inputs:
        meta = snapshot.get("_meta", {}) if isinstance(snapshot, dict) else {}
        is_full = bool(meta.get("full")) or (
            isinstance(snapshot, dict)
            and "songs" in snapshot
            and "profile" in snapshot
            and "achievement" in snapshot
            and not meta
        )

        if is_full:
            current_profile = snapshot.get("profile", {}) if isinstance(snapshot, dict) else {}
            current_achievement = snapshot.get("achievement", {}) if isinstance(snapshot, dict) else {}
            songs = snapshot.get("songs", []) if isinstance(snapshot, dict) else []
            song_map = {_song_key(s): s for s in songs}
            has_base = True
        else:
            if not has_base:
                continue
            if "profile" in snapshot:
                current_profile = snapshot.get("profile") or {}
            if "achievement" in snapshot:
                current_achievement = snapshot.get("achievement") or {}
            for s in snapshot.get("songs", []) or []:
                song_map[_song_key(s)] = s
            for key in snapshot.get("songs_removed", []) or []:
                song_map.pop(tuple(key), None)

        snapshots.append(
            (
                dt,
                {
                    "profile": current_profile,
                    "achievement": current_achievement,
                    "songs": list(song_map.values()),
                },
            )
        )

    return snapshots

def _limit_trend_points_to_recent_days(
    points: List[TrendPoint], max_days: Optional[int]
) -> List[TrendPoint]:
    ceiling = history_time_ceiling()
    points = [point for point in points if not is_future_history_time(point[0], ceiling)]
    if not points or not max_days:
        return points

    latest_date = points[-1][0].date()
    cutoff_date = latest_date - datetime.timedelta(days=max_days - 1)
    return [point for point in points if point[0].date() >= cutoff_date]

def _build_daily_rating_points_from_view(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_days: Optional[int] = 30,
    *,
    collapse_duplicate_versions: bool = False,
    archive_namespace: Optional[str] = None,
    aggregate_topn_value_fn: Optional[
        Callable[[List[RatingResult], str, int], float]
    ] = None,
    compute_dim_topn_means_fn: Optional[
        Callable[[List[RatingResult], int], Dict[str, float]]
    ] = None,
    results_from_records_fn: Optional[
        Callable[[List[Dict[str, Any]]], List[Any]]
    ] = None,
    _publication_store, snapshots,
) -> Tuple[TrendImageStatus, List[TrendPoint]]:
    from .b30_daily import archive, archive_path, needs_measurement, store_measurement
    ceiling = history_time_ceiling()
    snapshots = [(captured, admitted) for captured, payload in snapshots
                 if (admitted := admit_history_snapshot(captured, payload, ceiling)) is not None]
    custom = any((aggregate_topn_value_fn, compute_dim_topn_means_fn, results_from_records_fn))
    namespace = archive_namespace or (None if custom else f"v1-top{N}" + ("-merged" if collapse_duplicate_versions else ""))
    if not snapshots:
        if namespace and archive_path(user_id, namespace,userdata_dir=_publication_store.root).exists():
            with archive(user_id, namespace, userdata_dir=_publication_store.root, publication_store=_publication_store, writable=False) as days:
                frozen = sorted((datetime.datetime.fromisoformat(row["capturedAt"]).replace(tzinfo=None), row["dimensions"], row["rating"]) for row in days.values())
            if frozen:
                return "ok", _limit_trend_points_to_recent_days(frozen, max_days)
        return "no_snapshot", []

    latest_snapshot_date = snapshots[-1][0].date()
    cutoff_date = (
        latest_snapshot_date - datetime.timedelta(days=max_days - 1)
        if max_days
        else None
    )
    snapshots_by_date: Dict[datetime.date, Tuple[datetime.datetime, Dict[str, Any]]] = {}
    for dt, snapshot in snapshots:
        if cutoff_date is not None and dt.date() < cutoff_date:
            continue
        snapshots_by_date[dt.date()] = (dt, snapshot)
    snapshots = list(snapshots_by_date.values())

    aggregate_topn_value_fn = aggregate_topn_value_fn or aggregate_topN_value
    compute_dim_topn_means_fn = compute_dim_topn_means_fn or compute_dim_topN_means
    # Reading an archived value does not depend on today's algorithm inputs.
    cfg = const_table = None
    def default_results(records):
        nonlocal cfg, const_table
        if cfg is None:
            cfg = load_rating_config(json_path)
            const_table = build_const_table(cfg["const_table"]["const_to_score"])
        return _compute_results_from_userdata_records(records, cfg, const_table,
            collapse_duplicate_versions=collapse_duplicate_versions)
    results_from_records_fn = results_from_records_fn or default_results

    points: List[TrendPoint] = []
    from contextlib import nullcontext
    with archive(user_id, namespace, userdata_dir=_publication_store.root, publication_store=_publication_store) if namespace else nullcontext({}) as days:
        for captured, snapshot in snapshots:
            day = captured.date().isoformat()
            if needs_measurement(days, captured):
                records = snapshot.get("songs", []) if isinstance(snapshot, dict) else snapshot
                if not records:
                    continue
                results = results_from_records_fn(records)
                if not results:
                    continue
                store_measurement(days, captured, compute_dim_topn_means_fn(results, N),
                                  aggregate_topn_value_fn(results, "AI_rating", N), len(results),
                                  origin="historical-snapshot")
            row = days[day]
            points.append((datetime.datetime.fromisoformat(row["capturedAt"]).replace(tzinfo=None),
                           row["dimensions"], row["rating"]))
        if namespace:
            # Persisted days remain readable even after source snapshot retention.
            points = [(datetime.datetime.fromisoformat(row["capturedAt"]).replace(tzinfo=None),
                       row["dimensions"], row["rating"]) for row in days.values()]

    if not points:
        return "no_rating_data", []

    points.sort(key=lambda x: x[0])
    daily: Dict[datetime.date, TrendPoint] = {}
    for dt, dim_means, overall in points:
        daily[dt.date()] = (dt, dim_means, overall)

    daily_points = sorted(daily.values(), key=lambda x: x[0])
    return "ok", _limit_trend_points_to_recent_days(daily_points, max_days)

def capture(provider, view, store, command, current):
    N,args,use_v2,dynamic,dim=command
    try:
        observed=str(datetime.datetime.fromtimestamp(round(view.file_times('current')['ctime'])))
    except FileNotFoundError:
        observed=None
    provider.b30_observed_at=observed
    provider.b30_inputs=dict(observed_at=observed, history_snapshots=(), daily_points=[])
    from .b30_support.parsing import _parse_taikob_dim_arg
    v2_dim,unknown=_parse_taikob_dim_arg(args,v2.V2_TAIKOB_DIM_ALIASES)
    if use_v2 and not dynamic and not unknown and current is not None:
        from .taikob_v2_data import load_v2_snapshot
        provider.b30_snapshot=load_v2_snapshot()
    # Invalid v2 requests and single dimensions never prepare history.
    summary=(use_v2 and not dynamic and v2_dim is None and not unknown) or (not use_v2 and not args)
    if not summary or current is None:
        return ()
    timed=list(_history_snapshot_inputs(view))
    history=[dict(capturedAt=dt.isoformat(),payload=payload) for dt,payload in timed]
    snapshots=_reconstruct_user_snapshots(timed)
    provider.verify_initial()
    # The legacy B30 renderer supplies custom aggregation functions (including
    # v1 defaults), so its namespace is None. Preserve this distinction from
    # explicit daily trend commands, whose named archives persist measurements.
    _,points=_build_daily_rating_points_from_view(store.identity,N,
        json_path=str(__import__('taiko_bot.runtime.public.config',fromlist=['root']).root()/'songs/rating_structured_with_ids.json'),
        collapse_duplicate_versions=not use_v2,
        aggregate_topn_value_fn=partial(v2.aggregate_topN_value_v2,snapshot=provider.b30_snapshot) if use_v2 else aggregate_topN_value,
        compute_dim_topn_means_fn=partial(v2.compute_dim_topN_means_v2,snapshot=provider.b30_snapshot) if use_v2 else compute_dim_topN_means,
        results_from_records_fn=(lambda records:v2.compute_all_v2_from_userdata_records(records,song_map=provider.b30_snapshot.song_map)) if use_v2 else None,
        _publication_store=store,snapshots=snapshots)
    provider.b30_inputs.update(history_snapshots=history,daily_points=points)
    return history
