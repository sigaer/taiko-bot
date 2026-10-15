from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from taiko_bot.offline.score_estimator import (
    build_score_estimator_profile,
    estimate_chart_score_from_records,
)
from taiko_bot.offline.score_prediction_support import (
    resolve_chart_feature,
    resolve_scoreline_chart,
)
from taiko_bot.offline.target_recommend import (
    _chart_title_key,
    _score_target_pair_pressure_penalty,
    _score_target_tolerance,
    _target_score_required_dims,
)
from taiko_bot.offline.score_line import load_scoreline_data


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    profile = build_score_estimator_profile(
        records,
        exclude_song_id=song_id,
        exclude_level=level,
    )
    title_key = profile.title_keys_by_id.get(song_id, "")
    chart = resolve_scoreline_chart(
        song_id,
        level,
        title_key,
        scoreline_path=profile.scoreline_path,
        song_data_path=profile.song_data_path,
    )
    assert chart is not None

    feature = resolve_chart_feature(
        song_id=song_id,
        level=level,
        title_key=title_key or _chart_title_key(chart),
        features_by_key=profile.features_by_key,
        features_by_title_level=profile.features_by_title_level,
    )
    assert feature is not None

    tolerance = _score_target_tolerance(chart, target_score, roll_speed_ips)
    assert tolerance is not None
    assert bool(tolerance.get("reachable"))

    required_dims = _target_score_required_dims(
        chart=chart,
        feature=feature,
        target_score=target_score,
        tolerance=tolerance,
        const_table=profile.const_table,
    )
    return _score_target_pair_pressure_penalty(profile.stable_profile, required_dims)


