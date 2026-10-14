from __future__ import annotations

import pytest

from taiko_bot.runtime.player.center.b30_support.b30_render import (
    B30_DELTA_EPSILON,
    _topn_entry_keys,
    compute_b30_update_diff,
)
from taiko_application.score.b30_single import B30SingleRenderer

def _format_rating_delta(value):
    return B30SingleRenderer._format_rating_delta(None,value)


def _entry(song_no: int, level: int) -> dict:
    return {
        "song_no": song_no,
        "level": level,
        "high_score": 1_000_000,
        "good_cnt": 100,
        "ok_cnt": 0,
        "dondaful_combo_cnt": 1,
    }


def test_topn_entry_keys():
    top = [(12.5, _entry(101, 4)), (11.0, _entry(202, 5))]
    assert _topn_entry_keys(top) == {(101, 4), (202, 5)}


def test_format_rating_delta_uses_adaptive_precision():
    assert _format_rating_delta(0.0) == "+0.00"
    assert _format_rating_delta(0.044273) == "+0.04"
    assert _format_rating_delta(0.004273) == "+0.004"
    assert _format_rating_delta(0.000897) == "+0.0009"
    assert _format_rating_delta(0.00001) == "+<0.0001"


def test_compute_b30_update_diff_no_previous_snapshot(monkeypatch):
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._load_previous_song_map",
        lambda _uid, **kwargs: None,
    )
    new_keys, improved_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        1,
        2,
        current_results=[object()],
        rating_index={},
        const_table=[],
        current_top_entries=[(10.0, _entry(1, 4))],
    )
    assert new_keys == set()
    assert improved_deltas == {}
    assert dim_deltas == {}
    assert total_delta == 0.0


def test_compute_b30_update_diff_new_topn_keys(monkeypatch):
    prev_entries = [_entry(100, 4), _entry(200, 5)]
    curr_top = [
        (15.0, _entry(100, 4)),
        (14.0, _entry(300, 4)),
    ]
    prev_top = [
        (15.0, _entry(100, 4)),
        (13.0, _entry(200, 5)),
    ]

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._load_previous_song_map",
        lambda _uid, **kwargs: {(100, 4): prev_entries[0], (200, 5): prev_entries[1]},
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._pick_top_entries",
        lambda entries, rating_index, const_table, n, **_kwargs: prev_top
        if len(entries) == 2 and (100, 4) in {(e["song_no"], e["level"]) for e in entries}
        else curr_top,
    )
    fake_means = lambda results, n: {
            "大歌力": 10.0,
            "体力": 9.0,
            "高速处理": 8.0,
            "精度力": 7.0,
            "节奏处理": 6.0,
            "复合处理": 5.0,
        }

    new_keys, improved_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        1,
        2,
        current_results=[object()],
        rating_index={},
        const_table=[],
        current_top_entries=curr_top,
        results_from_records_fn=lambda records: [object()] if records else [],
        compute_dim_topn_means_fn=fake_means,
        aggregate_topn_value_fn=lambda _results, _column, _n: 0.0,
    )
    assert new_keys == {(300, 4)}
    assert (200, 5) not in new_keys
    assert improved_deltas == {}
    assert dim_deltas == {}
    assert total_delta == 0.0


def test_compute_b30_update_diff_dim_deltas(monkeypatch):
    prev_map = {(1, 4): _entry(1, 4)}
    curr_top = [(12.0, _entry(1, 4))]

    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._load_previous_song_map",
        lambda _uid, **kwargs: prev_map,
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._pick_top_entries",
        lambda entries, rating_index, const_table, n, **_kwargs: [(11.0, _entry(1, 4))],
    )

    call_count = {"n": 0}

    def fake_means(results, n):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return {
                "大歌力": 10.0,
                "体力": 9.0,
                "高速处理": 8.0,
                "精度力": 7.0,
                "节奏处理": 6.0,
                "复合处理": 5.0,
            }
        return {
            "大歌力": 10.2,
            "体力": 9.0,
            "高速处理": 7.8,
            "精度力": 7.0,
            "节奏处理": 6.0,
            "复合处理": 5.0,
        }

    new_keys, improved_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        1,
        20,
        current_results=[object(), object()],
        rating_index={},
        const_table=[],
        current_top_entries=curr_top,
        results_from_records_fn=lambda _records: [object()],
        compute_dim_topn_means_fn=fake_means,
        aggregate_topn_value_fn=lambda _results, _column, _n: 0.0,
    )
    assert new_keys == set()
    assert improved_deltas == {(1, 4): 1.0}
    assert abs(dim_deltas["大歌力"] - 0.2) < B30_DELTA_EPSILON
    assert abs(dim_deltas["高速处理"] - (-0.2)) < B30_DELTA_EPSILON
    assert "体力" not in dim_deltas
    assert total_delta == 0.0


def test_compute_b30_update_diff_keeps_small_real_delta(monkeypatch):
    previous = _entry(1, 4)
    current = _entry(1, 4)
    previous_results = [object()]
    current_results = [object()]
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._load_previous_song_map",
        lambda _uid, **kwargs: {(1, 4): previous},
    )
    monkeypatch.setattr(
        "taiko_bot.runtime.player.center.b30_support.b30_render._pick_top_entries",
        lambda entries, rating_index, const_table, n, **_kwargs: [(6.50, previous)],
    )

    new_keys, improved_deltas, dim_deltas, total_delta = compute_b30_update_diff(
        1,
        20,
        current_results=current_results,
        rating_index={},
        const_table=[],
        current_top_entries=[(6.544273, current)],
        results_from_records_fn=lambda _records: previous_results,
        compute_dim_topn_means_fn=lambda _results, _n: {},
        aggregate_topn_value_fn=lambda results, _column, _n: (
            6.461091 if results is current_results else 6.460194
        ),
    )

    assert new_keys == set()
    assert improved_deltas == {(1, 4): pytest.approx(0.044273)}
    assert dim_deltas == {}
    assert abs(total_delta - 0.000897) < B30_DELTA_EPSILON
