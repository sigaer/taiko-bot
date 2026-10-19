from __future__ import annotations


from . import catalog as _domain

from sakura_taiko_core.rating import v1 as _v1

from sakura_taiko_core.models import calculation as _models

from sakura_taiko_core.chart import client_groups as _client_groups

from sakura_taiko_core.score import calculation as _calculation

from sakura_taiko_core.recommendation import candidates as _candidates

import json

from pathlib import Path

from typing import Dict, List, Optional, Any

import matplotlib.pyplot as plt

from io import BytesIO

from matplotlib import font_manager

from matplotlib.transforms import offset_copy

from taiko_bot.settings import get_settings


from .song_visibility import is_song_publicly_visible

UNPLAYED_BG = "#E8F3FF"  # 非常浅的蓝色，不影响可读性

POSITIVE_COLOR = "#2E7D32"  # 淡绿（正向）

NEGATIVE_COLOR = "#C62828"  # 淡红（负向）

NEUTRAL_COLOR = "#000000"  # 黑色

def build_duplicate_song_groups(song_data_path=get_settings().root_dir / "songs/song_data.json"):
    try: rows = json.loads(Path(song_data_path).read_text(encoding="utf-8"))
    except Exception: rows = []
    return _client_groups.build_rating_duplicate_groups(rows)

PAIR_ID_GROUPS = build_duplicate_song_groups()

PAIR_ID_MAP = {
    song_id: idx for idx, pair in enumerate(PAIR_ID_GROUPS) for song_id in pair
}

RatingResult = _models.RatingResult

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

build_const_table = _v1.build_const_table

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
    groups, pair_ids = _domain.rating_identity_inputs()
    return _calculation._compute_results_from_userdata_records(userdata_records, cfg, const_table,
        collapse_duplicate_versions=collapse_duplicate_versions, duplicate_groups=groups,
        default_ids=pair_ids, visible_song_ids=_domain.visibility_inputs(userdata_records, cfg["songs"]),
        identity_namespace="pair")

def build_all_stats_from_records(records, json_path="./songs/rating_structured_with_ids.json"):
    cfg = load_rating_config(json_path)
    _, pair_ids = _domain.rating_identity_inputs()
    return _candidates.build_all_stats_from_records(records, cfg,
        default_ids=pair_ids, visible_song_ids=_domain.visibility_inputs(records, cfg["songs"]),
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
    _, pair_ids = _domain.rating_identity_inputs()
    on_shelf = load_on_shelf_song_ids()
    if not on_shelf:
        return []
    return _candidates.recommend_songs(all_stats, songs_cfg, const_table, best_key, limit,
        default_ids=pair_ids, visible_song_ids=_domain.visibility_inputs(songs=songs_cfg),
        on_shelf_song_ids=on_shelf, identity_namespace="pair")

def compute_recommendations_from_records(
    records: list,
    best_key: str = "rating",
    limit: int = 20,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
) -> List[dict]:
    """Calculate recommendations from already authorized records."""
    all_stats, songs_cfg, const_table = build_all_stats_from_records(
        records, json_path=json_path
    )
    return recommend_songs(
        all_stats, songs_cfg, const_table, best_key=best_key, limit=limit
    )
