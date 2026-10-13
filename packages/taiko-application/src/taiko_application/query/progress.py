from sakura_taiko_core.chart import progress_catalog as domain_progress
from sakura_taiko_core.score import progress as domain_summary
from .context import ProgressQueryContext


def _sort_items(context):
    return domain_progress._sort_items(context.items, catalog=context.catalog)


def _build_static_progress_title(context):
    return domain_progress._build_static_progress_title(
        context.value[0], context.value[1], context.value[2], catalog=context.catalog
    )


def available_pass_progress_keys(context):
    return domain_progress.available_pass_progress_keys(catalog=context.catalog)


def query_progress_items_by_pass_const(context):
    return domain_progress.query_progress_items_by_pass_const(
        context.value, catalog=context.catalog
    )


def available_const_progress_keys(context):
    return domain_progress.available_const_progress_keys(catalog=context.catalog)


def query_progress_items_by_const(context):
    return domain_progress.query_progress_items_by_const(
        context.value, catalog=context.catalog
    )


def load_star_progress_chart_keys(context):
    return domain_progress.load_star_progress_chart_keys(catalog=context.catalog)


def available_star_progress_values(context):
    return domain_progress.available_star_progress_values(catalog=context.catalog)


def query_progress_items_by_star(context):
    return domain_progress.query_progress_items_by_star(
        context.value, catalog=context.catalog
    )


def summarize_progress(context: ProgressQueryContext):
    return domain_summary.build_star_progress_summary(
        context.items,
        context.best_map,
        available_chart_keys=context.available_chart_keys,
    )
