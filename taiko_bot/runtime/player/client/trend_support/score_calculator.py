from __future__ import annotations


from sakura_taiko_core.rating import v1 as _v1


import json

from pathlib import Path

from typing import Dict, Iterable, List, Optional, Any, Tuple

import matplotlib.pyplot as plt

import numpy as np

from io import BytesIO

from matplotlib import font_manager

import datetime

from taiko_bot.settings import get_settings

from taiko_bot.history_adapter import iter_trend_history




TREND_DIM_COLUMNS = ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"]

TREND_SHORT_LABELS = {
    "大歌力": "大歌",
    "体力": "体力",
    "高速处理": "高速",
    "精度力": "精度",
    "节奏处理": "节奏",
    "复合处理": "复合",
    "综合Rating": "综合",
}

TREND_COLORS = {
    "大歌力": "#4E79A7",
    "体力": "#F28E2B",
    "高速处理": "#E15759",
    "精度力": "#76B7B2",
    "节奏处理": "#59A14F",
    "复合处理": "#EDC949",
    "综合Rating": "#111111",
}

TrendPoint = Tuple[datetime.datetime, Dict[str, float], float]

PlayTrendPoint = Tuple[int, Dict[str, float], float]

def _trend_series_value(
    point: TrendPoint | PlayTrendPoint, series_name: str
) -> float:
    if series_name == "综合Rating":
        return float(point[2])
    return float(point[1].get(series_name, 0.0))

def _is_same_trend_point(
    prev_point: TrendPoint | PlayTrendPoint,
    current_point: TrendPoint | PlayTrendPoint,
    displayed_series: List[str],
) -> bool:
    for series_name in displayed_series:
        if (
            abs(
                _trend_series_value(prev_point, series_name)
                - _trend_series_value(current_point, series_name)
            )
            > 1e-9
        ):
            return False
    return True

def _filter_unchanged_trend_points(
    points: List[TrendPoint] | List[PlayTrendPoint],
    displayed_series: List[str],
) -> List[TrendPoint] | List[PlayTrendPoint]:
    if len(points) <= 1:
        return points

    filtered = [points[0]]
    for idx in range(1, len(points)):
        current_point = points[idx]
        prev_raw_point = points[idx - 1]
        if _is_same_trend_point(prev_raw_point, current_point, displayed_series):
            continue
        filtered.append(current_point)
    return filtered

def _smooth_playtrend_rate_series(
    x: np.ndarray,
    y: np.ndarray,
    *,
    dense_points: int = 200,
) -> Tuple[np.ndarray, np.ndarray]:
    """按曲数对维度值求导，并做滑动平均与插值以绘制平滑速率曲线。"""
    x_arr = np.asarray(x, dtype=float)
    y_arr = np.asarray(y, dtype=float)
    if x_arr.size < 2:
        return x_arr, np.zeros_like(x_arr, dtype=float)

    rates = np.gradient(y_arr, x_arr)
    window = min(5, x_arr.size if x_arr.size % 2 == 1 else x_arr.size - 1)
    if window >= 3:
        kernel = np.ones(window, dtype=float) / window
        rates = np.convolve(rates, kernel, mode="same")

    x_dense = np.linspace(x_arr[0], x_arr[-1], max(dense_points, x_arr.size * 4))
    rates_dense = np.interp(x_dense, x_arr, rates)
    return x_dense, rates_dense

def _calc_playtrend_rate_ylim(values: List[float]) -> Tuple[float, float]:
    if not values:
        return -0.05, 0.05
    vmin = min(values)
    vmax = max(values)
    pad = max(0.002, (vmax - vmin) * 0.15) if vmax > vmin else 0.01
    return vmin - pad, vmax + pad

