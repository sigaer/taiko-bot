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

from .snapshot_history import list_snapshot_files, parse_snapshot_time
from .song_visibility import (
    is_song_id_publicly_visible,
    is_song_publicly_visible,
)

USERDATA_DIR = get_settings().userdata_dir

# ---------- 数据结构 ----------
UNPLAYED_BG = "#E8F3FF"  # 非常浅的蓝色，不影响可读性
POSITIVE_COLOR = "#2E7D32"  # 淡绿（正向）
NEGATIVE_COLOR = "#C62828"  # 淡红（负向）
NEUTRAL_COLOR = "#000000"  # 黑色
RatingAlgorithm = Literal["great-only", "comprehensive"]
ACCURACY_WEIGHTS = {
    "great-only": {"GREAT": 1.0, "GOOD": 0.0},
    "comprehensive": {"GREAT": 1.0, "GOOD": 0.5},
}
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


def _normalize_duplicate_song_level_signature(song: Dict[str, Any]) -> Tuple[str, ...]:
    return tuple(str(song.get(f"level_{level}") or "").strip() for level in range(1, 6))


def build_duplicate_song_groups(
    song_data_path: str | Path = get_settings().root_dir / "songs" / "song_data.json",
) -> List[Tuple[int, ...]]:
    """
    构建推荐流程的“同曲多 ID”分组。
    - 保留手工维护的已知共谱分组
    - 自动补充：song_data 中曲名完全一致且难度签名一致的多 ID 曲目
    """

    group_candidates: List[Tuple[int, ...]] = [tuple(group) for group in MANUAL_PAIR_ID_GROUPS]
    try:
        song_data = load_json(song_data_path)
    except Exception:
        song_data = []

    if isinstance(song_data, list):
        duplicate_ids_by_signature: Dict[Tuple[str, Tuple[str, ...]], Set[int]] = {}
        for item in song_data:
            if not isinstance(item, dict):
                continue
            if not is_song_publicly_visible(item):
                continue
            title = str(item.get("song_name") or "").strip()
            if not title:
                continue
            try:
                song_id = int(item.get("id"))
            except Exception:
                continue
            signature = (title, _normalize_duplicate_song_level_signature(item))
            duplicate_ids_by_signature.setdefault(signature, set()).add(song_id)

        for ids in duplicate_ids_by_signature.values():
            if len(ids) > 1:
                group_candidates.append(tuple(sorted(ids)))

    parent: Dict[int, int] = {}

    def find(song_id: int) -> int:
        root = parent.setdefault(song_id, song_id)
        if root != song_id:
            parent[song_id] = find(root)
        return parent[song_id]

    def union(left: int, right: int) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for group in group_candidates:
        normalized = [int(song_id) for song_id in group]
        if len(normalized) < 2:
            continue
        for song_id in normalized:
            parent.setdefault(song_id, song_id)
        anchor = normalized[0]
        for song_id in normalized[1:]:
            union(anchor, song_id)

    merged: Dict[int, Set[int]] = {}
    for song_id in list(parent):
        merged.setdefault(find(song_id), set()).add(song_id)

    return sorted(
        [tuple(sorted(song_ids)) for song_ids in merged.values() if len(song_ids) > 1]
    )


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


@dataclass
class SongMetrics:
    """最终用于六维属性的四个谱面维度（AD/AE/AF/AG）"""

    complex_proc: float  # AD 复合处理
    stamina: float  # AE 体力
    speed: float  # AF 高速处理
    rhythm: float  # AG 节奏处理


@dataclass
class RatingResult:
    """返回：综合 AI + 六维 + 中间变量"""

    song_id: int
    level: int
    song_name: str
    high_score: int
    const_value: float  # F 列：定数
    accuracy: float  # G 列：良率(0~1)

    M_const_score: float  # M 列：定数得点
    N_acc_score: float  # N 列：精度得点
    raw_complex_proc: float  # AD 复合处理原值
    raw_stamina: float  # AE 体力原值
    raw_speed: float  # AF 高速处理原值
    raw_rhythm: float  # AG 节奏处理原值
    P_param: float  # P 列：幂指数参数
    Q_weight: float  # Q 列：二维权重
    AI_rating: float  # AI 列：综合 rating

    big_song: float  # AJ 大歌力
    stamina: float  # AK 体力
    speed: float  # AL 高速处理
    accuracy_power: float  # AM 精度力
    rhythm: float  # AN 节奏处理
    complex_proc: float  # AO 复合处理


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


def build_const_table(const_map: Dict[str, float]) -> List[tuple]:
    """
    const_map: {"1.0": 0.05, "1.5": 0.10, ...}
    转成按定数排序的列表 [(1.0,0.05), (1.5,0.10), ...]
    """
    items: List[tuple] = []
    for k, v in const_map.items():
        items.append((float(k), float(v)))
    items.sort(key=lambda x: x[0])
    return items


def lookup_const_score(const_value: float, table: List[tuple]) -> float:
    """
    对应 M 列：
    =INDEX(Sheet2!$B$2:$B$64, MATCH(F3,Sheet2!$A$2:$A$64,0))
    这里做了插值 + 边界 clamp。
    """
    if not table:
        raise ValueError("Const table is empty")

    c = float(const_value)

    if c <= table[0][0]:
        return table[0][1]
    if c >= table[-1][0]:
        return table[-1][1]

    prev_c, prev_s = table[0]
    for cc, ss in table[1:]:
        if abs(cc - c) < 1e-9:
            return ss
        if c < cc:
            t = (c - prev_c) / (cc - prev_c)
            return prev_s + t * (ss - prev_s)
        prev_c, prev_s = cc, ss

    return table[-1][1]


