"""Prepared catalog adapter to the existing, pinned Core 0.1.1 formulas."""

from sakura_taiko_core.chart import catalog
from sakura_taiko_core.score import calculation
from sakura_taiko_core.rating import v1
from sakura_taiko_core.dimension import v1 as dimension
from sakura_taiko_core.recommendation import candidates


class DaniRating:
    """Only fixed Core functions and caller-provided identity inputs, never host IO."""

    aggregate_topN_value = staticmethod(v1.aggregate_topN_value)
    calc_accuracy = staticmethod(v1.calc_accuracy)
    lookup_const_score = staticmethod(v1.lookup_const_score)
    calc_y = staticmethod(v1.calc_y)
    compute_P = staticmethod(v1.compute_P)
    compute_Q = staticmethod(v1.compute_Q)
    compute_AI = staticmethod(v1.compute_AI)
    compute_AD_AE_AF_AG = staticmethod(dimension.compute_AD_AE_AF_AG)
    compute_six_dims = staticmethod(dimension.compute_six_dims)
    _get_song_indicator_value = staticmethod(candidates._get_song_indicator_value)

    def __init__(self, default_ids, duplicate_groups):
        self.default_ids = default_ids
        self.duplicate_groups = duplicate_groups

    def _find_song_info_for_recommend_record(self, song_id, level, by_id, by_identity):
        return catalog._find_song_info_for_recommend_record(
            song_id, level, by_id, by_identity, self.default_ids
        )

    def _compute_results_from_userdata_records(
        self, records, cfg, const_table, *, collapse_duplicate_versions=False
    ):
        return calculation._compute_results_from_userdata_records(
            records,
            cfg,
            const_table,
            collapse_duplicate_versions=collapse_duplicate_versions,
            duplicate_groups=self.duplicate_groups,
            default_ids=self.default_ids,
        )


def build_rating_context(cfg, *, default_ids, duplicate_groups):
    songs = cfg["songs"]
    return {
        "module": DaniRating(default_ids, duplicate_groups),
        "cfg": cfg,
        "songs": songs,
        "const_table": v1.build_const_table(cfg["const_table"]["const_to_score"]),
        "idx_by_id_level": catalog._build_song_index_by_id_level(songs),
        "idx_by_identity": catalog._build_song_index_by_identity(songs, default_ids),
    }
