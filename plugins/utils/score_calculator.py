
from taiko_bot import domain as _domain
from sakura_taiko_core.rating import v1 as _v1
from sakura_taiko_core.dimension import v1 as _dims
from sakura_taiko_core.models import calculation as _models
from sakura_taiko_core.chart import catalog as _catalog, client_groups as _client_groups
from sakura_taiko_core.score import calculation as _calculation
from sakura_taiko_core.recommendation import candidates as _candidates
import json
import math
import pandas as pd
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Any, Literal, Tuple, Set
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from io import BytesIO
from matplotlib import font_manager
import os
import datetime
from matplotlib.transforms import offset_copy
from taiko_bot.settings import get_settings
from taiko_bot.userdata_provider import get_cached_userdata, ensure_userdata_history_available
from taiko_bot.history_adapter import iter_trend_history

from .song_visibility import (
    is_song_id_publicly_visible,
    is_song_publicly_visible,
)


# ---------- 数据结构 ----------
UNPLAYED_BG = "#E8F3FF"  # 非常浅的蓝色，不影响可读性
POSITIVE_COLOR = "#2E7D32"  # 淡绿（正向）
NEGATIVE_COLOR = "#C62828"  # 淡红（负向）
NEUTRAL_COLOR = "#000000"  # 黑色
RatingAlgorithm = _v1.RatingAlgorithm
ACCURACY_WEIGHTS = _v1.ACCURACY_WEIGHTS
MANUAL_PAIR_ID_GROUPS = _client_groups.MANUAL_PAIR_ID_GROUPS


_normalize_duplicate_song_level_signature = _client_groups._normalize_duplicate_song_level_signature


def build_duplicate_song_groups(song_data_path=get_settings().root_dir / "songs/song_data.json"):
    try: rows = load_json(song_data_path)
    except Exception: rows = []
    return _client_groups.build_rating_duplicate_groups(rows)


PAIR_ID_GROUPS = build_duplicate_song_groups()
PAIR_ID_MAP = {
    song_id: idx for idx, pair in enumerate(PAIR_ID_GROUPS) for song_id in pair
}
CN_COL_TO_ATTR = {
    "AI_rating": "AI_rating",  # 允许英文直通
    "大歌力": "big_song",
    "体力": "stamina",
    "高速处理": "speed",
    "精度力": "accuracy_power",
    "节奏处理": "rhythm",
    "复合处理": "complex_proc",
}
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


SongMetrics = _models.SongMetrics


RatingResult = _models.RatingResult


# ---------- 数据加载 ----------


def load_rating_config(json_path: str | Path) -> dict:
    """
    读取 rating_structured.json：
    {
      "songs": {...},
      "const_table": {
        "const_to_score": { "1.0": 0.05, ... }
      }
    }
    """
    json_path = Path(json_path)
    with json_path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_json(file_path: str | Path) -> list:
    """加载 JSON 文件"""
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_on_shelf_song_ids(
    song_data_path: str | Path = get_settings().root_dir / "songs" / "song_data.json",
) -> set[int]:
    on_shelf_ids: set[int] = set()
    try:
        song_data = load_json(song_data_path)
    except Exception:
        return on_shelf_ids

    if not isinstance(song_data, list):
        return on_shelf_ids

    for item in song_data:
        if not isinstance(item, dict):
            continue
        try:
            song_id = int(item.get("id"))
        except Exception:
            continue
        if not is_song_publicly_visible(item):
            continue
        on_shelf_ids.add(song_id)
    return on_shelf_ids


# ---------- 1. 定数 → M 列（定数得点） ----------


build_const_table = _v1.build_const_table


lookup_const_score = _v1.lookup_const_score


# ---------- 2. 良率 G → N 列（精度得点） ----------
calc_accuracy = _v1.calc_accuracy


_calc_accuracy_for_record = _v1._calc_accuracy_for_record


calc_y = _v1.calc_y


accuracy_to_score = _v1.accuracy_to_score


# ---------- 3. P 列：幂指数参数 ----------


compute_P = _v1.compute_P


# ---------- 4. Q 列：二维权重 ----------


compute_Q = _v1.compute_Q


# ---------- 5. AI 列：综合 rating（幂平均） ----------


compute_AI = _v1.compute_AI


# ---------- 6. 由 H~L 计算 AD,AE,AF,AG ----------


compute_AD_AE_AF_AG = _dims.compute_AD_AE_AF_AG