# ---------- 2. 良率 G → N 列（精度得点） ----------
def calc_accuracy(
    total_notes: int,
    great_cnt: int,
    good_cnt: int,
    algorithm: RatingAlgorithm = "comprehensive",
) -> float:
    """
    TS: calcAccuracy(totalNotes, userScore, algorithm)
    accuracy = (great*Wg + good*Wk)/totalNotes
    threshold: great-only 0.5, comprehensive 0.75
    < threshold -> 0
    """
    if total_notes <= 0:
        return 0.0
    w = ACCURACY_WEIGHTS[algorithm]
    acc = (great_cnt * w["GREAT"] + good_cnt * w["GOOD"]) / float(total_notes)
    acc = max(0.0, min(1.0, acc))
    threshold = 0.5 if algorithm == "great-only" else 0.75
    return 0.0 if acc < threshold else acc


def _calc_accuracy_for_record(
    total_notes: int,
    great_cnt: int,
    good_cnt: int,
    dondaful_combo_cnt: int,
    algorithm: RatingAlgorithm = "comprehensive",
) -> float:
    if dondaful_combo_cnt > 0:
        return 1.0
    return calc_accuracy(
        total_notes=total_notes,
        great_cnt=great_cnt,
        good_cnt=good_cnt,
        algorithm=algorithm,
    )


def calc_y(
    accuracy: float,
    normalization_factor: float = 15.5,
    algorithm: RatingAlgorithm = "comprehensive",
) -> float:
    """
    TS: calcY(accuracy, algorithm)
    great-only: 旧Excel分段
    comprehensive: 新分段 + 高段归一化拉伸到 NORMALIZATION_FACTOR
    """
    if algorithm == "great-only":
        g0, g1, g2 = 0.5, 0.6832, 0.9625

        def y1(a):
            return 4425 * (a - 0.5) ** 4.876

        def y2(a):
            return 30.748 * a - 19.88

        def y3(a):
            return 0.228 * (2.718 ** (3.386 * (a**24.658))) + 8.862

    else:
        g0, g1, g2 = 0.75, 0.8278, 0.9793

        def y1(a):
            return 16730 * (a - 0.75) ** 3.805

        def y2(a):
            return 56.4468 * a - 45.7187

        def y3(a):
            return 0.2246 * (2.718 ** (120 * (a - 0.972))) + 9.02

    if accuracy <= g0:
        return 0.0
    if accuracy <= g1:
        return float(y1(accuracy))
    if accuracy <= g2:
        return float(y2(accuracy))

    # 高段：归一化拉伸，使 accuracy=1 对齐到 NORMALIZATION_FACTOR
    y_g2 = float(y3(g2))
    y_1 = float(y3(1.0))
    if abs(y_1 - y_g2) < 1e-12:
        return normalization_factor
    return y_g2 + (float(y3(accuracy)) - y_g2) / (y_1 - y_g2) * (
        normalization_factor - y_g2
    )


def accuracy_to_score(G: float) -> float:
    """
    对应 N 列公式：
    =IF(AND(G3>=0.5,G3<=0.6832),
         4425*POWER(G3-0.5,4.876),
       IF(AND(G3>0.6832,G3<=0.9625),
         30.748*G3-19.88,
         0.228*POWER(2.718,3.386*POWER(G3,24.658))+8.862))
    """
    g = float(G)
    if g < 0.5:
        return 0
    if 0.5 <= g <= 0.6832:
        return 4425 * (g - 0.5) ** 4.876
    elif 0.6832 < g <= 0.9625:
        return 30.748 * g - 19.88
    else:
        return 0.228 * math.exp(3.386 * (g**24.658)) + 8.862


# ---------- 3. P 列：幂指数参数 ----------


def compute_P(M: float, N: float, P1: float = 150.0) -> float:
    """
    对应：
    = $P$1 - SQRT( POWER($P$1,2) - POWER(M3-N3,2)/2 )
    """
    diff = M - N
    inner = P1**2 - (diff**2) / 2.0
    inner = max(inner, 0.0)
    return P1 - math.sqrt(inner)


# ---------- 4. Q 列：二维权重 ----------


def compute_Q(M: float, N: float) -> float:
    """
    对应：
    =MAX(
       SQRT(25 - POWER(M3-15.5,2)/25 - POWER(N3-23,2)/69) - 4,
       0.5
     )
    """
    term = 25 - (M - 15.5) ** 2 / 25.0 - (N - 23.0) ** 2 / 69.0
    if term < 0:
        base = 0.0
    else:
        base = math.sqrt(term) - 4.0
    return max(base, 0.5)


# ---------- 5. AI 列：综合 rating（幂平均） ----------


def compute_AI(M: float, N: float, P: float, Q: float) -> float:
    """
    对应：
    =POWER(Q3*POWER(M3,P3)+(1-Q3)*POWER(N3,P3),1/P3)
    """
    if abs(P) < 1e-9:
        m = max(M, 1e-9)
        n = max(N, 1e-9)
        return math.exp(Q * math.log(m) + (1 - Q) * math.log(n))

    value = Q * (M**P) + (1.0 - Q) * (N**P)
    value = max(value, 0.0)
    return value ** (1.0 / P)


# ---------- 6. 由 H~L 计算 AD,AE,AF,AG ----------


