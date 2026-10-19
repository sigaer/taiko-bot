from __future__ import annotations


from sakura_taiko_core.rating.v1 import build_const_table, aggregate_topN_value, compute_dim_topN_means

from sakura_taiko_core.models.calculation import RatingResult

from sakura_taiko_core.score import calculation as domain_calculation

from .taiko_domain_adapter import identity_inputs

import json

import math

import os

from pathlib import Path

from typing import Dict, List, Any, Tuple

from io import BytesIO

if os.environ.get("TAIKO_COMPUTE_ONLY") != "1":
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from matplotlib import font_manager
    from matplotlib.transforms import offset_copy

from .duplicate_versions import build_duplicate_song_groups, duplicate_identity_key

PAIR_ID_GROUPS = build_duplicate_song_groups()

PAIR_ID_MAP = {
    song_id: idx for idx, pair in enumerate(PAIR_ID_GROUPS) for song_id in pair
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
    default_ids, duplicate_groups = identity_inputs()
    return domain_calculation._compute_results_from_userdata_records(
        userdata_records, cfg, const_table, collapse_duplicate_versions=collapse_duplicate_versions,
        duplicate_groups=duplicate_groups, default_ids=default_ids)

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


def generate_top_N_image(
    results: List[RatingResult],
    N: int = 20,
    user_id=None,
    dynamic_origin=False,
    font_path: str | None = None,
    observed_at=None,
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
            title=f"六维属性（top{N} 加权平均）\n更新于{observed_at}",
            font_path=font_path,
            dynamic_origin=dynamic_origin,
        )
    else:
        fig, ax = plot_radar_from_values(
            dim_means,
            title=f"六维属性（各自 top{N} 均值）\n更新于{observed_at}",
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