# ---------- 7. 六维属性 AJ~AO ----------


_scale_dim = _dims._scale_dim


compute_six_dims = _dims.compute_six_dims


# ---------- 8. 总入口：从用户数据 + JSON 计算一整套 ----------


def compute_all_from_userdata(
    user_id: int,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    *,
    collapse_duplicate_versions: bool = True,
) -> List[RatingResult]:
    """
    给定用户 ID，读取用户数据文件并计算所有曲目的综合 AI 和六维属性。

    1. 读取 userdata.json 文件，获取所有歌曲的信息；
    2. 根据 song_no 查找 structured JSON 中的曲目信息；
    3. 根据 good_cnt / combo 计算良率，进而计算 AI 和六维。
    """
    # 用户数据文件路径
    userdata_blob = get_cached_userdata(str(user_id))
    userdata = (
        userdata_blob.get("songs", [])
        if isinstance(userdata_blob, dict)
        else userdata_blob
    )

    cfg = load_rating_config(json_path)  # 读取 structured JSON
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)
    return _compute_results_from_userdata_records(
        userdata,
        cfg,
        const_table,
        collapse_duplicate_versions=collapse_duplicate_versions,
    )


def compute_all_from_userdata_records(
    userdata_records: List[Dict[str, Any]],
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    *,
    collapse_duplicate_versions: bool = True,
) -> List[RatingResult]:
    """
    给定用户数据记录（songs 列表），计算所有曲目的综合 AI 和六维属性。
    """
    cfg = load_rating_config(json_path)
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)
    return _compute_results_from_userdata_records(
        userdata_records,
        cfg,
        const_table,
        collapse_duplicate_versions=collapse_duplicate_versions,
    )


def _compute_results_from_userdata_records(userdata_records, cfg, const_table, *, collapse_duplicate_versions=True):
    return _calculation._compute_results_from_userdata_records(userdata_records, cfg, const_table,
        collapse_duplicate_versions=collapse_duplicate_versions, duplicate_groups=PAIR_ID_GROUPS,
        default_ids=PAIR_ID_MAP, visible_song_ids=_domain.visibility_inputs(userdata_records, cfg["songs"]),
        identity_namespace="pair")


# ---------- 排序并输出前20项 ----------
get_top20_weighted_average = _v1.get_top20_weighted_average


get_top20_median = _v1.get_top20_median


top_value_compensate = _v1.top_value_compensate


def get_top_N(results: List[RatingResult], sort_by: str, N: int = 20) -> pd.DataFrame:
    """
    根据给定的指标（如 AI_rating），返回前 N 排名的结果。
    """
    # 将计算结果转换为 DataFrame
    df = pd.DataFrame(
        [
            {
                "song_name": result.song_name,
                "AI_rating": result.AI_rating,
                "大歌力": result.big_song,
                "体力": result.stamina,
                "高速处理": result.speed,
                "精度力": result.accuracy_power,
                "节奏处理": result.rhythm,
                "复合处理": result.complex_proc,
            }
            for result in results
        ]
    )

    # 按照指定指标（例如 AI_rating）进行排序并输出前 N 项
    top_N = df.sort_values(by=sort_by, ascending=False).head(N)
    return top_N


# ---------- 雷达图绘制函数 ----------
TOP20_COMPENSATE_TABLE = {
    # attr -> (full_mid, full_ave, threshold)
    # 这些常数来自 TS（calculator.ts）最新版；请你按 TS 文件填入准确数值
    # 下面只是结构示例：
    "AI_rating": (15.270459, 15.299638, 14.58),
    "大歌力": (15.260226, 15.290645, 14.54),
    "体力": (14.680215, 14.915699, 13.36),
    "高速处理": (14.24503, 14.585896, 13.99),
    "精度力": (15.384801, 15.399022, 15.03),
    "节奏处理": (14.521553, 14.831288, 14.02),
    "复合处理": (13.744459, 14.255545, 13.45),
}


aggregate_topN_value = _v1.aggregate_topN_value


compute_dim_topN_means = _v1.compute_dim_topN_means