def compute_AD_AE_AF_AG(song_info: dict) -> SongMetrics:
    """
    H：AD = 复合处理
    I：平均密度
    J：瞬间密度
    K：叩き分け
    L：BPM变化

    AD = H
    AE = IF(I>J, I+(I/100)*(1-J/I)*(100-I), I-(1-I/J)*I)
    AF = IF(J>I, J-(1-I/J)*(J-I),       J+(1-J/I)*(I-J))
    AG = K + (K/100)*(L/100)*(100-K)
    """

    def fnum(x, default=0.0):
        try:
            return float(x)
        except Exception:
            return default

    H = fnum(song_info.get("复合处理", 0.0))
    I = fnum(song_info.get("平均密度", 0.0))
    J = fnum(song_info.get("瞬间密度", 0.0))
    K = fnum(song_info.get("叩き分け", 0.0))
    L = fnum(song_info.get("BPM变化", 0.0))

    # AD
    AD = H

    # 数值安全防止除零
    eps = 1e-9

    # AE 体力
    if I <= eps and J <= eps:
        AE = 0.0
    elif I > J:
        AE = I + (I / 100.0) * (1.0 - J / max(I, eps)) * (100.0 - I)
    else:
        AE = I - (1.0 - I / max(J, eps)) * I

    # AF 高速处理
    if I <= eps and J <= eps:
        AF = 0.0
    elif J > I:
        AF = J - (1.0 - I / max(J, eps)) * (J - I)
    else:
        AF = J + (1.0 - J / max(I, eps)) * (I - J)

    # AG 节奏处理
    AG = K + (K / 100.0) * (L / 100.0) * (100.0 - K)

    return SongMetrics(
        complex_proc=AD,
        stamina=AE,
        speed=AF,
        rhythm=AG,
    )


# ---------- 7. 六维属性 AJ~AO ----------


def _scale_dim(dim_0_100: float) -> float:
    """谱面维度 0–100 映射到 ~0–15.5，对应 *15.5/100"""
    return float(dim_0_100) * 15.5 / 100.0


def compute_six_dims(
    AI: float, M: float, N: float, metrics: SongMetrics
) -> Dict[str, float]:
    """
    对应 6 列：
    AJ 大歌力 =SQRT(AI3*M3)
    AK 体力   =SQRT(AI3*AE3*15.5/100)
    AL 高速   =SQRT(AI3*AF3*15.5/100)
    AM 精度力 =SQRT(AI3*N3)
    AN 节奏   =SQRT(AI3*AG3*15.5/100)
    AO 复合   =SQRT(AI3*AD3*15.5/100)
    """
    AI = float(AI)
    M = float(M)
    N = float(N)

    big_song = math.sqrt(max(AI * M, 0.0))
    stamina = math.sqrt(max(AI * _scale_dim(metrics.stamina), 0.0))
    speed = math.sqrt(max(AI * _scale_dim(metrics.speed), 0.0))
    accuracy_pow = math.sqrt(max(AI * N, 0.0))
    rhythm = math.sqrt(max(AI * _scale_dim(metrics.rhythm), 0.0))
    complex_power = math.sqrt(max(AI * _scale_dim(metrics.complex_proc), 0.0))

    return {
        "大歌力": big_song,
        "体力": stamina,
        "高速处理": speed,
        "精度力": accuracy_pow,
        "节奏处理": rhythm,
        "复合处理": complex_power,
    }


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
    if userdata_blob is None:
        userdata_path = USERDATA_DIR / f"{user_id}data.json"
        userdata_blob = load_json(userdata_path)  # 读取用户数据
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


def _compute_results_from_userdata_records(
    userdata_records: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    const_table: List[tuple],
    *,
    collapse_duplicate_versions: bool = True,
) -> List[RatingResult]:
    songs = cfg["songs"]
    idx = _build_song_index_by_id_level(songs)
    idx_by_identity = _build_song_index_by_identity(songs)
    best_pair_keys: Dict[int, Tuple[int, int]] = {}
    best_pair_acc: Dict[int, float] = {}
    if collapse_duplicate_versions:
        for rec in userdata_records:
            try:
                song_no = int(rec.get("song_no"))
                level = int(rec.get("level"))
            except Exception:
                continue
            if not is_song_id_publicly_visible(song_no):
                continue
            pair_id = PAIR_ID_MAP.get(song_no)
            if pair_id is None:
                continue
            found = _find_song_info_for_recommend_record(
                song_no, level, idx, idx_by_identity
            )
            if not found:
                continue
            _, song_info = found
            total_notes = int(song_info.get("combo", 0) or 0)
            good_cnt = int(rec.get("good_cnt", 0) or 0)
            ok_cnt = int(rec.get("ok_cnt", 0) or 0)
            dondaful_cnt = int(rec.get("dondaful_combo_cnt", 0) or 0)
            accuracy = _calc_accuracy_for_record(
                total_notes=total_notes,
                great_cnt=good_cnt,
                good_cnt=ok_cnt,
                dondaful_combo_cnt=dondaful_cnt,
                algorithm="comprehensive",
            )
            if accuracy > best_pair_acc.get(pair_id, -1.0):
                best_pair_acc[pair_id] = accuracy
                best_pair_keys[pair_id] = (song_no, level)
    results: List[RatingResult] = []
    for user_record in userdata_records:
        song_no = user_record["song_no"]
        level = user_record["level"]
        if level < 4:
            continue
        if not is_song_id_publicly_visible(song_no):
            continue
        if collapse_duplicate_versions:
            pair_id = PAIR_ID_MAP.get(song_no)
            if pair_id is not None and best_pair_keys.get(pair_id) != (song_no, level):
                continue
        good_cnt = int(user_record.get("good_cnt", 0) or 0)  # 良
        ok_cnt = int(user_record.get("ok_cnt", 0) or 0)  # 可

        # 查找对应的歌曲
        found = _find_song_info_for_recommend_record(song_no, level, idx, idx_by_identity)
        song_name = None
        if found:
            song_key, song_info = found
            song_name = songs[song_key]["song_name_cn"]
            if level == 5:
                song_name += "(里谱)"

        if not song_name:
            print(
                f"警告：歌曲 {song_no} (level {level}) 在 structured JSON 中未找到匹配"
            )
            continue

        # 获取歌曲的定数（score）
        const_value = song_info["score"]

        # 根据 good_cnt 计算良率
        total_notes = int(song_info.get("combo", 0) or 0)
        dondaful_cnt = int(user_record.get("dondaful_combo_cnt", 0) or 0)
        accuracy = _calc_accuracy_for_record(
            total_notes=total_notes,
            great_cnt=good_cnt,
            good_cnt=ok_cnt,
            dondaful_combo_cnt=dondaful_cnt,
            algorithm="comprehensive",
        )
        if accuracy == 0.0:
            continue  # comprehensive 阈值未达（<0.75），前端行为是直接丢弃

        # 由 H~L 计算 AD/AE/AF/AG
        metrics = compute_AD_AE_AF_AG(song_info)

        # 定数得点 M
        M = lookup_const_score(const_value, const_table)

        # 精度得点 N
        N = calc_y(
            accuracy=accuracy,
            normalization_factor=15.5,
            algorithm="comprehensive",
        )
        # P、Q
        P = compute_P(M, N)
        Q = compute_Q(M, N)

        # 综合 AI
        AI = compute_AI(M, N, P, Q)

        # 六维属性
        six = compute_six_dims(AI, M, N, metrics)

        results.append(
            RatingResult(
                song_id=song_no,
                level=level,
                song_name=song_name,
                high_score=int(user_record.get("high_score", 0) or 0),
                const_value=const_value,
                accuracy=accuracy,
                M_const_score=M,
                N_acc_score=N,
                raw_complex_proc=metrics.complex_proc,
                raw_stamina=metrics.stamina,
                raw_speed=metrics.speed,
                raw_rhythm=metrics.rhythm,
                P_param=P,
                Q_weight=Q,
                AI_rating=AI,
                big_song=six["大歌力"],
                stamina=six["体力"],
                speed=six["高速处理"],
                accuracy_power=six["精度力"],
                rhythm=six["节奏处理"],
                complex_proc=six["复合处理"],
            )
        )

    return results


