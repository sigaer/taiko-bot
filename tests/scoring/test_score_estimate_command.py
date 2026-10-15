from __future__ import annotations

import pytest

from taiko_bot.runtime.player.center.score_handlers import (
    _format_score_estimate_message,
    _parse_score_estimate_request,
    _resolve_score_estimate_query,
)
from sakura_taiko_core.recommendation.estimator import ChartScoreEstimate, ScoreEstimateSnapshot


def _snapshot(score: int) -> ScoreEstimateSnapshot:
    return ScoreEstimateSnapshot(
        score=score,
        raw_score=float(score),
        good_rate=0.97,
        hit_rate=0.995,
        roll_speed_ips=24.5,
        pred_good=485,
        pred_ok=12,
        pred_ng=3,
        pred_pound=80,
        neighbor_count=9,
        profile_match=88.0,
    )


def test_parse_score_estimate_request_supports_optional_level_prefix() -> None:
    assert _parse_score_estimate_request("估分 红") == (4, "红", "红", False)
    assert _parse_score_estimate_request("估分里红") == (5, "里红", "红", True)
    assert _parse_score_estimate_request("估分 里 红") == (5, "里 红", "红", True)
    assert _parse_score_estimate_request("估分 表谱 红") == (4, "表谱 红", "红", True)


def test_parse_score_estimate_request_rejects_empty_query() -> None:
    with pytest.raises(ValueError):
        _parse_score_estimate_request("估分")


def test_resolve_score_estimate_query_uses_stripped_resolution_for_explicit_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.score_handlers._resolve_what_song_query",
        lambda raw_q, stripped_q: [[114, f"{raw_q}->{stripped_q}"]],
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.score_handlers.queryMusic",
        lambda raw_q, **kwargs: [[514, raw_q]],
    )

    assert _resolve_score_estimate_query("里红", "红", True) == [[114, "里红->红"]]
    assert _resolve_score_estimate_query("红", "红", False) == [[514, "红"]]


def test_format_score_estimate_message_includes_scores_and_above_goku() -> None:
    estimate = ChartScoreEstimate(
        song_id=1,
        level=5,
        current_score=980000,
        goku_score=1000000,
        score_ceiling_35ips=1012000,
        above_goku=True,
        reliability=82.35,
        data_sufficiency="ok",
        stable=_snapshot(1003000),
        pb=_snapshot(1009000),
    )

    message = _format_score_estimate_message("示例歌曲", 5, estimate)

    assert "示例歌曲（里谱）" in message
    assert "当前分数：980000" in message
    assert "稳定分：1003000" in message
    assert "冲分：1009000" in message
    assert "极分参考" not in message
    assert "35打理论上限" not in message
    assert "超极分" not in message


def test_format_score_estimate_message_handles_insufficient_data() -> None:
    estimate = ChartScoreEstimate(
        song_id=1,
        level=4,
        current_score=None,
        goku_score=1000000,
        score_ceiling_35ips=1008000,
        above_goku=False,
        reliability=0.0,
        data_sufficiency="insufficient_data",
        stable=None,
        pb=None,
    )

    message = _format_score_estimate_message("示例歌曲", 4, estimate)

    assert "示例歌曲（表谱）" in message
    assert "当前分数：未游玩" in message
    assert "稳定分：暂无" in message
    assert "冲分：暂无" in message


def test_format_score_estimate_message_handles_hard_mismatch() -> None:
    estimate = ChartScoreEstimate(
        song_id=1,
        level=4,
        current_score=456000,
        goku_score=1000000,
        score_ceiling_35ips=1008000,
        above_goku=False,
        reliability=24.0,
        data_sufficiency="hard_mismatch",
        stable=None,
        pb=None,
    )

    message = _format_score_estimate_message("示例歌曲", 4, estimate)

    assert "示例歌曲（表谱）" in message
    assert "当前分数：456000" in message
    assert "稳定分：暂无" in message
    assert "冲分：暂无" in message