def plot_radar_from_values(
    dim_values: Dict[str, float],
    title: str,
    font_path: str | None = None,
    dynamic_origin=False,
):
    """
    dim_values: {'大歌力': x1, '体力': x2, ...}  每个维度已经是最终要画的值（比如各自 topN 的均值）
    返回 (fig, ax)
    """
    # 固定顺序，保持和你表格一致
    categories = ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"]
    values = [dim_values[c] for c in categories]
    rmax = 14.0
    if dynamic_origin:
        vmin = math.floor(min(values) if values else 0.0)
        rmin = max(0.0, vmin - 1.0)
        vmax = math.ceil(max(values) if values else 0.0)
        rmax = min(15.5, vmax + 0.2)
    else:
        rmin = 0.0

    num_vars = len(categories)
    angles = np.linspace(0, 2 * np.pi, num_vars, endpoint=False).tolist()

    # 闭合多边形
    values = np.concatenate((values, [values[0]]))
    angles += angles[:1]

    # 用 add_subplot + polar，方便去掉外矩形
    fig = plt.figure(figsize=(6, 6))
    ax = fig.add_subplot(111, polar=True)
    ax.set_frame_on(False)  # 去掉那层讨厌的矩形边框

    # 固定最大最小值，设定刻度范围为 0 到 14
    # ax.set_ylim(0, 14)  # 强制纵坐标范围为 [0, 14]
    ax.set_ylim(rmin, rmax)  # 动态纵坐标

    # 填充 & 轮廓
    ax.fill(angles, values, alpha=0.25)
    ax.plot(angles, values, linewidth=2)

    # 坐标轴 & 标签
    fp = font_manager.FontProperties(fname=font_path) if font_path else None
    ax.set_yticklabels([])  # 不要同心圆刻度数字
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(categories, fontproperties=fp)

    # 网格虚线
    ax.grid(linestyle="--", linewidth=0.5)

    # 添加每个轴的数值标签
    for i in range(num_vars):
        ax.text(
            angles[i],
            values[i] + 0.05,
            f"{values[i]:.2f}",
            horizontalalignment="center",
            size=10,
            color="black",
            fontproperties=font_manager.FontProperties(fname=font_path),
        )

    ax.set_title(title, fontproperties=fp, fontsize=16, pad=20)

    return fig, ax


# ---------- 输出 AI rating 和雷达图 ----------
def get_topN_by_rating(results: List[RatingResult], N: int = 20) -> pd.DataFrame:
    df = pd.DataFrame(
        [
            {
                "song_name": r.song_name,
                "accuracy": r.accuracy,
                "const_value": r.const_value,
                "AI_rating": r.AI_rating,
                "大歌力": r.big_song,
                "体力": r.stamina,
                "高速处理": r.speed,
                "精度力": r.accuracy_power,
                "节奏处理": r.rhythm,
                "复合处理": r.complex_proc,
            }
            for r in results
        ]
    )
    return df.sort_values(by="AI_rating", ascending=False).head(N)


# def plot_top_N_results(top_N: pd.DataFrame):
#     """
#     将 top_N 的结果输出为图像，包含雷达图和 AI rating 文字。
#     """
#     font_path = "assets/fonts/DDFont.ttf"  # 指定中文字体路径
#     # 设置图形大小
#     fig, ax = plt.subplots(figsize=(10, 6))

#     # 绘制六维数据的雷达图
#     plot_radar(
#         top_N,
#         ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"],
#         f"Top {len(top_N)} Songs - 六维属性",
#         ax=ax,
#         font_path=font_path,
#     )

#     # 展示前N项的曲名和AI rating，设置位置
#     for i, row in top_N.iterrows():
#         ax.text(
#             0.8,
#             0.95 - i * 0.04,
#             f"{row['song_name']}: AI rating = {row['AI_rating']:.2f}",
#             color="black",
#             fontsize=12,
#             va="bottom",
#             fontproperties=font_manager.FontProperties(fname=font_path),
#         )
#     # 保存图像到字节流
#     byte_io = BytesIO()
#     plt.savefig(byte_io, format="png")
#     byte_io.seek(0)  # 重置文件指针到文件开头
#     plt.close()  # 关闭图形，防止显示在屏幕上

#     return byte_io


# ---------- 主程序 ----------
def getUtime(user_id):
    get_cached_userdata(str(user_id))
    return str(datetime.datetime.now().replace(microsecond=0))


def _song_key(song: Dict[str, Any]) -> tuple:
    return (song.get("song_no"), song.get("level"))


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


def load_user_snapshots(
    user_id: int,
    history_snapshots: Optional[List[Dict[str, Any]]] = None,
) -> List[Tuple[datetime.datetime, Dict[str, Any]]]:
    return list(iter_user_snapshots(user_id, history_snapshots=history_snapshots))