# ---------- 排序并输出前20项 ----------
def get_top20_weighted_average(results: List[RatingResult], attr: str) -> float:
    """
    对应前端 getTop20WeightedAverage：
    - results: 一组对象（例如 RatingResult）
    - attr: 需要计算的字段名，例如 "AI_rating"、"big_song"、"stamina" 等
    返回：按 TS 逻辑计算的 top20 加权平均值
    """
    # 取出该字段的所有非空数值
    values = []
    for r in results:
        v = getattr(r, attr, None)
        if v is not None:
            values.append(float(v))

    if not values:
        return 0.0

    # 从大到小排序
    values.sort(reverse=True)

    # 取前 20
    top = values[:20]
    n = len(top)

    # TS 中的权重设计：
    # 1–5 名：40%（平均到 5 首，每首 0.4/5）
    # 6–10 名：30%（平均到 5 首，每首 0.3/5）
    # 11–16 名：20%（平均到 6 首，每首 0.2/6）
    # 17–20 名：10%（平均到 4 首，每首 0.1/4）
    base_weights = (
        [0.4 / 5] * 5 + [0.3 / 5] * 5 + [0.2 / 6] * 6 + [0.1 / 4] * 4
    )  # 共 20 项，和为 1

    # 如果不足 20 条，裁剪并重新归一化
    weights = base_weights[:n]
    w_sum = sum(weights)
    if w_sum == 0:
        return 0.0
    weights = [w / w_sum for w in weights]

    return sum(v * w for v, w in zip(top, weights))


def get_top20_median(results: List[RatingResult], attr: str) -> float:
    """
    对应前端 getTop20Median：
    从指定字段中取值 → 降序排序 → 取前 20 → 计算中位数
    """
    values = []
    for r in results:
        v = getattr(r, attr, None)
        if v is not None:
            values.append(float(v))

    if not values:
        return 0.0

    values.sort(reverse=True)
    top = values[:20]
    n = len(top)

    if n == 0:
        return 0.0
    if n % 2 == 1:
        # 奇数个：取中间那一个
        mid = n // 2
        return top[mid]
    else:
        # 偶数个：取中间两个的平均
        mid_right = n // 2
        mid_left = mid_right - 1
        return (top[mid_left] + top[mid_right]) / 2.0


def top_value_compensate(
    rating_mid: float,
    full_mid: float,
    rating_ave: float,
    full_ave: float,
    threshold: float,
    max_value: float = 15.5,
) -> float:
    """
    对应 TS 的 topValueCompensate：

    - rating_mid:  某一「评分子集」的 top20 中位数（例如：你真实游玩的曲目，AI_rating 的 top20 中位数）
    - full_mid:    「完整曲池」的 top20 中位数（例如：所有曲目在该维度的设定值 top20 中位数）
    - rating_ave:  「评分子集」的 top20 加权平均
    - full_ave:    「完整曲池」的 top20 加权平均
    - threshold:   补偿起点阈值（TS 中的 threshold）
    - max_value:   理论上限值，默认 15.5（对应定数/六维的最大值）

    返回：补偿后的“顶值评价”
    """
    # 若子集的加权平均还没到 threshold，直接用中位数，不做补偿
    if rating_ave < threshold:
        return rating_mid

    # 防止 full_ave == threshold 时的除零
    if full_ave <= threshold:
        # 理论上不会发生；保守起见直接返回 rating_mid
        return rating_mid

    per = (rating_ave - threshold) / (full_ave - threshold)
    # 线性插到 max_value 方向
    return rating_mid + per * (max_value - full_mid)


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


