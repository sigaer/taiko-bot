from __future__ import annotations


from sakura_taiko_core.score import progress as _progress

from .progress_catalog import load_active_song_ids

StarProgressSummary = _progress.StarProgressSummary

def build_star_progress_summary(progress_items, best_map):
    return _progress.build_star_progress_summary(progress_items, best_map,
        active_song_ids=load_active_song_ids())