def iter_user_snapshots(user_id, history_snapshots=None):
    if history_snapshots is None:
        history_snapshots = ensure_userdata_history_available(str(user_id))
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


def generate_dim_top_image(
    results, N: int, dim: str, user_id=None, font_path: str | None = None
) -> BytesIO:
    """
    dim: "大歌力"/"体力"/"高速处理"/"精度力"/"节奏处理"/"复合处理"
    results: compute_all_from_userdata 的输出（你项目里通常是 list[dict] 或 list[dataclass]）
    """
    # 兼容 dict / dataclass
    rows = []
    for r in results:
        if isinstance(r, dict):
            rows.append(r)
        else:
            rows.append(r.__dict__)

    df = pd.DataFrame(rows)
    if dim not in df.columns:
        # 你的字段名如果不同，这里报错提示最直观
        raise ValueError(f"结果中不存在维度列：{dim}，现有列：{list(df.columns)}")

    topN = df.sort_values(by=dim, ascending=False).head(int(N)).reset_index(drop=True)

    fp = font_manager.FontProperties(fname=font_path) if font_path else None
    dim_map = {
        "big_song": "大歌力",
        "stamina": "体力",
        "speed": "高速处理",
        "accuracy_power": "精度力",
        "rhythm": "节奏处理",
        "complex_proc": "复合处理",
    }
    title = f"{dim_map[dim]} Top{len(topN)}"
    if user_id is not None:
        title += f"  (ID:{user_id})"

    # 太宽了
    # fig_w, dpi = 14.0, 170
    fig_w, dpi = 9.5, 170
    fontsize_title, fontsize_body, line_spacing = 18, 11, 1.54

    total_lines = 2 + len(topN)
    total_pt = total_lines * fontsize_body * line_spacing + fontsize_title * 1.3 + 24
    fig_h = max(3.5, total_pt / 72.0)

    fig = plt.figure(figsize=(fig_w, fig_h))
    ax = fig.add_subplot(111)
    ax.axis("off")

    x0, y0 = 0.02, 0.95
    ax.text(
        x0,
        y0,
        title,
        fontproperties=fp,
        fontsize=fontsize_title,
        va="top",
        transform=ax.transAxes,
    )

    header = "No | 曲名 | 分数"
    header_t = offset_copy(
        ax.transAxes, fig=fig, y=-(fontsize_title * 1.2), units="points"
    )
    ax.text(
        x0,
        y0,
        header,
        fontproperties=fp,
        fontsize=fontsize_body,
        va="top",
        transform=header_t,
        alpha=0.95,
    )

    base_offset_pt = fontsize_title * 1.2 + fontsize_body * line_spacing * 1.6
    for i, row in enumerate(topN.itertuples(index=False), start=1):
        song_name = getattr(row, "song_name", getattr(row, "曲名", ""))
        const_value = getattr(row, "const_value", 0)
        accuracy = getattr(row, "accuracy", 0)
        value = float(getattr(row, dim))
        line = f"{i:>2d} | {song_name} | {const_value:.1f} * {round(accuracy*100,2)}% => {value:.2f}"

        dy_pt = -(base_offset_pt + (i - 1) * fontsize_body * line_spacing)
        t = offset_copy(ax.transAxes, fig=fig, y=dy_pt, units="points")
        ax.text(
            x0,
            y0,
            line,
            fontproperties=fp,
            fontsize=fontsize_body,
            va="top",
            transform=t,
        )

    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
    buf.seek(0)
    plt.close(fig)
    return buf


