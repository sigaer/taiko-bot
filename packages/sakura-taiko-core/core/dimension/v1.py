from __future__ import annotations
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple, Iterable, Literal, Sequence
from ..models.calculation import SongMetrics, RatingResult, SongStats, V2SongData, V2RatingResult, FullScoreRef
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
