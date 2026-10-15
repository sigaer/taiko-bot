"""Prepare named daily archives while holding the authorized source lease."""
from functools import partial
from .b30_history import (
    _history_snapshot_inputs, _reconstruct_user_snapshots,
    _build_daily_rating_points_from_view,
)
from .b30_support import taikob_v2 as v2
from .trend_support.score_calculator import _build_playcount_rating_points_with_status
from ...public.config import root


def capture(provider, view, store, command):
    play, version, options, _ = command
    timed = list(_history_snapshot_inputs(view))
    snapshots = _reconstruct_user_snapshots(timed)
    calculation = {}
    if version == "v2":
        from .taikob_v2_data import load_v2_snapshot
        snapshot = load_v2_snapshot()
        calculation = dict(
            aggregate_topn_value_fn=partial(v2.aggregate_topN_value_v2, snapshot=snapshot),
            compute_dim_topn_means_fn=partial(v2.compute_dim_topN_means_v2, snapshot=snapshot),
            results_from_records_fn=partial(v2.compute_all_v2_from_userdata_records, song_map=snapshot.song_map),
        )
    provider.verify_initial()
    common = dict(N=options["N"], json_path=str(root()/"songs/rating_structured_with_ids.json"),
                  snapshots=snapshots, **calculation)
    if play:
        points = _build_playcount_rating_points_with_status(
            store.identity, max_points=options["max_points"], **common)
    else:
        points = _build_daily_rating_points_from_view(
            store.identity, max_days=options["max_days"],
            archive_namespace=f"{version}-top{options['N']}",
            _publication_store=store, **common)
    provider.trend_points = points
    return tuple(dict(capturedAt=dt.isoformat(), payload=payload) for dt,payload in timed)
