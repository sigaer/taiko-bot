from __future__ import annotations

import pytest

from plugins.utils import taikob_v2


@pytest.fixture(autouse=True)
def clear_v2_song_cache():
    taikob_v2._load_v2_song_map.cache_clear()
    yield
    taikob_v2._load_v2_song_map.cache_clear()


def test_compute_all_v2_from_userdata_records_uses_constants_csv(tmp_path, monkeypatch):
    csv_path = tmp_path / "constants_id_v2.csv"
    csv_path.write_text(
        "id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,stamina,handspeed,burst,complex,rhythm\n"
        "100,Test Song,oni,1000,9.5,10.0,10.5,55,60,58,57,59\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(taikob_v2, "V2_CONSTANTS_CSV", csv_path)
    taikob_v2._load_v2_song_map.cache_clear()

    results = taikob_v2.compute_all_v2_from_userdata_records(
        [
            {
                "song_no": 100,
                "level": 4,
                "high_score": 950000,
                "good_cnt": 920,
                "ok_cnt": 60,
                "ng_cnt": 20,
                "dondaful_combo_cnt": 0,
            }
        ]
    )

    assert len(results) == 1
    assert results[0].song_id == 100
    assert results[0].AI_rating > 0
    assert results[0].accuracy_rt > 0


def test_compute_all_v2_includes_hard_charts(tmp_path, monkeypatch):
    csv_path = tmp_path / "constants_id_v2.csv"
    csv_path.write_text(
        "id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,stamina,handspeed,burst,complex,rhythm\n"
        "101,Hard Song,hard,500,4.0,4.5,5.0,4.1,4.2,4.3,4.4,4.5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(taikob_v2, "V2_CONSTANTS_CSV", csv_path)
    taikob_v2._load_v2_song_map.cache_clear()

    results = taikob_v2.compute_all_v2_from_userdata_records(
        [
            {
                "song_no": 101,
                "level": 3,
                "high_score": 900000,
                "good_cnt": 430,
                "ok_cnt": 60,
                "ng_cnt": 10,
                "dondaful_combo_cnt": 0,
            }
        ]
    )

    assert len(results) == 1
    assert results[0].level == 3
    assert results[0].song_name == "Hard Song"


def test_v2_constants_loader_filters_independent_double_play_song_ids(
    tmp_path, monkeypatch
):
    csv_path = tmp_path / "constants_id_v2.csv"
    csv_path.write_text(
        "id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,stamina,handspeed,burst,complex,rhythm\n"
        "900,【双打】 双龙之乱,oni,448,6.3,8.1,8.7,2.4,10.2,7.9,3.2,9.4\n"
        "393,双龙之乱,oni,970,13.9,13.8,13.6,14.8,15.5,15.0,11.2,9.0\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(taikob_v2, "V2_CONSTANTS_CSV", csv_path)
    taikob_v2._load_v2_song_map.cache_clear()

    song_map = taikob_v2._load_v2_song_map()

    assert (900, 4) not in song_map
    assert (393, 4) in song_map


@pytest.mark.parametrize(
    ("accuracy", "constant_attr"),
    [
        (0.90, "sub_constant_1"),
        (0.95, "main_constant"),
        (1.00, "sub_constant_2"),
    ],
)
def test_v2_rating_matches_upstream_interpolation_reference_points(accuracy, constant_attr):
    chart = taikob_v2.V2SongData(
        song_id=102,
        level=4,
        title="Anchor Song",
        total_notes=1000,
        sub_constant_1=6.0,
        main_constant=8.0,
        sub_constant_2=10.0,
        stamina=7.0,
        handspeed=7.0,
        burst=7.0,
        complex=7.0,
        rhythm=7.0,
    )

    result = taikob_v2._calculate_v2_from_chart(
        chart,
        accuracy_per=accuracy,
        bad_per=0.0,
    )
    expected = taikob_v2._calc_single_rating(
        getattr(chart, constant_attr),
        taikob_v2.calc_y(accuracy, 15.5, "comprehensive"),
    )

    assert result.AI_rating == pytest.approx(expected)