def _days_ago(days: int) -> str:
    return (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


def _scoreline_row(
    song_id: int,
    *,
    title: str | None = None,
    level: int = 4,
    goku_score: int = 1_000_000,
    max_combo: int = 500,
    initial_points: int = 2_000,
    ok_points: int = 1_000,
    roll_total_seconds: float = 0.0,
    balloon_hits: int = 0,
) -> dict:
    title = title or f"Song {song_id}"
    return {
        "id": song_id,
        "title": title,
        "title_jp": title,
        "title_cn": title,
        "level": level,
        "difficulty_label": "里谱" if level == 5 else "表谱",
        "tenjo_score": max(0, goku_score - 10000),
        "goku_score": goku_score,
        "rating_scores": {
            "goku": goku_score,
            "ziya": int(goku_score * 0.95),
            "fenya": int(goku_score * 0.90),
            "jinya": int(goku_score * 0.80),
        },
        "roll_required": 0,
        "roll_speed_ips": 0,
        "max_combo": max_combo,
        "initial_points": initial_points,
        "ok_points": ok_points,
        "roll_total_seconds": roll_total_seconds,
        "balloon_hits": balloon_hits,
        "balloons": [balloon_hits] if balloon_hits > 0 else [],
    }


def _score_from_counts(chart: dict, good: int, ok: int, pound: int) -> int:
    return (
        int(good) * int(chart["initial_points"])
        + int(ok) * int(chart["ok_points"])
        + int(pound) * 100
    )


def _song_data_row(song_id: int, *, title: str | None = None, level: int = 4, max_combo: int = 500) -> dict:
    title = title or f"Song {song_id}"
    row = {
        "id": song_id,
        "song_name": title,
        "song_name_jp": title,
        "song_name_cn": title,
        "shelf_status": 0,
        "max_combo": ["-", "-", "-", "-", "-"],
    }
    row[f"level_{level}"] = 8 if level == 4 else 10
    row["max_combo"][level - 1] = max_combo
    return row


def _rating_row(
    song_id: int,
    *,
    title: str | None = None,
    level: int = 4,
    const: float = 8.0,
    stamina: float | None = None,
    speed: float | None = None,
    rhythm: float | None = None,
    complex_value: float | None = None,
    hs_change: float | None = None,
) -> dict:
    title = title or f"Song {song_id}"
    return {
        "id": song_id,
        "level": level,
        "song_name_cn": title,
        "song_name": title,
        "曲名": title,
        "score": const,
        "combo": 500,
        "复合处理": (
            float(complex_value)
            if complex_value is not None
            else 40.0 + (song_id % 5)
        ),
        "平均密度": float(stamina) if stamina is not None else 48.0 + (song_id % 7),
        "瞬间密度": float(speed) if speed is not None else 52.0 + (song_id % 6),
        "叩き分け": float(rhythm) if rhythm is not None else 45.0 + (song_id % 4),
        "BPM变化": 8.0 + (song_id % 3),
        "HS变化": float(hs_change) if hs_change is not None else 5.0 + (song_id % 5),
    }


def _record_for_chart(
    chart: dict,
    *,
    good: int,
    ok: int,
    pound: int,
    age_days: int,
) -> dict:
    note_count = int(chart["max_combo"])
    hit = min(note_count, good + ok)
    return {
        "song_no": int(chart["id"]),
        "level": int(chart["level"]),
        "high_score": _score_from_counts(chart, good, ok, pound),
        "good_cnt": good,
        "ok_cnt": ok,
        "ng_cnt": max(0, note_count - hit),
        "combo_cnt": hit,
        "pound_cnt": pound,
        "clear_cnt": 1,
        "full_combo_cnt": 1 if hit == note_count else 0,
        "dondaful_combo_cnt": 1 if good == note_count and ok == 0 else 0,
        "update_datetime": _days_ago(age_days),
    }


def _build_fixture_paths(tmp_path: Path, charts: list[dict], rating_rows: list[dict], song_rows: list[dict]) -> tuple[Path, Path, Path]:
    scoreline_path = tmp_path / "taiko_goku_onis.json"
    rating_path = tmp_path / "rating.json"
    song_data_path = tmp_path / "song_data.json"
    _write_json(scoreline_path, charts)
    _write_json(
        rating_path,
        {
            "songs": {f"song-{row['id']}-{row['level']}": row for row in rating_rows},
            "const_table": {
                "const_to_score": {
                    "7.0": 5.5,
                    "8.0": 6.5,
                    "8.5": 7.2,
                    "9.0": 7.9,
                    "10.0": 9.0,
                    "11.0": 10.1,
                }
            },
        },
    )
    _write_json(song_data_path, song_rows)
    return scoreline_path, rating_path, song_data_path


def test_real_sample_scores_still_match_chart_formula() -> None:
    charts = {
        (int(row["id"]), int(row["level"])): row
        for row in load_scoreline_data("/home/sigaer/taiko/songs/taiko_goku_onis.json")
        if row.get("id") is not None
    }
    payload = json.loads(
        Path("/home/sigaer/taiko/userdata/20041443/data_20260519_233251_636016.json").read_text(
            encoding="utf-8"
        )
    )

    checked = 0
    for record in payload.get("songs", []):
        key = (int(record["song_no"]), int(record["level"]))
        if key[1] not in (4, 5) or key not in charts:
            continue
        chart = charts[key]
        assert record["high_score"] == _score_from_counts(
            chart,
            int(record.get("good_cnt", 0)),
            int(record.get("ok_cnt", 0)),
            int(record.get("pound_cnt", 0)),
        )
        checked += 1
    assert checked >= 20


def test_strong_user_nine_star_estimate_does_not_collapse_to_low_band() -> None:
    payload = json.loads(
        Path("/home/sigaer/taiko/userdata/99408699data.json").read_text(
            encoding="utf-8"
        )
    )

    result = estimate_chart_score_from_records(
        payload.get("songs", []),
        288,
        4,
    )

    assert result.data_sufficiency == "ok"
    assert result.current_score is not None
    assert result.stable is not None
    assert result.pb is not None
    assert result.stable.score >= 820_000
    assert result.pb.score >= result.stable.score

    simple_ten_result = estimate_chart_score_from_records(
        payload.get("songs", []),
        283,
        4,
    )

    assert simple_ten_result.data_sufficiency == "ok"
    assert simple_ten_result.stable is not None
    assert simple_ten_result.pb is not None
    assert simple_ten_result.stable.score == 810_000
    assert simple_ten_result.pb.score >= simple_ten_result.stable.score


def test_user_without_matching_raw_capacity_caps_or_rejects_super_hard_charts() -> None:
    payload = json.loads(
        Path("/home/sigaer/taiko/userdata/99408699data.json").read_text(
            encoding="utf-8"
        )
    )

    for song_id in (463, 1350):
        result = estimate_chart_score_from_records(
            payload.get("songs", []),
            song_id,
            4,
        )

        assert result.data_sufficiency == "ok"
        assert result.stable is not None
        assert result.pb is not None
        assert 500_000 <= result.stable.score <= 680_000
        assert result.stable.score <= result.pb.score <= 700_000

    hardest = estimate_chart_score_from_records(
        payload.get("songs", []),
        1172,
        4,
    )
    assert hardest.data_sufficiency == "hard_mismatch"
    assert hardest.stable is None
    assert hardest.pb is None


def test_estimator_allows_above_goku_when_35ips_ceiling_is_higher(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(
            song_id,
            goku_score=505_000,
            max_combo=500,
            initial_points=1_000,
            ok_points=500,
            roll_total_seconds=10.0,
        )
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=8.0))
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=500, ok=0, pound=350, age_days=10))

    target_chart = _scoreline_row(
        99,
        goku_score=505_000,
        max_combo=500,
        initial_points=1_000,
        ok_points=500,
        roll_total_seconds=10.0,
    )
    charts.append(target_chart)
    rating_rows.append(_rating_row(99, const=8.0))
    song_rows.append(_song_data_row(99))
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    result = estimate_chart_score_from_records(
        records,
        99,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.data_sufficiency == "ok"
    assert result.stable is not None
    assert result.pb is not None
    assert result.score_ceiling_35ips > result.goku_score
    assert result.above_goku is True
    assert result.stable.score > result.goku_score
    assert result.pb.score <= result.score_ceiling_35ips


def test_estimator_clamps_roll_speed_to_35(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(
            song_id,
            goku_score=505_000,
            max_combo=500,
            initial_points=1_000,
            ok_points=500,
            roll_total_seconds=10.0,
        )
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=8.1))
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=500, ok=0, pound=900, age_days=5))

    target_chart = _scoreline_row(
        77,
        goku_score=505_000,
        max_combo=500,
        initial_points=1_000,
        ok_points=500,
        roll_total_seconds=10.0,
    )
    charts.append(target_chart)
    rating_rows.append(_rating_row(77, const=8.1))
    song_rows.append(_song_data_row(77))
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    result = estimate_chart_score_from_records(
        records,
        77,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.stable is not None
    assert result.pb is not None
    assert result.stable.roll_speed_ips <= 35.0
    assert result.pb.roll_speed_ips <= 35.0
    assert result.pb.pred_pound <= compute_roll_hits_limit(target_chart)


def compute_roll_hits_limit(chart: dict) -> int:
    return int(chart["balloon_hits"]) + int(round(float(chart["roll_total_seconds"]) * 35.0))


def test_estimator_uses_profile_mainline_for_unplayed_chart(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 13):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=8.0 + song_id * 0.01))
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=470, ok=20, pound=50, age_days=20))
    for song_id in range(13, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=10.5 + song_id * 0.01))
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=380, ok=80, pound=0, age_days=40))

    target_chart = _scoreline_row(30)
    charts.append(target_chart)
    rating_rows.append(_rating_row(30, const=8.05))
    song_rows.append(_song_data_row(30))
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    result = estimate_chart_score_from_records(
        records,
        30,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.data_sufficiency == "ok"
    assert result.stable is not None
    assert result.pb is not None
    assert result.stable.neighbor_count >= 6
    assert result.stable.score >= 900_000
    assert result.pb.score >= result.stable.score


def test_played_chart_current_score_does_not_change_estimated_scores(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    base_records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=8.0))
        song_rows.append(_song_data_row(song_id))
        base_records.append(_record_for_chart(chart, good=470, ok=20, pound=50, age_days=20))

    target_chart = _scoreline_row(30)
    charts.append(target_chart)
    rating_rows.append(_rating_row(30, const=8.0))
    song_rows.append(_song_data_row(30))
    low_current_record = _record_for_chart(
        target_chart,
        good=350,
        ok=80,
        pound=20,
        age_days=15,
    )
    high_current_record = _record_for_chart(
        target_chart,
        good=500,
        ok=0,
        pound=80,
        age_days=15,
    )
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    low_result = estimate_chart_score_from_records(
        [*base_records, low_current_record],
        30,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    high_result = estimate_chart_score_from_records(
        [*base_records, high_current_record],
        30,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert low_result.current_score == low_current_record["high_score"]
    assert high_result.current_score == high_current_record["high_score"]
    assert low_result.stable is not None
    assert low_result.pb is not None
    assert high_result.stable is not None
    assert high_result.pb is not None
    assert low_result.stable.score == high_result.stable.score
    assert low_result.pb.score == high_result.pb.score


def test_duplicate_title_feature_fallback_still_produces_estimate(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(_rating_row(song_id, const=8.0))
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=460, ok=30, pound=30, age_days=20))

    charts.append(_scoreline_row(100, title="Hater"))
    charts.append(_scoreline_row(200, title="Hater"))
    rating_rows.append(_rating_row(200, title="Hater", const=8.2))
    song_rows.append(_song_data_row(100, title="Hater"))
    song_rows.append(_song_data_row(200, title="Hater"))
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    result = estimate_chart_score_from_records(
        records,
        100,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.data_sufficiency == "ok"
    assert result.stable is not None
    assert result.pb is not None


def test_estimator_returns_hard_mismatch_for_far_beyond_capacity_chart(tmp_path: Path) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(
            _rating_row(
                song_id,
                const=7.0,
                stamina=20.0,
                speed=20.0,
                rhythm=20.0,
                complex_value=20.0,
                hs_change=5.0,
            )
        )
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=420, ok=60, pound=0, age_days=20))

    target_chart = _scoreline_row(99)
    charts.append(target_chart)
    rating_rows.append(
        _rating_row(
            99,
            const=11.0,
            stamina=95.0,
            speed=95.0,
            rhythm=95.0,
            complex_value=95.0,
            hs_change=20.0,
        )
    )
    song_rows.append(_song_data_row(99))
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    result = estimate_chart_score_from_records(
        records,
        99,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert result.data_sufficiency == "hard_mismatch"
    assert result.stable is None
    assert result.pb is None


def test_estimator_rejects_close_const_chart_with_raw_dims_far_beyond_capacity(
    tmp_path: Path,
) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(
            _rating_row(
                song_id,
                const=7.0,
                stamina=20.0,
                speed=20.0,
                rhythm=20.0,
                complex_value=20.0,
                hs_change=5.0,
            )
        )
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=420, ok=60, pound=0, age_days=20))

    easy_target = _scoreline_row(98)
    hard_target = _scoreline_row(99)
    charts.extend([easy_target, hard_target])
    rating_rows.append(
        _rating_row(
            98,
            const=7.4,
            stamina=20.0,
            speed=20.0,
            rhythm=20.0,
            complex_value=20.0,
            hs_change=5.0,
        )
    )
    rating_rows.append(
        _rating_row(
            99,
            const=7.4,
            stamina=95.0,
            speed=95.0,
            rhythm=95.0,
            complex_value=95.0,
            hs_change=20.0,
        )
    )
    song_rows.extend([_song_data_row(98), _song_data_row(99)])
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    easy_result = estimate_chart_score_from_records(
        records,
        98,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    hard_result = estimate_chart_score_from_records(
        records,
        99,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert easy_result.data_sufficiency == "ok"
    assert hard_result.data_sufficiency == "hard_mismatch"
    assert easy_result.stable is not None
    assert easy_result.pb is not None
    assert hard_result.stable is None
    assert hard_result.pb is None


def test_estimator_penalizes_double_edge_speed_complex_chart(
    tmp_path: Path,
) -> None:
    charts = []
    rating_rows = []
    song_rows = []
    records = []
    for song_id in range(1, 25):
        chart = _scoreline_row(song_id)
        charts.append(chart)
        rating_rows.append(
            _rating_row(
                song_id,
                const=7.0,
                stamina=20.0,
                speed=20.0,
                rhythm=20.0,
                complex_value=20.0,
                hs_change=5.0,
            )
        )
        song_rows.append(_song_data_row(song_id))
        records.append(_record_for_chart(chart, good=420, ok=60, pound=0, age_days=20))

    single_edge_target = _scoreline_row(98)
    double_edge_target = _scoreline_row(99)
    charts.extend([single_edge_target, double_edge_target])
    rating_rows.append(
        _rating_row(
            98,
            const=7.4,
            stamina=20.0,
            speed=30.0,
            rhythm=20.0,
            complex_value=20.0,
            hs_change=5.0,
        )
    )
    rating_rows.append(
        _rating_row(
            99,
            const=7.4,
            stamina=20.0,
            speed=30.0,
            rhythm=20.0,
            complex_value=30.0,
            hs_change=5.0,
        )
    )
    song_rows.extend([_song_data_row(98), _song_data_row(99)])
    scoreline_path, rating_path, song_data_path = _build_fixture_paths(
        tmp_path, charts, rating_rows, song_rows
    )

    single_edge_result = estimate_chart_score_from_records(
        records,
        98,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )
    double_edge_result = estimate_chart_score_from_records(
        records,
        99,
        4,
        scoreline_path=scoreline_path,
        rating_path=rating_path,
        song_data_path=song_data_path,
    )

    assert single_edge_result.data_sufficiency == "ok"
    assert double_edge_result.data_sufficiency == "ok"
    assert single_edge_result.stable is not None
    assert single_edge_result.pb is not None
    assert double_edge_result.stable is not None
    assert double_edge_result.pb is not None
    assert double_edge_result.stable.score < single_edge_result.stable.score
    assert double_edge_result.pb.score < single_edge_result.pb.score
