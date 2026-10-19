from __future__ import annotations


import datetime

import json

from pathlib import Path

from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from PIL import Image, ImageDraw

from .b30_single import _compute_rating_for_entry, _load_rating_resources, build_song_index

from .draw_dress import TITLE_FONT_PATH, draw_player_info, _crop_with_pad, _get_font, _get_font_by_path, _load_previous_song_map, build_dress_image

from .score_calculator import TREND_COLORS, TREND_DIM_COLUMNS, TREND_SHORT_LABELS, _compute_results_from_userdata_records, aggregate_topN_value, compute_all_from_userdata_records, compute_dim_topN_means, load_rating_config
from .duplicate_versions import build_duplicate_song_groups

ROOT_DIR = __import__("taiko_bot.runtime.public.config", fromlist=["root"]).root()

ASSETS_DIR = ROOT_DIR / "assets"

TEMPLATE_DEFAULT = ASSETS_DIR / "templates" / "b30_template.png"

SONG_DB_DEFAULT = ROOT_DIR / "songs" / "song_data.json"

RATING_JSON_DEFAULT = ROOT_DIR / "songs" / "rating_structured_with_ids.json"

B30_DELTA_EPSILON = 1e-9

from taiko_application.score import ScorePresentationContext, B30Renderer

def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def _trend_series_value(
    point: Tuple[datetime.datetime, Dict[str, float], float], name: str
) -> float:
    if name == "综合Rating":
        return float(point[2])
    return float(point[1].get(name, 0.0))