def aggregate_topN_value(results: List[RatingResult], col: str, N: int) -> float:
    """
    col: 中文列名（如“体力”“大歌力”），或 AI_rating
    """
    attr = CN_COL_TO_ATTR.get(col)
    if not attr:
        raise KeyError(f"未知维度列名: {col}")

    values = [
        float(getattr(r, attr)) for r in results if getattr(r, attr, None) is not None
    ]

    if not values:
        return 0.0

    values.sort(reverse=True)
    top = values[:N]

    # N != 20：旧行为（算术平均）
    if N != 20:
        return float(sum(top) / len(top))

    # N == 20：TS 新版补偿算法
    full_params = TOP20_COMPENSATE_TABLE.get(col)
    if not full_params:
        # 没配置就降级
        mid = get_top20_median(results, attr)
        ave = get_top20_weighted_average(results, attr)
        return ave

    full_mid, full_ave, threshold = full_params
    rating_mid = get_top20_median(results, attr)
    rating_ave = get_top20_weighted_average(results, attr)

    return float(
        top_value_compensate(
            rating_mid, full_mid, rating_ave, full_ave, threshold, max_value=15.5
        )
    )


def compute_dim_topN_means(
    results: List[RatingResult], N: int = 20
) -> Dict[str, float]:
    """
    根据每个维度自己排序取 topN，再对该维度求平均。
    返回一个 dict: {维度名: 该维度 topN 的平均值}
    """
    # df = pd.DataFrame(
    #     [
    #         {
    #             "song_name": r.song_name,
    #             "AI_rating": r.AI_rating,
    #             "大歌力": r.big_song,
    #             "体力": r.stamina,
    #             "高速处理": r.speed,
    #             "精度力": r.accuracy_power,
    #             "节奏处理": r.rhythm,
    #             "复合处理": r.complex_proc,
    #         }
    #         for r in results
    #     ]
    # )

    dim_cols = ["大歌力", "体力", "高速处理", "精度力", "节奏处理", "复合处理"]
    dim_means: Dict[str, float] = {}

    for col in dim_cols:
        dim_means[col] = aggregate_topN_value(results, col, N)

    return dim_means


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
    if get_cached_userdata(str(user_id)) is not None:
        return str(datetime.datetime.now().replace(microsecond=0))
    path = str(USERDATA_DIR / f"{user_id}data.json")
    if os.path.exists(path):
        ts = round(os.path.getctime(path))
        return str(datetime.datetime.fromtimestamp(ts))
    else:
        return None


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
    if history_snapshots is not None:
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
        return snapshots

    history_dir = USERDATA_DIR / str(user_id)
    if not history_dir.exists():
        return []
    snapshot_files = list_snapshot_files(history_dir)
    if not snapshot_files:
        return []

    snapshots: List[Tuple[datetime.datetime, Dict[str, Any]]] = []
    current_profile: Dict[str, Any] = {}
    current_achievement: Dict[str, Any] = {}
    song_map: Dict[tuple, Dict[str, Any]] = {}
    has_base = False

    for path in snapshot_files:
        try:
            snapshot = load_json(path)
        except Exception:
            continue
        dt = parse_snapshot_time(path)
        meta = snapshot.get("_meta", {}) if isinstance(snapshot, dict) else {}
        is_full = bool(meta.get("full")) or (
            isinstance(snapshot, dict)
            and "songs" in snapshot
            and "profile" in snapshot
            and "achievement" in snapshot
            and not meta
        )

        if is_full:
            current_profile = snapshot.get("profile", {}) if isinstance(snapshot, dict) else {}
            current_achievement = snapshot.get("achievement", {}) if isinstance(snapshot, dict) else {}
            songs = snapshot.get("songs", []) if isinstance(snapshot, dict) else []
            song_map = {_song_key(s): s for s in songs}
            has_base = True
        else:
            if not has_base:
                continue
            if "profile" in snapshot:
                current_profile = snapshot.get("profile") or {}
            if "achievement" in snapshot:
                current_achievement = snapshot.get("achievement") or {}
            for s in snapshot.get("songs", []) or []:
                song_map[_song_key(s)] = s
            for key in snapshot.get("songs_removed", []) or []:
                song_map.pop(tuple(key), None)

        snapshots.append(
            (
                dt,
                {
                    "profile": current_profile,
                    "achievement": current_achievement,
                    "songs": list(song_map.values()),
                },
            )
        )

    return snapshots


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
    snapshots = load_user_snapshots(user_id, history_snapshots=history_snapshots)
    if not snapshots:
        return []

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
    snapshots = load_user_snapshots(user_id, history_snapshots=history_snapshots)
    if not snapshots:
        return []

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


@dataclass
class SongStats:
    """
    推荐算法用的用户侧统计对象（对齐 recommend.ts）
    title 只用于展示，推荐内部匹配必须依赖歌曲身份键，不能依赖标题。
    """

    title: str
    song_id: int
    level: int

    rating: float  # 对应：AI_rating
    daigouryoku: float  # 对应：大歌力
    stamina: float  # 对应：体力
    speed: float  # 对应：高速处理
    accuracy_power: float  # 对应：精度力
    rhythm: float  # 对应：节奏处理
    complex: float  # 对应：复合处理

    great: int  # userdata good_cnt
    good: int  # userdata ok_cnt
    bad: int  # userdata ng_cnt


def _median(values: List[float]) -> float:
    vs = sorted([float(v) for v in values if v is not None])
    n = len(vs)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return vs[mid]
    return (vs[mid - 1] + vs[mid]) / 2.0


def _build_song_index_by_id_level(songs: dict) -> Dict[tuple, tuple]:
    """
    (id, level) -> (song_key_in_cfg, song_info)
    注意：song_key_in_cfg 是 songs 字典的 key，不一定等于 song_name_cn
    """
    idx = {}
    for k in songs:
        info = songs[k]
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        idx[(sid, lvl)] = (k, info)
    return idx


