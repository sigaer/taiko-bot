from __future__ import annotations

import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taiko_bot.runtime.player.center.recommendation_support import target_render as utils_module
from taiko_bot.offline.score_calculator import (
    aggregate_topN_value,
    build_const_table,
    calc_y,
    compute_AI,
    compute_P,
    compute_Q,
    compute_all_from_userdata_records,
    load_rating_config,
    lookup_const_score,
)
from taiko_bot.offline.score_estimator import (
    build_score_estimator_profile,
    estimate_target_reach_batch,
    forecast_chart_performance_batch,
)
from taiko_bot.offline.performance_forecast import build_chart_performance_forecast
from taiko_bot.runtime.player.center.recommendation_support.target_render import render_target_recommendation_image_bytes
from taiko_bot.offline.target_recommend import (
    DONDAFUL_TARGET,
    FULL_COMBO_TARGET,
    _build_best_entry_map,
    _build_dondaful_row,
    _build_score_target_row,
    _build_owned_score_target_row,
    _build_user_profile,
    _load_candidate_charts,
    _load_rating_features,
    _load_rating_support,
    _load_rating_features_by_title_level,
    _load_song_title_keys,
    _chart_title_key,
    _const_match,
    _profile_match,
    _recommend_index_from_likelihood,
    _score_target_pair_pressure_penalty,
    _score_target_tolerance,
    _dondaful_required_dims,
    _exceeds_target_score_dim_limits,
    _full_combo_required_dims,
    _hs_change_penalty,
    _target_score_required_dims,
    _scale_user_dim_to_raw_capacity,
    _score_target_owner,
    UserProfile,
    compute_target_recommendations_for_user,
    parse_target_recommendation_key,
    parse_target_recommendation_request,
    parse_target_recommendation_star_filter,
)


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _scoreline_row(song_id: int, *, level: int = 4) -> dict:
    goku_score = 1000000 + song_id * 10
    return {
        "id": song_id,
        "title": f"Song {song_id}",
        "title_jp": f"Song {song_id}",
        "title_cn": f"曲目 {song_id}",
        "level": level,
        "difficulty_label": "里谱" if level == 5 else "表谱",
        "tenjo_score": goku_score - 10000,
        "goku_score": goku_score,
        "rating_scores": {
            "goku": goku_score,
            "ziya": int(goku_score * 0.95),
            "fenya": int(goku_score * 0.90),
            "jinya": int(goku_score * 0.80),
        },
        "roll_required": 0,
        "roll_speed_ips": 0,
        "max_combo": 500,
        "initial_points": 2000,
        "ok_points": 1000,
        "roll_total_seconds": 0.0,
        "balloon_hits": 0,
    }


def _rating_payload(song_ids: range) -> dict:
    songs = {}
    for song_id in song_ids:
        songs[f"song-{song_id}"] = {
            "id": song_id,
            "level": 4,
            "song_name_cn": f"曲目 {song_id}",
            "score": 8.0 + (song_id % 4) * 0.1,
            "combo": 500,
            "复合处理": 35 + song_id % 10,
            "平均密度": 40 + song_id % 9,
            "瞬间密度": 42 + song_id % 8,
            "叩き分け": 45 + song_id % 7,
            "BPM变化": 10 + song_id % 5,
        }
    return {
        "songs": songs,
        "const_table": {"const_to_score": {"8.0": 3.0, "8.3": 3.75}},
    }


def _song_data(song_ids: range) -> list[dict]:
    return [
        {
            "id": song_id,
            "shelf_status": 0,
            "level_4": 8,
            "level_5": "-",
            "max_combo": ["-", "-", "-", 500, "-"],
        }
        for song_id in song_ids
    ]


def _userdata(song_ids: range) -> dict:
    songs = []
    for song_id in song_ids:
        songs.append(
            {
                "song_no": song_id,
                "level": 4,
                "high_score": 890000 + song_id * 100,
                "good_cnt": 440,
                "ok_cnt": 50,
                "ng_cnt": 10,
                "combo_cnt": 430,
                "clear_cnt": 1,
                "full_combo_cnt": 0,
                "dondaful_combo_cnt": 0,
                "best_score_rank": 5,
            }
        )
    return {"profile": {"mydon_name": "Tester"}, "songs": songs, "achievement": {}}


def _fixture_paths(tmp_path: Path, count: int = 24) -> tuple[Path, Path, Path, Path]:
    song_ids = range(1, count + 1)
    userdata_dir = tmp_path / "userdata"
    scoreline_path = tmp_path / "taiko_goku_onis.json"
    rating_path = tmp_path / "rating.json"
    song_data_path = tmp_path / "song_data.json"
    _write_json(userdata_dir / "114514data.json", _userdata(song_ids))
    _write_json(scoreline_path, [_scoreline_row(song_id) for song_id in song_ids])
    _write_json(rating_path, _rating_payload(song_ids))
    _write_json(song_data_path, _song_data(song_ids))
    return userdata_dir, scoreline_path, rating_path, song_data_path


def _boost_userdata_to_high_capacity(payload: dict) -> None:
    for index, record in enumerate(payload.get("songs", []), start=1):
        record["high_score"] = 998000 + index * 10
        record["good_cnt"] = 499
        record["ok_cnt"] = 1
        record["ng_cnt"] = 0
        record["combo_cnt"] = 500


def _load_real_user_records(user_id: int) -> list[dict]:
    payload = json.loads(
        Path(f"/home/sigaer/taiko/userdata/{user_id}data.json").read_text(
            encoding="utf-8"
        )
    )
    return payload["songs"]


def _real_sample_pair_penalty(
    user_id: int,
    song_id: int,
    level: int,
    target_score: int,
    roll_speed_ips: float,
) -> float:
    records = _load_real_user_records(user_id)
    estimator_profile = build_score_estimator_profile(
        records,
        exclude_song_id=song_id,
        exclude_level=level,
    )
    charts = _load_candidate_charts(
        estimator_profile.scoreline_path,
        estimator_profile.song_data_path,
    )
    chart = next(
        chart
        for chart in charts
        if int(chart["id"]) == song_id and int(chart["level"]) == level
    )
    feature = estimator_profile.features_by_key[(song_id, level)]
    tolerance = _score_target_tolerance(chart, target_score, roll_speed_ips)

    assert tolerance is not None
    assert bool(tolerance.get("reachable"))

    required_dims = _target_score_required_dims(
        chart=chart,
        feature=feature,
        target_score=target_score,
        tolerance=tolerance,
        const_table=estimator_profile.const_table,
    )
    return _score_target_pair_pressure_penalty(
        estimator_profile.stable_profile,
        required_dims,
    )


def _legacy_clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, float(value)))


def _legacy_sigmoid01(value: float, scale: float) -> float:
    if scale <= 0:
        return 1.0 if value >= 0 else 0.0
    x = _legacy_clamp(value / scale, -40.0, 40.0)
    return 1.0 / (1.0 + math.exp(-x))


def _legacy_profile_probability_factor(profile_match: float, const_match: float) -> float:
    combined = _legacy_clamp(
        (profile_match * 0.72 + const_match * 0.28) / 100.0, 0.0, 1.0
    )
    return _legacy_clamp(0.22 + 0.78 * (combined**1.45), 0.05, 1.0)


def _legacy_recommend_index_from_likelihood(likelihood: float) -> float:
    p = _legacy_clamp(likelihood / 100.0, 0.0, 1.0)
    return _legacy_clamp((1.0 - ((1.0 - p) ** 1.7)) * 100.0, 0.0, 100.0)


