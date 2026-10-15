
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
from taiko_bot.userdata_provider import get_cached_userdata

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
