from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import quote

import pytest

from taiko_bot.offline import score_line
from taiko_bot.offline.annual_summary.aggregates import estimate_pound_speed
from taiko_bot.offline.chart_roll_metadata import apply_chart_roll_metadata_overrides
from taiko_bot.offline.song_update_task import (
    _apply_levels_and_max_combo,
    _apply_other_song_wiki_fields,
    _build_down_shelf_song,
    _build_other_song,
    _build_score_detail_page_index,
    _build_rating_entry,
    _collect_rating_target_pairs,
    _extract_other_db_songs,
    _merge_wahlap_song_without_roll_metadata,
    _parse_score_detail_rows_from_html,
    _parse_wiki_score_rows,
    _restrict_levels_by_raw_snapshot,
    _score_row_needs_detail_refresh,
    _wiki_page_base_path,
)

ROLL_FIELDS = {"roll_times", "roll_time", "balloons", "balloon_num"}


def test_new_song_roll_metadata_is_not_taken_from_taiko_wiki() -> None:
    song = _build_down_shelf_song(
        {
            "songNo": "7",
            "title": "Example",
            "courses": {
                "oni": {
                    "level": 8,
                    "maxCombo": 400,
                    "rollTime": [99.0],
                    "balloon": [999],
                }
            },
        }
    )

    assert "roll_times" not in song
    assert "roll_time" not in song
    assert "balloons" not in song
    assert "balloon_num" not in song


def test_wahlap_refresh_preserves_existing_parser_roll_metadata() -> None:
    old_song = {
        "id": 7,
        "bpm": "120",
        "roll_times": [None, None, None, [1.5], None],
        "roll_time": [None, None, None, 1.5, None],
        "balloons": [None, None, None, [8], None],
        "balloon_num": [None, None, None, 8, None],
    }
    upstream_song = {
        "id": 7,
        "bpm": "999",
        "roll_times": [None, None, None, [99.0], None],
        "roll_time": [None, None, None, 99.0, None],
        "balloons": [None, None, None, [999], None],
        "balloon_num": [None, None, None, 999, None],
    }

    merged = _merge_wahlap_song_without_roll_metadata(upstream_song, old_song)

    assert merged["bpm"] == "120"
    assert merged["roll_times"][3] == [1.5]
    assert merged["roll_time"][3] == 1.5
    assert merged["balloons"][3] == [8]
    assert merged["balloon_num"][3] == 8


def test_new_wahlap_song_drops_upstream_roll_metadata() -> None:
    merged = _merge_wahlap_song_without_roll_metadata(
        {
            "id": 7,
            "roll_times": [[99.0]],
            "roll_time": [99.0],
            "balloons": [[999]],
            "balloon_num": [999],
        }
    )

    assert not ROLL_FIELDS.intersection(merged)


def test_final_song_record_override_keeps_waraeru_correction() -> None:
    song = {
        "id": 890,
        "roll_times": [None, None, None, [17.74], None],
        "roll_time": [None, None, None, 17.74, None],
        "balloons": [None, None, None, [50], None],
        "balloon_num": [None, None, None, 50, None],
        "isPlayed": False,
    }

    apply_chart_roll_metadata_overrides(song)

    assert song["roll_times"][3] == pytest.approx(
        [0.532, 0.532, 0.532, 0.231, 0.231, 0.231, 0.231, 0.231, 0.116]
    )
    assert song["roll_time"][3] == pytest.approx(2.867)
    assert song["balloons"][3] == [6, 6, 6, 6, 6, 6, 6, 938, 8]
    assert song["balloon_num"][3] == 988
    assert song["isPlayed"] is True


