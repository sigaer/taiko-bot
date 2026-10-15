from types import SimpleNamespace

from taiko_bot.offline import recommendation_intelligence as bridge


def test_rating_contract_preserves_v1_top20_semantics(monkeypatch):
    calls = {}
    rows = [{"AI_rating": 10.0}, {"AI_rating": 12.0}]

    def fake_compute(user_id, **kwargs):
        calls.update(kwargs)
        return rows

    monkeypatch.setattr(bridge, "compute_all_from_userdata", fake_compute)
    monkeypatch.setattr(bridge.application_recommendation, "aggregate_topN_value", lambda values, key, n: 11.0)
    monkeypatch.setattr(bridge.application_recommendation, "compute_dim_topN_means", lambda values, n: {"大歌力": 9.0, "体力": 8.0})
    payload = bridge.build_player_rating_intelligence(7)

    assert payload["model"] == "v1"
    assert payload["aggregation"] == "per-dimension-top20"
    assert payload["duplicateHandling"] == "preserve"
    assert payload["overallRating"] == 11.0
    assert payload["sampleCount"] == 2
    assert calls["collapse_duplicate_versions"] is False
    assert [item["key"] for item in payload["dimensions"]] == [key for key, _ in bridge.DIMENSION_COLUMNS]


def test_ordinary_projection_is_structured_and_does_not_leak_renderer_index():
    payload = bridge.project_ordinary_recommendations(
        [{
            "song_id": 12, "level": 4, "title": "Test", "is_unplayed": True,
            "song_indicator": 10, "reference_indicator": 11,
            "indicator_deviation_percent": -0.1, "is_in_strict_range": True,
            "recommend_index": 99,
        }],
        basis="rating",
    )
    assert payload["model"] == "v1"
    assert payload["basis"] == "rating"
    assert payload["items"][0]["songId"] == 12
    assert "recommend_index" not in payload["items"][0]


def test_target_projection_keeps_target_progress_and_gap_fields():
    result = SimpleNamespace(
        target_key="full_combo", candidate_count=3, required_count=10, is_enough=False,
        rows=[{
            "song_id": 12, "level": 4, "star": "9", "title": "Test", "score": 900000,
            "target_score": None, "gap_kind": "combo", "gap_value": 4,
            "progress": 82.345, "recommend_index": 76.5, "is_unplayed": False,
        }],
    )
    item = bridge.project_target_recommendations(result)["items"][0]
    assert item == {
        "songId": 12, "level": 4, "star": "9", "title": "Test", "currentScore": 900000,
        "targetScore": None, "targetKey": "full_combo", "gapKind": "combo", "gapValue": 4,
        "progressPercent": 82.34, "targetRecommendationIndex": 76.5, "isUnplayed": False,
    }