def generate_top_N_image(
    results: List[RatingResult],
    N: int = 20,
    user_id=None,
    dynamic_origin=False,
    font_path: str | None = None,
) -> BytesIO:
    """
    六维雷达图：
      每一维 = 该维度自己的 topN 均值
    右侧文字列表：
      仍然是 AI_rating 的 topN（如需改成别的也很容易）
    返回：PNG 字节流
    """
    if not font_path:
        font_path = "/usr/share/fonts/msyhbd.ttc"
    # 1. 六维各自 topN 均值
    dim_means = compute_dim_topN_means(results, N)

    # 2. AI_rating topN（用于右侧文字）
    topN_rating_df = get_topN_by_rating(results, N)

    # 3. 画雷达图
    if N == 20:
        fig, ax = plot_radar_from_values(
            dim_means,
            title=f"六维属性（top{N} 加权平均）\n更新于{getUtime(user_id)}",
            font_path=font_path,
            dynamic_origin=dynamic_origin,
        )
    else:
        fig, ax = plot_radar_from_values(
            dim_means,
            title=f"六维属性（各自 top{N} 均值）\n更新于{getUtime(user_id)}",
            font_path=font_path,
            dynamic_origin=dynamic_origin,
        )

    # 4. 在同一张图上右侧加文字（简单一点就直接画在极坐标上右半边）
    fp = font_manager.FontProperties(fname=font_path) if font_path else None

    # 这里用 fig.text，而不是 ax.text，方便放在图的右侧固定位置
    y_start = 0.95
    y_step = 0.035
    fig.text(
        1.05,
        y_start,
        f"综合Rating best{N} 成绩",
        fontproperties=fp,
        fontsize=15,
    )

    rating_sum = 0
    for i, row in enumerate(topN_rating_df.itertuples(index=False)):
        if i >= N:
            break
        fig.text(
            1.05,
            y_start - 0.04 - (i + 2) * y_step,
            f"{i+1:2d}. {row.song_name} {row.const_value:.1f}*{round(row.accuracy*100,2)}% => {row.AI_rating:.2f}",
            fontproperties=fp,
            fontsize=9,
        )
        rating_sum += row.AI_rating
    if N == 20:
        overall = aggregate_topN_value(results, "AI_rating", 20)
    else:
        # 旧逻辑：AI_rating topN 算术平均
        overall = (
            float(topN_rating_df["AI_rating"].mean())
            if not topN_rating_df.empty
            else 0.0
        )
    # fig.text(
    #     1.05,
    #     y_start - 0.055,
    #     f"Rating : {round(rating_sum/N,2)}",
    #     fontproperties=fp,
    #     fontsize=15,
    # )
    fig.text(
        1.05,
        y_start - 0.055,
        f"Rating : {overall:.2f}",
        fontproperties=fp,
        fontsize=15,
    )

    # 5. 导出为字节流
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    return buf


# ============================================================
# 推荐算法（最小侵入：仅新增，不修改你已有的任何函数）
# recommend.ts 对齐点：
# 1) best20 按用户侧 best_key 取 top20
# 2) best20IndicatorMedian 使用“谱面侧指标”的中位数
# 3) rating/daigouryoku/accuracy_power 的 indicator 来自 const_to_score（即 lookup_const_score）
# 4) stamina/speed/rhythm/complex 的 indicator 来自 AD/AE/AF/AG（原始值，不做*15.5/100）
# 5) 候选=全曲库-best20，含未游玩；并做 rating 上限 best20RatingMedian+0.2
# 6) accuracyFactor：未游玩=0.5；已游玩 acc>=0.5 => 1-acc；否则=1
# 7) balanceScore = indicatorDev*1 - scoreDev*2 - accuracyFactor*1.5
# 8) strictRange：indicator ∈ [0.9*median, 1.05*median]
# 9) 未游玩额外阈值：indicatorDev<=0.10
# 10) 输出尽量未游玩/已游玩各一半，不足互补
# ============================================================


SongStats = _models.ClientSongStats


_median = _candidates._median


_build_song_index_by_id_level = _catalog._build_song_index_by_id_level


def get_song_chart_identity_key(song_id, level):
    return _catalog._get_recommend_identity_key(song_id, level, PAIR_ID_MAP, identity_namespace="pair")


_get_recommend_identity_key = get_song_chart_identity_key


def _build_song_index_by_identity(songs):
    return _catalog._build_song_index_by_identity(songs, PAIR_ID_MAP,
        _domain.visibility_inputs(songs=songs), identity_namespace="pair")


def _find_song_info_for_recommend_record(song_id, level, idx_by_id_level, idx_by_identity):
    return _catalog._find_song_info_for_recommend_record(song_id, level, idx_by_id_level,
        idx_by_identity, PAIR_ID_MAP, identity_namespace="pair")


_get_title_like_existing = _catalog._get_title_like_existing


_get_song_indicator_value = _candidates._get_song_indicator_value