def test_sil_vous_president_ura_override_keeps_trailing_long_roll() -> None:
    song = {
        "id": 1061,
        "roll_times": [None, None, None, None, [0.142] * 6],
        "roll_time": [None, None, None, None, 0.852],
        "balloons": [None, None, None, None, [2]],
        "balloon_num": [None, None, None, None, 2],
    }

    apply_chart_roll_metadata_overrides(song)

    assert song["roll_times"][4] == pytest.approx([0.142045] * 6 + [2.017045])
    assert song["roll_time"][4] == pytest.approx(2.869315)
    assert song["balloons"][4] == [2]
    assert song["balloon_num"][4] == 2


def test_fuuma_module_oni_override_keeps_balloon_count_and_roll_duration() -> None:
    song = {
        "id": 1274,
        "roll_times": [None, None, None, [3.89], None],
        "roll_time": [None, None, None, 3.89, None],
        "balloons": [None, None, None, [24], None],
        "balloon_num": [None, None, None, 24, None],
    }

    apply_chart_roll_metadata_overrides(song)

    assert song["roll_times"][3] == pytest.approx([
        0.259434,
        0.259434,
        0.259434,
        0.259434,
        0.683962,
        3.372642,
        0.542453,
        0.683962,
        0.259434,
        0.259434,
        0.683962,
    ])
    assert song["roll_time"][3] == pytest.approx(7.523585)
    assert song["balloons"][3] == [24]
    assert song["balloon_num"][3] == 24


def test_branch_and_unbreakable_roll_overrides_are_persisted() -> None:
    songs = [
        {
            "id": song_id,
            "roll_times": [None] * 5,
            "roll_time": [None] * 5,
            "balloons": [None] * 5,
            "balloon_num": [None] * 5,
        }
        for song_id in (67, 681, 1352)
    ]

    for song in songs:
        apply_chart_roll_metadata_overrides(song)

    by_id = {song["id"]: song for song in songs}
    assert by_id[67]["roll_time"][3] == pytest.approx(0.172414)
    assert by_id[67]["balloon_num"][3] == 30
    assert by_id[681]["roll_time"][4] == pytest.approx(1.342857)
    assert by_id[681]["balloon_num"][4] == 21
    assert by_id[1352]["roll_time"][3] == pytest.approx(5.054056)
    assert by_id[1352]["balloon_num"][3] == 0


@pytest.mark.parametrize(
    ("song_id", "level", "roll_times", "balloons"),
    [
        (519, 5, [0.716040], []),
        (302, 4, [1.208849], []),
        (751, 4, [0.201343], []),
        (1130, 4, [0.653847], [3]),
        (149, 4, [0.653845, 0.653845], [12, 12, 12, 12]),
        (149, 5, [1.576921], []),
        (163, 4, [0.500000, 1.382352], []),
        (355, 4, [0.531250, 0.531250, 0.729167], [100, 6]),
        (770, 4, [7.421042], []),
    ],
)
def test_confirmed_yellow_roll_overrides_are_persisted_and_used_by_annual_speed(
    song_id: int,
    level: int,
    roll_times: list[float],
    balloons: list[int],
) -> None:
    song = {
        "id": song_id,
        "roll_times": [None] * 5,
        "roll_time": [None] * 5,
        "balloons": [None] * 5,
        "balloon_num": [None] * 5,
    }
    index = level - 1
    song["roll_times"][index] = [999.0]
    song["roll_time"][index] = 999.0
    song["balloons"][index] = [999]
    song["balloon_num"][index] = 999

    apply_chart_roll_metadata_overrides(song)

    assert song["roll_times"][index] == pytest.approx(roll_times)
    assert song["roll_time"][index] == pytest.approx(sum(roll_times))
    assert song["balloons"][index] == balloons
    assert song["balloon_num"][index] == sum(balloons)
    variable_hits = 10
    pound_count = sum(balloons) + variable_hits
    assert estimate_pound_speed(
        {"pound_cnt": pound_count}, {song_id: song}, (song_id, level)
    ) == round(variable_hits / sum(roll_times), 2)