def get_song_chart_identity_key(song_id: int, level: int) -> Tuple[str, int, int]:
    """
    推荐流程的歌曲身份键：
    - 已知双版本共谱歌曲：按 pair_id + level 视为同一项
    - 其余歌曲：按 song_id + level 区分
    """
    pair_id = PAIR_ID_MAP.get(song_id)
    if pair_id is not None:
        return ("pair", pair_id, level)
    return ("song", song_id, level)


def _get_recommend_identity_key(song_id: int, level: int) -> Tuple[str, int, int]:
    return get_song_chart_identity_key(song_id, level)


def _build_song_index_by_identity(songs: dict) -> Dict[tuple, tuple]:
    """
    (identity_key) -> (song_key_in_cfg, song_info)
    用于推荐流程按歌曲身份匹配，避免同标题歌曲互相串歌。
    """
    idx = {}
    for k in songs:
        info = songs[k]
        try:
            sid = int(info.get("id"))
            lvl = int(info.get("level"))
        except Exception:
            continue
        if not is_song_id_publicly_visible(sid):
            continue
        idx.setdefault(_get_recommend_identity_key(sid, lvl), (k, info))
    return idx


def _find_song_info_for_recommend_record(
    song_id: int,
    level: int,
    idx_by_id_level: Dict[tuple, tuple],
    idx_by_identity: Dict[tuple, tuple],
) -> Optional[tuple]:
    """
    优先按原始 song_id + level 精确匹配；
    如果结构化曲库没有该 ID，则回退到“同曲组 + 同难度”的谱面信息。
    这样可以用同谱面版本完成计算，同时保留用户实际游玩的 song_id。
    """
    exact = idx_by_id_level.get((song_id, level))
    if exact is not None:
        return exact
    return idx_by_identity.get(_get_recommend_identity_key(song_id, level))


def _get_title_like_existing(song_info: dict, level: int) -> str:
    """
    完全复用你 compute_all_from_userdata 内的命名方式：
    title = song_info["song_name_cn"] + "(里谱)" if level==5
    这样 title 才能和你 RatingResult.song_name 保持一致，也能用于推荐。
    """
    title = song_info.get("song_name_cn") or song_info.get("曲名") or ""
    if level == 5:
        title += "(里谱)"
    return title


def _get_song_indicator_value(
    song_info: dict,
    dimension: str,
    const_table: List[tuple],
) -> float:
    """
    对齐你要求：
    - rating/daigouryoku/accuracy_power：来自 cfg["const_table"]["const_to_score"]（即 lookup_const_score）
    - stamina/speed/rhythm/complex：来自 AD/AE/AF/AG 原始值（compute_AD_AE_AF_AG）
    """
    const_value = float(song_info.get("score", 0.0) or 0.0)

    if dimension in ("rating", "daigouryoku", "accuracy_power"):
        return float(lookup_const_score(const_value, const_table))

    metrics = compute_AD_AE_AF_AG(song_info)
    if dimension == "stamina":
        return float(metrics.stamina)  # AE 原始
    if dimension == "speed":
        return float(metrics.speed)  # AF 原始
    if dimension == "rhythm":
        return float(metrics.rhythm)  # AG 原始
    if dimension == "complex":
        return float(metrics.complex_proc)  # AD 原始

    return 0.0


