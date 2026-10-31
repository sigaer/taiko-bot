from __future__ import annotations
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, Iterable, Literal, Sequence
from ..models.calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef
RatingAlgorithm = Literal["great-only", "comprehensive"]

ACCURACY_WEIGHTS = {
    "great-only": {"GREAT": 1.0, "GOOD": 0.0},
    "comprehensive": {"GREAT": 1.0, "GOOD": 0.5},
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

def compute_P(M: float, N: float, P1: float = 150.0) -> float:
    """
    对应：
    = $P$1 - SQRT( POWER($P$1,2) - POWER(M3-N3,2)/2 )
    """
    diff = M - N
    inner = P1**2 - (diff**2) / 2.0
    inner = max(inner, 0.0)
    return P1 - math.sqrt(inner)

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
    if col == "AI_rating" and results and not hasattr(results[0], "AI_rating"):
        attr = "rating"
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