def _apply_playcount_xticks(
    ax,
    x_values: List[float],
    labels: List[str],
    fp: font_manager.FontProperties,
) -> None:
    max_labels = 8
    step = max(1, len(labels) // max_labels)
    tick_idx = list(range(0, len(labels), step))
    if tick_idx and tick_idx[-1] != len(labels) - 1:
        tick_idx.append(len(labels) - 1)
    ax.set_xticks([x_values[i] for i in tick_idx])
    ax.set_xticklabels(
        [labels[i] for i in tick_idx],
        rotation=35,
        ha="right",
        fontproperties=fp,
    )


build_const_table = _v1.build_const_table

aggregate_topN_value = _v1.aggregate_topN_value

compute_dim_topN_means = _v1.compute_dim_topN_means

def _parse_center_snapshot_datetime(raw_value: str) -> datetime.datetime:
    text = str(raw_value or "").strip()
    if not text:
        raise ValueError("empty snapshot timestamp")
    for candidate in (text, text.replace("_", " "), text.replace("Z", "+00:00")):
        try:
            return datetime.datetime.fromisoformat(candidate)
        except ValueError:
            continue
    raise ValueError(f"invalid snapshot timestamp: {text}")

def iter_user_snapshots(user_id, history_snapshots=None):
    if history_snapshots is None:
        raise ValueError("captured history required")
    if not history_snapshots or all(isinstance(item, dict) and item.get("historyFormat") == "raw-v1" for item in history_snapshots):
        yield from iter_trend_history(history_snapshots)
    else:
        # Existing explicit, caller-supplied center DTOs retain their old
        # already-prepared semantics; implicit reads use the versioned format.
        snapshots: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
        for item in history_snapshots:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload")
            if not isinstance(payload, dict):
                continue
            captured_at = str(item.get("capturedAt") or "").strip()
            try:
                dt = _parse_center_snapshot_datetime(captured_at)
            except ValueError:
                continue
            snapshots.append((dt, payload))
        snapshots.sort(key=lambda item: item[0])
        yield from snapshots

def _limit_trend_points_to_recent_days(
    points: List[TrendPoint], max_days: Optional[int]
) -> List[TrendPoint]:
    if not points or not max_days:
        return points

    latest_date = points[-1][0].date()
    cutoff_date = latest_date - datetime.timedelta(days=max_days - 1)
    return [point for point in points if point[0].date() >= cutoff_date]

def build_daily_rating_points(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_days: Optional[int] = 30,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> List[TrendPoint]:
    snapshots = iter_user_snapshots(user_id, history_snapshots=history_snapshots)

    cfg = load_rating_config(json_path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)

    points: List[TrendPoint] = []
    for dt, snapshot in snapshots:
        records = snapshot.get("songs", []) if isinstance(snapshot, dict) else snapshot
        if not records:
            continue
        try:
            results = _compute_results_from_userdata_records(records, cfg, const_table)
        except Exception as e:
            print(f"警告：跳过异常历史快照 {user_id} {dt}: {e}")
            continue
        if not results:
            continue
        dim_means = compute_dim_topN_means(results, N)
        overall = aggregate_topN_value(results, "AI_rating", N)
        points.append((dt, dim_means, overall))

    if not points:
        return []

    points.sort(key=lambda x: x[0])
    daily: Dict[datetime.date, TrendPoint] = {}
    for dt, dim_means, overall in points:
        daily[dt.date()] = (dt, dim_means, overall)

    daily_points = sorted(daily.values(), key=lambda x: x[0])
    return _limit_trend_points_to_recent_days(daily_points, max_days)

def _sum_total_stage_count(songs: Iterable[Dict[str, Any]]) -> int:
    total = 0
    for song in songs:
        if not isinstance(song, dict):
            continue
        try:
            total += int(song.get("stage_cnt") or 0)
        except (TypeError, ValueError):
            continue
    return total

def build_playcount_rating_points(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_points: Optional[int] = 80,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> List[PlayTrendPoint]:
    snapshots = iter_user_snapshots(user_id, history_snapshots=history_snapshots)

    cfg = load_rating_config(json_path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)

    by_play_count: Dict[int, PlayTrendPoint] = {}
    last_play_count = -1

    for dt, snapshot in snapshots:
        records = snapshot.get("songs", []) if isinstance(snapshot, dict) else snapshot
        if not records:
            continue
        play_count = _sum_total_stage_count(records)
        if play_count < last_play_count:
            print(
                f"警告：跳过曲数回退快照 {user_id} {dt}: "
                f"{play_count} < {last_play_count}"
            )
            continue
        last_play_count = play_count
        try:
            results = _compute_results_from_userdata_records(records, cfg, const_table)
        except Exception as e:
            print(f"警告：跳过异常历史快照 {user_id} {dt}: {e}")
            continue
        if not results:
            continue
        dim_means = compute_dim_topN_means(results, N)
        overall = aggregate_topN_value(results, "AI_rating", N)
        by_play_count[play_count] = (play_count, dim_means, overall)

    points = sorted(by_play_count.values(), key=lambda x: x[0])
    if max_points and len(points) > max_points:
        points = points[-max_points:]
    return points

def generate_rating_playcount_image(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_points: Optional[int] = 80,
    bar_mode: bool = False,
    show_all: bool = False,
    selected_dim: Optional[str] = None,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> Optional[BytesIO]:
    """
    读取用户历史快照，按累计总曲数聚合后生成六维/综合或单维走势图及上涨速率图。
    """
    play_points = build_playcount_rating_points(
        user_id,
        N=N,
        json_path=json_path,
        max_points=max_points,
        history_snapshots=history_snapshots,
    )
    if not play_points:
        return None

    dims = TREND_DIM_COLUMNS
    supported_series = dims + ["综合Rating"]
    if selected_dim and selected_dim not in supported_series:
        raise ValueError(f"不支持的趋势维度：{selected_dim}")
    displayed_series = [selected_dim] if selected_dim else supported_series

    if not bar_mode and not show_all:
        play_points = _filter_unchanged_trend_points(play_points, displayed_series)

    def _calc_trend_ylim(values: List[float]) -> Tuple[float, float]:
        if values:
            vmin = min(values)
            rmin = max(0, vmin - 0.2)
            vmax = max(values)
            rmax = min(15.5, vmax + 0.2)
        else:
            rmin, rmax = 0.0, 15.5
        return rmin, rmax

    if bar_mode:
        categories = displayed_series
        category_labels = [
            TREND_SHORT_LABELS.get(category, category) for category in categories
        ]
        ranges: List[tuple] = []
        values_flat: List[float] = []
        for category in categories:
            vals = [_trend_series_value(p, category) for p in play_points]
            if vals:
                vmin, vmax = min(vals), max(vals)
            else:
                vmin, vmax = 0.0, 0.0
            ranges.append((vmin, vmax))
            values_flat.extend(vals)

        fig_w = (
            3.6
            if len(categories) == 1
            else min(12.0, max(7.0, 3.0 + len(categories) * 1.1)) * 0.5
        )
        fig_h = 5.5
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        x = np.arange(len(categories))
        bottoms = [vmin for vmin, _ in ranges]
        heights = [vmax - vmin for vmin, vmax in ranges]

        ax.bar(
            x,
            heights,
            bottom=bottoms,
            width=0.55,
            color=[TREND_COLORS.get(category, "#4E79A7") for category in categories],
            edgecolor="#455A64",
            alpha=0.85,
        )

        rmin, rmax = _calc_trend_ylim(values_flat)
        ax.set_ylim(rmin, rmax)
        ax.grid(linestyle="--", linewidth=0.5, alpha=0.6, axis="y")

        fp = font_manager.FontProperties(fname="assets/fonts/DDFont.ttf")
        ax.set_xticks(x)
        ax.set_xticklabels(category_labels, fontproperties=fp)
        ax.set_ylabel("维度值", fontproperties=fp)
        ax.set_title(
            f"{' / '.join(category_labels)}区间（Top{N} 均值，按曲数）",
            fontproperties=fp,
            fontsize=14,
            pad=12,
        )
        ax.margins(x=0.05)
        y_pad = (rmax - rmin) * 0.015 if rmax > rmin else 0.05
        for idx, (vmin, vmax) in enumerate(ranges):
            delta = max(0.0, vmax - vmin)
            label = f"+{delta:.2f}"
            y_pos = min(rmax, vmax + y_pad)
            ax.text(
                x[idx],
                y_pos,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
                fontproperties=fp,
            )

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)
        return buf

    x_values = [float(p[0]) for p in play_points]
    labels = [str(p[0]) for p in play_points]
    x_arr = np.asarray(x_values, dtype=float)

    fig_w = min(12.5, max(5.6, 3.1 + len(play_points) * 0.36))
    fig_h = 10.2
    fig, (ax_top, ax_rate) = plt.subplots(
        2,
        1,
        figsize=(fig_w, fig_h),
        sharex=True,
        gridspec_kw={"height_ratios": [1.15, 0.95], "hspace": 0.32},
    )

    fp = font_manager.FontProperties(fname="assets/fonts/DDFont.ttf")
    values_flat: List[float] = []
    rate_values_flat: List[float] = []
    line_width = 2.8 if selected_dim else 2.0
    rating_width = 3.0 if selected_dim == "综合Rating" else 2.6
    rate_line_width = 2.6 if selected_dim else 2.0
    rate_rating_width = 2.8 if selected_dim == "综合Rating" else 2.4
    for series_name in displayed_series:
        y = [_trend_series_value(p, series_name) for p in play_points]
        values_flat.extend(y)
        ax_top.plot(
            x_values,
            y,
            marker="o",
            linewidth=rating_width if series_name == "综合Rating" else line_width,
            color=TREND_COLORS.get(series_name),
            label=series_name,
        )

        rate_x, rate_y = _smooth_playtrend_rate_series(x_arr, np.asarray(y, dtype=float))
        rate_values_flat.extend(rate_y.tolist())
        ax_rate.plot(
            rate_x,
            rate_y,
            linewidth=rate_rating_width if series_name == "综合Rating" else rate_line_width,
            color=TREND_COLORS.get(series_name),
            label=series_name,
        )

    rmin, rmax = _calc_trend_ylim(values_flat)
    ax_top.set_ylim(rmin, rmax)
    ax_top.grid(linestyle="--", linewidth=0.5, alpha=0.6)
    title_text = (
        f"{TREND_SHORT_LABELS.get(selected_dim, selected_dim)}走势（Top{N} 均值，按曲数）"
        if selected_dim
        else f"六维走势（Top{N} 均值，按曲数）"
    )
    ax_top.set_title(
        title_text,
        fontproperties=fp,
        fontsize=14,
        pad=12,
    )
    ax_top.set_ylabel("维度值", fontproperties=fp)
    ax_top.tick_params(labelbottom=False)

    rate_rmin, rate_rmax = _calc_playtrend_rate_ylim(rate_values_flat)
    ax_rate.set_ylim(rate_rmin, rate_rmax)
    ax_rate.axhline(0.0, color="#9E9E9E", linewidth=0.8, linestyle=":", alpha=0.8)
    ax_rate.grid(linestyle="--", linewidth=0.5, alpha=0.6)
    rate_title_text = (
        f"{TREND_SHORT_LABELS.get(selected_dim, selected_dim)}上涨速率（Top{N} 均值，按曲数）"
        if selected_dim
        else f"六维上涨速率（Top{N} 均值，按曲数）"
    )
    ax_rate.set_title(
        rate_title_text,
        fontproperties=fp,
        fontsize=14,
        pad=12,
    )
    ax_rate.set_ylabel("上涨速率 (/曲)", fontproperties=fp)
    ax_rate.set_xlabel("总曲数", fontproperties=fp)
    _apply_playcount_xticks(ax_rate, x_values, labels, fp)

    ax_top.legend(
        prop=fp,
        ncol=1,
        fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
    )
    ax_top.margins(x=0.02)
    ax_rate.margins(x=0.02)

    fig.tight_layout(rect=(0, 0, 0.86, 1))
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

def generate_rating_trend_image(
    user_id: int,
    N: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    max_days: Optional[int] = 30,
    bar_mode: bool = False,
    show_all: bool = False,
    selected_dim: Optional[str] = None,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> Optional[BytesIO]:
    """
    读取用户历史快照，按天聚合后生成六维/综合或单维走势图。
    """
    daily_points = build_daily_rating_points(
        user_id,
        N=N,
        json_path=json_path,
        max_days=max_days,
        history_snapshots=history_snapshots,
    )
    if not daily_points:
        return None

    dims = TREND_DIM_COLUMNS
    supported_series = dims + ["综合Rating"]
    if selected_dim and selected_dim not in supported_series:
        raise ValueError(f"不支持的趋势维度：{selected_dim}")
    displayed_series = [selected_dim] if selected_dim else supported_series

    if not bar_mode and not show_all:
        daily_points = _filter_unchanged_trend_points(daily_points, displayed_series)

    def _calc_trend_ylim(values: List[float]) -> Tuple[float, float]:
        if values:
            # vmin = math.floor(min(values))
            # rmin = max(min(values) - 0.5, vmin - 0.2)
            # vmax = math.ceil(max(values))
            # rmax = min(15.5, vmax + 0.2, max(values) + 0.5)
            vmin = min(values)
            rmin = max(0, vmin - 0.2)
            vmax = max(values)
            rmax = min(15.5, vmax + 0.2)
        else:
            rmin, rmax = 0.0, 15.5
        return rmin, rmax

    if bar_mode:
        categories = displayed_series
        category_labels = [
            TREND_SHORT_LABELS.get(category, category) for category in categories
        ]
        ranges: List[tuple] = []
        values_flat: List[float] = []
        for category in categories:
            vals = [_trend_series_value(p, category) for p in daily_points]
            if vals:
                vmin, vmax = min(vals), max(vals)
            else:
                vmin, vmax = 0.0, 0.0
            ranges.append((vmin, vmax))
            values_flat.extend(vals)

        fig_w = (
            3.6
            if len(categories) == 1
            else min(12.0, max(7.0, 3.0 + len(categories) * 1.1)) * 0.5
        )
        fig_h = 5.5
        fig, ax = plt.subplots(figsize=(fig_w, fig_h))

        x = np.arange(len(categories))
        bottoms = [vmin for vmin, _ in ranges]
        heights = [vmax - vmin for vmin, vmax in ranges]

        ax.bar(
            x,
            heights,
            bottom=bottoms,
            width=0.55,
            color=[TREND_COLORS.get(category, "#4E79A7") for category in categories],
            edgecolor="#455A64",
            alpha=0.85,
        )

        rmin, rmax = _calc_trend_ylim(values_flat)
        ax.set_ylim(rmin, rmax)
        ax.grid(linestyle="--", linewidth=0.5, alpha=0.6, axis="y")

        fp = font_manager.FontProperties(fname="assets/fonts/DDFont.ttf")
        ax.set_xticks(x)
        ax.set_xticklabels(category_labels, fontproperties=fp)
        ax.set_ylabel("维度值", fontproperties=fp)
        ax.set_title(
            f"{' / '.join(category_labels)}区间（Top{N} 均值，按天）",
            fontproperties=fp,
            fontsize=14,
            pad=12,
        )
        ax.margins(x=0.05)
        y_pad = (rmax - rmin) * 0.015 if rmax > rmin else 0.05
        for idx, (vmin, vmax) in enumerate(ranges):
            delta = max(0.0, vmax - vmin)
            label = f"+{delta:.2f}"
            y_pos = min(rmax, vmax + y_pad)
            ax.text(
                x[idx],
                y_pos,
                label,
                ha="center",
                va="bottom",
                fontsize=8,
                fontproperties=fp,
            )

        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        buf.seek(0)
        plt.close(fig)
        return buf

    labels = [p[0].strftime("%m-%d") for p in daily_points]
    x_step = max(0.45, min(1.0, len(daily_points) / 10))
    x = [i * x_step for i in range(len(daily_points))]

    fig_w = min(12.5, max(5.6, 3.1 + len(daily_points) * 0.36))
    fig_h = 5.5
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    fp = font_manager.FontProperties(fname="assets/fonts/DDFont.ttf")
    values_flat: List[float] = []
    line_width = 2.8 if selected_dim else 2.0
    rating_width = 3.0 if selected_dim == "综合Rating" else 2.6
    for series_name in displayed_series:
        y = [_trend_series_value(p, series_name) for p in daily_points]
        values_flat.extend(y)
        ax.plot(
            x,
            y,
            marker="o",
            linewidth=rating_width if series_name == "综合Rating" else line_width,
            color=TREND_COLORS.get(series_name),
            label=series_name,
        )

    rmin, rmax = _calc_trend_ylim(values_flat)
    ax.set_ylim(rmin, rmax)
    ax.grid(linestyle="--", linewidth=0.5, alpha=0.6)
    title_text = (
        f"{TREND_SHORT_LABELS.get(selected_dim, selected_dim)}走势（Top{N} 均值，按天）"
        if selected_dim
        else f"六维走势（Top{N} 均值，按天）"
    )
    ax.set_title(
        title_text,
        fontproperties=fp,
        fontsize=14,
        pad=12,
    )
    ax.set_ylabel("维度值", fontproperties=fp)

    max_labels = 8
    step = max(1, len(labels) // max_labels)
    tick_idx = list(range(0, len(labels), step))
    ax.set_xticks([x[i] for i in tick_idx])
    ax.set_xticklabels(
        [labels[i] for i in tick_idx],
        rotation=35,
        ha="right",
        fontproperties=fp,
    )
    ax.legend(
        prop=fp,
        ncol=1,
        fontsize=9,
        loc="upper left",
        bbox_to_anchor=(1.02, 1.0),
        borderaxespad=0.0,
    )
    ax.margins(x=0.02)

    fig.tight_layout(rect=(0, 0, 0.86, 1))
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf

from taiko_bot.runtime.player.client.b30_support.score_calculator import _compute_results_from_userdata_records, aggregate_topN_value, build_const_table, compute_dim_topN_means, load_rating_config