def _days_ago_timestamp(days_ago: int) -> str:
    return (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


def _legacy_unplayed_score_target_likelihood(
    *,
    chart: dict,
    target_score: int,
    tolerance: dict,
    profile,
    feature: dict,
    profile_match: float,
    const_match: float,
) -> float:
    note_count = max(1, int(chart["max_combo"]))
    max_ok = max(0, int(tolerance["max_ok"]))
    ok_allow_ratio = _legacy_clamp(max_ok / note_count, 0.0, 1.0)
    required_good_rate = 1.0 - ok_allow_ratio
    profile_factor = _legacy_profile_probability_factor(profile_match, const_match)
    goku_score = max(1, int(chart["goku_score"]))
    feature_factor = 0.88 + profile_match / 100.0 * 0.18
    const_value = float(feature["const"])
    const_excess = max(0.0, const_value - profile.difficulty_capacity)
    estimated_score = goku_score * profile.score_ratio_median * feature_factor
    score_margin = (
        estimated_score / max(1, target_score) - 1.0 - const_excess * 0.018
    )
    score_probability = _legacy_sigmoid01(score_margin, 0.040)
    accuracy_probability = _legacy_sigmoid01(
        profile.accuracy_median - required_good_rate,
        0.060,
    )
    base_probability = (
        score_probability * 0.52
        + accuracy_probability * 0.30
        + ok_allow_ratio * 0.18
    )
    return _legacy_clamp(base_probability * profile_factor * 100.0, 0.0, 100.0)


def test_parse_target_recommendation_key_supports_requested_aliases() -> None:
    assert parse_target_recommendation_key("极") == "goku"
    assert parse_target_recommendation_key("紫雅") == "ziya"
    assert parse_target_recommendation_key("粉雅") == "fenya"
    assert parse_target_recommendation_key("金雅") == "jinya"
    assert parse_target_recommendation_key("全连") == FULL_COMBO_TARGET
    assert parse_target_recommendation_key("全良") == DONDAFUL_TARGET


def test_parse_target_recommendation_request_supports_optional_star_filter() -> None:
    assert parse_target_recommendation_star_filter("9") == "9"
    assert parse_target_recommendation_star_filter("9星") == "9"
    assert parse_target_recommendation_star_filter("九星") == "9"
    assert parse_target_recommendation_request("紫雅 9") == ("ziya", "9", None)
    assert parse_target_recommendation_request("紫雅 9星") == ("ziya", "9", None)
    assert parse_target_recommendation_request("紫雅 九星") == ("ziya", "9", None)
    assert parse_target_recommendation_request("紫雅9星") == ("ziya", "9", None)
    assert parse_target_recommendation_request("紫雅 abc") == ("ziya", None, "invalid_star")


def test_target_reach_keeps_objective_difficulty_after_capacity_is_met(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path,
        count=24,
    )
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [
        record for record in userdata["songs"] if record["song_no"] not in {21, 22}
    ]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.0,
            "复合处理": 24.0,
            "平均密度": 25.0,
            "瞬间密度": 26.0,
            "叩き分け": 24.0,
            "BPM变化": 2.0,
        }
    )
    rating_payload["songs"]["song-22"].update(
        {
            "score": 8.3,
            "复合处理": 34.0,
            "平均密度": 34.0,
            "瞬间密度": 35.0,
            "叩き分け": 33.0,
            "BPM变化": 4.0,
        }
    )
    _write_json(rating_path, rating_payload)

    records = userdata["songs"]
    estimator_profile = build_score_estimator_profile(
        records,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    candidates = []
    for song_id in (21, 22):
        chart = next(chart for chart in charts if chart["id"] == song_id)
        candidates.append(
            {
                "chart": chart,
                "feature": estimator_profile.features_by_key[(song_id, 4)],
                "entry": None,
                "targets": {"fenya": chart["rating_scores"]["fenya"]},
            }
        )

    reaches = estimate_target_reach_batch(estimator_profile, candidates)
    easier = reaches[(21, 4)]["fenya"]
    harder = reaches[(22, 4)]["fenya"]

    assert easier.required_accuracy_power < harder.required_accuracy_power
    assert easier.objective_load < harder.objective_load
    assert easier.likelihood > harder.likelihood


def test_target_reach_uses_fresh_weak_target_record_as_bounded_evidence(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path,
        count=24,
    )
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    records = userdata["songs"]
    estimator_profile = build_score_estimator_profile(
        records,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    chart = next(chart for chart in _load_candidate_charts(scoreline_path, song_data_path) if chart["id"] == 21)
    feature = estimator_profile.features_by_key[(21, 4)]
    target = chart["rating_scores"]["fenya"]
    entry = {
        "song_no": 21,
        "level": 4,
        "high_score": 899_000,
        "good_cnt": 499,
        "ok_cnt": 1,
        "ng_cnt": 0,
        "combo_cnt": 500,
    }
    recent = estimate_target_reach_batch(
        estimator_profile,
        [{"chart": chart, "feature": feature, "entry": {**entry, "update_datetime": _days_ago_timestamp(7)}, "targets": {"fenya": target}}],
    )[(21, 4)]["fenya"]
    stale = estimate_target_reach_batch(
        estimator_profile,
        [{"chart": chart, "feature": feature, "entry": {**entry, "update_datetime": _days_ago_timestamp(400)}, "targets": {"fenya": target}}],
    )[(21, 4)]["fenya"]
    baseline = estimate_target_reach_batch(
        estimator_profile,
        [{"chart": chart, "feature": feature, "entry": None, "targets": {"fenya": target}}],
    )[(21, 4)]["fenya"]

    assert recent.likelihood < stale.likelihood < baseline.likelihood
    assert baseline.likelihood - stale.likelihood < baseline.likelihood - recent.likelihood
    assert recent.roll_speed_ips == pytest.approx(25.0)
    assert recent.used_roll_evidence is False


def test_real_user_target_reach_uses_objective_load_and_roll_evidence() -> None:
    records = _load_real_user_records(2258735)
    estimator_profile = build_score_estimator_profile(records)
    charts = _load_candidate_charts(
        estimator_profile.scoreline_path,
        estimator_profile.song_data_path,
    )
    candidates = []
    for song_id in (13, 1215, 1337):
        chart = next(chart for chart in charts if int(chart["id"]) == song_id and int(chart["level"]) == 4)
        candidates.append(
            {
                "chart": chart,
                "feature": estimator_profile.features_by_key[(song_id, 4)],
                "entry": estimator_profile.best_map.get((song_id, 4)),
                "targets": {"fenya": chart["rating_scores"]["fenya"]},
            }
        )

    reaches = estimate_target_reach_batch(estimator_profile, candidates)
    heart = reaches[(13, 4)]["fenya"]
    nosferatu = reaches[(1215, 4)]["fenya"]
    dive = reaches[(1337, 4)]["fenya"]

    assert heart.required_accuracy_power < nosferatu.required_accuracy_power
    assert dive.required_accuracy_power < heart.required_accuracy_power
    assert len({round(estimate.objective_load, 6) for estimate in (heart, nosferatu, dive)}) == 3
    assert all(estimate.used_roll_evidence for estimate in (heart, nosferatu, dive))
    assert all(estimate.roll_speed_ips > 25.0 for estimate in (heart, nosferatu, dive))


def test_real_user_36779742_filters_hard_mismatch_from_jinya() -> None:
    result = compute_target_recommendations_for_user(36779742, "jinya")

    assert 890 not in {row["song_id"] for row in result.rows}
    records = _load_real_user_records(36779742)
    profile = build_score_estimator_profile(records)
    charts_by_key = {
        (int(chart["id"]), int(chart["level"])): chart
        for chart in _load_candidate_charts(
            profile.scoreline_path,
            profile.song_data_path,
        )
    }
    candidates = []
    for row in result.rows:
        key = (int(row["song_id"]), int(row["level"]))
        chart = charts_by_key[key]
        candidates.append({"chart": chart})
    forecasts = forecast_chart_performance_batch(profile, candidates)

    for row in result.rows:
        key = (int(row["song_id"]), int(row["level"]))
        forecast = forecasts[key]
        assert forecast.data_sufficiency == "ok"
        if int(row["target_text"]) > forecast.pb_score:
            assert float(row["recommend_index"]) < 50.0


def test_real_user_2258735_easy_goku_outranks_edge_jinya() -> None:
    goku = compute_target_recommendations_for_user(2258735, "goku")
    jinya = compute_target_recommendations_for_user(2258735, "jinya")
    assert goku.rows
    easy = goku.rows[0]

    assert float(easy["recommend_index"]) >= 87.5
    records = _load_real_user_records(2258735)
    profile = build_score_estimator_profile(records)
    charts_by_key = {
        (int(chart["id"]), int(chart["level"])): chart
        for chart in _load_candidate_charts(
            profile.scoreline_path,
            profile.song_data_path,
        )
    }
    candidates = [
        {"chart": charts_by_key[(int(row["song_id"]), int(row["level"]))]}
        for row in jinya.rows
    ]
    forecasts = forecast_chart_performance_batch(profile, candidates)
    for row in jinya.rows:
        key = (int(row["song_id"]), int(row["level"]))
        if forecasts[key].stable_score < int(row["target_text"]):
            assert float(row["recommend_index"]) < float(easy["recommend_index"])


def test_score_target_uses_target_score_and_default_roll_assumption(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        limit=10,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.rows
    assert len(result.rows) <= 10
    row = result.rows[0]
    assert row["target_text"].isdigit()
    assert str(row["gap_text"]).startswith("差")
    assert row["progress"] < 100.0
    assert row["star"] == "8"
    assert 0 <= row["recommend_index"] <= 100
    assert 0 <= row["target_band_index"] <= row["recommend_index"]
    indexes = [row["recommend_index"] for row in result.rows]
    assert indexes == sorted(indexes, reverse=True)


def test_full_combo_and_dondaful_exclude_already_achieved_charts(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path)
    path = userdata_dir / "114514data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["songs"][0]["full_combo_cnt"] = 1
    payload["songs"][1]["dondaful_combo_cnt"] = 1
    _write_json(path, payload)

    fc_result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    df_result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert all(row["song_id"] not in {1, 2} for row in fc_result.rows)
    assert all(row["song_id"] != 2 for row in df_result.rows)


def test_unplayed_charts_can_enter_recommendations(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=30)
    path = userdata_dir / "114514data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["songs"] = payload["songs"][:5]
    _write_json(path, payload)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        limit=10,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.candidate_count > 0
    assert any(row["is_unplayed"] for row in result.rows)
    assert any(row["gap_text"] == "未游玩" for row in result.rows)


def test_user_profile_uses_user_side_rating_and_six_dims(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path)
    userdata = json.loads((userdata_dir / "114514data.json").read_text(encoding="utf-8"))
    records = userdata["songs"]
    rating_results = compute_all_from_userdata_records(records, rating_path)

    profile = _build_user_profile(
        records,
        _build_best_entry_map(records),
        _load_candidate_charts(scoreline_path, song_data_path),
        _load_rating_features(rating_path),
        rating_path,
    )

    expected_rating = min(
        aggregate_topN_value(rating_results, "AI_rating", 20) * 0.98,
        aggregate_topN_value(rating_results, "AI_rating", 40),
    )
    expected_stamina = min(
        aggregate_topN_value(rating_results, "体力", 20) * 0.98,
        aggregate_topN_value(rating_results, "体力", 40),
    )
    expected_raw_stamina = min(
        _scale_user_dim_to_raw_capacity(
            aggregate_topN_value(rating_results, "体力", 20),
            aggregate_topN_value(rating_results, "AI_rating", 20),
        )
        * 0.98,
        _scale_user_dim_to_raw_capacity(
            aggregate_topN_value(rating_results, "体力", 40),
            aggregate_topN_value(rating_results, "AI_rating", 40),
        ),
    )
    assert profile.rating_capacity == pytest.approx(expected_rating)
    assert profile.user_dim_capacity["stamina"] == pytest.approx(expected_stamina)
    assert profile.dim_capacity["stamina"] == pytest.approx(expected_raw_stamina)


def test_target_score_required_dims_matches_current_formula(tmp_path: Path) -> None:
    _, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=1)
    chart = _load_candidate_charts(scoreline_path, song_data_path)[0]
    features_by_key, _, const_table = _load_rating_support(rating_path)
    feature = features_by_key[(1, 4)]
    tolerance = _score_target_tolerance(
        chart,
        int(chart["rating_scores"]["fenya"]),
        25.0,
    )
    assert tolerance is not None

    required_dims = _target_score_required_dims(
        chart=chart,
        feature=feature,
        target_score=int(chart["rating_scores"]["fenya"]),
        tolerance=tolerance,
        const_table=const_table,
    )
    assert required_dims is not None

    note_count = int(chart["max_combo"])
    max_ok = int(tolerance["max_ok"])
    target_accuracy = 1.0 - 0.5 * (max_ok / note_count)
    M = lookup_const_score(float(feature["const"]), const_table)
    N = calc_y(target_accuracy, normalization_factor=15.5, algorithm="comprehensive")
    AI = compute_AI(M, N, compute_P(M, N), compute_Q(M, N))
    assert required_dims["big_song"] == pytest.approx(math.sqrt(AI * M))
    assert required_dims["stamina"] == pytest.approx(
        math.sqrt(AI * float(feature["stamina"]) * 15.5 / 100.0)
    )
    assert required_dims["speed"] == pytest.approx(
        math.sqrt(AI * float(feature["speed"]) * 15.5 / 100.0)
    )
    assert required_dims["accuracy_power"] == pytest.approx(math.sqrt(AI * N))
    assert required_dims["rhythm"] == pytest.approx(
        math.sqrt(AI * float(feature["rhythm"]) * 15.5 / 100.0)
    )
    assert required_dims["complex"] == pytest.approx(
        math.sqrt(AI * float(feature["complex"]) * 15.5 / 100.0)
    )


def test_full_combo_required_dims_use_fixed_target_accuracy(tmp_path: Path) -> None:
    _, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=1)
    chart = _load_candidate_charts(scoreline_path, song_data_path)[0]
    features_by_key, _, const_table = _load_rating_support(rating_path)
    feature = features_by_key[(1, 4)]

    required_dims = _full_combo_required_dims(
        chart=chart,
        feature=feature,
        const_table=const_table,
    )
    assert required_dims is not None

    M = lookup_const_score(float(feature["const"]), const_table)
    N = calc_y(0.90, normalization_factor=15.5, algorithm="comprehensive")
    AI = compute_AI(M, N, compute_P(M, N), compute_Q(M, N))
    assert required_dims["big_song"] == pytest.approx(math.sqrt(AI * M))
    assert required_dims["speed"] == pytest.approx(
        math.sqrt(AI * float(feature["speed"]) * 15.5 / 100.0)
    )
    assert required_dims["complex"] == pytest.approx(
        math.sqrt(AI * float(feature["complex"]) * 15.5 / 100.0)
    )
    assert required_dims["accuracy_power"] == pytest.approx(math.sqrt(AI * N))


def test_dondaful_required_dims_use_fixed_target_accuracy(tmp_path: Path) -> None:
    _, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=1)
    chart = _load_candidate_charts(scoreline_path, song_data_path)[0]
    features_by_key, _, const_table = _load_rating_support(rating_path)
    feature = features_by_key[(1, 4)]

    required_dims = _dondaful_required_dims(
        chart=chart,
        feature=feature,
        const_table=const_table,
    )
    assert required_dims is not None

    M = lookup_const_score(float(feature["const"]), const_table)
    N = calc_y(0.995, normalization_factor=15.5, algorithm="comprehensive")
    AI = compute_AI(M, N, compute_P(M, N), compute_Q(M, N))
    assert required_dims["accuracy_power"] == pytest.approx(math.sqrt(AI * N))
    assert required_dims["rhythm"] == pytest.approx(
        math.sqrt(AI * float(feature["rhythm"]) * 15.5 / 100.0)
    )
    assert required_dims["big_song"] == pytest.approx(math.sqrt(AI * M))


