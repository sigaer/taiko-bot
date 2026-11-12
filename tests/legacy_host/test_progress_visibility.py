"""Synthetic regressions for the song scope shared by progress commands."""
import importlib
import json
import os
from types import SimpleNamespace

import pytest

from taiko_bot.progress_visibility import is_progress_song_available


@pytest.mark.parametrize("song", [
    {"id": song_id, "shelf_status": 0}
    for song_id in (231, 678, 987, 1167, 1200)
] + [
    {"id": 10, "shelf_status": status} for status in (1, "1", "已下架", 2, "2")
] + [
    {"id": 10, field: "【双打】合成曲目"}
    for field in ("song_name", "song_name_jp")
])
def test_progress_excludes_retired_and_double_songs(song):
    assert not is_progress_song_available(song)


@pytest.fixture
def catalog(tmp_path, monkeypatch):
    profile = os.getenv("TAIKO_PROGRESS_TEST_PROFILE", "center")
    base = f"taiko_bot.runtime.player.{profile}.progress_support"
    catalog = importlib.import_module(base + ".progress_catalog")
    render = importlib.import_module(base + ".render")
    stars = importlib.import_module(base + ".progress_star")
    songs = [
        {"id": 1, "song_name": "在架单人", "shelf_status": 0, "level_4": 3},
        {"id": 231, "song_name": "限界突破×Survivor", "shelf_status": 0, "level_4": 3},
        {"id": 3, "song_name": "下架曲", "shelf_status": 1, "level_4": 3},
        {"id": 4, "song_name": "【双打】双打", "shelf_status": 0, "level_4": 3},
        {"id": 5, "song_name": "中文名", "song_name_jp": "【双打】日本名", "level_4": 3},
        {"id": 6, "song_name": "国行未上架", "shelf_status": 2, "level_4": 3},
    ]
    song_dir = tmp_path / "songs"
    song_dir.mkdir()
    for name in ("song_data.json", "song_data_raw.json"):
        (song_dir / name).write_text(json.dumps(songs))
    (song_dir / "music_donda_list.json").write_text(json.dumps({"SS": songs}))
    monkeypatch.setattr(catalog, "SONG_DATA_PATH", song_dir / "song_data.json")
    monkeypatch.setattr(catalog, "_load_rating_entries", lambda: [
        {"id": song["id"], "level": 4, "score": 3.0} for song in songs
    ])
    monkeypatch.setattr(catalog, "_load_static_progress_map", lambda: {
        "3.0": [song["id"] for song in songs], "4.0": [231, 3, 4, 5, 6]
    })
    monkeypatch.setattr(render, "BASE", tmp_path)
    caches = [getattr(catalog, name) for name in (
        "load_song_index", "load_active_song_ids", "available_star_progress_values",
        "available_const_progress_keys", "available_pass_progress_keys",
    )]
    for function in caches:
        function.cache_clear()
    yield SimpleNamespace(catalog=catalog, render=render, stars=stars, songs=songs)
    for function in caches:
        function.cache_clear()


def test_all_progress_catalogs_exclude_retired_and_double_songs(catalog):
    queries = [
        catalog.catalog.query_progress_items_by_star(3),
        catalog.catalog.query_progress_items_by_const(3.0),
        catalog.catalog.query_progress_items_by_pass_const("3.0"),
    ]
    assert all([(item.song_id, item.level) for item in items] == [(1, 4)] for items in queries)
    assert catalog.catalog.available_star_progress_values() == {3}
    assert catalog.catalog.available_pass_progress_keys() == {"3.0"}


def test_summary_rejects_excluded_scores_even_when_passed_directly(catalog):
    items = [(song["id"], 4, song["song_name"]) for song in catalog.songs]
    best_map = {(sid, level): {"dondaful_combo_cnt": 1, "best_score_rank": 8}
                for sid, level, _ in items if sid != 1}
    summary = catalog.stars.build_star_progress_summary(items, best_map)
    assert summary.total_count == summary.unplayed_count == 1
    assert summary.played_count == summary.dondaful_count == 0
    assert sum(summary.rank_counts.values()) == 0


@pytest.mark.parametrize("kind", ["star", "const", "pass", "custom"])
def test_progress_render_receives_only_eligible_rows(catalog, monkeypatch, kind):
    render = catalog.render
    monkeypatch.setattr(render, "_build_progress_rows", lambda items, *_: items)
    monkeypatch.setattr(render, "_render_progress_table_image", lambda **kwargs: kwargs)
    monkeypatch.setattr(render, "_render_star_progress_summary_panel", lambda **_: SimpleNamespace(height=1))
    monkeypatch.setattr(render, "_render_star_progress_profile_panel", lambda **_: None)
    userdata = {"songs": [{"song_no": song["id"], "level": 4, "high_score": 999999,
                           "dondaful_combo_cnt": 1} for song in catalog.songs]}
    calls = {
        "star": (render.render_star_progress_image_bytes, {"star_value": 3}),
        "const": (render.render_progress_image_bytes, {"decimal": "3.0"}),
        "pass": (render.render_pass_progress_image_bytes, {"decimal": "3.0"}),
        "custom": (render.render_progress_image_bytes_by_list, {"progress_name": "SS"}),
    }
    function, kwargs = calls[kind]
    result = function(user_id=123, userdata=userdata, **kwargs)
    assert [(sid, level) for sid, level, _ in result["rows"]] == [(1, 4)]
    assert result["total_count"] == 1
