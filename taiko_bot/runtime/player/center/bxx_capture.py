"""Extra BXX detail, derived from the existing update-time calculation results."""
from taiko_bot.runtime.player.bxx_summary import measurement


def model(records, results, version, *, top20=None):
    from .b30_support.b30_render import _pick_top_entries
    if version == 'v1':
        from .b30_support import score_calculator as score
        from taiko_bot.public_catalog_cache import rating_resources
        from taiko_bot.runtime.paths import root
        path = root() / 'songs/rating_structured_with_ids.json'
        # The old daily v1 measurement is unmerged. BXX has always collapsed
        # duplicate versions; preserve both consumers' established policies.
        unmerged_results = results
        results = score.compute_all_from_userdata_records(records, json_path=path,
                                                          collapse_duplicate_versions=True)
        _, index, table = rating_resources(path)
        top = _pick_top_entries(records, index, table, 50, collapse_duplicate_versions=True)
        aggregate = score.aggregate_topN_value
    else:
        from . import taikob_v2 as score
        # Reuse exactly the results already computed for the daily values.
        ratings = {(row.song_id, row.level): float(row.AI_rating) for row in results}
        song_map = score._load_v2_song_map()
        def rating(entry):
            try:
                key = (int(entry.get('song_no', 0)), int(entry.get('level', 0)))
            except (ValueError, TypeError):
                return None
            value = ratings.get(key)
            if value is not None:
                return value
            # Aggregation deduplicates versions while the displayed v2 cards
            # retain them. Match the renderer for an unselected version too.
            result = score._build_result_from_entry(entry, song_map)
            return float(result.AI_rating) if result is not None else None
        top = _pick_top_entries(records, {}, [], 50, min_level=3,
                                entry_rating_getter=rating)
        aggregate = score.aggregate_topN_value_v2
    if version == 'v2':
        from sakura_taiko_core.rating.v2 import V2_COL_TO_ATTR, V2_DIM_COLUMNS
        attributes = {column: V2_COL_TO_ATTR[column] for column in (*V2_DIM_COLUMNS, 'AI_rating')}
        return measurement(results, top, aggregate, attributes=attributes, top20=top20)
    measured = measurement(results, top, aggregate)
    # The Viewer adapter explicitly retains its existing unmerged v1 policy.
    # Those numbers already exist in the daily calculation passed by the owner.
    measured['unmerged'] = measurement(unmerged_results,
        _pick_top_entries(records, index, table, 50), aggregate, top20=top20)
    return measured
