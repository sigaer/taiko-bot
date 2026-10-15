from __future__ import annotations


from sakura_taiko_core.models.calculation import V2RatingResult, FullScoreRef

from sakura_taiko_core.rating import v2 as domain_v2

from sakura_taiko_core.score import v2 as domain_score_v2

from .taiko_domain_adapter import identity_inputs

from functools import lru_cache

from typing import Any, Dict, List, Mapping, Optional, Tuple

from .b30_support.memory import bounded_memoize, budget, rating_result_bytes

from .taikob_v2_data import V2SongData, load_v2_snapshot

def _load_v2_song_map() -> Mapping[Tuple[int, int], V2SongData]:
    return load_v2_snapshot().song_map

def _calculate_v2_from_chart(chart, *, accuracy_per, bad_per):
    return domain_v2._calculate_v2_from_chart(chart, accuracy_per=accuracy_per, bad_per=bad_per,
        profile="v2-center-20261010")

@bounded_memoize("taiko.rating_v2", 100_000,
                 budget("TAIKO_V2_CACHE_MAX_BYTES", 64 * 1024**2),
                 weight=rating_result_bytes)
def _calculate_v2_from_chart_cached(
    chart: V2SongData,
    accuracy_per: float,
    bad_per: float,
) -> V2RatingResult:
    return _calculate_v2_from_chart(
        chart,
        accuracy_per=accuracy_per,
        bad_per=bad_per,
    )

def compute_all_v2_from_userdata_records(userdata_records, *, song_map=None):
    active_song_map = song_map if song_map is not None else _load_v2_song_map()
    default_ids, _ = identity_inputs()
    return domain_score_v2.compute_all_v2_from_userdata_records(userdata_records,
        song_map=active_song_map, profile="v2-center-20261010", default_ids=default_ids,
        calculate=_calculate_v2_from_chart_cached)

@lru_cache(maxsize=4)
def _calc_full_score_refs_for_snapshot(revision, songs):
    return domain_v2._calc_full_score_refs_for_snapshot(revision, songs, profile="v2-center-20261010")

def _calc_full_score_refs() -> Dict[str, FullScoreRef]:
    snapshot = load_v2_snapshot()
    return _calc_full_score_refs_for_snapshot(
        snapshot.revision,
        tuple(snapshot.song_map.values()),
    )

def aggregate_topN_value_v2(results, col, N):
    return domain_v2.aggregate_topN_value_v2(results, col, N,
        full_score_refs=_calc_full_score_refs() if N == 20 and results else None)

def compute_dim_topN_means_v2(results, N=20):
    return domain_v2.compute_dim_topN_means_v2(results, N,
        full_score_refs=_calc_full_score_refs() if N == 20 and results else None)
