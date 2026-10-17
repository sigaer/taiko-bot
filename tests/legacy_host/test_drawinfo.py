"""Sakura-owned helpers still used by legacy private commands.
Migrated score presentation regressions: Taiko tests/runtime_ownership/test_score_presentation.py.
"""
import taiko_bot.offline.drawinfo as drawinfo


def test_collect_entries_for_song_prefers_best_record_in_group_without_name_error(
    monkeypatch,
) -> None:
    monkeypatch.setattr(drawinfo, "_load_note_count_map", lambda: {(1001, 4): 500, (1002, 4): 500})
    monkeypatch.setattr(drawinfo, "group_ids_for_query", lambda song_id=None, title="": [1001, 1002])

    records = [
        {
            "song_no": 1001,
            "level": 4,
            "good_cnt": 490,
            "ok_cnt": 10,
            "high_score": 980000,
            "clear_cnt": 1,
            "full_combo_cnt": 0,
            "dondaful_combo_cnt": 0,
        },
        {
            "song_no": 1002,
            "level": 4,
            "good_cnt": 485,
            "ok_cnt": 10,
            "high_score": 990000,
            "clear_cnt": 1,
            "full_combo_cnt": 1,
            "dondaful_combo_cnt": 0,
        },
    ]

    entries = drawinfo._collect_entries_for_song(
        records,
        1001,
        title="Test Song",
        prefer_best_in_group=True,
    )

    assert entries[4]["song_no"] == 1001


def test_available_chart_levels_are_ordered_from_high_to_low() -> None:
    assert drawinfo._available_chart_levels(
        {"level_3": 7, "level_4": 9, "level_5": 10}
    ) == [5, 4, 3]
    assert drawinfo._available_chart_levels(
        {"level_3": 7, "level_4": 9, "level_5": "-"}
    ) == [4, 3]