def test_score_target_owner_prefers_the_best_target_band() -> None:
    assert (
        _score_target_owner(
            {
                "jinya": {"recommend_likelihood": 80.0},
                "fenya": {"recommend_likelihood": 60.0},
            }
        )
        == "fenya"
    )
    assert (
        _score_target_owner(
            {
                "fenya": {"recommend_likelihood": 76.0},
                "ziya": {"recommend_likelihood": 55.0},
                "goku": {"recommend_likelihood": 15.0},
            }
        )
        == "ziya"
    )


def test_same_title_same_face_is_excluded_when_already_played(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=6)

    score_rows = [_scoreline_row(song_id) for song_id in range(1, 7)]
    for idx in (0, 5):
        score_rows[idx]["title"] = "Shared Song"
        score_rows[idx]["title_jp"] = "Shared Song"
        score_rows[idx]["title_cn"] = "同名歌曲"
    _write_json(scoreline_path, score_rows)

    song_rows = _song_data(range(1, 7))
    song_rows[0]["song_name"] = "同名歌曲"
    song_rows[5]["song_name"] = "同名歌曲"
    _write_json(song_data_path, song_rows)

    path = userdata_dir / "114514data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["songs"] = [payload["songs"][0]]
    _write_json(path, payload)

    records = payload["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key = _load_rating_features(rating_path)
    features_by_title_level = _load_rating_features_by_title_level(rating_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    candidate_chart = next(
        c for c in charts if c.get("title_cn") == "同名歌曲" and c.get("level") == 4
    )
    candidate_song_id = int(candidate_chart["id"])
    title_key = _chart_title_key(candidate_chart) or title_keys_by_id.get(candidate_song_id, "")
    candidate_feature = features_by_key.get((candidate_song_id, 4)) or features_by_title_level[(title_key, 4)]
    candidate_rows = {}
    for target_key in ("jinya", "fenya", "ziya", "goku"):
        row = _build_score_target_row(
            chart=candidate_chart,
            entry=None,
            target_key=target_key,
            profile=profile,
            feature=candidate_feature,
            roll_speed_ips=25.0,
        )
        if row is not None:
            candidate_rows[target_key] = row
    candidate_owner = _score_target_owner(candidate_rows)
    assert candidate_owner is not None

    result = compute_target_recommendations_for_user(
        "114514",
        candidate_owner,
        limit=6,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert candidate_song_id not in ids


def test_same_title_other_face_remains_candidate_when_only_ura_played(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path, count=6
    )

    score_rows = [_scoreline_row(song_id) for song_id in range(1, 7)]
    score_rows[0] = _scoreline_row(1, level=5)
    score_rows[0]["title"] = "Shared Song(裏譜面)"
    score_rows[0]["title_jp"] = "Shared Song"
    score_rows[0]["title_cn"] = "同名歌曲"
    score_rows[5]["title"] = "Shared Song"
    score_rows[5]["title_jp"] = "Shared Song"
    score_rows[5]["title_cn"] = "同名歌曲"
    _write_json(scoreline_path, score_rows)

    song_rows = _song_data(range(1, 7))
    song_rows[0]["song_name"] = "同名歌曲"
    song_rows[0]["level_4"] = "-"
    song_rows[0]["level_5"] = 9
    song_rows[0]["max_combo"] = ["-", "-", "-", "-", 500]
    song_rows[5]["song_name"] = "同名歌曲"
    _write_json(song_data_path, song_rows)

    rating_payload = _rating_payload(range(1, 7))
    rating_payload["songs"]["song-1-ura"] = {
        "id": 1,
        "level": 5,
        "song_name_cn": "同名歌曲",
        "score": 10.2,
        "combo": 500,
        "复合处理": 60,
        "平均密度": 62,
        "瞬间密度": 64,
        "叩き分け": 58,
        "BPM变化": 12,
    }
    rating_payload["songs"]["song-6"].update(
        {
            "复合处理": 36,
            "平均密度": 40,
            "瞬间密度": 42,
            "叩き分け": 45,
            "BPM变化": 10,
        }
    )
    _write_json(rating_path, rating_payload)

    path = userdata_dir / "114514data.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["songs"] = [payload["songs"][0]]
    payload["songs"][0]["song_no"] = 1
    payload["songs"][0]["level"] = 5
    payload["songs"][0]["high_score"] = 980000
    payload["songs"][0]["good_cnt"] = 470
    payload["songs"][0]["ok_cnt"] = 25
    payload["songs"][0]["ng_cnt"] = 5
    payload["songs"][0]["combo_cnt"] = 460
    _write_json(path, payload)

    records = payload["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key = _load_rating_features(rating_path)
    features_by_title_level = _load_rating_features_by_title_level(rating_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    candidate_chart = next(
        c for c in charts if c.get("title_cn") == "同名歌曲" and c.get("level") == 4
    )
    candidate_song_id = int(candidate_chart["id"])
    title_key = _chart_title_key(candidate_chart) or title_keys_by_id.get(candidate_song_id, "")
    candidate_feature = features_by_key.get((candidate_song_id, 4)) or features_by_title_level[(title_key, 4)]
    candidate_rows = {}
    for target_key in ("jinya", "fenya", "ziya", "goku"):
        row = _build_score_target_row(
            chart=candidate_chart,
            entry=None,
            target_key=target_key,
            profile=profile,
            feature=candidate_feature,
            roll_speed_ips=25.0,
        )
        if row is not None:
            candidate_rows[target_key] = row
    candidate_owner = _score_target_owner(candidate_rows)
    assert candidate_owner is not None

    result = compute_target_recommendations_for_user(
        "114514",
        candidate_owner,
        limit=6,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert candidate_song_id in ids


def test_missing_exact_rating_uses_same_title_level_feature(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=21)

    score_rows = [_scoreline_row(song_id) for song_id in range(1, 22)]
    score_rows[20] = _scoreline_row(21, level=5)
    score_rows[20]["title"] = "Hard Clone"
    score_rows[20]["title_jp"] = "Hard Clone"
    score_rows[20]["title_cn"] = "Hard Clone"
    _write_json(scoreline_path, score_rows)

    song_rows = _song_data(range(1, 22))
    song_rows[20]["level_5"] = 10
    _write_json(song_data_path, song_rows)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    default_rating = _rating_payload(range(1, 21))
    _write_json(rating_path, default_rating)
    records = userdata["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    title_key = "hard clone"

    default_features_by_key = _load_rating_features(rating_path)
    default_features_by_title = _load_rating_features_by_title_level(rating_path)
    profile = _build_user_profile(records, best_map, charts, default_features_by_key, rating_path)
    chart = next(c for c in charts if c.get("id") == 21 and c.get("level") == 5)
    default_feature = default_features_by_key.get((21, 5)) or default_features_by_title.get(
        (title_key, 5)
    )
    if default_feature is None:
        default_feature = {
            "const": profile.difficulty_capacity,
            "stamina": profile.dim_capacity.get("stamina", 50.0),
            "speed": profile.dim_capacity.get("speed", 50.0),
            "rhythm": profile.dim_capacity.get("rhythm", 50.0),
            "complex": profile.dim_capacity.get("complex", 50.0),
        }
    default_rows = {}
    for target_key in ("jinya", "fenya", "ziya", "goku"):
        row = _build_score_target_row(
            chart=chart,
            entry=None,
            target_key=target_key,
            profile=profile,
            feature=default_feature,
            roll_speed_ips=25.0,
        )
        if row is not None:
            default_rows[target_key] = row
    default_owner = _score_target_owner(default_rows)
    assert default_owner is not None
    default_row = _build_owned_score_target_row(
        chart=chart,
        entry=None,
        requested_target_key=default_owner,
        profile=profile,
        feature=default_feature,
        roll_speed_ips=25.0,
    )
    assert default_row is not None
    default_index = default_row["recommend_index"]

    hard_rating = _rating_payload(range(1, 21))
    hard_rating["songs"]["hard-clone-source"] = {
        "id": 900,
        "level": 5,
        "song_name_cn": "Hard Clone",
        "score": 10.6,
        "combo": 500,
        "复合处理": 92,
        "平均密度": 88,
        "瞬间密度": 95,
        "叩き分け": 90,
        "BPM变化": 80,
    }
    _write_json(rating_path, hard_rating)

    hard_features_by_key = _load_rating_features(rating_path)
    hard_features_by_title = _load_rating_features_by_title_level(rating_path)
    hard_profile = _build_user_profile(records, best_map, charts, hard_features_by_key, rating_path)
    hard_feature = hard_features_by_key.get((21, 5)) or hard_features_by_title.get(
        (title_key, 5)
    )
    if hard_feature is None:
        hard_feature = {
            "const": hard_profile.difficulty_capacity,
            "stamina": hard_profile.dim_capacity.get("stamina", 50.0),
            "speed": hard_profile.dim_capacity.get("speed", 50.0),
            "rhythm": hard_profile.dim_capacity.get("rhythm", 50.0),
            "complex": hard_profile.dim_capacity.get("complex", 50.0),
        }
    hard_rows = {}
    for target_key in ("jinya", "fenya", "ziya", "goku"):
        row = _build_score_target_row(
            chart=chart,
            entry=None,
            target_key=target_key,
            profile=hard_profile,
            feature=hard_feature,
            roll_speed_ips=25.0,
        )
        if row is not None:
            hard_rows[target_key] = row
    hard_owner = _score_target_owner(hard_rows)
    assert hard_owner is not None
    hard_row = _build_owned_score_target_row(
        chart=chart,
        entry=None,
        requested_target_key=hard_owner,
        profile=hard_profile,
        feature=hard_feature,
        roll_speed_ips=25.0,
    )
    assert hard_row is not None
    hard_index = hard_row["recommend_index"]

    assert hard_index < default_index - 15


def test_unplayed_score_target_is_relaxed_but_stays_in_ziya_band(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path, count=24
    )
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    score_rows[20]["goku_score"] = 1006830
    score_rows[20]["tenjo_score"] = 1006830
    score_rows[20]["rating_scores"] = {
        "goku": 1006830,
        "ziya": 956490,
        "fenya": 906150,
        "jinya": 805470,
    }
    score_rows[20]["max_combo"] = 713
    score_rows[20]["initial_points"] = 1410
    score_rows[20]["ok_points"] = 700
    _write_json(scoreline_path, score_rows)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 9.1,
            "平均密度": 48.23092,
            "瞬间密度": 29.158651247401245,
            "叩き分け": 3.6858031984,
            "BPM变化": 9.1,
        }
    )
    _write_json(rating_path, rating_payload)

    records = userdata["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key = _load_rating_features(rating_path)
    features_by_title_level = _load_rating_features_by_title_level(rating_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    profile = _build_user_profile(
        records,
        best_map,
        charts,
        features_by_key,
        rating_path,
    )

    chart = next(c for c in charts if c.get("id") == 21 and c.get("level") == 4)
    title_key = _chart_title_key(chart) or title_keys_by_id.get(21, "")
    feature = features_by_key.get((21, 4)) or features_by_title_level[(title_key, 4)]

    row_by_target = {}
    for target_key in ("jinya", "fenya", "ziya", "goku"):
        row = _build_score_target_row(
            chart=chart,
            entry=None,
            target_key=target_key,
            profile=profile,
            feature=feature,
            roll_speed_ips=25.0,
        )
        if row is not None:
            row_by_target[target_key] = row

    owned_row = _build_owned_score_target_row(
        chart=chart,
        entry=None,
        requested_target_key="ziya",
        profile=profile,
        feature=feature,
        roll_speed_ips=25.0,
    )
    assert owned_row is not None

    assert _score_target_owner(row_by_target) == "ziya"
    if "goku" in row_by_target:
        assert (
            row_by_target["goku"]["recommend_likelihood"]
            < row_by_target["ziya"]["recommend_likelihood"]
        )

    profile_match = _profile_match(profile, feature)
    const_match = _const_match(profile, feature)
    tolerance = _score_target_tolerance(
        chart,
        int(row_by_target["ziya"]["target_text"]),
        25.0,
    )
    assert tolerance is not None
    legacy_likelihood = _legacy_unplayed_score_target_likelihood(
        chart=chart,
        target_score=int(row_by_target["ziya"]["target_text"]),
        tolerance=tolerance,
        profile=profile,
        feature=feature,
        profile_match=profile_match,
        const_match=const_match,
    )
    legacy_index = _legacy_recommend_index_from_likelihood(legacy_likelihood)
    assert owned_row["recommend_likelihood"] > legacy_likelihood
    assert owned_row["recommend_index"] > legacy_index


def test_played_score_baseline_only_penalizes_recent_weak_scores(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path, count=24
    )
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    score_rows[20]["goku_score"] = 1006830
    score_rows[20]["tenjo_score"] = 1006830
    score_rows[20]["rating_scores"] = {
        "goku": 1006830,
        "ziya": 956490,
        "fenya": 906150,
        "jinya": 805470,
    }
    score_rows[20]["max_combo"] = 713
    score_rows[20]["initial_points"] = 1410
    score_rows[20]["ok_points"] = 700
    _write_json(scoreline_path, score_rows)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 9.1,
            "平均密度": 48.23092,
            "瞬间密度": 29.158651247401245,
            "叩き分け": 3.6858031984,
            "BPM变化": 9.1,
        }
    )
    _write_json(rating_path, rating_payload)

    records = userdata["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key = _load_rating_features(rating_path)
    features_by_title_level = _load_rating_features_by_title_level(rating_path)
    title_keys_by_id = _load_song_title_keys(song_data_path)
    profile = _build_user_profile(
        records,
        best_map,
        charts,
        features_by_key,
        rating_path,
    )

    chart = next(c for c in charts if c.get("id") == 21 and c.get("level") == 4)
    title_key = _chart_title_key(chart) or title_keys_by_id.get(21, "")
    feature = features_by_key.get((21, 4)) or features_by_title_level[(title_key, 4)]

    def _rows_for(entry: dict | None) -> dict[str, dict]:
        row_by_target = {}
        for target_key in ("jinya", "fenya", "ziya", "goku"):
            row = _build_score_target_row(
                chart=chart,
                entry=entry,
                target_key=target_key,
                profile=profile,
                feature=feature,
                roll_speed_ips=25.0,
            )
            if row is not None:
                row_by_target[target_key] = row
        return row_by_target

    unplayed_rows = _rows_for(None)
    baseline_owner = _score_target_owner(unplayed_rows)
    assert baseline_owner == "ziya"

    weak_entry_template = {
        "song_no": 21,
        "level": 4,
        "high_score": 930000,
        "good_cnt": 580,
        "ok_cnt": 71,
        "ng_cnt": 30,
        "combo_cnt": 472,
        "clear_cnt": 1,
        "full_combo_cnt": 0,
        "dondaful_combo_cnt": 0,
    }
    old_weak_entry = {
        **weak_entry_template,
        "update_datetime": _days_ago_timestamp(400),
        "highscore_datetime": _days_ago_timestamp(400),
    }
    recent_weak_entry = {
        **weak_entry_template,
        "update_datetime": _days_ago_timestamp(7),
        "highscore_datetime": _days_ago_timestamp(7),
    }

    old_rows = _rows_for(old_weak_entry)
    recent_rows = _rows_for(recent_weak_entry)
    assert _score_target_owner(old_rows) == baseline_owner
    assert _score_target_owner(recent_rows) == baseline_owner

    baseline_likelihood = unplayed_rows["ziya"]["recommend_likelihood"]
    old_likelihood = old_rows["ziya"]["recommend_likelihood"]
    recent_likelihood = recent_rows["ziya"]["recommend_likelihood"]

    assert old_likelihood == pytest.approx(baseline_likelihood)
    assert recent_likelihood < old_likelihood
    assert recent_likelihood <= baseline_likelihood - 0.5


def test_recommend_index_is_the_direct_three_attempt_probability() -> None:
    likelihoods = [78.5, 77.8, 77.1, 76.4, 75.7]
    mapped_indexes = [_recommend_index_from_likelihood(value) for value in likelihoods]

    ordered_by_likelihood = sorted(
        range(len(likelihoods)),
        key=lambda idx: likelihoods[idx],
        reverse=True,
    )
    ordered_by_index = sorted(
        range(len(mapped_indexes)),
        key=lambda idx: mapped_indexes[idx],
        reverse=True,
    )

    assert ordered_by_index == ordered_by_likelihood
    assert max(mapped_indexes) - min(mapped_indexes) >= 0.8
    assert mapped_indexes == likelihoods


def test_shared_forecast_keeps_stable_and_pb_probability_anchors() -> None:
    forecast = build_chart_performance_forecast(
        song_id=1,
        level=4,
        stable_score=900_000,
        pb_score=940_000,
        score_ceiling=1_020_000,
        reliability=80.0,
        data_sufficiency="ok",
    )

    assert forecast.single_attempt_probability(900_000) == pytest.approx(0.5)
    assert forecast.reach_probability(900_000) == pytest.approx(0.875)
    assert forecast.reach_probability(940_000) == pytest.approx(0.5)
    assert forecast.reach_probability(941_000) < 0.5
    assert forecast.reach_probability(899_000) > 0.875


def test_not_enough_candidates_returns_message_without_enough_flag(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=8)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.is_enough is False
    assert f"{result.candidate_count}/10" in result.message


def test_target_band_ownership_returns_actual_candidate_count(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=12)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.candidate_count > 0
    assert len(result.rows) == min(20, result.candidate_count)
    assert result.is_enough is (len(result.rows) >= 10)


def test_filters_double_charts_and_cn_unavailable_difficulties(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    score_rows[0]["title"] = "【双打】Song 1"
    score_rows[0]["title_jp"] = "【双打】Song 1"
    score_rows[0]["title_cn"] = "【双打】曲目 1"
    score_rows[1]["level"] = 5
    score_rows[1]["difficulty_label"] = "里谱"
    score_rows[2]["id"] = 1003
    score_rows[2]["title_cn"] = "下架曲目"
    _write_json(scoreline_path, score_rows)

    song_rows = _song_data(range(1, 25))
    song_rows[1]["level_5"] = "-"
    song_rows[1]["max_combo"] = ["-", "-", "-", 500, 640]
    song_rows[2]["id"] = 1003
    song_rows[2]["shelf_status"] = 1
    _write_json(song_data_path, song_rows)

    result = compute_target_recommendations_for_user(
        "114514",
        "ziya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 1 not in ids
    assert 2 not in ids
    assert 1003 not in ids


def test_target_recommendation_supports_star_filter(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    song_rows = _song_data(range(1, 25))
    song_rows[0]["level_4"] = 9
    song_rows[1]["level_4"] = 9
    song_rows[2]["level_4"] = 10
    _write_json(song_data_path, song_rows)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
        star_filter="9星",
    )

    assert 0 < result.candidate_count <= 2
    assert result.is_enough is False
    assert "9星" in result.message
    assert {row["star"] for row in result.rows} == {"9"}


def test_score_target_filters_unplayed_candidate_when_speed_requirement_exceeds_limit(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    _write_json(scoreline_path, score_rows)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 20.0,
            "平均密度": 42.0,
            "瞬间密度": 95.0,
            "叩き分け": 45.0,
            "BPM变化": 0.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids


def test_score_target_keeps_candidate_within_speed_limit(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    _write_json(scoreline_path, score_rows)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 20.0,
            "平均密度": 42.0,
            "瞬间密度": 47.0,
            "叩き分け": 45.0,
            "BPM变化": 0.0,
        }
    )
    _write_json(rating_path, rating_payload)

    records = json.loads(
        (userdata_dir / "114514data.json").read_text(encoding="utf-8")
    )["songs"]
    profile = build_score_estimator_profile(
        records,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    chart = next(
        chart
        for chart in _load_candidate_charts(scoreline_path, song_data_path)
        if int(chart["id"]) == 21
    )
    forecast = forecast_chart_performance_batch(
        profile,
        [{"chart": chart}],
    )[(21, 4)]

    assert forecast.data_sufficiency == "ok"


def test_score_target_penalizes_high_hs_change_chart(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] not in {21, 22}]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    base_payload = {
        "score": 8.0,
        "复合处理": 30.0,
        "平均密度": 34.0,
        "瞬间密度": 36.0,
        "叩き分け": 38.0,
        "BPM变化": 7.0,
    }
    rating_payload["songs"]["song-21"].update({**base_payload, "HS变化": 0.0})
    rating_payload["songs"]["song-22"].update({**base_payload, "HS变化": 100.0})
    _write_json(rating_path, rating_payload)

    records = userdata["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key, _, const_table = _load_rating_support(rating_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    chart_by_id = {int(chart["id"]): chart for chart in charts}

    row_21 = _build_score_target_row(
        chart=chart_by_id[21],
        entry=None,
        target_key="fenya",
        profile=profile,
        feature=features_by_key[(21, 4)],
        roll_speed_ips=25.0,
        const_table=const_table,
    )
    row_22 = _build_score_target_row(
        chart=chart_by_id[22],
        entry=None,
        target_key="fenya",
        profile=profile,
        feature=features_by_key[(22, 4)],
        roll_speed_ips=25.0,
        const_table=const_table,
    )

    assert row_21 is not None
    assert row_22 is not None
    assert row_21["recommend_likelihood"] > row_22["recommend_likelihood"]
    assert row_21["recommend_index"] > row_22["recommend_index"]


def test_hs_change_penalty_uses_threshold_80_and_non_linear_curve() -> None:
    assert _hs_change_penalty({"hs_change": 79.0}, 14.0) == pytest.approx(0.0)
    assert _hs_change_penalty({"hs_change": 80.0}, 14.0) == pytest.approx(0.0)
    penalty_85 = _hs_change_penalty({"hs_change": 85.0}, 14.0)
    penalty_100 = _hs_change_penalty({"hs_change": 100.0}, 14.0)
    assert penalty_85 > 0.0
    assert penalty_100 > penalty_85
    assert penalty_100 == pytest.approx(14.0)


def test_score_target_hs_curve_penalizes_85_and_100_more_than_80(tmp_path: Path) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] not in {21, 22, 23}]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    base_payload = {
        "score": 8.0,
        "复合处理": 30.0,
        "平均密度": 34.0,
        "瞬间密度": 36.0,
        "叩き分け": 38.0,
        "BPM变化": 7.0,
    }
    rating_payload["songs"]["song-21"].update({**base_payload, "HS变化": 80.0})
    rating_payload["songs"]["song-22"].update({**base_payload, "HS变化": 85.0})
    rating_payload["songs"]["song-23"].update({**base_payload, "HS变化": 100.0})
    _write_json(rating_path, rating_payload)

    records = userdata["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key, _, const_table = _load_rating_support(rating_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    chart_by_id = {int(chart["id"]): chart for chart in charts}

    rows = {}
    for song_id in (21, 22, 23):
        rows[song_id] = _build_score_target_row(
            chart=chart_by_id[song_id],
            entry=None,
            target_key="fenya",
            profile=profile,
            feature=features_by_key[(song_id, 4)],
            roll_speed_ips=25.0,
            const_table=const_table,
        )

    assert rows[21] is not None
    assert rows[22] is not None
    assert rows[23] is not None
    assert rows[21]["recommend_likelihood"] > rows[22]["recommend_likelihood"]
    assert rows[22]["recommend_likelihood"] > rows[23]["recommend_likelihood"]


def test_score_target_filters_played_candidate_when_speed_requirement_exceeds_limit(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    score_rows = [_scoreline_row(song_id) for song_id in range(1, 25)]
    _write_json(scoreline_path, score_rows)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 20.0,
            "平均密度": 42.0,
            "瞬间密度": 95.0,
            "叩き分け": 45.0,
            "BPM变化": 0.0,
        }
    )
    _write_json(rating_path, rating_payload)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    target_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    target_entry["high_score"] = 850000
    target_entry["good_cnt"] = 420
    target_entry["ok_cnt"] = 60
    target_entry["ng_cnt"] = 20
    _write_json(userdata_path, userdata)

    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids


def test_full_combo_filters_unplayed_candidate_when_primary_dims_exceed_limit(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 92.0,
            "平均密度": 44.0,
            "瞬间密度": 97.0,
            "叩き分け": 46.0,
            "BPM变化": 8.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids


def test_full_combo_filters_played_candidate_when_primary_dims_exceed_limit(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    target_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    target_entry["good_cnt"] = 495
    target_entry["ok_cnt"] = 4
    target_entry["ng_cnt"] = 1
    target_entry["combo_cnt"] = 499
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 92.0,
            "平均密度": 44.0,
            "瞬间密度": 97.0,
            "叩き分け": 46.0,
            "BPM变化": 8.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids


def test_full_combo_prefers_easier_unplayed_chart_over_near_fc_risk_chart(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 22]
    risk_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    risk_entry["good_cnt"] = 495
    risk_entry["ok_cnt"] = 4
    risk_entry["ng_cnt"] = 1
    risk_entry["combo_cnt"] = 499
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 57.0,
            "平均密度": 46.0,
            "瞬间密度": 58.0,
            "叩き分け": 47.0,
            "BPM变化": 9.0,
        }
    )
    rating_payload["songs"]["song-22"].update(
        {
            "score": 8.0,
            "复合处理": 28.0,
            "平均密度": 34.0,
            "瞬间密度": 35.0,
            "叩き分け": 36.0,
            "BPM变化": 7.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    order = {row["song_id"]: index for index, row in enumerate(result.rows)}
    row_by_id = {row["song_id"]: row for row in result.rows}
    assert 21 in order
    assert 22 in order
    assert order[22] < order[21]
    assert row_by_id[22]["recommend_index"] > row_by_id[21]["recommend_index"]
    assert row_by_id[22]["recommend_index"] < 100.0


def test_full_combo_keeps_unplayed_candidate_within_primary_limits(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.0,
            "复合处理": 30.0,
            "平均密度": 34.0,
            "瞬间密度": 36.0,
            "叩き分け": 38.0,
            "BPM变化": 7.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    row_by_id = {row["song_id"]: row for row in result.rows}
    assert 21 in row_by_id
    assert row_by_id[21]["recommend_index"] < 100.0


def test_full_combo_penalizes_high_hs_change_chart(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] not in {21, 22}]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    base_payload = {
        "score": 8.0,
        "复合处理": 30.0,
        "平均密度": 34.0,
        "瞬间密度": 36.0,
        "叩き分け": 38.0,
        "BPM变化": 7.0,
    }
    rating_payload["songs"]["song-21"].update({**base_payload, "HS变化": 0.0})
    rating_payload["songs"]["song-22"].update({**base_payload, "HS变化": 100.0})
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=40,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    row_by_id = {row["song_id"]: row for row in result.rows}
    assert 21 in row_by_id
    assert 22 in row_by_id
    assert row_by_id[21]["recommend_index"] > row_by_id[22]["recommend_index"]


def test_full_combo_hs_curve_penalizes_85_and_100_more_than_80(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] not in {21, 22, 23}]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    base_payload = {
        "score": 8.0,
        "复合处理": 30.0,
        "平均密度": 34.0,
        "瞬间密度": 36.0,
        "叩き分け": 38.0,
        "BPM变化": 7.0,
    }
    rating_payload["songs"]["song-21"].update({**base_payload, "HS变化": 80.0})
    rating_payload["songs"]["song-22"].update({**base_payload, "HS变化": 85.0})
    rating_payload["songs"]["song-23"].update({**base_payload, "HS变化": 100.0})
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=40,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    row_by_id = {row["song_id"]: row for row in result.rows}
    assert row_by_id[21]["recommend_index"] > row_by_id[22]["recommend_index"]
    assert row_by_id[22]["recommend_index"] > row_by_id[23]["recommend_index"]


def test_full_combo_filters_zero_index_candidates_from_results(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    target_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    target_entry["good_cnt"] = 450
    target_entry["ok_cnt"] = 20
    target_entry["ng_cnt"] = 30
    target_entry["combo_cnt"] = 100
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 58.0,
            "平均密度": 50.0,
            "瞬间密度": 62.0,
            "叩き分け": 44.0,
            "BPM变化": 10.0,
            "HS变化": 100.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        FULL_COMBO_TARGET,
        limit=60,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids
    assert all(row["recommend_index"] > 0.0 for row in result.rows)


def test_dondaful_filters_candidates_when_rhythm_or_accuracy_exceeds_limit(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    played_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    played_entry["good_cnt"] = 498
    played_entry["ok_cnt"] = 1
    played_entry["ng_cnt"] = 1
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 22]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    for key in ("song-21", "song-22"):
        rating_payload["songs"][key].update(
            {
                "score": 8.3,
                "复合处理": 36.0,
                "平均密度": 40.0,
                "瞬间密度": 43.0,
                "叩き分け": 95.0,
                "BPM变化": 8.0,
            }
        )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids
    assert 22 not in ids


def test_dondaful_prefers_better_fit_unplayed_chart_over_near_ap_risk_chart(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 22]
    risk_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    risk_entry["good_cnt"] = 498
    risk_entry["ok_cnt"] = 2
    risk_entry["ng_cnt"] = 0
    risk_entry["combo_cnt"] = 500
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 40.0,
            "平均密度": 44.0,
            "瞬间密度": 46.0,
            "叩き分け": 54.0,
            "BPM变化": 7.0,
        }
    )
    rating_payload["songs"]["song-22"].update(
        {
            "score": 8.0,
            "复合处理": 35.0,
            "平均密度": 39.0,
            "瞬间密度": 41.0,
            "叩き分け": 38.0,
            "BPM变化": 7.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    order = {row["song_id"]: index for index, row in enumerate(result.rows)}
    row_by_id = {row["song_id"]: row for row in result.rows}
    assert 21 in order
    assert 22 in order
    assert order[22] < order[21]
    assert row_by_id[22]["recommend_index"] > row_by_id[21]["recommend_index"]
    assert row_by_id[22]["recommend_index"] < 100.0


def test_dondaful_low_risk_progress_does_not_saturate_to_full_score(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    easy_one = next(record for record in userdata["songs"] if record["song_no"] == 21)
    easy_two = next(record for record in userdata["songs"] if record["song_no"] == 22)
    easy_one["good_cnt"] = 499
    easy_one["ok_cnt"] = 1
    easy_one["ng_cnt"] = 0
    easy_one["combo_cnt"] = 500
    easy_two["good_cnt"] = 498
    easy_two["ok_cnt"] = 2
    easy_two["ng_cnt"] = 0
    easy_two["combo_cnt"] = 500
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    for key in ("song-21", "song-22"):
        rating_payload["songs"][key].update(
            {
                "score": 8.0,
                "复合处理": 28.0,
                "平均密度": 34.0,
                "瞬间密度": 36.0,
                "叩き分け": 38.0,
                "BPM变化": 6.0,
            }
        )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        limit=60,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    row_by_id = {row["song_id"]: row for row in result.rows}
    assert 21 in row_by_id
    assert 22 in row_by_id
    assert row_by_id[21]["recommend_index"] < 100.0
    assert row_by_id[22]["recommend_index"] < 100.0
    assert row_by_id[21]["recommend_index"] > row_by_id[22]["recommend_index"]


def test_dondaful_keeps_candidate_when_only_non_primary_dims_are_high(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] != 21]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.0,
            "复合处理": 88.0,
            "平均密度": 36.0,
            "瞬间密度": 98.0,
            "叩き分け": 38.0,
            "BPM变化": 6.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        limit=30,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 in ids


def test_dondaful_hs_curve_penalizes_85_and_100_more_than_80(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)
    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    _write_json(userdata_path, userdata)
    rating_payload = _rating_payload(range(1, 25))
    base_payload = {
        "score": 8.0,
        "复合处理": 30.0,
        "平均密度": 34.0,
        "瞬间密度": 36.0,
        "叩き分け": 38.0,
        "BPM变化": 7.0,
    }
    rating_payload["songs"]["song-21"].update({**base_payload, "HS变化": 80.0})
    rating_payload["songs"]["song-22"].update({**base_payload, "HS变化": 85.0})
    rating_payload["songs"]["song-23"].update({**base_payload, "HS变化": 100.0})
    _write_json(rating_path, rating_payload)

    records = json.loads(userdata_path.read_text(encoding="utf-8"))["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key, _, const_table = _load_rating_support(rating_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    chart_by_id = {int(chart["id"]): chart for chart in charts}

    rows = {}
    for song_id in (21, 22, 23):
        rows[song_id] = _build_dondaful_row(
            chart=chart_by_id[song_id],
            entry=best_map.get((song_id, 4)),
            profile=profile,
            feature=features_by_key[(song_id, 4)],
            const_table=const_table,
        )

    assert rows[21] is not None
    assert rows[22] is not None
    assert rows[23] is not None
    assert rows[21]["recommend_index"] > rows[22]["recommend_index"]
    assert rows[22]["recommend_index"] > rows[23]["recommend_index"]


def test_dondaful_filters_zero_index_candidates_from_results(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    target_entry = next(record for record in userdata["songs"] if record["song_no"] == 21)
    target_entry["good_cnt"] = 420
    target_entry["ok_cnt"] = 40
    target_entry["ng_cnt"] = 40
    target_entry["combo_cnt"] = 200
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 36.0,
            "平均密度": 44.0,
            "瞬间密度": 45.0,
            "叩き分け": 72.0,
            "BPM变化": 10.0,
            "HS变化": 100.0,
        }
    )
    _write_json(rating_path, rating_payload)

    result = compute_target_recommendations_for_user(
        "114514",
        DONDAFUL_TARGET,
        limit=60,
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    ids = {row["song_id"] for row in result.rows}
    assert 21 not in ids
    assert all(row["recommend_index"] > 0.0 for row in result.rows)


def test_score_target_hard_capacity_gap_filters_edge_chart(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path, count=24)

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [record for record in userdata["songs"] if record["song_no"] not in {21, 22}]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.3,
            "复合处理": 28.0,
            "平均密度": 35.0,
            "瞬间密度": 34.0,
            "叩き分け": 36.0,
            "BPM变化": 4.0,
            "HS变化": 0.0,
        }
    )
    rating_payload["songs"]["song-22"].update(
        {
            "score": 8.3,
            "复合处理": 70.0,
            "平均密度": 60.0,
            "瞬间密度": 74.0,
            "叩き分け": 65.0,
            "BPM变化": 20.0,
            "HS变化": 0.0,
        }
    )
    _write_json(rating_path, rating_payload)

    records = json.loads((userdata_dir / "114514data.json").read_text(encoding="utf-8"))["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key, _, const_table = _load_rating_support(rating_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    chart_by_id = {int(chart["id"]): chart for chart in charts}

    rows = {}
    for song_id in (21, 22):
        rows[song_id] = _build_score_target_row(
            chart=chart_by_id[song_id],
            entry=None,
            target_key="fenya",
            profile=profile,
            feature=features_by_key[(song_id, 4)],
            roll_speed_ips=25.0,
            const_table=const_table,
        )

    assert rows[21] is not None
    assert rows[22] is None


def test_score_target_pair_penalty_only_triggers_on_double_edge() -> None:
    profile = UserProfile(
        played_count=24,
        score_ratio_median=0.9,
        accuracy_median=0.92,
        combo_median=0.9,
        rating_capacity=10.0,
        difficulty_capacity=10.0,
        dim_capacity={
            "big_song": 10.0,
            "stamina": 10.0,
            "speed": 10.0,
            "accuracy_power": 10.0,
            "rhythm": 10.0,
            "complex": 10.0,
        },
        user_dim_capacity={
            "big_song": 10.0,
            "stamina": 10.0,
            "speed": 10.0,
            "accuracy_power": 10.0,
            "rhythm": 10.0,
            "complex": 10.0,
        },
    )
    single_edge = {
        "big_song": 0.0,
        "stamina": 0.0,
        "speed": 10.0,
        "accuracy_power": 0.0,
        "rhythm": 0.0,
        "complex": 9.6,
    }
    double_edge = {
        "big_song": 0.0,
        "stamina": 0.0,
        "speed": 10.0,
        "accuracy_power": 0.0,
        "rhythm": 0.0,
        "complex": 10.0,
    }
    dominant_edge = {
        "big_song": 0.0,
        "stamina": 0.0,
        "speed": 10.5,
        "accuracy_power": 0.0,
        "rhythm": 0.0,
        "complex": 9.8,
    }

    assert _score_target_pair_pressure_penalty(profile, single_edge) == 0.0
    assert _score_target_pair_pressure_penalty(profile, double_edge) > 0.0
    assert _score_target_pair_pressure_penalty(profile, dominant_edge) == 0.0


def test_single_dim_overflow_slack_only_relaxes_single_pressure_target() -> None:
    profile = UserProfile(
        played_count=24,
        score_ratio_median=0.9,
        accuracy_median=0.92,
        combo_median=0.9,
        rating_capacity=10.0,
        difficulty_capacity=10.0,
        dim_capacity={
            "big_song": 10.0,
            "stamina": 10.0,
            "speed": 10.0,
            "accuracy_power": 10.0,
            "rhythm": 10.0,
            "complex": 10.0,
        },
        user_dim_capacity={
            "big_song": 10.0,
            "stamina": 10.0,
            "speed": 10.0,
            "accuracy_power": 10.0,
            "rhythm": 10.0,
            "complex": 10.0,
        },
    )
    single_dim = {
        "big_song": 0.0,
        "stamina": 10.78,
        "speed": 8.4,
        "accuracy_power": 0.0,
        "rhythm": 0.0,
        "complex": 8.8,
    }
    multi_dim = {
        "big_song": 9.7,
        "stamina": 10.78,
        "speed": 8.4,
        "accuracy_power": 0.0,
        "rhythm": 0.0,
        "complex": 9.8,
    }

    assert _exceeds_target_score_dim_limits(profile, single_dim) is False
    assert _exceeds_target_score_dim_limits(profile, multi_dim) is True


def test_score_target_pair_penalty_pushes_speed_complex_edge_chart_lower(
    tmp_path: Path,
) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(
        tmp_path, count=24
    )

    userdata_path = userdata_dir / "114514data.json"
    userdata = json.loads(userdata_path.read_text(encoding="utf-8"))
    _boost_userdata_to_high_capacity(userdata)
    userdata["songs"] = [
        record for record in userdata["songs"] if record["song_no"] not in {21, 22, 23}
    ]
    _write_json(userdata_path, userdata)

    rating_payload = _rating_payload(range(1, 25))
    rating_payload["songs"]["song-21"].update(
        {
            "score": 8.4,
            "复合处理": 28.0,
            "平均密度": 34.0,
            "瞬间密度": 35.0,
            "叩き分け": 40.0,
            "BPM变化": 6.0,
            "HS变化": 0.0,
        }
    )
    rating_payload["songs"]["song-22"].update(
        {
            "score": 8.4,
            "复合处理": 78.0,
            "平均密度": 36.0,
            "瞬间密度": 180.0,
            "叩き分け": 41.0,
            "BPM变化": 6.0,
            "HS变化": 0.0,
        }
    )
    rating_payload["songs"]["song-23"].update(
        {
            "score": 8.4,
            "复合处理": 28.0,
            "平均密度": 36.0,
            "瞬间密度": 180.0,
            "叩き分け": 41.0,
            "BPM变化": 6.0,
            "HS变化": 0.0,
        }
    )
    _write_json(rating_path, rating_payload)

    records = json.loads(userdata_path.read_text(encoding="utf-8"))["songs"]
    best_map = _build_best_entry_map(records)
    charts = _load_candidate_charts(scoreline_path, song_data_path)
    features_by_key, _, const_table = _load_rating_support(rating_path)
    profile = _build_user_profile(records, best_map, charts, features_by_key, rating_path)
    chart_by_id = {int(chart["id"]): chart for chart in charts}

    capacities = dict(profile.user_dim_capacity)
    required_by_song = {
        21: {
            "big_song": 0.0,
            "stamina": 0.0,
            "speed": capacities["speed"] * 1.03,
            "accuracy_power": 0.0,
            "rhythm": 0.0,
            "complex": capacities["complex"] * 0.94,
        },
        22: {
            "big_song": 0.0,
            "stamina": 0.0,
            "speed": capacities["speed"] * 1.03,
            "accuracy_power": 0.0,
            "rhythm": 0.0,
            "complex": capacities["complex"] * 1.01,
        },
        23: {
            "big_song": 0.0,
            "stamina": 0.0,
            "speed": capacities["speed"] * 1.05,
            "accuracy_power": 0.0,
            "rhythm": 0.0,
            "complex": capacities["complex"] * 0.98,
        },
    }
    base_likelihoods = {
        21: 80.0,
        22: 76.0,
        23: 74.5,
    }
    adjusted_likelihoods = {}
    adjusted_indexes = {}
    pair_penalties = {}
    for song_id, required_dims in required_by_song.items():
        pair_penalties[song_id] = _score_target_pair_pressure_penalty(
            profile, required_dims
        )
        adjusted_likelihoods[song_id] = base_likelihoods[song_id] - pair_penalties[song_id]
        adjusted_indexes[song_id] = _recommend_index_from_likelihood(
            adjusted_likelihoods[song_id]
        )

    assert pair_penalties[21] == 0.0
    assert pair_penalties[23] == 0.0
    assert pair_penalties[22] > 0.0
    assert adjusted_likelihoods[23] > adjusted_likelihoods[22]
    assert adjusted_indexes[23] > adjusted_indexes[22]
    assert adjusted_indexes[21] >= adjusted_indexes[23]
    assert (
        adjusted_likelihoods[23] - adjusted_likelihoods[22]
        > base_likelihoods[23] - base_likelihoods[22]
    )




def test_target_recommendation_renderer_returns_png_bytes(tmp_path: Path, monkeypatch) -> None:
    userdata_dir, scoreline_path, rating_path, song_data_path = _fixture_paths(tmp_path)
    result = compute_target_recommendations_for_user(
        "114514",
        "fenya",
        userdata_dir=userdata_dir,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    drawn_text: list[str] = []
    arrow_boxes: list[tuple[int, int, int, int]] = []
    original_draw_text = utils_module._draw_text_with_font_drop
    original_draw_arrow = utils_module._draw_target_recommend_arrow

    def _capture_draw_text(draw, pos, text, **kwargs):
        drawn_text.append(str(text))
        return original_draw_text(draw, pos, text, **kwargs)

    def _capture_draw_arrow(draw, box):
        arrow_boxes.append(box)
        return original_draw_arrow(draw, box)

    monkeypatch.setattr(utils_module, "_draw_text_with_font_drop", _capture_draw_text)
    monkeypatch.setattr(utils_module, "_draw_target_recommend_arrow", _capture_draw_arrow)

    png = render_target_recommendation_image_bytes(
        user_id=114514,
        userdata=result.userdata,
        target_display=result.target_display,
        rows=result.rows,
    )

    assert png.startswith(b"\x89PNG")
    assert len(arrow_boxes) == len(result.rows)
    assert not any(text.endswith("%") for text in drawn_text)
    assert "ID" in drawn_text
    assert "星级" in drawn_text
    assert "目标分数" in drawn_text
    assert "差距" in drawn_text
    assert "推荐指数" in drawn_text
    assert f"{result.rows[0]['recommend_index']:.1f}" in drawn_text
    assert any(text.startswith("粉雅目标推荐") for text in drawn_text)
    assert "当前进度" not in drawn_text
    assert "达成进度" not in drawn_text
    assert "成就" not in drawn_text
