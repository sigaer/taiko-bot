from __future__ import annotations


from taiko_application.query import ProgressQueryContext, summarize_progress

from sakura_taiko_core.chart.progress_catalog import ProgressCatalogInputs

from sakura_taiko_core.score.progress import StarProgressSummary

from .progress_catalog import load_star_progress_chart_keys

def build_star_progress_summary(progress_items, best_map):
    return summarize_progress(
        ProgressQueryContext(
            ProgressCatalogInputs(),
            items=progress_items,
            best_map=best_map,
            available_chart_keys=load_star_progress_chart_keys(),
        )
    )
