import json

import pytest
from sakura_taiko_core.chart.progress_catalog import is_song_on_shelf

from taiko_bot.runtime.player.center.progress_support.render import _build_best_entry_map
from taiko_bot.runtime.player.center.progress_support import progress_catalog, progress_star
from taiko_bot.runtime.player.center.progress_support.progress_catalog import (
    available_star_progress_values,
    load_active_song_ids,
    load_song_index,
    query_progress_items_by_star,
)
from taiko_bot.runtime.player.center.progress_support.progress_star import build_star_progress_summary


@pytest.fixture
def basic_star_catalog(tmp_path, monkeypatch):
    songs = [
        {'id': 1, 'song_name': 'Synthetic one', 'level_4': 1, 'shelf_status': 0},
        {'id': 2, 'song_name': 'Synthetic ten', 'level_4': 10, 'shelf_status': 0},
        {'id': 3, 'song_name': 'Synthetic removed', 'level_4': 10, 'shelf_status': 1},
    ]
    path = tmp_path/'song_data.json'
    path.write_text(json.dumps(songs))
    (tmp_path/'song_data_raw.json').write_text(json.dumps(songs))
    monkeypatch.setattr(progress_catalog, 'SONG_DATA_PATH', path)
    for fn in (progress_catalog.load_song_index, progress_catalog.load_active_song_ids, progress_catalog.available_star_progress_values):
        fn.cache_clear()
    yield
    for fn in (progress_catalog.load_song_index, progress_catalog.load_active_song_ids, progress_catalog.available_star_progress_values):
        fn.cache_clear()


def test_available_star_progress_values_supports_up_to_10(basic_star_catalog) -> None:
    star_values = available_star_progress_values()
    assert 10 in star_values
    assert 1 in star_values


def test_query_progress_items_by_star_returns_ten_star_charts(basic_star_catalog) -> None:
    items = query_progress_items_by_star(10)
    assert items
    assert all(item.level in {4, 5} for item in items)


def test_build_best_entry_map_skips_delisted_songs(basic_star_catalog) -> None:
    song_index = load_song_index()
    delisted_id = next(
        song_id
        for song_id, song in song_index.items()
        if not is_song_on_shelf(song.get("shelf_status"))
    )
    active_id = next(iter(load_active_song_ids()))

    best_map = _build_best_entry_map(
        [
            {
                "song_no": delisted_id,
                "level": 4,
                "high_score": 999999,
                "good_cnt": 100,
                "ok_cnt": 0,
            },
            {
                "song_no": active_id,
                "level": 4,
                "high_score": 12345,
                "good_cnt": 10,
                "ok_cnt": 0,
            },
        ]
    )

    assert (delisted_id, 4) not in best_map
    assert best_map[(active_id, 4)]["high_score"] == 12345


def test_build_star_progress_summary_counts_subset_stats(monkeypatch) -> None:
    progress_items = [
        (1001, 4, "A"),
        (1002, 5, "B"),
        (1003, 4, "C"),
        (1004, 5, "D"),
    ]
    best_map = {
        (1001, 4): {
            "clear_cnt": 1,
            "full_combo_cnt": 0,
            "dondaful_combo_cnt": 0,
            "best_score_rank": 7,
        },
        (1002, 5): {
            "clear_cnt": 1,
            "full_combo_cnt": 1,
            "dondaful_combo_cnt": 0,
            "best_score_rank": 8,
        },
        (1003, 4): {
            "clear_cnt": 1,
            "full_combo_cnt": 1,
            "dondaful_combo_cnt": 1,
            "best_score_rank": 1,
        },
    }

    monkeypatch.setattr(
        progress_star,
        "load_star_progress_chart_keys",
        lambda: {(song_id, level) for song_id, level, _ in progress_items},
    )
    summary = build_star_progress_summary(progress_items, best_map)

    assert summary.total_count == 4
    assert summary.played_count == 3
    assert summary.unplayed_count == 1
    assert summary.clear_count == 1
    assert summary.full_count == 1
    assert summary.dondaful_count == 1
    assert summary.rank_counts[8] == 1
    assert summary.rank_counts[7] == 1
    assert summary.blank_rank_count == 1


@pytest.fixture
def cn_star_catalog(tmp_path, monkeypatch):
    songs = [
        {"id": 1, "song_name": "国行单人", "level_4": 9, "level_5": 10},
        {"id": 2, "song_name": "国行双谱", "level_4": 9, "level_5": 10, "shelf_status": 0},
        {"id": 3, "song_name": "【双打】双打", "level_4": 8, "level_5": 10},
        {"id": 4, "song_name": "已下架", "level_4": 9, "shelf_status": "1"},
        {"id": 5, "song_name": "其他曲目", "level_4": 7, "shelf_status": 2},
        {"id": 6, "song_name": "国行未上架", "level_4": 6, "shelf_status": 0},
        {"id": 7, "song_name": "日本名标记", "song_name_jp": "【双打】日本名", "level_4": 5},
        {"id": 8, "song_name": "原始库下架", "level_4": 4, "shelf_status": 0},
    ]
    raw_songs = [dict(song) for song in songs if song["id"] != 6]
    raw_songs[0]["level_5"] = "-"  # 元数据补齐的里谱尚未在国行实装。
    raw_songs[-1]["shelf_status"] = 1
    song_path = tmp_path / "song_data.json"
    song_path.write_text(json.dumps(songs), encoding="utf-8")
    (tmp_path / "song_data_raw.json").write_text(json.dumps(raw_songs), encoding="utf-8")
    monkeypatch.setattr(progress_catalog, "SONG_DATA_PATH", song_path)
    monkeypatch.setattr(progress_catalog, "load_song_index", lambda: {song["id"]: song for song in songs})
    progress_catalog.available_star_progress_values.cache_clear()
    yield
    progress_catalog.available_star_progress_values.cache_clear()


def test_star_catalog_only_counts_cn_released_single_player_charts(cn_star_catalog) -> None:
    assert available_star_progress_values() == {9, 10}
    assert {(item.song_id, item.level) for item in query_progress_items_by_star(9)} == {(1, 4), (2, 4)}
    assert {(item.song_id, item.level) for item in query_progress_items_by_star(10)} == {(2, 5)}
    assert not query_progress_items_by_star(7)


def test_star_summary_ignores_out_of_scope_scores_and_duplicate_charts(cn_star_catalog) -> None:
    keys = [(1, 4), (1, 5), (2, 4), (2, 5), (3, 4), (3, 5), (4, 4), (5, 4), (6, 4), (7, 4), (8, 4), (999, 4), (2, 3)]
    items = [(song_id, level, "title") for song_id, level in keys + [(1, 4)]]
    best_map = {key: {"dondaful_combo_cnt": 1, "best_score_rank": 8} for key in keys if key != (2, 5)}

    summary = build_star_progress_summary(items, best_map)

    assert summary.total_count == 3
    assert summary.played_count == 2
    assert summary.unplayed_count == 1
    assert summary.dondaful_count == 2
    assert summary.rank_counts[8] == 2
    assert summary.clear_count == summary.full_count == summary.blank_rank_count == 0
