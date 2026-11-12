from __future__ import annotations


import datetime

from pathlib import Path

from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw

from .b30_single import _compute_rating_for_entry, _load_rating_resources

from .draw_dress import TITLE_FONT_PATH, draw_player_info, _crop_with_pad, _get_font, _get_font_by_path, build_dress_image

from .score_calculator import TREND_COLORS, TREND_DIM_COLUMNS, TREND_SHORT_LABELS, aggregate_topN_value, compute_all_from_userdata_records, compute_dim_topN_means
from .duplicate_versions import build_duplicate_song_groups

ROOT_DIR = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

ASSETS_DIR = ROOT_DIR / "assets"

TEMPLATE_DEFAULT = ASSETS_DIR / "templates" / "b30_template.png"

SONG_DB_DEFAULT = ROOT_DIR / "songs" / "song_data.json"

RATING_JSON_DEFAULT = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

from taiko_application.score import ScorePresentationContext, B30Renderer
from taiko_bot.runtime.player.prepared_rating import reusable_v1_results

from taiko_bot.public_catalog_cache import song_index as cached_song_index

def compute_b30_update_diff(current_top_entries, current_results, N, comparison,
                            aggregate_topn_value_fn, compute_dim_topn_means_fn):
    from ...bxx_summary import update_diff
    return update_diff(current_top_entries, compute_dim_topn_means_fn(current_results, N),
                       aggregate_topn_value_fn(current_results, "AI_rating", N), comparison)


def _growth_rows(results, N, comparison, aggregate, dimensions, labels, colors):
    from ...bxx_summary import growth
    values = growth(dimensions(results, N), aggregate(results, "AI_rating", N), comparison)
    if values is None:
        return []
    return [dict(category=name, label=labels.get(name, name), delta=value,
                 color=_hex_to_rgba(colors.get(name, "#4E79A7")))
            for name, value in values.items()]


def _format_update_date(observed_at) -> str:
    ts = observed_at
    if not ts:
        return "更新于未知"
    try:
        dt = datetime.datetime.fromisoformat(ts)
    except Exception:
        return f"更新于{ts[:10]}"
    return f"更新于{dt.strftime('%Y-%m-%d')}"

def _build_best_entry_map(
    entries: List[Dict[str, Any]],
) -> Dict[Tuple[int, int], Dict[str, Any]]:
    best: Dict[Tuple[int, int], Dict[str, Any]] = {}
    for entry in entries:
        try:
            song_no = int(entry.get("song_no", 0))
            level = int(entry.get("level", 0))
            score = int(entry.get("high_score", 0) or 0)
        except Exception:
            continue
        key = (song_no, level)
        if key not in best or score > int(best[key].get("high_score", 0) or 0):
            best[key] = entry
    return best

def _pick_top_entries(
    entries: List[Dict[str, Any]],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
    N: int,
    *,
    collapse_duplicate_versions: bool = False,
    entry_rating_getter: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    min_level: int = 4,
) -> List[Tuple[float, Dict[str, Any]]]:
    best_map = _build_best_entry_map(entries)
    rated: List[Tuple[float, Dict[str, Any]]] = []
    for entry in best_map.values():
        try:
            song_no = int(entry.get("song_no", 0))
            level = int(entry.get("level", 0))
        except Exception:
            song_no = 0
            level = 0
        if level < min_level:
            continue
        if entry_rating_getter is None:
            rating = _compute_rating_for_entry(entry, rating_index, const_table)
        else:
            rating = entry_rating_getter(entry)
        if rating is None or rating <= 0:
            continue
        rated.append((float(rating), entry))

    if collapse_duplicate_versions:
        pair_ids = {song_id: index for index, group in enumerate(build_duplicate_song_groups()) for song_id in group}
        deduped: Dict[Tuple[str, int, int], Tuple[float, Dict[str, Any]]] = {}
        for rating, entry in rated:
            try:
                song_no = int(entry.get("song_no", 0))
                level = int(entry.get("level", 0))
            except Exception:
                continue
            pair_id = pair_ids.get(song_no)
            identity = (
                ("pair", pair_id, level)
                if pair_id is not None
                else ("song", song_no, level)
            )
            prev = deduped.get(identity)
            if prev is None or rating > prev[0]:
                deduped[identity] = (rating, entry)
        rated = list(deduped.values())

    rated.sort(key=lambda x: x[0], reverse=True)
    return rated[:N]