def build_all_stats_for_user(user_id, json_path="./songs/rating_structured_with_ids.json"):
    records = get_cached_userdata(str(user_id))["songs"]
    cfg = load_rating_config(json_path)
    return _candidates.build_all_stats_from_records(records, cfg,
        default_ids=PAIR_ID_MAP, visible_song_ids=_domain.visibility_inputs(records, cfg["songs"]),
        profile="recommend-client-20261010", identity_namespace="pair")


def generate_recommend_image(
    recs: List[Dict[str, Any]],
    title: str = "Taiko 推荐歌曲",
    subtitle: Optional[str] = None,
    font_path: Optional[str] = None,
    dpi: int = 170,
    fontsize_title: int = 20,
    fontsize_subtitle: int = 12,
    fontsize_body: int = 11,
    line_spacing: float = 1.10,  # 行距倍数：1.05~1.20 都可；你要接近 1 倍就 1.05~1.10
    left_margin: float = 0.012,
    top_margin_axes: float = 0.975,
    max_rows: Optional[int] = None,  # 可选：限制最多显示多少行（例如 30）
) -> BytesIO:
    """
    将推荐结果 recs（list[dict]）渲染成图片并返回 BytesIO。
    关键：使用固定列宽表格渲染，保证列对齐，并在图头补充图例说明。
    """
    # -------- 字体 --------
    fp = font_manager.FontProperties(fname=font_path) if font_path else None

    def _ellipsize(text: str, limit: int) -> str:
        text = str(text)
        if limit <= 0 or len(text) <= limit:
            return text
        if limit <= 1:
            return "…"
        return text[: limit - 1] + "…"

    # -------- 空结果兜底 --------
    if not recs:
        fig = plt.figure(figsize=(12, 3))
        ax = fig.add_axes([0, 0, 1, 1])
        ax.axis("off")
        ax.text(
            left_margin,
            0.85,
            title,
            fontproperties=fp,
            fontsize=fontsize_title,
            va="top",
        )
        ax.text(
            left_margin,
            0.55,
            "暂无可推荐曲目（可能曲库匹配失败或数据不足）",
            fontproperties=fp,
            fontsize=fontsize_body,
            va="top",
        )
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", dpi=dpi)
        buf.seek(0)
        plt.close(fig)
        return buf

    scores = [float(r.get("recommend_score", 0.0)) for r in recs]
    s_min, s_max = min(scores), max(scores)
    den = (s_max - s_min) if (s_max - s_min) != 0 else 1.0

    def to_index(s: float) -> float:
        return (s_max - s) / den * 100.0

    # -------- 截断行数（可选）--------
    if max_rows is not None and max_rows > 0:
        recs = recs[:max_rows]

    n = len(recs)

    display_rows: List[Dict[str, Any]] = []
    max_name_len = 0
    for idx, r in enumerate(recs, start=1):
        name = _ellipsize(str(r.get("title", "")), 24)
        song_id = str(r.get("song_id", ""))
        is_unplayed = bool(r.get("is_unplayed", False))
        dev = float(r.get("indicator_deviation_percent", 0.0)) * 100.0
        acc = float(r.get("accuracy", 0.0)) * 100.0
        song_indicator = float(r.get("song_indicator", 0.0))
        reference_indicator = float(r.get("reference_indicator", 0.0))
        raw_score = float(r.get("recommend_score", 0.0))
        rec_index = to_index(raw_score)
        strict = "*" if r.get("is_in_strict_range") else ""
        display_rows.append(
            {
                "no": f"{idx:>2d}{strict}",
                "song_id": song_id,
                "name": name,
                "is_unplayed": is_unplayed,
                "dev": dev,
                "song_indicator_text": f"{song_indicator:6.2f}",
                "reference_indicator_text": f"{reference_indicator:6.2f}",
                "dev_text": f"{dev:+6.2f}%",
                "acc_text": "-" if is_unplayed else f"{acc:6.2f}%",
                "score_text": f"{rec_index:6.1f}",
            }
        )
        max_name_len = max(max_name_len, len(name))

    # -------- 动态计算画布大小 --------
    # 1 inch = 72 pt
    fig_w_inch = max(16.0, min(22.0, 10.5 + max_name_len * 0.22))
    body_pt = (n + 3) * fontsize_body * max(line_spacing, 1.12) * 1.65
    total_pt = (
        body_pt
        + fontsize_title * 1.25
        + (fontsize_subtitle * 1.1 if subtitle else 0)
        + 56
    )
    fig_h_inch = max(4.3, total_pt / 72.0)

    fig = plt.figure(figsize=(fig_w_inch, fig_h_inch))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.axis("off")

    # -------- 标题区 --------
    title_y = top_margin_axes
    fig.text(
        left_margin,
        title_y,
        title,
        fontproperties=fp,
        fontsize=fontsize_title,
        va="top",
    )
    if subtitle:
        subtitle_transform = offset_copy(
            ax.transAxes, fig=fig, y=-(fontsize_title * 1.35), units="points"
        )
        ax.text(
            left_margin,
            title_y,
            subtitle,
            fontproperties=fp,
            fontsize=fontsize_subtitle,
            va="top",
            transform=subtitle_transform,
        )
    legend_text = (
        "说明：用户中位数=你在当前维度 best20 的谱面指标中位数；谱面指标=该曲用于匹配的维度值。\n"
        "指标偏差=(谱面指标-用户中位数)/用户中位数；* 表示谱面指标在用户中位数的 90%~105% 严格区间。"
    )
    legend_offset_pt = fontsize_title * 1.35 + (fontsize_subtitle * 1.25 if subtitle else 0)
    legend_transform = offset_copy(
        ax.transAxes, fig=fig, y=-legend_offset_pt, units="points"
    )
    ax.text(
        left_margin,
        title_y,
        legend_text,
        fontproperties=fp,
        fontsize=max(9, fontsize_body - 1),
        va="top",
        transform=legend_transform,
        color="#374151",
    )

    table = ax.table(
        cellText=[
            [
                row["no"],
                row["song_id"],
                row["name"],
                "是" if row["is_unplayed"] else "否",
                row["song_indicator_text"],
                row["reference_indicator_text"],
                row["dev_text"],
                row["acc_text"],
                row["score_text"],
            ]
            for row in display_rows
        ],
        colLabels=[
            "No",
            "ID",
            "曲名",
            "未游玩",
            "谱面指标",
            "用户中位数",
            "指标偏差",
            "精度",
            "推荐指数",
        ],
        colLoc="center",
        cellLoc="center",
        colWidths=[
            0.052,
            0.078,
            0.332,
            0.068,
            0.105,
            0.105,
            0.105,
            0.078,
            0.077,
        ],
        bbox=[left_margin, 0.028, 1.0 - left_margin * 2, 0.705],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(fontsize_body)
    for (row_idx, col_idx), cell in table.get_celld().items():
        cell.set_edgecolor("#D1D5DB")
        cell.set_linewidth(0.7)
        cell.get_text().set_fontproperties(fp)
        if row_idx == 0:
            cell.set_facecolor("#F3F4F6")
            cell.get_text().set_weight("bold")
            cell.get_text().set_color("#111827")
            cell.get_text().set_ha("center")
            cell.PAD = 0.04
            continue

        row = display_rows[row_idx - 1]
        cell.set_facecolor(UNPLAYED_BG if row["is_unplayed"] else "#FFFFFF")
        cell.get_text().set_ha("center")

        if col_idx == 6:
            if row["dev"] < 0:
                cell.get_text().set_color(POSITIVE_COLOR)
            elif row["dev"] > 0:
                cell.get_text().set_color(NEGATIVE_COLOR)
            else:
                cell.get_text().set_color(NEUTRAL_COLOR)
            cell.get_text().set_weight("bold")
        else:
            cell.get_text().set_color("#111827")
        cell.PAD = 0.045

    # -------- 输出 --------
    buf = BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0.02, dpi=dpi)
    buf.seek(0)
    plt.close(fig)
    return buf


def recommend_songs(all_stats, songs_cfg, const_table, best_key="rating", limit=20):
    return _candidates.recommend_songs(all_stats, songs_cfg, const_table, best_key, limit,
        default_ids=PAIR_ID_MAP, visible_song_ids=_domain.visibility_inputs(songs=songs_cfg),
        on_shelf_song_ids=load_on_shelf_song_ids(), identity_namespace="pair")


def compute_recommendations_for_user(
    user_id: int,
    best_key: str = "rating",
    limit: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
) -> List[dict]:
    """
    你在 bot 里只需要调用这个：
        recs = compute_recommendations_for_user(taiko_id, best_key="stamina", limit=20)
    """
    all_stats, songs_cfg, const_table = build_all_stats_for_user(
        user_id, json_path=json_path
    )
    return recommend_songs(
        all_stats, songs_cfg, const_table, best_key=best_key, limit=limit
    )
