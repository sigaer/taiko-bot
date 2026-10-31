"""Extracted numerical value types. Field layouts preserve legacy outputs."""

from __future__ import annotations

from dataclasses import dataclass

from typing import List, Dict, Any, Optional, Tuple

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

@dataclass
class ClientSongStats:
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

@dataclass
class SongStats(ClientSongStats):
    accuracy: float = 0.0

@dataclass(frozen=True)
class V2SongData:
    song_id: int
    level: int
    title: str
    total_notes: int
    sub_constant_1: float
    main_constant: float
    sub_constant_2: float
    stamina: float
    handspeed: float
    burst: float
    complex: float
    rhythm: float

@dataclass
class V2RatingResult:
    song_id: int
    level: int
    song_name: str
    high_score: int
    accuracy: float
    bad_rate: float
    AI_rating: float
    stamina_rt: float
    handspeed_rt: float
    burst_rt: float
    complex_rt: float
    rhythm_rt: float
    accuracy_rt: float

@dataclass(frozen=True)
class FullScoreRef:
    threshold: float
    fullA: float
    fullB: float
