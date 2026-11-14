"""Discrete target inversion using the installed Rating kernels."""
from __future__ import annotations

import math
from collections.abc import Mapping

from sakura_taiko_core.models.calculation import V2SongData
from sakura_taiko_core.rating.target import SongRatingTargetResult
from sakura_taiko_core.rating.v2 import _calculate_v2_from_chart


def compute_v2_rating_target(chart: V2SongData, target_rating: float) -> SongRatingTargetResult:
    notes = chart.total_notes
    if notes <= 0:
        raise ValueError("谱面音符数数据不完整。")
    if not math.isfinite(target_rating) or target_rating <= 0:
        raise ValueError("目标 Rating 必须为正有限数。")

    def rating(ok_count: int) -> float:
        return _calculate_v2_from_chart(
            chart, accuracy_per=1.0 - 0.5 * ok_count / notes, bad_per=0.0,
            profile="v2-center-20261010",
        ).AI_rating

    maximum = rating(0)
    if maximum + 1e-12 < target_rating:
        return SongRatingTargetResult(False, target_rating, maximum, maximum, notes, 0, notes, 1.0)
    # The center's v2 record policy excludes precision below 75%.
    low, high = 0, notes // 2
    while low < high:
        middle = (low + high + 1) // 2
        if rating(middle) + 1e-12 >= target_rating:
            low = middle
        else:
            high = middle - 1
    return SongRatingTargetResult(
        True, target_rating, rating(low), maximum, notes - low, low, notes,
        1.0 - 0.5 * low / notes,
    )


def format_rating_targets(
    title: str, level_label: str, target_rating: float,
    results: Mapping[str, SongRatingTargetResult | str],
) -> str:
    sections = [f"歌曲：{title}（{level_label}）\n目标单曲 Rating：{target_rating:g}\n按无不可计算，连打不影响 Rating。"]
    for version in ("v1", "v2"):
        result = results[version]
        if isinstance(result, str):
            body = result
        elif not result.reachable:
            body = f"即使全良也无法达到，最高约为 {result.max_rating:.2f}。"
        else:
            body = (
                f"最低良数：{result.good_count}\n最多可数：{result.ok_count}\n"
                f"精度：{result.accuracy * 100:.2f}%\n预计单曲 Rating：{result.achieved_rating:.2f}"
            )
        sections.append(f"【Rating {version}】\n{body}")
    sections.append("v2 按精度不低于 75% 的成绩计入规则计算。")
    return "\n\n".join(sections)
