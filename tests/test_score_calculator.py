from plugins.utils.score_calculator import compute_all_from_userdata_records


def test_compute_all_from_userdata_records_collapses_duplicate_versions_by_default():
    records = [
        {
            "song_no": 433,
            "level": 4,
            "good_cnt": 760,
            "ok_cnt": 5,
            "high_score": 998000,
            "dondaful_combo_cnt": 0,
        },
        {
            "song_no": 1265,
            "level": 4,
            "good_cnt": 765,
            "ok_cnt": 0,
            "high_score": 1000000,
            "dondaful_combo_cnt": 1,
        },
    ]

    results = compute_all_from_userdata_records(records)

    assert len(results) == 1
    assert results[0].song_id == 1265


def test_compute_all_from_userdata_records_ignores_hidden_or_non_public_songs():
    records = [
        {
            "song_no": 900,
            "level": 4,
            "good_cnt": 440,
            "ok_cnt": 0,
            "high_score": 1000000,
        },
        {
            "song_no": 987,
            "level": 4,
            "good_cnt": 380,
            "ok_cnt": 0,
            "high_score": 1000000,
        },
        {
            "song_no": 1429,
            "level": 4,
            "good_cnt": 100,
            "ok_cnt": 0,
            "high_score": 1000000,
        },
    ]

    results = compute_all_from_userdata_records(records)

    assert results == []
