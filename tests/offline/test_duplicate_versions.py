from __future__ import annotations

import json

from taiko_bot.runtime.player.center.duplicate_versions import (
    build_duplicate_song_groups,
    choose_best_record_in_group,
    collapse_query_results_by_group,
    default_song_id_for_query,
)


def test_build_duplicate_song_groups_merges_same_title_even_with_different_levels(tmp_path):
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {"id": 523, "song_name": "Synchronicity", "level_4": 8, "level_5": "-"},
                {"id": 766, "song_name": "Synchronicity", "level_4": 7, "level_5": "-"},
                {"id": 1001, "song_name": "Other", "level_4": 9, "level_5": "-"},
            ]
        ),
        encoding="utf-8",
    )

    groups = build_duplicate_song_groups(song_data_path)

    assert (523, 766) in groups


def test_default_song_id_for_query_returns_smallest_id(tmp_path):
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {"id": 1262, "song_name": "Phoenix"},
                {"id": 323, "song_name": "Phoenix"},
            ]
        ),
        encoding="utf-8",
    )

    assert default_song_id_for_query(1262, song_data_path=song_data_path) == 323
    assert default_song_id_for_query(title="Phoenix", song_data_path=song_data_path) == 323


def test_collapse_query_results_by_group_keeps_single_default_entry(tmp_path):
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {"id": 1262, "song_name": "Phoenix"},
                {"id": 323, "song_name": "Phoenix"},
                {"id": 1000, "song_name": "Different"},
            ]
        ),
        encoding="utf-8",
    )

    rows = collapse_query_results_by_group(
        [[1262, "Phoenix"], [323, "Phoenix"], [1000, "Different"]],
        song_data_path=song_data_path,
    )

    assert rows == [[323, "Phoenix"], [1000, "Different"]]


def test_choose_best_record_in_group_prefers_highest_accuracy_then_score(tmp_path):
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {"id": 1146, "song_name": "Hater"},
                {"id": 1264, "song_name": "Hater"},
            ]
        ),
        encoding="utf-8",
    )
    note_count_by_key = {(1146, 4): 500, (1264, 4): 500}
    records = [
        {
            "song_no": 1146,
            "level": 4,
            "good_cnt": 490,
            "ok_cnt": 10,
            "high_score": 980000,
            "clear_cnt": 1,
            "full_combo_cnt": 0,
            "dondaful_combo_cnt": 0,
        },
        {
            "song_no": 1264,
            "level": 4,
            "good_cnt": 485,
            "ok_cnt": 10,
            "high_score": 990000,
            "clear_cnt": 1,
            "full_combo_cnt": 1,
            "dondaful_combo_cnt": 0,
        },
    ]

    best = choose_best_record_in_group(
        records,
        song_id=1146,
        level=4,
        note_count_by_key=note_count_by_key,
        song_data_path=song_data_path,
    )

    assert best is not None
    assert best["song_no"] == 1146