def test_parse_wiki_score_rows_handles_ranges_and_precision_rows() -> None:
    source = """
|''曲名''|''天井スコア''|極スコア|必要連打数|要求連打速度|h
|[[アイドルライフスターターパック>収録曲/おに/アイドルライフスターターパック]]|981360|1002860～1003060|215～217||
|[[怪獣>収録曲/おに/怪獣]]|>|1002000|0|精度曲|
|[[はいよろこんで(裏譜面)>収録曲/おに/はいよろこんで(裏譜面)]]|1003520|1005020|15|24.5打/秒|
""".strip()

    rows = _parse_wiki_score_rows(source, "ポップス")

    assert rows[0]["title"] == "アイドルライフスターターパック"
    assert rows[0]["level"] == 4
    assert rows[0]["tenjo_score"] == 981360
    assert rows[0]["goku_score"] == 1002860
    assert rows[0]["roll_required"] == 215
    assert rows[0]["roll_speed_ips"] is None

    assert rows[1]["title"] == "怪獣"
    assert rows[1]["tenjo_score"] == 1002000
    assert rows[1]["roll_required"] == 0
    assert rows[1]["roll_speed_ips"] is None

    assert rows[2]["title"] == "はいよろこんで(裏譜面)"
    assert rows[2]["level"] == 5
    assert rows[2]["roll_speed_ips"] == 24.5


def test_parse_wiki_score_rows_keeps_double_chart_identity() -> None:
    source = """
|''曲名''|''天井スコア''|極スコア|必要連打数|要求連打速度|h
|[[桂月>収録曲/おに/桂月]]|986630|1001230|146|約17.87打/秒|
|BGCOLOR(pink):[[【双打】 桂月>収録曲/おに/【双打】 桂月]]|BGCOLOR(pink):985900|BGCOLOR(pink):1000300|BGCOLOR(pink):|BGCOLOR(pink):|
""".strip()

    rows = _parse_wiki_score_rows(source, "ナムコオリジナル")

    assert [(row["title"], row["level"]) for row in rows] == [
        ("桂月", 4),
        ("【双打】 桂月", 4),
    ]
    assert rows[0]["detail_page"] == "収録曲/おに/桂月"
    assert rows[1]["detail_page"] == "収録曲/おに/【双打】 桂月"


def test_parse_wiki_score_rows_ignores_non_song_table_controls() -> None:
    source = """
|LEFT:300|100|200|300|400|
|[[桂月>収録曲/おに/桂月]]|986630|1001230|146|約17.87打/秒|
""".strip()

    rows = _parse_wiki_score_rows(source, "ナムコオリジナル")

    assert [row["title"] for row in rows] == ["桂月"]


def test_wiki_detail_page_fetch_ignores_anchor_fragment() -> None:
    assert _wiki_page_base_path("収録曲/おに/KAGEKIYO(裏譜面)#double") == (
        "収録曲/おに/KAGEKIYO(裏譜面)"
    )


def test_parse_score_detail_rows_accepts_seven_column_ac16_table() -> None:
    html = """
<table>
  <tr><th colspan="7">桂月 ～ Twilight Laurel ～</th></tr>
  <tr>
    <th>バージョン</th><th>ジャンル</th><th>難易度</th><th>最大コンボ数</th>
    <th colspan="2">天井スコア</th><th>初項</th>
  </tr>
  <tr>
    <td>AC16.6.6</td><td>ナムコオリジナル</td><td>★×8</td><td>421</td>
    <td>986630点</td><td>＋連打</td><td>2330点</td>
  </tr>
</table>
"""

    assert _parse_score_detail_rows_from_html(html) == [
        {
            "selected_version": "AC16.6.6",
            "tenjo_score": 986630,
            "initial_points": 2330,
            "row_index": 0,
        }
    ]