def _load_trend_ranges_with_options(
    user_id: int,
    N: int,
    *,
    daily_points,
    max_days: int = 30,
    collapse_duplicate_versions: bool = False,
    aggregate_topn_value_fn: Callable[
        [List[Any], str, int], float
    ] = aggregate_topN_value,
    compute_dim_topn_means_fn: Callable[
        [List[Any], int], Dict[str, float]
    ] = compute_dim_topN_means,
    results_from_records_fn: Optional[
        Callable[[List[Dict[str, Any]]], List[Any]]
    ] = None,
    trend_dim_columns: Optional[List[str]] = None,
    trend_short_labels: Optional[Dict[str, str]] = None,
    trend_colors: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    trend_dim_columns = trend_dim_columns or list(TREND_DIM_COLUMNS)
    trend_short_labels = trend_short_labels or TREND_SHORT_LABELS
    trend_colors = trend_colors or TREND_COLORS
    if not daily_points:
        return []

    rows: List[Dict[str, Any]] = []
    for category in [*trend_dim_columns, "综合Rating"]:
        values = [_trend_series_value(point, category) for point in daily_points]
        if not values:
            continue
        vmin = min(values)
        vmax = max(values)
        rows.append(
            {
                "category": category,
                "label": trend_short_labels.get(category, category),
                "delta": max(0.0, vmax - vmin),
                "latest": values[-1],
                "color": _hex_to_rgba(trend_colors.get(category, "#4E79A7")),
            }
        )
    return rows

def _topn_entry_keys(
    top_entries: List[Tuple[float, Dict[str, Any]]],
) -> Set[Tuple[int, int]]:
    keys: Set[Tuple[int, int]] = set()
    for _, entry in top_entries:
        try:
            keys.add((int(entry.get("song_no", 0)), int(entry.get("level", 0))))
        except (TypeError, ValueError):
            continue
    return keys

def _entry_key(entry: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    try:
        return int(entry.get("song_no", 0)), int(entry.get("level", 0))
    except (TypeError, ValueError):
        return None

def compute_b30_update_diff(
    user_id: int,
    N: int,
    *,
    current_results: List[Any],
    rating_index: Dict[Tuple[int, int], dict],
    const_table: List[tuple],
    current_top_entries: List[Tuple[float, Dict[str, Any]]],
    collapse_duplicate_versions: bool = False,
    compute_dim_topn_means_fn: Callable[
        [List[Any], int], Dict[str, float]
    ] = compute_dim_topN_means,
    aggregate_topn_value_fn: Callable[
        [List[Any], str, int], float
    ] = aggregate_topN_value,
    results_from_records_fn: Optional[
        Callable[[List[Dict[str, Any]]], List[Any]]
    ] = None,
    trend_dim_columns: Optional[List[str]] = None,
    entry_rating_getter: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    min_level: int = 4,
    history_snapshots=(),
) -> Tuple[
    Set[Tuple[int, int]],
    Dict[Tuple[int, int], float],
    Dict[str, float],
    float,
]:
    trend_dim_columns = trend_dim_columns or list(TREND_DIM_COLUMNS)
    prev_map = _load_previous_song_map(user_id, history_snapshots=history_snapshots)
    if not prev_map:
        return set(), {}, {}, 0.0

    prev_top_entries = _pick_top_entries(
        list(prev_map.values()),
        rating_index,
        const_table,
        N,
        collapse_duplicate_versions=collapse_duplicate_versions,
        entry_rating_getter=entry_rating_getter,
        min_level=min_level,
    )
    prev_keys = _topn_entry_keys(prev_top_entries)
    curr_keys = _topn_entry_keys(current_top_entries)
    new_keys = curr_keys - prev_keys
    prev_rating_by_key = {
        key: float(rating)
        for rating, entry in prev_top_entries
        if (key := _entry_key(entry)) is not None
    }
    current_rating_by_key = {
        key: float(rating)
        for rating, entry in current_top_entries
        if (key := _entry_key(entry)) is not None
    }
    improved_rating_deltas = {
        key: current_rating_by_key[key] - prev_rating_by_key[key]
        for key in curr_keys & prev_keys
        if current_rating_by_key[key] - prev_rating_by_key[key] > B30_DELTA_EPSILON
    }

    if results_from_records_fn is not None:
        prev_results = results_from_records_fn(list(prev_map.values()))
    else:
        cfg = load_rating_config(RATING_JSON_DEFAULT)
        prev_results = _compute_results_from_userdata_records(
            list(prev_map.values()),
            cfg,
            const_table,
            collapse_duplicate_versions=collapse_duplicate_versions,
        )
    if not prev_results or not current_results:
        return new_keys, improved_rating_deltas, {}, 0.0

    prev_means = compute_dim_topn_means_fn(prev_results, N)
    curr_means = compute_dim_topn_means_fn(current_results, N)
    dim_deltas: Dict[str, float] = {}
    for category in trend_dim_columns:
        delta = float(curr_means.get(category, 0.0)) - float(
            prev_means.get(category, 0.0)
        )
        if abs(delta) > B30_DELTA_EPSILON:
            dim_deltas[category] = delta
    total_delta = float(
        aggregate_topn_value_fn(current_results, "AI_rating", N)
    ) - float(aggregate_topn_value_fn(prev_results, "AI_rating", N))
    if abs(total_delta) <= B30_DELTA_EPSILON:
        total_delta = 0.0
    return new_keys, improved_rating_deltas, dim_deltas, total_delta

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
    results_from_records_fn: Optional[
        Callable[[List[Dict[str, Any]]], List[Any]]
    ] = None,
    trend_dim_columns: Optional[List[str]] = None,
    trend_short_labels: Optional[Dict[str, str]] = None,
    trend_colors: Optional[Dict[str, str]] = None,
    entry_rating_getter: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    card_rating_resolver: Optional[Callable[[Dict[str, Any]], Optional[float]]] = None,
    min_level: int = 4,
    userdata, history_snapshots, daily_points, observed_at,
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

    song_db = _load_json(Path(song_db_path))
    song_index = build_song_index(song_db)

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

    if results_from_userdata_fn is None:
        results = compute_all_from_userdata_records(
            entries,
            collapse_duplicate_versions=collapse_duplicate_versions,
        )
    else:
        results = results_from_userdata_fn(user_id)
    overall = aggregate_topn_value_fn(results, "AI_rating", N)
    new_keys, improved_rating_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        user_id,
        N,
        current_results=results,
        rating_index=rating_index,
        const_table=const_table,
        current_top_entries=top_entries,
        collapse_duplicate_versions=collapse_duplicate_versions,
        compute_dim_topn_means_fn=compute_dim_topn_means_fn,
        aggregate_topn_value_fn=aggregate_topn_value_fn,
        results_from_records_fn=results_from_records_fn,
        trend_dim_columns=trend_dim_columns,
        entry_rating_getter=entry_rating_getter,
        min_level=min_level,
        history_snapshots=history_snapshots,
    )

    trend_rows = _load_trend_ranges_with_options(
        user_id,
        N,
        daily_points=daily_points,
        max_days=30,
        collapse_duplicate_versions=collapse_duplicate_versions,
        aggregate_topn_value_fn=aggregate_topn_value_fn,
        compute_dim_topn_means_fn=compute_dim_topn_means_fn,
        results_from_records_fn=results_from_records_fn,
        trend_dim_columns=trend_dim_columns,
        trend_short_labels=trend_short_labels,
        trend_colors=trend_colors,
    )
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
            return B30Renderer(context).render()
        finally:
            title_img.close()
    finally:
        info_canvas.close()
        dress_img.close()

def _hex_to_rgba(hex_color, alpha=255):
    return B30Renderer(ScorePresentationContext(ASSETS_DIR))._hex_to_rgba(
        hex_color, alpha
    )
