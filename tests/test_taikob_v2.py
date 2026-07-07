from __future__ import annotations

from plugins.utils import taikob_v2


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