def test_score_detail_page_index_separates_normal_and_double_charts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = """
|''曲名''|''天井スコア''|極スコア|必要連打数|要求連打速度|h
|[[桂月>収録曲/おに/桂月]]|986630|1001230|146|約17.87打/秒|
|BGCOLOR(pink):[[【双打】 桂月>収録曲/おに/【双打】 桂月]]|BGCOLOR(pink):985900|BGCOLOR(pink):1000300|BGCOLOR(pink):|BGCOLOR(pink):|
""".strip()
    page = "作品/新AC/極スコア/おに/テスト"
    cache_name = quote(page, safe="").replace("%", "_") + ".txt"
    (tmp_path / cache_name).write_text(source, encoding="utf-8")

    monkeypatch.setattr(
        "taiko_bot.offline.song_update_task.WIKIWIKI_SCORE_PAGE_SLUGS",
        ("テスト",),
    )
    monkeypatch.setattr(
        "taiko_bot.offline.song_update_task.WIKIWIKI_SCORE_CACHE_DIR",
        tmp_path,
    )

    index = _build_score_detail_page_index()

    assert index[("桂月", 4)] == "収録曲/おに/桂月"
    assert index[("【双打】桂月", 4)] == "収録曲/おに/【双打】 桂月"


def test_score_row_detail_refresh_compares_optional_roll_speed() -> None:
    existing = {
        "tenjo_score": 986630,
        "goku_score": 1001230,
        "roll_required": 146,
        "roll_speed_ips": None,
        "initial_points": 2330,
        "selected_version": "AC16.6.6",
    }
    parsed = {
        "tenjo_score": 986630,
        "goku_score": 1001230,
        "roll_required": 146,
        "roll_speed_ips": 17.87,
    }

    assert _score_row_needs_detail_refresh(existing, parsed) is True


def test_build_rating_entry_uses_song_data_chart_fields() -> None:
    song = {
        "id": 402,
        "song_name_jp": "Rotter Tarmination",
        "song_name": "Rotter Tarmination",
        "level_4": 8,
        "bpm": "200(100-800)",
        "max_combo": [182, 249, 438, 681, 943],
        "roll_time": [3.55, 3.55, 5.35, 0.0, 1.025],
        "balloon_num": [8, 10, 16, 1019, 766],
    }
    chart_datas = {
        "radar_compound": 80,
        "radar_density_ave": 70,
        "radar_density_inst": 90,
        "radar_change_hs": 10,
        "radar_change_bpm": 20,
        "radar_division": 30,
    }

    key, entry = _build_rating_entry(song, 4, chart_datas, 8.7)

    assert key == "Rotter Tarmination"
    assert entry["combo"] == 681
    assert entry["bpm"] == "200(100-800)"
    assert entry["roll_time"] == "0.000秒"
    assert entry["balloon_num"] == 1019


def test_raw_snapshot_restricts_unavailable_ura_level() -> None:
    song_record = _apply_levels_and_max_combo(
        {"id": 1303},
        [2, 3, 5, 7, 8],
        [95, 168, 274, 331, 548],
    )
    raw_song = {
        "id": 1303,
        "level_1": 2,
        "level_2": 3,
        "level_3": 5,
        "level_4": 7,
        "level_5": "-",
    }

    _restrict_levels_by_raw_snapshot(song_record, raw_song)

    assert song_record["level_4"] == 7
    assert song_record["level_5"] == "-"
    assert song_record["max_combo"][3] == 331
    assert song_record["max_combo"][4] == "-"


def test_raw_snapshot_preserves_score_confirmed_ura_level() -> None:
    song_record = _apply_levels_and_max_combo(
        {"id": 1370},
        [5, 6, 8, 10, 10],
        [216, 319, 471, 786, 1123],
    )
    raw_song = {
        "id": 1370,
        "level_1": 5,
        "level_2": 6,
        "level_3": 8,
        "level_4": 10,
        "level_5": "-",
    }

    _restrict_levels_by_raw_snapshot(song_record, raw_song, preserve_levels={5})

    assert song_record["level_5"] == 10
    assert song_record["max_combo"][4] == 1123


