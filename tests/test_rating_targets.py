"""Target boundaries are checked against forward v2 calculations."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from sakura_taiko_core.models.calculation import V2SongData
from sakura_taiko_core.rating.v2 import _calculate_v2_from_chart
from taiko_bot.rating_targets import compute_v2_rating_target, format_rating_targets
from taiko_bot.runtime.player.center import score_rating_target as service


def chart(notes=101):
    return V2SongData(42, 4, "测试曲", notes, 8.0, 10.0, 12.0, 10.0, 10.0, 10.0, 10.0, 10.0)


def forward(song, ok):
    return _calculate_v2_from_chart(song, accuracy_per=1 - 0.5 * ok / song.total_notes,
        bad_per=0, profile="v2-center-20261010").AI_rating


@pytest.mark.parametrize("notes", [101, 1000])
@pytest.mark.parametrize("precision", [0.75, 0.88, 0.9, 0.95, 1.0])
def test_v2_discrete_boundary_matches_forward_kernel(notes, precision):
    song = chart(notes)
    target = _calculate_v2_from_chart(song, accuracy_per=precision, bad_per=0,
        profile="v2-center-20261010").AI_rating
    expected = max(ok for ok in range(notes // 2 + 1) if forward(song, ok) + 1e-12 >= target)
    result = compute_v2_rating_target(song, target)
    assert result.reachable and result.ok_count == expected
    assert result.good_count + result.ok_count == notes
    assert result.achieved_rating == pytest.approx(forward(song, expected))
    assert result.accuracy >= .75
    if expected < notes // 2:
        assert forward(song, expected + 1) + 1e-12 < target


def test_v2_unreachable_and_low_target():
    song = chart()
    result = compute_v2_rating_target(song, forward(song, 0) + 0.01)
    assert not result.reachable and result.max_rating == forward(song, 0)
    assert result.good_count == song.total_notes and result.ok_count == 0
    low = compute_v2_rating_target(song, 1e-6)
    assert low.ok_count == song.total_notes // 2 and low.accuracy >= .75


@pytest.mark.parametrize("target", [0, -1, float("nan"), float("inf")])
def test_invalid_target(target):
    with pytest.raises(ValueError):
        compute_v2_rating_target(chart(), target)


def test_missing_note_count():
    with pytest.raises(ValueError):
        compute_v2_rating_target(replace(chart(), total_notes=0), 10)


@pytest.fixture
def models(monkeypatch):
    config = {"songs": {"fixture": {"id": 42, "level": 4, "combo": 101, "score": 10}},
        "const_table": {"const_to_score": {"10": 12}}}
    monkeypatch.setattr(service, "load_rating_config", lambda path: config)
    monkeypatch.setattr(service, "group_ids_for_query", lambda **kw: (7, 42))
    monkeypatch.setattr(service, "default_song_id_for_query", lambda *a, **kw: 42)
    monkeypatch.setattr(service, "load_v2_snapshot", lambda: SimpleNamespace(song_map={
        (7, 4): replace(chart(), song_id=7, total_notes=999), (42, 4): chart()}))
    return config


def test_both_versions_choose_canonical_song_and_show_counts(models):
    message = service.build_song_rating_target_message(7, 4, "测试曲", "表谱", 10)
    for version in ("v1", "v2"):
        assert f"【Rating {version}】" in message
    assert message.count("最低良数") == 2 and message.count("最多可数") == 2
    assert "无不可" in message and "75%" in message
    assert "999" not in message


def test_v1_missing_does_not_hide_v2(models):
    models["songs"].clear()
    message = service.build_song_rating_target_message(42, 4, "测试曲", "表谱", 10)
    assert "【Rating v1】\n该歌曲暂无" in message
    assert "【Rating v2】\n最低良数" in message


def test_v2_source_failure_does_not_hide_v1(models, monkeypatch):
    def fail():
        raise service.V2DataSourceError("synthetic failure")
    monkeypatch.setattr(service, "load_v2_snapshot", fail)
    message = service.build_song_rating_target_message(42, 4, "测试曲", "表谱", 10)
    assert "【Rating v1】\n最低良数" in message
    assert "【Rating v2】\nRating 数据暂时不可用" in message


def test_v1_source_failure_does_not_hide_v2(models, monkeypatch):
    monkeypatch.setattr(service, "load_rating_config", lambda path: (_ for _ in ()).throw(OSError()))
    message = service.build_song_rating_target_message(42, 4, "测试曲", "表谱", 10)
    assert "【Rating v1】\nRating 数据暂时不可用" in message
    assert "【Rating v2】\n最低良数" in message


def test_independent_reachability():
    reachable = compute_v2_rating_target(chart(), 10)
    impossible = replace(reachable, reachable=False, max_rating=9.5)
    text = format_rating_targets("测试曲", "表谱", 10, {"v1": impossible, "v2": reachable})
    assert "【Rating v1】\n即使全良也无法达到，最高约为 9.50" in text
    assert "【Rating v2】\n最低良数" in text
