from __future__ import annotations

from pathlib import Path

from taiko_bot.offline.tja_roll_sync import (
    _course_fields,
    _parsed_course_fields,
    _replace_song_roll_fields,
    audit_song_data,
)


def test_parsed_course_fields_normalizes_roll_totals() -> None:
    fields = _parsed_course_fields({"roll_times": [0.104167], "balloons": [45]})
    assert fields == {
        "roll_times": [0.104167],
        "roll_time": 0.104167,
        "balloons": [45],
        "balloon_num": 45,
    }


def test_replace_song_roll_fields_uses_course_field_index() -> None:
    song = {
        "roll_times": [[1], [2], [3], [4], [5]],
        "roll_time": [1, 2, 3, 4, 5],
        "balloons": [[1], [2], [3], [4], [5]],
        "balloon_num": [1, 2, 3, 4, 5],
    }
    _replace_song_roll_fields(song, {5: _parsed_course_fields({"roll_times": [0.104167], "balloons": [45]})})
    assert _course_fields(song, 5) == ([0.104167], 0.104167, [45], 45)
    assert _course_fields(song, 4) == ([4], 4, [4], 4)


def _write_test_tja(path: Path, roll: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"BPM:120\nTITLE:Same Song\nCOURSE:Oni\nLEVEL:8\n#START\n{roll},\n#END\n",
        encoding="utf-8",
    )


def test_audit_prefers_song_id_mapping_over_ambiguous_title(tmp_path: Path) -> None:
    first = tmp_path / "01 Pop/Same Song/Same Song.tja"
    mapped = tmp_path / "01 Pop/Same Song/Same Song -New Audio-.tja"
    _write_test_tja(first, "5008")
    _write_test_tja(mapped, "50008")
    song = {
        "id": 7,
        "song_name": "Same Song",
        "level_1": "-",
        "level_2": "-",
        "level_3": "-",
        "level_4": 8,
        "level_5": "-",
    }

    report = audit_song_data(
        [song],
        tja_root=tmp_path,
        song_tja_mapping={7: "01 Pop/Same Song/Same Song -New Audio-.tja"},
    )

    assert report["songs"][0]["match"]["strategy"] == "song_id_mapping"
    assert report["songs"][0]["ready"] is True
    assert report["proposedSongData"][0]["roll_times"][3] == [1.6]


def test_audit_preserves_existing_values_for_empty_mapped_path(tmp_path: Path) -> None:
    song = {
        "id": 7,
        "song_name": "Unavailable Song",
        "level_4": 8,
        "roll_times": [None, None, None, [9.0], None],
        "roll_time": [None, None, None, 9.0, None],
        "balloons": [None, None, None, [10], None],
        "balloon_num": [None, None, None, 10, None],
    }

    report = audit_song_data(
        [song], tja_root=tmp_path, song_tja_mapping={7: ""}
    )

    assert report["songs"][0]["blocked"] == ["empty_mapping_path"]
    assert report["songs"][0]["ready"] is False
    assert report["proposedSongData"] == [song]
