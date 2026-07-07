from __future__ import annotations

from plugins.utils import target_recommend


def test_parse_target_recommendation_request_supports_star_filter():
    assert target_recommend.parse_target_recommendation_request("紫雅 9星") == ("ziya", "9", None)
    assert target_recommend.parse_target_recommendation_request("全连") == (
        target_recommend.FULL_COMBO_TARGET,
        None,
        None,
    )
    assert target_recommend.parse_target_recommendation_request("粉雅 abc") == ("fenya", None, "invalid_star")


def test_compute_target_recommendations_filters_achieved_and_sorts_candidates(monkeypatch):
    monkeypatch.setattr(
        target_recommend,
        "_load_userdata_payload",
        lambda _user_id: {
            "songs": [
                {
                    "song_no": 1,
                    "level": 4,
                    "high_score": 960000,
                    "good_cnt": 900,
                    "ok_cnt": 50,
                    "ng_cnt": 10,
                    "combo_cnt": 800,
                    "full_combo_cnt": 0,
                    "dondaful_combo_cnt": 0,
                },
                {
                    "song_no": 2,
                    "level": 4,
                    "high_score": 910000,
                    "good_cnt": 850,
                    "ok_cnt": 80,
                    "ng_cnt": 20,
                    "combo_cnt": 780,
                    "full_combo_cnt": 0,
                    "dondaful_combo_cnt": 0,
                },
            ]
        },
    )
    monkeypatch.setattr(
        target_recommend,
        "_build_user_profile",
        lambda _records: {
            "rating": 12.4,
            "const": 10.2,
            "big_song": 11.3,
            "stamina": 10.8,
            "speed": 10.2,
            "accuracy_power": 10.9,
            "rhythm": 9.9,
            "complex_proc": 10.1,
        },
    )
    monkeypatch.setattr(
        target_recommend,
        "_load_scoreline_rows",
        lambda: [
            {
                "id": 1,
                "level": 4,
                "title": "Achieved Song",
                "title_cn": "Achieved Song",
                "rating_scores": {"ziya": 950000},
                "max_combo": 1000,
            },
            {
                "id": 2,
                "level": 4,
                "title": "Near Song",
                "title_cn": "Near Song",
                "rating_scores": {"ziya": 950000},
                "max_combo": 1000,
            },
            {
                "id": 3,
                "level": 4,
                "title": "Far Song",
                "title_cn": "Far Song",
                "rating_scores": {"ziya": 950000},
                "max_combo": 1000,
            },
        ],
    )
    monkeypatch.setattr(
        target_recommend,
        "_build_song_maps",
        lambda: (
            {
                1: {"id": 1, "song_name": "Achieved Song"},
                2: {"id": 2, "song_name": "Near Song"},
                3: {"id": 3, "song_name": "Far Song"},
            },
            {(1, 4): "9", (2, 4): "9", (3, 4): "9"},
        ),
    )
    const_table = [(9.0, 9.0), (10.0, 10.0), (11.0, 11.0)]
    monkeypatch.setattr(
        target_recommend,
        "_load_rating_lookup",
        lambda: (
            {
                (1, 4): {"id": 1, "level": 4, "score": 10.0, "复合处理": 60, "平均密度": 70, "瞬间密度": 72, "叩き分け": 50, "BPM变化": 35},
                (2, 4): {"id": 2, "level": 4, "score": 10.1, "复合处理": 61, "平均密度": 71, "瞬间密度": 72, "叩き分け": 50, "BPM变化": 35},
                (3, 4): {"id": 3, "level": 4, "score": 11.2, "复合处理": 82, "平均密度": 88, "瞬间密度": 92, "叩き分け": 80, "BPM变化": 78},
            },
            {},
            const_table,
        ),
    )

    result = target_recommend.compute_target_recommendations_for_user("123", "ziya", star_filter="9")

    assert result.is_enough is True
    assert [row["song_id"] for row in result.rows] == [2, 3]
    assert result.rows[0]["recommend_index"] >= result.rows[1]["recommend_index"]
    assert result.rows[0]["target_text"] == "950000"
