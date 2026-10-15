from __future__ import annotations
from taiko_bot.offline.paths import root as _runtime_root

from sakura_taiko_core.rating.v1 import (
    build_const_table,
    lookup_const_score,
    calc_accuracy,
    _calc_accuracy_for_record,
    calc_y,
    accuracy_to_score,
    compute_P,
    compute_Q,
    compute_AI,
    get_top20_weighted_average,
    get_top20_median,
    top_value_compensate,
    aggregate_topN_value,
    compute_dim_topN_means,
    RatingAlgorithm,
    ACCURACY_WEIGHTS,
    CN_COL_TO_ATTR,
    TOP20_COMPENSATE_TABLE,
)
from sakura_taiko_core.dimension.v1 import compute_AD_AE_AF_AG, _scale_dim, compute_six_dims
from sakura_taiko_core.models.calculation import SongMetrics, RatingResult, SongStats
from sakura_taiko_core.chart.catalog import _build_song_index_by_id_level, _get_title_like_existing
from sakura_taiko_core.chart import catalog as domain_catalog
from sakura_taiko_core.score import calculation as domain_calculation
from sakura_taiko_core.recommendation import candidates as domain_candidates
from .taiko_domain_adapter import identity_inputs
from taiko_store.reader import read_current_json, score_read_view


import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Any, Literal, Tuple, Set
from io import BytesIO
import datetime

if os.environ.get("TAIKO_COMPUTE_ONLY") != "1":
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib import font_manager
    from matplotlib.transforms import offset_copy

from .chart_availability import (
    load_cn_available_chart_keys,
    load_on_shelf_song_ids,
)
from taiko_bot.runtime.player.center.duplicate_versions import build_duplicate_song_groups, duplicate_identity_key

# ---------- 数据结构 ----------
UNPLAYED_BG = "#E8F3FF"  # 非常浅的蓝色，不影响可读性
POSITIVE_COLOR = "#2E7D32"  # 淡绿（正向）
NEGATIVE_COLOR = "#C62828"  # 淡红（负向）
NEUTRAL_COLOR = "#000000"  # 黑色
MANUAL_PAIR_ID_GROUPS = [
    (399, 400),
    (433, 1265),
    (939, 1263),
    (450, 1257),
    (1146, 1264),
    (750, 1260),
    (141, 1258),
    (191, 1266),
    (527, 1261),
    (323, 1262),
    (137, 1259),
]


PAIR_ID_GROUPS = build_duplicate_song_groups()
PAIR_ID_MAP = {
    song_id: idx for idx, pair in enumerate(PAIR_ID_GROUPS) for song_id in pair
}


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


# ---------- 1. 定数 → M 列（定数得点） ----------


# ---------- 2. 良率 G → N 列（精度得点） ----------


# ---------- 3. P 列：幂指数参数 ----------


# ---------- 4. Q 列：二维权重 ----------


# ---------- 5. AI 列：综合 rating（幂平均） ----------


# ---------- 6. 由 H~L 计算 AD,AE,AF,AG ----------


# ---------- 7. 六维属性 AJ~AO ----------


# ---------- 8. 总入口：从用户数据 + JSON 计算一整套 ----------


def compute_all_from_userdata(
    user_id: int,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
    *,
    collapse_duplicate_versions: bool = False,
) -> List[RatingResult]:
    """
    给定用户 ID，读取用户数据文件并计算所有曲目的综合 AI 和六维属性。

    1. 读取 userdata.json 文件，获取所有歌曲的信息；
    2. 根据 song_no 查找 structured JSON 中的曲目信息；
    3. 根据 good_cnt / combo 计算良率，进而计算 AI 和六维。
    """
    userdata_blob = read_current_json(os.environ.get("TAIKO_USERDATA_DIR", "./userdata"), str(user_id))
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
    collapse_duplicate_versions: bool = False,
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


def _compute_results_from_userdata_records(userdata_records, cfg, const_table, *, collapse_duplicate_versions=False):
    default_ids, _ = identity_inputs()
    return domain_calculation._compute_results_from_userdata_records(
        userdata_records, cfg, const_table, collapse_duplicate_versions=collapse_duplicate_versions,
        duplicate_groups=PAIR_ID_GROUPS, default_ids=default_ids)


# ---------- 排序并输出前20项 ----------


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
    if N > 0:
        deduped: Dict[Tuple[str, int, int], RatingResult] = {}
        for result in results:
            identity = duplicate_identity_key(int(result.song_id), int(result.level))
            current = deduped.get(identity)
            if current is None or float(result.AI_rating) > float(current.AI_rating):
                deduped[identity] = result
        results = list(deduped.values())
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
def _snapshot_userdata_root(userdata_dir):
    return userdata_dir if userdata_dir is not None else os.environ.get("TAIKO_USERDATA_DIR", str(_runtime_root() / 'userdata'))


def getUtime(user_id, *, userdata_dir: str | Path | None = None):
    with score_read_view(_snapshot_userdata_root(userdata_dir), str(user_id)) as view:
        try:
            ts = round(view.file_times("current")["ctime"])
        except FileNotFoundError:
            return None
        return str(datetime.datetime.fromtimestamp(ts))


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


def _get_recommend_identity_key(song_id, level):
    return duplicate_identity_key(song_id, level)


def _build_song_index_by_identity(songs):
    default_ids, _ = identity_inputs()
    return domain_catalog._build_song_index_by_identity(songs, default_ids)


def _find_song_info_for_recommend_record(song_id, level, idx_by_id_level, idx_by_identity):
    default_ids, _ = identity_inputs()
    return domain_catalog._find_song_info_for_recommend_record(song_id, level, idx_by_id_level, idx_by_identity, default_ids)


def build_all_stats_for_user(user_id, json_path="./songs/rating_structured_with_ids.json", *, collapse_duplicate_versions=True):
    records = read_current_json(os.environ.get("TAIKO_USERDATA_DIR", "./userdata"), str(user_id))["songs"]
    cfg = load_rating_config(json_path)
    default_ids, _ = identity_inputs()
    return domain_candidates.build_all_stats_from_records(records, cfg,
        collapse_duplicate_versions=collapse_duplicate_versions, default_ids=default_ids)


def collapse_stats_for_recommendation(stats):
    default_ids, _ = identity_inputs()
    return domain_candidates.collapse_stats_for_recommendation(stats, default_ids=default_ids)


def recommend_songs(all_stats, songs_cfg, const_table, best_key="rating", limit=20):
    default_ids, _ = identity_inputs()
    return domain_candidates.recommend_songs(all_stats, songs_cfg, const_table, best_key, limit,
        default_ids=default_ids, cn_available_chart_keys=load_cn_available_chart_keys(),
        on_shelf_song_ids=load_on_shelf_song_ids())


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