def render_b30_image(
    user_id: int,
    N: int = 30,
    *,
    template_path: str | Path = TEMPLATE_DEFAULT,
    song_db_path: str | Path = SONG_DB_DEFAULT,
    assets_base: str | Path = ASSETS_DIR,
    rating_json_path: str | Path = RATING_JSON_DEFAULT,
    collapse_duplicate_versions: bool = False,
    aggregate_topn_value_fn: Callable[
        [List[Any], str, int], float
    ] = aggregate_topN_value,
    compute_dim_topn_means_fn: Callable[
        [List[Any], int], Dict[str, float]
    ] = compute_dim_topN_means,
    rating_label: Optional[str] = None,
    results_from_userdata_fn: Optional[Callable[[int], List[Any]]] = None,
    trend_dim_columns: Optional[List[str]] = None,
    trend_short_labels: Optional[Dict[str, str]] = None,
    trend_colors: Optional[Dict[str, str]] = None,
    entry_rating_getter: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    card_rating_resolver: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    min_level: int = 4,
    userdata, comparison, observed_at,
    precomputed_results=None,
    as_png_bytes=True,
) -> bytes:
    trend_dim_columns = trend_dim_columns or list(TREND_DIM_COLUMNS)
    trend_short_labels = trend_short_labels or TREND_SHORT_LABELS
    trend_colors = trend_colors or TREND_COLORS
    assets_base = Path(assets_base)
    template_path = Path(template_path)
    # Validate the required resource before acquiring score inputs.
    with Image.open(template_path):
        pass

    entries = userdata.get("songs", []) if isinstance(userdata, dict) else []

    song_index = cached_song_index(song_db_path)

    _, rating_index, const_table = _load_rating_resources(str(rating_json_path))
    top_entries = _pick_top_entries(
        entries,
        rating_index,
        const_table,
        N,
        collapse_duplicate_versions=collapse_duplicate_versions,
        entry_rating_getter=entry_rating_getter,
        min_level=min_level,
    )

    if precomputed_results is not None and reusable_v1_results(precomputed_results,profile='center',collapse=collapse_duplicate_versions,user_id=user_id,records=entries):
        results = precomputed_results
    elif results_from_userdata_fn is None:
        results = compute_all_from_userdata_records(
            entries,
            collapse_duplicate_versions=collapse_duplicate_versions,
        )
    else:
        results = results_from_userdata_fn(user_id)
    overall = aggregate_topn_value_fn(results, "AI_rating", N)
    new_keys, improved_rating_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        top_entries, results, N, comparison, aggregate_topn_value_fn, compute_dim_topn_means_fn)
    trend_rows = _growth_rows(results, N, comparison, aggregate_topn_value_fn,
                             compute_dim_topn_means_fn, trend_short_labels, trend_colors)
    dress_img = build_dress_image(userdata)
    info_canvas = Image.new("RGBA", (499, 1600), (0, 0, 0, 0))
    try:
        plate_box = draw_player_info(
            base=info_canvas,
            draw=ImageDraw.Draw(info_canvas),
            userdata=userdata,
            sx=1.0,
            sy=1.0,
            font=_get_font(16),
            stroke_width=2,
            fill=(255, 255, 255),
            stroke_fill=(0, 0, 0),
            offset_xy=(0, 0),
            title_font=_get_font_by_path(TITLE_FONT_PATH, 16),
        )
        title_img = _crop_with_pad(info_canvas, plate_box, pad=4)
        try:
            # The old single renderer uses the default rating source for card text,
            # independently of the source used to order this B30 request.
            card_ratings = {}
            for _, entry in top_entries[:N]:
                key = (
                    int(entry.get("song_no", 0) or 0),
                    int(entry.get("level", 0) or 0),
                )
                if not song_index.get(key[0]):
                    continue
                _, card_index, card_consts = _load_rating_resources(
                    str(RATING_JSON_DEFAULT)
                )
                override = (
                    card_rating_resolver(entry)
                    if card_rating_resolver is not None
                    else None
                )
                card_ratings[key] = (
                    (_compute_rating_for_entry(entry, card_index, card_consts) or 0.0)
                    if override is None
                    else float(override)
                )
            from .b30_single import FONT_TITLE_FALLBACK_PATHS

            context = ScorePresentationContext(
                assets_base=assets_base,
                layout_assets_base=ASSETS_DIR,
                template_path=template_path,
                title_font_candidates=tuple(FONT_TITLE_FALLBACK_PATHS),
                top_entries=top_entries,
                song_index=song_index,
                card_ratings=card_ratings,
                overall=overall,
                dim_means=compute_dim_topn_means_fn(results, N) if results else {},
                trend_rows=trend_rows,
                trend_columns=trend_dim_columns,
                trend_labels=trend_short_labels,
                update_diff=(new_keys, improved_rating_deltas, dim_deltas, total_delta),
                update_text=_format_update_date(observed_at),
                has_results=bool(results),
                count=N,
                rating_label=rating_label,
                dress_image=dress_img,
                title_image=title_img,
            )
            return B30Renderer(context).render(as_png_bytes=as_png_bytes)
        finally:
            title_img.close()
    finally:
        info_canvas.close()
        dress_img.close()

def _hex_to_rgba(hex_color, alpha=255):
    return B30Renderer(ScorePresentationContext(ASSETS_DIR))._hex_to_rgba(
        hex_color, alpha
    )