def test_collect_rating_target_pairs_includes_score_confirmed_ura_level() -> None:
    song_data = [
        {
            "id": 1370,
            "song_name_jp": "Extreme End",
            "song_name": "Extreme End",
            "level_4": 10,
            "level_5": "-",
            "roll_time": [7.415, 6.815, 7.681, 10.977, 3.498],
        }
    ]

    pairs = _collect_rating_target_pairs(song_data, {1370: {5}})

    assert pairs == [(1370, 4), (1370, 5)]


def test_collect_rating_target_pairs_skips_score_confirmed_levels_without_chart_metadata() -> None:
    song_data = [
        {
            "id": 153,
            "song_name_jp": "エンジェル ドリーム",
            "song_name": "Angel Dream",
            "level_4": 8,
            "level_5": "-",
            "max_combo": [194, 270, 462, 694, "-"],
            "roll_time": [1.431, 1.431, 3.705, 3.916, None],
        }
    ]

    pairs = _collect_rating_target_pairs(song_data, {153: {5}})

    assert pairs == [(153, 4)]


def test_rebuild_scoreline_dataset_reads_roll_and_balloons_from_song_data(tmp_path: Path, monkeypatch) -> None:
    score_path = tmp_path / "song_score.json"
    song_data_path = tmp_path / "song_data.json"
    stream_path = tmp_path / "taiko_goku_all_levels_stream.json"
    unified_path = tmp_path / "taiko_goku_onis.json"
    stream_path.write_text("[]", encoding="utf-8")
    score_path.write_text(
        json.dumps(
            [
                {
                    "title": "Test Song",
                    "level": 4,
                    "tenjo_score": 990000,
                    "goku_score": 1000000,
                    "roll_required": 12,
                    "roll_speed_ips": 18.0,
                    "max_combo": 0,
                    "initial_points": 2000,
                    "selected_version": "AC16.1.0",
                    "id": 1,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    song_data_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "song_name_jp": "Test Song",
                    "song_name": "测试歌曲",
                    "max_combo": [100, 200, 300, 400, "-"],
                    "roll_times": [None, None, None, [1.2, 0.8], None],
                    "balloons": [None, None, None, [5, 7], None],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(score_line, "SCORE_PATH", score_path)
    monkeypatch.setattr(score_line, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(score_line, "ALL_LEVELS_STREAM_PATH", stream_path)
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    row_count, matched_count = score_line.rebuild_scoreline_dataset(unified_path)
    rows = json.loads(unified_path.read_text(encoding="utf-8"))

    assert row_count == 1
    assert matched_count == 1
    assert rows[0]["max_combo"] == 400
    assert rows[0]["roll_times"] == [1.2, 0.8]
    assert rows[0]["roll_total_seconds"] == 2.0
    assert rows[0]["balloons"] == [5, 7]
    assert rows[0]["balloon_hits"] == 12


def test_rebuild_scoreline_dataset_uses_stream_as_base_and_appends_unknown_rows(
    tmp_path: Path, monkeypatch
) -> None:
    score_path = tmp_path / "song_score.json"
    song_data_path = tmp_path / "song_data.json"
    stream_path = tmp_path / "taiko_goku_all_levels_stream.json"
    unified_path = tmp_path / "taiko_goku_onis.json"
    score_path.write_text(
        json.dumps(
            [
                {"id": 1, "title": "Stream Song", "level": 4},
                {"id": 2, "title": "Unknown Song", "level": 5},
            ]
        ),
        encoding="utf-8",
    )
    song_data_path.write_text("[]", encoding="utf-8")
    stream_row = {
        "id": 1,
        "title": "Stream Song",
        "level": 1,
        "difficulty_label": "简单谱",
        "goku_score": 1_000_000,
        "initial_points": 5_000,
        "max_combo": 200,
        "roll_total_seconds": 3.5,
        "balloon_hits": 10,
        "match_source": "donnote_api",
    }
    stream_oni_row = {
        "id": 1,
        "title": "Stream Song",
        "level": 4,
        "goku_score": 1_001_230,
        "stream_only_field": True,
    }
    stream_path.write_text(
        json.dumps([stream_row, stream_oni_row]), encoding="utf-8"
    )

    monkeypatch.setattr(score_line, "SCORE_PATH", score_path)
    monkeypatch.setattr(score_line, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(score_line, "ALL_LEVELS_STREAM_PATH", stream_path)
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    row_count, _ = score_line.rebuild_scoreline_dataset(unified_path)
    rows = json.loads(unified_path.read_text(encoding="utf-8"))

    assert row_count == 3
    assert rows[:2] == [stream_row, stream_oni_row]
    assert rows[0]["level"] == 1
    assert rows[0]["match_source"] == "donnote_api"
    assert rows[0]["roll_total_seconds"] == 3.5
    assert rows[0]["initial_points"] == 5_000
    assert rows[1]["stream_only_field"] is True
    assert rows[2]["id"] == 2
    assert rows[2]["level"] == 5
    assert rows[2]["title"] == "Unknown Song"


def test_rebuild_scoreline_dataset_prefers_complete_duplicate_chart(
    tmp_path: Path, monkeypatch
) -> None:
    score_path = tmp_path / "song_score.json"
    song_data_path = tmp_path / "song_data.json"
    stream_path = tmp_path / "taiko_goku_all_levels_stream.json"
    unified_path = tmp_path / "taiko_goku_onis.json"
    stream_path.write_text("[]", encoding="utf-8")
    score_path.write_text(
        json.dumps(
            [
                {
                    "id": 969,
                    "title": "いただきバベル",
                    "level": 4,
                    "tenjo_score": 995860,
                    "goku_score": 1003960,
                    "max_combo": 493,
                    "initial_points": 2020,
                    "selected_version": "AC16.2.0",
                },
                {
                    "id": None,
                    "title": "いただきバベル (Prod. ケンモチヒデフミ)",
                    "level": 4,
                    "tenjo_score": 995860,
                    "goku_score": 1003960,
                    "max_combo": 493,
                    "initial_points": None,
                    "selected_version": None,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    song_data_path.write_text(
        json.dumps(
            [
                {
                    "id": 969,
                    "song_name_jp": "いただきバベル (Prod. ケンモチヒデフミ)",
                    "song_name": "Itadaki Babel (Prod. Kenmochi Hidefumi)",
                    "max_combo": [94, 158, 306, 493, "-"],
                    "roll_times": [None, None, None, [4.65], None],
                    "balloons": [None, None, None, [], None],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(score_line, "SCORE_PATH", score_path)
    monkeypatch.setattr(score_line, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(score_line, "ALL_LEVELS_STREAM_PATH", stream_path)
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    row_count, matched_count = score_line.rebuild_scoreline_dataset(unified_path)
    rows = json.loads(unified_path.read_text(encoding="utf-8"))

    assert row_count == 1
    assert matched_count == 1
    assert rows[0]["title"] == "いただきバベル (Prod. ケンモチヒデフミ)"
    assert rows[0]["initial_points"] == 2020
    assert rows[0]["selected_version"] == "AC16.2.0"


def test_chart_index_does_not_replace_complete_chart_with_incomplete_duplicate(
    tmp_path: Path, monkeypatch
) -> None:
    unified_path = tmp_path / "taiko_goku_onis.json"
    unified_path.write_text(
        json.dumps(
            [
                {
                    "id": 969,
                    "level": 4,
                    "initial_points": 2020,
                    "max_combo": 493,
                    "goku_score": 1003960,
                },
                {
                    "id": 969,
                    "level": 4,
                    "initial_points": 0,
                    "max_combo": 493,
                    "goku_score": 1003960,
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    by_id, _ = score_line._build_chart_index(unified_path.stat().st_mtime_ns)

    assert by_id[(969, 4)]["initial_points"] == 2020


def test_rebuild_scoreline_dataset_corrects_waraeru_aggregated_api_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    score_path = tmp_path / "song_score.json"
    song_data_path = tmp_path / "song_data.json"
    stream_path = tmp_path / "taiko_goku_all_levels_stream.json"
    unified_path = tmp_path / "taiko_goku_onis.json"
    stream_path.write_text("[]", encoding="utf-8")
    score_path.write_text(
        json.dumps(
            [{
                "id": 890,
                "title": "わら得る2000",
                "level": 4,
                "goku_score": 1_007_080,
                "max_combo": 818,
                "initial_points": 1210,
            }],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    song_data_path.write_text(
        json.dumps(
            [{
                "id": 890,
                "song_name_jp": "わら得る2000",
                "song_name": "可笑可啸2000",
                "max_combo": [284, 386, 605, 818, "-"],
                "roll_times": [None, None, None, [17.74], None],
                "balloons": [None, None, None, [50], None],
            }],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(score_line, "SCORE_PATH", score_path)
    monkeypatch.setattr(score_line, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(score_line, "ALL_LEVELS_STREAM_PATH", stream_path)
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    score_line.rebuild_scoreline_dataset(unified_path)
    row = json.loads(unified_path.read_text(encoding="utf-8"))[0]

    assert row["roll_total_seconds"] == pytest.approx(2.867)
    assert row["balloons"] == [6, 6, 6, 6, 6, 6, 6, 938, 8]
    assert row["balloon_hits"] == 988


def test_get_scoreline_entry_refreshes_when_source_data_changes(tmp_path: Path, monkeypatch) -> None:
    score_path = tmp_path / "song_score.json"
    song_data_path = tmp_path / "song_data.json"
    stream_path = tmp_path / "taiko_goku_all_levels_stream.json"
    unified_path = tmp_path / "taiko_goku_onis.json"
    stream_path.write_text("[]", encoding="utf-8")
    score_path.write_text(
        json.dumps(
            [
                {
                    "title": "Test Song",
                    "level": 4,
                    "tenjo_score": 990000,
                    "goku_score": 1000000,
                    "roll_required": 8,
                    "roll_speed_ips": 16.0,
                    "max_combo": 0,
                    "initial_points": 2500,
                    "selected_version": "AC16.1.0",
                    "id": 1,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    song_data_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "song_name_jp": "Test Song",
                    "song_name": "测试歌曲",
                    "max_combo": [100, 200, 300, 400, "-"],
                    "roll_times": [None, None, None, [], None],
                    "balloons": [None, None, None, [], None],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(score_line, "SCORE_PATH", score_path)
    monkeypatch.setattr(score_line, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(score_line, "ALL_LEVELS_STREAM_PATH", stream_path)
    monkeypatch.setattr(score_line, "UNIFIED_PATH", unified_path)
    score_line._load_scoreline_data.cache_clear()
    score_line._build_chart_index.cache_clear()

    from taiko_bot.offline import score_prediction_support
    from taiko_bot.runtime.player.center import duplicate_versions
    monkeypatch.setattr(score_prediction_support, "SCORELINE_PATH", unified_path)
    monkeypatch.setattr(duplicate_versions, "SONG_DATA_PATH", song_data_path)
    first = __import__("taiko_bot.offline.score_prediction_support", fromlist=["resolve_scoreline_chart"]).resolve_scoreline_chart(1, 4, "Test Song", scoreline_path=unified_path, song_data_path=song_data_path)
    assert first is not None
    assert first["roll_total_seconds"] == 0

    song_data_path.write_text(
        json.dumps(
            [
                {
                    "id": 1,
                    "song_name_jp": "Test Song",
                    "song_name": "测试歌曲",
                    "max_combo": [100, 200, 300, 400, "-"],
                    "roll_times": [None, None, None, [0.46], None],
                    "balloons": [None, None, None, [], None],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    refreshed_source_ns = unified_path.stat().st_mtime_ns + 1_000_000
    os.utime(song_data_path, ns=(refreshed_source_ns, refreshed_source_ns))

    second = __import__("taiko_bot.offline.score_prediction_support", fromlist=["resolve_scoreline_chart"]).resolve_scoreline_chart(1, 4, "Test Song", scoreline_path=unified_path, song_data_path=song_data_path)
    assert second is not None
    assert second["roll_total_seconds"] == 0.46


def test_extract_other_db_songs_keeps_only_non_digit_song_no() -> None:
    database_data = [
        {"songNo": "1", "title": "Digit Song"},
        {"songNo": "AC_893", "title": "Peace Sign"},
        {"songNo": "NS2_0016", "title": "Sign wa B"},
        {"songNo": "1523", "title": "Another Digit"},
        {"songNo": "CS_ttk3", "title": "Hamutaro"},
    ]

    other_songs = _extract_other_db_songs(database_data)

    assert [song["songNo"] for song in other_songs] == [
        "AC_893",
        "CS_ttk3",
        "NS2_0016",
    ]


def test_build_other_song_assigns_other_shelf_status_and_keeps_song_no() -> None:
    db_song = {
        "songNo": "AC_893",
        "title": "ピースサイン",
        "titleEn": "Peace Sign",
        "artists": ["Kenshi Yonezu"],
        "version": ["NAC"],
        "genre": ["pops"],
        "bpm": {"min": 200, "max": 200},
        "addedDate": 1600000000000,
        "order": 100,
        "courses": {
            "easy": {"level": 3, "maxCombo": 100},
            "normal": {"level": 5, "maxCombo": 200},
            "hard": {"level": 6, "maxCombo": 300},
            "oni": {"level": 8, "maxCombo": 500},
            "ura": None,
        },
    }

    song = _build_other_song(db_song, 100000)

    assert song["id"] == 100000
    assert song["sort"] == 100000
    assert song["songNo"] == "AC_893"
    assert song["shelf_status"] == 2
    assert song["song_name_jp"] == "ピースサイン"
    assert song["song_name"] == "Peace Sign"
    assert song["level_1"] == 3
    assert song["level_5"] == "-"
    assert song["max_combo"] == [100, 200, 300, 500, "-"]
    assert song["bpm"] == "200"


def test_apply_other_song_wiki_fields_preserves_id_and_refreshes_fields() -> None:
    db_song = {
        "songNo": "NS2_0016",
        "title": "サインはB -New Arrange Ver.-",
        "titleEn": "Sign wa B -New Arrange Ver.-",
        "artists": ["B小町"],
        "version": ["NS2"],
        "genre": ["anime"],
        "bpm": {"min": 178, "max": 178},
        "courses": {
            "easy": {"level": 3, "maxCombo": 120},
            "normal": {"level": 5, "maxCombo": 240},
            "hard": {"level": 6, "maxCombo": 360},
            "oni": {"level": 8, "maxCombo": 700},
            "ura": None,
        },
    }
    existing = {
        "id": 100003,
        "songNo": "NS2_0016",
        "song_name_jp": "旧标题",
        "song_name": "Old Title",
        "shelf_status": 2,
        "level_1": "-",
    }

    updated = _apply_other_song_wiki_fields(existing, db_song)

    assert updated["id"] == 100003
    assert updated["songNo"] == "NS2_0016"
    assert updated["shelf_status"] == 2
    assert updated["level_1"] == 3
    assert updated["level_4"] == 8
    assert updated["artists"] == ["B小町"]
    assert updated["version"] == ["NS2"]
    # Titles are preserved (refresh only updates wiki-derived fields).
    assert updated["song_name_jp"] == "旧标题"


def test_collect_rating_target_pairs_skips_other_songs() -> None:
    song_data = [
        {"id": 100000, "level_4": 8, "level_5": "-"},
        {"id": 123, "level_4": 10, "level_5": "-"},
    ]

    pairs = _collect_rating_target_pairs(song_data)

    assert pairs == [(123, 4)]