def build_all_stats_for_user(
    user_id: int,
    json_path: str | Path = "./songs/rating_structured_with_ids.json",
) -> tuple[List[SongStats], dict, List[tuple]]:
    """
    仅新增的“桥接层”：
    - 读 userdata
    - 读 cfg（songs + const_table）
    - 对每条用户成绩，计算 AI + 六维（复用你现有函数）
    - 不丢弃 accuracy<0.5：这类歌的 rating/六维记为0，但仍保留判定数，便于推荐做精度因子/已游玩判断
    返回：(all_stats, songs_cfg, const_table)
    """
    userdata_path = USERDATA_DIR / f"{user_id}data.json"
    userdata = load_json(userdata_path)["songs"]

    cfg = load_rating_config(json_path)
    songs = cfg["songs"]
    const_map = cfg["const_table"]["const_to_score"]
    const_table = build_const_table(const_map)
    idx = _build_song_index_by_id_level(songs)
    idx_by_identity = _build_song_index_by_identity(songs)

    best_identity_keys: Dict[Tuple[str, int, int], Tuple[int, int]] = {}
    best_identity_acc: Dict[Tuple[str, int, int], float] = {}
    for rec in userdata:
        try:
            song_no = int(rec.get("song_no"))
            level = int(rec.get("level"))
        except Exception:
            continue
        if not is_song_id_publicly_visible(song_no):
            continue
        identity_key = _get_recommend_identity_key(song_no, level)
        found = _find_song_info_for_recommend_record(
            song_no, level, idx, idx_by_identity
        )
        if not found:
            continue
        _, song_info = found
        total_notes = int(song_info.get("combo", 0) or 0)
        great = int(rec.get("good_cnt", 0) or 0)
        good = int(rec.get("ok_cnt", 0) or 0)
        dondaful_cnt = int(rec.get("dondaful_combo_cnt", 0) or 0)
        accuracy = _calc_accuracy_for_record(
            total_notes=total_notes,
            great_cnt=great,
            good_cnt=good,
            dondaful_combo_cnt=dondaful_cnt,
            algorithm="comprehensive",
        )
        if accuracy > best_identity_acc.get(identity_key, -1.0):
            best_identity_acc[identity_key] = accuracy
            best_identity_keys[identity_key] = (song_no, level)

    all_stats: List[SongStats] = []

    for rec in userdata:
        try:
            song_no = int(rec.get("song_no"))
            level = int(rec.get("level"))
        except Exception:
            continue
        if not is_song_id_publicly_visible(song_no):
            continue
        identity_key = _get_recommend_identity_key(song_no, level)
        if best_identity_keys.get(identity_key) != (song_no, level):
            continue

        found = _find_song_info_for_recommend_record(song_no, level, idx, idx_by_identity)
        if not found:
            continue

        song_key, song_info = found
        title = _get_title_like_existing(song_info, level)

        # 判定数
        great = int(rec.get("good_cnt", 0) or 0)
        good = int(rec.get("ok_cnt", 0) or 0)
        bad = int(rec.get("ng_cnt", 0) or 0)

        const_value = float(song_info.get("score", 0.0) or 0.0)
        # combo = float(song_info.get("combo", 0) or 0.0)
        # accuracy = (great / combo) if combo > 0 else 0.0

        # # 计算 AI + 六维（与原逻辑一致）
        # M = lookup_const_score(const_value, const_table)
        # N = accuracy_to_score(accuracy)

        # if N == 0:
        #     # 精度不足：按你已实现的行为，这类歌不会进入 rating 计算体系
        #     # 但推荐需要“已游玩”信息，因此保留一条 stats，分数置0
        #     all_stats.append(
        #         SongStats(
        #             title=title,
        #             song_id=song_no,
        #             level=level,
        #             rating=0.0,
        #             daigouryoku=0.0,
        #             stamina=0.0,
        #             speed=0.0,
        #             accuracy_power=0.0,
        #             rhythm=0.0,
        #             complex=0.0,
        #             great=great,
        #             good=good,
        #             bad=bad,
        #         )
        #     )
        #     continue
        total_notes = int(song_info.get("combo", 0) or 0)
        dondaful_cnt = int(rec.get("dondaful_combo_cnt", 0) or 0)
        accuracy = _calc_accuracy_for_record(
            total_notes=total_notes,
            great_cnt=great,
            good_cnt=good,
            dondaful_combo_cnt=dondaful_cnt,
            algorithm="comprehensive",
        )

        M = lookup_const_score(const_value, const_table)
        if accuracy == 0.0:
            # comprehensive 未达阈值：仍保留已游玩信息，但 rating/六维为0
            all_stats.append(
                SongStats(
                    title=title,
                    song_id=song_no,
                    level=level,
                    rating=0.0,
                    daigouryoku=0.0,
                    stamina=0.0,
                    speed=0.0,
                    accuracy_power=0.0,
                    rhythm=0.0,
                    complex=0.0,
                    great=great,
                    good=good,
                    bad=bad,
                )
            )
            continue

        N = calc_y(
            accuracy=accuracy, normalization_factor=15.5, algorithm="comprehensive"
        )
        P = compute_P(M, N)
        Q = compute_Q(M, N)
        AI = compute_AI(M, N, P, Q)

        metrics = compute_AD_AE_AF_AG(song_info)
        six = compute_six_dims(AI, M, N, metrics)

        all_stats.append(
            SongStats(
                title=title,
                song_id=song_no,
                level=level,
                rating=float(AI),
                daigouryoku=float(six["大歌力"]),
                stamina=float(six["体力"]),
                speed=float(six["高速处理"]),
                accuracy_power=float(six["精度力"]),
                rhythm=float(six["节奏处理"]),
                complex=float(six["复合处理"]),
                great=great,
                good=good,
                bad=bad,
            )
        )

    return all_stats, songs, const_table


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


