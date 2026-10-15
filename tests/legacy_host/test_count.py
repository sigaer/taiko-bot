from __future__ import annotations

import taiko_bot.runtime.player.center.draw_dress as draw_dress

SAMPLE_USERDATA = {
    "songs": [
        {"song_no": 1001, "level": 4, "stage_cnt": 3, "best_score_rank": 6},
        {"song_no": 1001, "level": 4, "stage_cnt": 5, "best_score_rank": 7},
        {"song_no": 1002, "level": 5, "stage_cnt": 2, "best_score_rank": 6},
        {"song_no": 1003, "level": 5, "stage_cnt": 4, "best_score_rank": 7},
        {"song_no": 1004, "level": 3, "stage_cnt": 1, "best_score_rank": 8},
        {"song_no": 1005, "level": 4, "stage_cnt": 6, "best_score_rank": 0},
    ]
}

SAMPLE_SONG_META = {
    1001: {"shelf_status": 0},
    1002: {"shelf_status": 0},
    1003: {"shelf_status": 1},
    1004: {"shelf_status": 0},
    1005: {"shelf_status": 0},
}


def test_my_don_total_stage_count_uses_all_song_records():
    songs = SAMPLE_USERDATA["songs"]

    expected = sum(int(song["stage_cnt"]) for song in songs)

    assert draw_dress._sum_my_don_total_stage_count(songs) == expected


def test_my_don_rank_counts_recompute_from_playable_song_records(monkeypatch):
    monkeypatch.setattr(draw_dress, "_load_song_display_map", lambda: SAMPLE_SONG_META)

    songs = SAMPLE_USERDATA["songs"]
    stats = draw_dress._collect_my_don_song_stats(songs)
    panel_stats = draw_dress._merge_my_don_level_stats(stats.get(4), stats.get(5))
    rank_counts = draw_dress._resolve_my_don_rank_counts({}, 5, panel_stats)

    assert panel_stats["played"] == 3
    assert rank_counts["blank"] == 1
    assert rank_counts["ranks"] == {2: 0, 3: 0, 4: 0, 5: 0, 6: 1, 7: 1, 8: 0}