def recommend_songs(
    all_stats: List[SongStats],
    songs_cfg: dict,
    const_table: List[tuple],
    best_key: str = "rating",
    limit: int = 20,
) -> List[dict]:
    """
    主推荐函数：复刻 recommend.ts 的总体行为（按你要求改 indicator 来源）
    best_key 支持：rating / daigouryoku / stamina / speed / accuracy_power / rhythm / complex
    返回 list[dict]，便于你直接转文字/转图片。
    """
    if not songs_cfg:
        return []
    if not all_stats:
        return []

    on_shelf_song_ids = load_on_shelf_song_ids()
    song_info_by_identity = _build_song_index_by_identity(songs_cfg)

    # 1) 用户侧 best20（按 best_key）
    best20 = sorted(all_stats, key=lambda s: float(getattr(s, best_key)), reverse=True)[
        :20
    ]
    best20_keys = {_get_recommend_identity_key(s.song_id, s.level) for s in best20}

    # 2) best20IndicatorMedian：best20 的“谱面侧指标”中位数
    best20_indicator_vals: List[float] = []
    for s in best20:
        found = song_info_by_identity.get(_get_recommend_identity_key(s.song_id, s.level))
        if not found:
            continue
        _, song_info = found
        v = _get_song_indicator_value(song_info, best_key, const_table)
        if v > 0:
            best20_indicator_vals.append(v)

    best20_indicator_median = _median(best20_indicator_vals)
    if best20_indicator_median <= 0:
        return []

    # 3) best20RatingMedian：用于“难度上限”过滤（谱面侧 rating 指标）
    best20_rating_vals: List[float] = []
    for s in best20:
        found = song_info_by_identity.get(_get_recommend_identity_key(s.song_id, s.level))
        if not found:
            continue
        _, song_info = found
        best20_rating_vals.append(
            _get_song_indicator_value(song_info, "rating", const_table)
        )

    best20_rating_median = _median(best20_rating_vals)

    # 4) 构造 candidates：全曲库 - best20；合并“已游玩/未游玩”
    played_map = {_get_recommend_identity_key(s.song_id, s.level): s for s in all_stats}
    seen_candidate_keys = set()

    candidates: List[dict] = []
    for k in songs_cfg:
        song_info = songs_cfg[k]
        try:
            song_id = int(song_info.get("id"))
        except Exception:
            song_id = None
        if song_id is None:
            continue
        if on_shelf_song_ids and song_id not in on_shelf_song_ids:
            continue

        lvl = int(song_info.get("level", 0) or 0)
        title = _get_title_like_existing(song_info, lvl)
        identity_key = _get_recommend_identity_key(song_id, lvl)

        if identity_key in best20_keys:
            continue
        if identity_key in seen_candidate_keys:
            continue
        seen_candidate_keys.add(identity_key)

        # rating 上限过滤：songRatingIndicator <= best20RatingMedian + 0.2
        song_rating_indicator = _get_song_indicator_value(
            song_info, "rating", const_table
        )
        if song_rating_indicator > best20_rating_median + 0.2:
            continue

        st = played_map.get(identity_key)
        is_unplayed = st is None
        if is_unplayed:
            st = SongStats(
                title=title,
                song_id=song_id,
                level=lvl,
                rating=0.0,
                daigouryoku=0.0,
                stamina=0.0,
                speed=0.0,
                accuracy_power=0.0,
                rhythm=0.0,
                complex=0.0,
                great=0,
                good=0,
                bad=0,
            )
        display_title = title
        display_song_id = song_id
        display_level = lvl
        if not is_unplayed:
            display_title = str(st.title)
            display_song_id = int(st.song_id)
            display_level = int(st.level)

        # 谱面侧 best_key 指标
        song_indicator = _get_song_indicator_value(song_info, best_key, const_table)
        if song_indicator <= 0:
            continue

        user_score_value = float(getattr(st, best_key))

        # accuracyFactor：未游玩=0.5；已游玩 acc>=0.5 => 1-acc；否则=1
        total_notes = float(song_info.get("combo", 0) or 0)
        if is_unplayed:
            user_acc = 0.0
            accuracy_factor = 0.5
        else:
            # user_acc = (st.great / total_notes) if total_notes > 0 else 0.0
            # if user_acc >= 0.5:
            #     accuracy_factor = 1.0 - user_acc
            # else:
            #     accuracy_factor = 1.0
            user_acc = 0.0
            if total_notes > 0:
                user_acc = (st.great + 0.5 * st.good) / total_notes

            if user_acc >= 0.5:
                accuracy_factor = 1.0 - user_acc
            else:
                accuracy_factor = 1.0
        indicator_dev_signed = (
            song_indicator - best20_indicator_median
        ) / best20_indicator_median
        indicator_dev_abs = abs(indicator_dev_signed)
        score_dev = (
            abs(user_score_value - best20_indicator_median) / best20_indicator_median
        )

        balance_score = (
            indicator_dev_abs * 1.0 - score_dev * 2.0 - accuracy_factor * 1.5
        )

        is_in_strict_range = (
            song_indicator <= best20_indicator_median * 1.05
            and song_indicator >= best20_indicator_median * 0.90
        )

        candidates.append(
            {
                "title": display_title,
                "song_id": display_song_id,
                "level": display_level,
                "is_unplayed": is_unplayed,
                "recommend_score": balance_score,
                "indicator_deviation_percent": indicator_dev_signed,  # 展示
                "indicator_deviation_abs": indicator_dev_abs,  # 排序
                "score_deviation_percent": score_dev,
                "user_indicator": user_score_value,
                "reference_indicator": best20_indicator_median,
                "accuracy": user_acc,
                "accuracy_factor": accuracy_factor,
                "is_in_strict_range": is_in_strict_range,
                "song_indicator": song_indicator,
                "rating_indicator": song_rating_indicator,
            }
        )

    # 5) 未游玩额外阈值：indicatorDev<=0.10
    UNPLAYED_INDICATOR_DEVIATION_THRESHOLD = 0.10
    unplayed = [
        c
        for c in candidates
        if c["is_unplayed"]
        and c["indicator_deviation_abs"] <= UNPLAYED_INDICATOR_DEVIATION_THRESHOLD
    ]
    played = [c for c in candidates if not c["is_unplayed"]]

    # 6) 分层排序
    strict_unplayed = [c for c in unplayed if c["is_in_strict_range"]]
    strict_played = [c for c in played if c["is_in_strict_range"]]
    loose_unplayed = [c for c in unplayed if not c["is_in_strict_range"]]
    loose_played = [c for c in played if not c["is_in_strict_range"]]

    # 严格范围：按 recommend_score 升序（未游玩优先由先拼接保证）
    strict_unplayed.sort(key=lambda c: c["recommend_score"])
    strict_played.sort(key=lambda c: c["recommend_score"])

    # 非严格范围：按 indicator 偏差升序
    loose_unplayed.sort(key=lambda c: c["indicator_deviation_abs"])
    loose_played.sort(key=lambda c: c["indicator_deviation_abs"])

    # 7) 输出：尽量未游玩/已游玩各一半
    half = int(limit) // 2
    out: List[dict] = []

    def take(src: List[dict], k: int):
        nonlocal out
        if k <= 0 or not src:
            return
        out.extend(src[:k])
        del src[:k]

    take(strict_unplayed, min(half, len(strict_unplayed)))
    take(strict_played, min(limit - len(out), len(strict_played)))

    if len(out) < limit:
        need_unplayed = max(0, half - len([x for x in out if x["is_unplayed"]]))
        take(loose_unplayed, min(need_unplayed, len(loose_unplayed)))
    if len(out) < limit:
        take(loose_played, min(limit - len(out), len(loose_played)))

    if len(out) < limit:
        take(loose_unplayed, min(limit - len(out), len(loose_unplayed)))
    if len(out) < limit:
        take(strict_unplayed, min(limit - len(out), len(strict_unplayed)))
    if len(out) < limit:
        take(strict_played, min(limit - len(out), len(strict_played)))

    return out[:limit]


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
