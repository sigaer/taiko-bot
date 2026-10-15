from __future__ import annotations

import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from pathlib import Path

import pytest

from taiko_bot.offline.annual_summary.aggregates import (
    build_achievements_and_breakthrough,
    build_keyword_and_rating,
    build_static_personality_sections,
    build_time_sections,
)
from taiko_bot.offline.annual_summary import cache as annual_cache
from taiko_bot.offline.annual_summary.events import build_observation_events
from taiko_bot.offline.annual_summary.finaltitle_model import FINAL_TITLE_KEYS
from taiko_bot.offline.annual_summary.helpers import format_dan_grade
from taiko_bot.offline.annual_summary.service import (
    _time_coverage,
    build_annual_result,
    build_public_summary,
)
from taiko_bot.offline.annual_summary.ratings import build_rating_distribution
from taiko_bot.offline.annual_summary.shadow import build_shadow_report
from taiko_bot.offline.annual_summary.reporting_window import resolve_reporting_window
from taiko_bot.offline.annual_summary.snapshots import (
    is_full_snapshot,
    load_snapshot_history,
    select_window,
)


TEST_VERSION = {
    "key": "annual_2026",
    "name": "2026 太鼓年度回顾",
    "startDate": "2025-10-09",
    "endDate": "2026-09-30",
    "endExclusive": "2026-10-01",
    "calendarDays": 357,
    "timezone": "Asia/Shanghai",
    "reportRevision": "annual-report-2026-r2-final-window",
}


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _song(
    song_no: int,
    *,
    stage: int,
    updated_at: str,
    highscore_at: str | None = None,
    score: int = 1_000_000,
    level: int = 4,
    clear: int = 0,
    full_combo: int = 0,
    dondaful: int = 0,
    good: int = 100,
    ok: int = 0,
    bad: int = 0,
    pound: int = 0,
    speed: float = 1.0,
    rank: int = 6,
) -> dict:
    return {
        "song_no": song_no,
        "level": level,
        "high_score": score,
        "best_score_rank": rank,
        "good_cnt": good,
        "ok_cnt": ok,
        "ng_cnt": bad,
        "pound_cnt": pound,
        "combo_cnt": good + ok,
        "stage_cnt": stage,
        "clear_cnt": clear,
        "full_combo_cnt": full_combo,
        "dondaful_combo_cnt": dondaful,
        "update_datetime": updated_at,
        "highscore_datetime": highscore_at or updated_at,
        "option_flg": [speed, 0, 0, "00"],
    }


def _payload(source: str | None, songs: list[dict], *, full: bool = True, dan: int = 0) -> dict:
    payload = {
        "profile": {
            "mydon_name": "Maru",
            "gameCostume": {
                "title": "太鼓好き",
                "titleplate_id": 2,
                "got_dan_max": dan,
                "dan_name": {"grade": str(dan), "level": 1},
            },
        },
        "achievement": {"count_level": 5},
        "dojo": {},
        "songs": songs,
    }
    if source is not None:
        payload["_meta"] = {"full": full, "source": source}
    elif not full:
        payload["_meta"] = {"full": False}
    return payload


def _snapshot(userdata: Path, uid: str, stamp: str, payload: dict) -> Path:
    path = userdata / uid / f"data_{stamp}.json"
    _write_json(path, payload)
    return path


def _selection(userdata: Path, uid: str, end: date = date(2026, 1, 31)):
    history = load_snapshot_history(uid, userdata_dir=userdata)
    return select_window(
        history.snapshots,
        start_date=date(2026, 1, 1),
        generated_at=datetime.combine(end, datetime.min.time()),
        end_date=end,
    )


def _canonical_event(
    song_no: int,
    plays: int,
    at: str | None,
    *,
    precision: str = "batch_last_play_proxy",
    event_type: str = "play_delta",
    score_delta: int = 0,
) -> dict:
    return {
        "eventId": f"evt_{song_no:024x}",
        "type": event_type,
        "source": "wahlap" if precision != "interval_only" else "hiroba",
        "sourceAccount": None,
        "mergeTopology": [],
        "songNo": song_no,
        "level": 4,
        "observedBetween": {"from": "2026-01-01T00:00:00", "to": "2026-01-03T00:00:00"},
        "representativeAt": at,
        "representativeDate": at[:10] if at else None,
        "nightDate": at[:10] if at else None,
        "timePrecision": precision,
        "before": {"high_score": 1_000_000},
        "after": {"high_score": 1_000_000 + score_delta},
        "delta": {"playCount": plays, "score": score_delta},
        "warnings": [],
        "sourceRef": {"from": {"file": "a", "sha256": "0" * 64}, "to": {"file": "b", "sha256": "1" * 64}},
    }


def test_reporting_window_contract_is_half_open_and_357_days():
    window = resolve_reporting_window(TEST_VERSION)
    assert window.start_at == datetime(2025, 10, 9, 0, 0, 0)
    assert window.end_exclusive_at == datetime(2026, 10, 1, 0, 0, 0)
    assert window.end_inclusive_date == date(2026, 9, 30)
    assert window.calendar_days == 357
    with pytest.raises(ValueError, match="endExclusive"):
        resolve_reporting_window({**TEST_VERSION, "endExclusive": "2026-09-30"})
    with pytest.raises(ValueError, match="calendarDays"):
        resolve_reporting_window({**TEST_VERSION, "calendarDays": 356})


def test_reporting_window_migration_keeps_all_45_final_title_keys():
    assert len(FINAL_TITLE_KEYS) == 45


def test_reporting_window_exact_boundaries_and_baseline(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "boundary"
    rows = [
        ("20251008_235959_000000", "2025-10-08T23:59:59+08:00", 1),
        ("20251009_000000_000000", "2025-10-09T00:00:00+08:00", 2),
        ("20251009_120000_000000", "2025-10-09T12:00:00+08:00", 3),
        ("20260930_235959_000000", "2026-09-30T23:59:59+08:00", 4),
        ("20260930_235959_999999", "2026-09-30T23:59:59.999999+08:00", 5),
        ("20261001_000000_000000", "2026-10-01T00:00:00+08:00", 6),
    ]
    for stamp, observed_at, stage in rows:
        payload = _payload(
            "wahlap",
            [_song(1, stage=stage, updated_at=observed_at, score=1_000_000)],
        )
        payload["_meta"]["observed_at"] = observed_at
        _snapshot(userdata, uid, stamp, payload)

    window = resolve_reporting_window(TEST_VERSION)
    history = load_snapshot_history(uid, userdata_dir=userdata)
    selection = select_window(
        history.snapshots,
        start_date=window.start_date,
        generated_at=datetime(2026, 10, 2),
        end_date=window.end_inclusive_date,
        start_at=window.start_at,
        end_exclusive_at=window.end_exclusive_at,
    )
    assert [item.observed_at for item in selection.window_snapshots] == [
        datetime(2025, 10, 9, 0, 0, 0),
        datetime(2025, 10, 9, 12, 0, 0),
        datetime(2026, 9, 30, 23, 59, 59),
        datetime(2026, 9, 30, 23, 59, 59, 999999),
    ]
    assert selection.baseline.observed_at == datetime(2025, 10, 8, 23, 59, 59)
    assert selection.end_state["songs"][0]["stage_cnt"] == 5
    events, _ = build_observation_events(
        selection,
        start_date=window.start_date,
        effective_end_date=selection.effective_end_date,
        start_at=window.start_at,
        end_exclusive_at=window.end_exclusive_at,
    )
    assert sum((item.get("delta") or {}).get("playCount", 0) for item in events) == 4
    assert all(
        not item.get("representativeAt")
        or "2025-10-09T00:00:00+08:00" <= item["representativeAt"] < "2026-10-01T00:00:00+08:00"
        for item in events
    )


@pytest.mark.parametrize(
    "observed_at",
    ["2025-10-09T00:00:00+08:00", "2026-09-30T23:59:59.999999+08:00"],
)
def test_reporting_window_sparse_single_boundary_record(tmp_path: Path, observed_at: str):
    userdata = tmp_path / "userdata"
    payload = _payload("wahlap", [_song(1, stage=1, updated_at=observed_at)])
    payload["_meta"]["observed_at"] = observed_at
    _snapshot(userdata, "sparse", "20260101_000000_000000", payload)
    window = resolve_reporting_window(TEST_VERSION)
    selection = select_window(
        load_snapshot_history("sparse", userdata_dir=userdata).snapshots,
        start_date=window.start_date,
        generated_at=datetime(2026, 10, 2),
        end_date=window.end_inclusive_date,
        start_at=window.start_at,
        end_exclusive_at=window.end_exclusive_at,
    )
    assert len(selection.window_snapshots) == 1


def test_reporting_window_outside_only_is_controlled_no_data(tmp_path: Path):
    userdata = tmp_path / "userdata"
    for uid, observed_at in (
        ("before", "2025-10-08T23:59:59+08:00"),
        ("after", "2026-10-01T00:00:00+08:00"),
    ):
        payload = _payload("wahlap", [_song(1, stage=1, updated_at=observed_at)])
        payload["_meta"]["observed_at"] = observed_at
        _snapshot(userdata, uid, "20260101_000000_000000", payload)
        window = resolve_reporting_window(TEST_VERSION)
        with pytest.raises(ValueError, match="no snapshots in annual window"):
            select_window(
                load_snapshot_history(uid, userdata_dir=userdata).snapshots,
                start_date=window.start_date,
                generated_at=datetime(2026, 10, 2),
                end_date=window.end_inclusive_date,
                start_at=window.start_at,
                end_exclusive_at=window.end_exclusive_at,
            )


def test_pre_window_source_time_remains_baseline_transition_without_annual_timestamp(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "source-boundary"
    before = _payload("wahlap", [_song(1, stage=1, updated_at="2025-10-08 22:00:00")])
    before["_meta"]["observed_at"] = "2025-10-08T23:00:00+08:00"
    after = _payload("wahlap", [_song(1, stage=2, updated_at="2025-10-08 23:59:59")])
    after["_meta"]["observed_at"] = "2025-10-09T00:00:01+08:00"
    _snapshot(userdata, uid, "20251008_230000_000000", before)
    _snapshot(userdata, uid, "20251009_000001_000000", after)
    window = resolve_reporting_window(TEST_VERSION)
    selection = select_window(
        load_snapshot_history(uid, userdata_dir=userdata).snapshots,
        start_date=window.start_date,
        generated_at=datetime(2026, 10, 2),
        end_date=window.end_inclusive_date,
        start_at=window.start_at,
        end_exclusive_at=window.end_exclusive_at,
    )
    events, _ = build_observation_events(
        selection,
        start_date=window.start_date,
        effective_end_date=selection.effective_end_date,
        start_at=window.start_at,
        end_exclusive_at=window.end_exclusive_at,
    )
    play_events = [item for item in events if item["type"] == "play_delta"]
    assert len(play_events) == 1
    assert play_events[0]["delta"]["playCount"] == 1
    assert play_events[0]["representativeAt"] is None
    assert "record_updated_at_outside_reporting_window" in play_events[0]["warnings"]


def test_cross_year_month_order_uses_year_month_keys():
    events = [
        _canonical_event(1, 2, "2026-09-30T23:59:59+08:00"),
        _canonical_event(2, 3, "2025-10-09T12:00:00+08:00"),
        _canonical_event(3, 4, "2026-01-01T10:00:00+08:00"),
    ]
    sections = build_time_sections(
        events,
        {1: {"id": 1}, 2: {"id": 2}, 3: {"id": 3}},
        start_date=date(2025, 10, 9),
        effective_end_date=date(2026, 9, 30),
        time_eligible=True,
    )
    assert [item["month"] for item in sections["monthlyFavorites"]["data"]] == [
        "2025-10", "2026-01", "2026-09"
    ]


def _song_data() -> list[dict]:
    return [
        {"id": song_no, "song_name": f"歌曲 {song_no}", "song_name_jp": f"曲 {song_no}", "level_4": 10}
        for song_no in range(1, 40)
    ]


def _rating_data() -> dict:
    return {
        "songs": {
            f"song_{song_no}": {
                "id": song_no,
                "level": 4,
                "song_name_cn": f"歌曲 {song_no}",
                "song_name": f"曲 {song_no}",
                "score": 10.0,
                "combo": 100,
                "复合处理": 20.0,
                "平均密度": 30.0 + song_no,
                "瞬间密度": 40.0 + song_no,
                "叩き分け": 50.0,
                "BPM变化": 10.0,
                "HS变化": 0.0,
            }
            for song_no in range(1, 40)
        },
        "const_table": {"const_to_score": {"10.0": 12.5}},
    }


def test_full_snapshot_shapes_and_sparse_delta():
    assert is_full_snapshot(_payload("wahlap", []))
    assert is_full_snapshot(_payload(None, []))
    assert is_full_snapshot({"_meta": {"full": True}, "songs": []})
    assert not is_full_snapshot({"_meta": {"full": False}, "songs": [_song(1, stage=1, updated_at="2026-01-01 01:00:00")]})


def test_rebuild_sparse_delta_inherits_source_and_preserves_unchanged_charts(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "1"
    _snapshot(userdata, uid, "20260101_000000_000000", _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-01 00:00:00"), _song(2, stage=1, updated_at="2026-01-01 00:00:00")]))
    _snapshot(userdata, uid, "20260102_000000_000000", {"_meta": {"full": False}, "songs": [_song(1, stage=3, updated_at="2026-01-01 12:00:00")]})
    history = load_snapshot_history(uid, userdata_dir=userdata)
    assert len(history.snapshots) == 2
    assert history.snapshots[-1].source == "wahlap"
    assert history.snapshots[-1].changed_keys == ((1, 4),)
    final = {(row["song_no"], row["level"]): row for row in history.snapshots[-1].state["songs"]}
    assert final[(1, 4)]["stage_cnt"] == 3
    assert final[(2, 4)]["stage_cnt"] == 1


def test_normalized_snapshot_cache_is_content_addressed_and_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    userdata = tmp_path / "userdata"
    cache = tmp_path / "cache"
    monkeypatch.setenv("TAIKO_ANNUAL_CACHE_DIR", str(cache))
    path = _snapshot(userdata, "cached", "20260101_000000_000000", _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-01 00:00:00")]))
    annual_cache.reset_normalized_cache_stats()
    assert load_snapshot_history("cached", userdata_dir=userdata).snapshots[-1].state["songs"][0]["stage_cnt"] == 1
    first_stats = annual_cache.get_normalized_cache_stats()
    assert first_stats["miss"] == 1
    assert first_stats["write"] == 1
    # Metadata planning writes the cold entry, then replay reads that entry
    # without retaining the first-pass payload.
    assert first_stats["hit"] == 1
    cached_files = list((cache / "normalized").glob("*/*.json"))
    assert len(cached_files) == 1
    assert cached_files[0].stat().st_mode & 0o077 == 0
    assert cache.stat().st_mode & 0o077 == 0
    assert (cache / "normalized").stat().st_mode & 0o077 == 0

    assert load_snapshot_history("cached", userdata_dir=userdata).snapshots[-1].state["songs"][0]["stage_cnt"] == 1
    assert annual_cache.get_normalized_cache_stats()["hit"] == 3

    _write_json(path, _payload("wahlap", [_song(1, stage=3, updated_at="2026-01-01 00:00:00")]))
    assert load_snapshot_history("cached", userdata_dir=userdata).snapshots[-1].state["songs"][0]["stage_cnt"] == 3
    assert len(list((cache / "normalized").glob("*/*.json"))) == 2


def test_normalized_snapshot_cache_version_corruption_and_concurrency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    userdata = tmp_path / "userdata"
    cache = tmp_path / "cache"
    monkeypatch.setenv("TAIKO_ANNUAL_CACHE_DIR", str(cache))
    path = _snapshot(
        userdata,
        "parallel",
        "20260101_000000_000000",
        _payload("wahlap", [_song(1, stage=7, updated_at="2026-01-01 00:00:00")]),
    )
    content_hash = annual_cache.hashlib.sha256(path.read_bytes()).hexdigest()
    original_key = annual_cache.normalized_cache_object_key(content_hash)
    monkeypatch.setattr(annual_cache, "SOURCE_LINEAGE_INFERENCE_VERSION", "source-lineage-test")
    assert annual_cache.normalized_cache_object_key(content_hash) != original_key
    monkeypatch.undo()
    monkeypatch.setenv("TAIKO_ANNUAL_CACHE_DIR", str(cache))

    annual_cache.reset_normalized_cache_stats()
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(
            executor.map(
                lambda _: load_snapshot_history("parallel", userdata_dir=userdata).snapshots[-1].state["songs"][0]["stage_cnt"],
                range(16),
            )
        )
    assert results == [7] * 16
    cached_files = list((cache / "normalized").glob("*/*.json"))
    assert len(cached_files) == 1
    assert annual_cache.get_normalized_cache_stats()["write"] == 1
    json.loads(cached_files[0].read_text(encoding="utf-8"))

    cached_files[0].write_text("{", encoding="utf-8")
    annual_cache.reset_normalized_cache_stats()
    assert load_snapshot_history("parallel", userdata_dir=userdata).snapshots[-1].state["songs"][0]["stage_cnt"] == 7
    stats = annual_cache.get_normalized_cache_stats()
    assert stats["corrupt"] == 1
    assert stats["write"] == 1
    json.loads(cached_files[0].read_text(encoding="utf-8"))


def test_current_wahlap_metadata_infers_neutral_legacy_lineage(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "2"
    _snapshot(userdata, uid, "20260101_000000_000000", _payload(None, [_song(1, stage=1, updated_at="2026-01-01 00:00:00")]))
    _snapshot(userdata, uid, "20260102_000000_000000", {"_meta": {"full": False, "source": "sakura-bot-sync"}, "songs": [_song(1, stage=2, updated_at="2026-01-01 12:00:00")]})
    _write_json(userdata / f"{uid}data.json", _payload("wahlap", [_song(1, stage=2, updated_at="2026-01-01 12:00:00")]))
    history = load_snapshot_history(uid, userdata_dir=userdata)
    assert {item.source for item in history.snapshots} == {"wahlap"}
    assert "lineage_source_inferred:wahlap" in history.warnings


def test_legacy_wahlap_profile_account_keeps_metadata_upgrade_comparable(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "34727379"
    baseline = _payload(None, [_song(1, stage=10, updated_at="2026-01-01 12:00:00")])
    baseline["profile"]["userid"] = uid
    _snapshot(userdata, uid, "20260101_180000_000000", baseline)
    _snapshot(
        userdata,
        uid,
        "20260102_180000_000000",
        {
            "_meta": {"full": False, "source": "sakura-bot-sync"},
            "songs": [_song(1, stage=20, updated_at="2026-01-02 12:00:00")],
        },
    )
    upgraded = {
        "_meta": {"full": False, "source": "wahlap", "source_account": uid},
        "songs": [_song(1, stage=30, updated_at="2026-01-03 12:00:00")],
    }
    _snapshot(userdata, uid, "20260103_180000_000000", upgraded)
    current = _payload("wahlap", [_song(1, stage=30, updated_at="2026-01-03 12:00:00")])
    current["_meta"]["source_account"] = uid
    current["profile"]["userid"] = uid
    _write_json(userdata / f"{uid}data.json", current)

    history = load_snapshot_history(uid, userdata_dir=userdata)
    assert {item.source for item in history.snapshots} == {"wahlap"}
    assert {item.source_account for item in history.snapshots} == {uid}
    assert "lineage_source_account_inferred" in history.warnings
    events, stats = build_observation_events(
        _selection(userdata, uid),
        start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 1, 31),
    )
    plays = [event for event in events if event["type"] == "play_delta"]
    assert stats["comparableTransitionCount"] == 2
    assert stats["skippedSourceTransitionCount"] == 0
    assert sum(event["delta"]["playCount"] for event in plays) == 20


def test_wahlap_account_switch_never_creates_cross_account_delta(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "account-switch"
    before = _payload("wahlap", [_song(1, stage=10, updated_at="2026-01-01 12:00:00")])
    before["_meta"]["source_account"] = "11111111"
    after = _payload("wahlap", [_song(1, stage=30, updated_at="2026-01-02 12:00:00")])
    after["_meta"]["source_account"] = "22222222"
    _snapshot(userdata, uid, "20260101_180000_000000", before)
    _snapshot(userdata, uid, "20260102_180000_000000", after)

    events, stats = build_observation_events(
        _selection(userdata, uid),
        start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 1, 31),
    )
    assert stats["comparableTransitionCount"] == 0
    assert stats["skippedSourceTransitionCount"] == 1
    assert not [event for event in events if event["type"] == "play_delta"]


def test_matching_wahlap_directory_identity_fills_legacy_account_gap(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "12345678"
    _snapshot(
        userdata,
        uid,
        "20260101_180000_000000",
        _payload(None, [_song(1, stage=10, updated_at="2026-01-01 12:00:00")]),
    )
    upgraded = _payload("wahlap", [_song(1, stage=30, updated_at="2026-01-02 12:00:00")])
    upgraded["_meta"]["source_account"] = uid
    _snapshot(userdata, uid, "20260102_180000_000000", upgraded)
    _write_json(userdata / f"{uid}data.json", upgraded)

    history = load_snapshot_history(uid, userdata_dir=userdata)
    assert {item.source_account for item in history.snapshots} == {uid}
    events, stats = build_observation_events(
        _selection(userdata, uid),
        start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 1, 31),
    )
    assert stats["comparableTransitionCount"] == 1
    assert sum(event["delta"]["playCount"] for event in events if event["type"] == "play_delta") == 20


def test_wahlap_play_uses_batch_proxy_and_highscore_uses_own_timestamp(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "3"
    baseline = [_song(i, stage=1, updated_at="2026-01-01 00:00:00", score=900_000) for i in range(1, 7)]
    current = []
    for i in range(1, 7):
        day = 1 if i <= 3 else 2
        current.append(_song(i, stage=3, updated_at=f"2026-01-0{day} 10:00:00", highscore_at=f"2026-01-0{day} 09:00:00", score=1_000_000))
    _snapshot(userdata, uid, "20260101_000000_000000", _payload("wahlap", baseline))
    _snapshot(userdata, uid, "20260103_000000_000000", _payload("wahlap", current))
    selection = _selection(userdata, uid)
    events, stats = build_observation_events(selection, start_date=date(2026, 1, 1), effective_end_date=date(2026, 1, 31))
    plays = [event for event in events if event["type"] == "play_delta"]
    scores = [event for event in events if event["type"] == "high_score"]
    assert stats["comparableTransitionCount"] == 1
    assert len(plays) == len(scores) == 6
    assert {event["timePrecision"] for event in plays} == {"batch_last_play_proxy"}
    assert {event["timePrecision"] for event in scores} == {"source_highscore_time"}
    assert plays[0]["representativeAt"].endswith("10:00:00+08:00")
    assert scores[0]["representativeAt"].endswith("09:00:00+08:00")
    assert _time_coverage(events)["eligible"] is True


@pytest.mark.parametrize("source", ["hiroba", "unknown"])
def test_low_trust_sources_never_create_precise_time(source: str, tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = source
    _snapshot(userdata, uid, "20260101_000000_000000", _payload(source, [_song(1, stage=1, updated_at="2026-01-01 00:00:00")]))
    _snapshot(userdata, uid, "20260102_000000_000000", _payload(source, [_song(1, stage=3, updated_at="2026-01-01 12:00:00", score=1_100_000)]))
    events, _ = build_observation_events(_selection(userdata, uid), start_date=date(2026, 1, 1), effective_end_date=date(2026, 1, 31))
    assert events
    assert all(event["representativeAt"] is None for event in events)
    assert all(event["timePrecision"] in {"interval_only", "none"} for event in events)
    assert _time_coverage(events)["ratio"] == 0


def test_manual_source_is_traceable_but_not_counted_as_play(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "manual"
    _snapshot(userdata, uid, "20260101_000000_000000", _payload("web-account", [_song(1, stage=1, updated_at="2026-01-01 00:00:00")]))
    _snapshot(userdata, uid, "20260102_000000_000000", _payload("web-account", [_song(1, stage=99, updated_at="2026-01-01 12:00:00")]))
    events, _ = build_observation_events(_selection(userdata, uid), start_date=date(2026, 1, 1), effective_end_date=date(2026, 1, 31))
    assert [event["type"] for event in events] == ["manual_adjustment"]
    assert _time_coverage(events)["totalObservedPlayCount"] == 0


def test_counter_regression_uses_high_water_and_does_not_double_count(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "counter"
    for day, stage in ((1, 100), (2, 50), (3, 80), (4, 110)):
        _snapshot(userdata, uid, f"2026010{day}_000000_000000", _payload("wahlap", [_song(1, stage=stage, updated_at=f"2026-01-0{day} 00:00:00")]))
    events, _ = build_observation_events(_selection(userdata, uid), start_date=date(2026, 1, 1), effective_end_date=date(2026, 1, 31))
    plays = [event for event in events if event["type"] == "play_delta"]
    assert sum(event["delta"]["playCount"] for event in plays) == 10
    assert any(event["type"] == "counter_anomaly" and "counter_regression" in event["warnings"] for event in events)


def test_source_switch_and_deleted_readded_chart_never_create_cross_epoch_delta(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "epochs"
    _snapshot(userdata, uid, "20260101_000000_000000", _payload("wahlap", [_song(1, stage=10, updated_at="2026-01-01 00:00:00")]))
    _snapshot(userdata, uid, "20260102_000000_000000", _payload("hiroba", [_song(1, stage=20, updated_at="2026-01-02 00:00:00")]))
    _snapshot(userdata, uid, "20260103_000000_000000", _payload("wahlap", [], full=True))
    _snapshot(userdata, uid, "20260104_000000_000000", _payload("wahlap", [_song(1, stage=30, updated_at="2026-01-04 00:00:00")]))
    events, _ = build_observation_events(_selection(userdata, uid), start_date=date(2026, 1, 1), effective_end_date=date(2026, 1, 31))
    assert not [event for event in events if event["type"] == "play_delta"]


def test_same_time_full_precedes_delta_and_metadata_reordering_warns(tmp_path: Path):
    userdata = tmp_path / "userdata"
    uid = "ordering"
    full = _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-02 00:00:00")])
    full["_meta"]["synced_at"] = "2026-01-03T00:00:00+08:00"
    delta = {"_meta": {"full": False, "source": "wahlap", "synced_at": "2026-01-02T00:00:00+08:00"}, "songs": [_song(1, stage=2, updated_at="2026-01-02 00:00:00")]}
    _write_json(userdata / uid / "data_20260101_000000_000000_b.json", full)
    _write_json(userdata / uid / "data_20260102_000000_000000_a.json", delta)
    history = load_snapshot_history(uid, userdata_dir=userdata)
    assert "out_of_order_snapshot:data_20260102_000000_000000_a.json" in history.warnings

    same_time = tmp_path / "same-time"
    _write_json(same_time / uid / "data_20260102_000000_000000_a.json", delta)
    _write_json(same_time / uid / "data_20260102_000000_000000_b.json", _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-02 00:00:00")]))
    rebuilt = load_snapshot_history(uid, userdata_dir=same_time)
    assert rebuilt.snapshots[-1].state["songs"][0]["stage_cnt"] == 2


def test_time_coverage_threshold_is_weighted_and_requires_records_and_days():
    trusted_79 = [_canonical_event(i, 1 if i < 5 else 75, "2026-01-01T10:00:00" if i < 3 else "2026-01-02T10:00:00") for i in range(1, 6)]
    low_21 = [_canonical_event(99, 21, None, precision="interval_only")]
    assert _time_coverage(trusted_79 + low_21)["ratio"] == 0.79
    assert _time_coverage(trusted_79 + low_21)["eligible"] is False
    trusted_80 = [_canonical_event(i, 1 if i < 5 else 76, "2026-01-01T10:00:00" if i < 3 else "2026-01-02T10:00:00") for i in range(1, 6)]
    low_20 = [_canonical_event(99, 20, None, precision="interval_only")]
    assert _time_coverage(trusted_80 + low_20)["ratio"] == 0.8
    assert _time_coverage(trusted_80 + low_20)["eligible"] is True


def test_night_activity_assigns_early_morning_to_previous_night():
    def canonical_event(at: str, song_no: int, plays: int) -> dict:
        moment = datetime.fromisoformat(at)
        night_date = (moment.date() if moment.hour >= 5 else moment.date().fromordinal(moment.date().toordinal() - 1)).isoformat()
        return {
            "type": "play_delta",
            "songNo": song_no,
            "level": 4,
            "representativeAt": moment.isoformat(),
            "representativeDate": moment.date().isoformat(),
            "nightDate": night_date,
            "timePrecision": "batch_last_play_proxy",
            "delta": {"playCount": plays},
            "observedBetween": {"from": moment.isoformat(), "to": moment.isoformat()},
        }

    sections = build_time_sections(
        [canonical_event("2026-01-31T23:50:00", 1, 2), canonical_event("2026-02-01T01:15:00", 2, 5)],
        {},
        start_date=date(2026, 1, 1),
        effective_end_date=date(2026, 2, 28),
        time_eligible=True,
    )
    assert sections["lateNight"]["data"]["activeDays"] == 1
    assert sections["timeOfDay"]["data"]["periods"]["late_night"] == 7


def test_speed_threshold_near_dondaful_challenge_and_pound_contract():
    base_songs = [
        _song(i, stage=1, updated_at="2026-01-01 00:00:00", speed=1.5, pound=i)
        for i in range(1, 11)
    ]
    state = {"songs": base_songs}
    sections = build_static_personality_sections("current_archive", [], state, {})
    assert sections["speedProfile"]["status"] == "unavailable"
    base_songs.append(_song(11, stage=1, updated_at="2026-01-01 00:00:00", speed=1.5, ok=3, bad=0, pound=99))
    events = [_canonical_event(12, 10, "2026-01-02T10:00:00")]
    sections = build_static_personality_sections("version_observed", events, {"songs": base_songs}, {})
    assert sections["speedProfile"]["data"]["speed"] == 1.5
    assert sections["speedProfile"]["data"]["eligibleChartCount"] == 11
    assert sections["nearDondaful"]["data"]["songNo"] == 11
    assert sections["challenge"]["data"]["playCount"] == 10
    assert sections["pound"]["data"]["totalPoundCount"] == sum(range(1, 11)) + 99
    assert sections["pound"]["data"]["topPoundCount"] == 99

    challenge_state = {"songs": [*base_songs, _song(12, stage=67, updated_at="2026-01-02 10:00:00")]}
    sections = build_static_personality_sections("version_observed", events, challenge_state, {})
    assert sections["challenge"]["data"]["playCount"] == 67
    assert sections["challenge"]["data"]["observedPlayCount"] == 10


def test_challenge_excludes_charts_with_any_completion_record():
    events = [
        _canonical_event(21, 30, "2026-01-02T10:00:00"),
        _canonical_event(22, 20, "2026-01-03T10:00:00"),
        _canonical_event(23, 12, "2026-01-04T10:00:00"),
    ]
    end_state = {
        "songs": [
            _song(21, stage=50, updated_at="2026-01-02 10:00:00", full_combo=1),
            _song(22, stage=40, updated_at="2026-01-03 10:00:00", dondaful=1),
            _song(23, stage=18, updated_at="2026-01-04 10:00:00", clear=1),
        ]
    }

    sections = build_static_personality_sections("version_observed", events, end_state, {})
    assert sections["challenge"]["status"] == "observed"
    assert sections["challenge"]["data"]["songNo"] == 23
    assert sections["challenge"]["data"]["playCount"] == 18

    completed_state = {
        "songs": [
            _song(21, stage=50, updated_at="2026-01-02 10:00:00", full_combo=1),
            _song(22, stage=40, updated_at="2026-01-03 10:00:00", dondaful=1),
            _song(23, stage=18, updated_at="2026-01-04 10:00:00", full_combo=1),
        ]
    }
    sections = build_static_personality_sections("version_observed", events, completed_state, {})
    assert sections["challenge"]["status"] == "unavailable"
    assert sections["challenge"]["reason"] == "no_qualifying_challenge"


def test_dan_codes_are_presented_as_player_facing_grades():
    assert format_dan_grade("12") == "七段"
    assert format_dan_grade("13") == "八段"
    assert format_dan_grade("19") == "达人"


def test_breakthrough_balances_difficulty_effort_and_single_unlock():
    easy_dondaful = _canonical_event(1, 2, "2026-01-02T10:00:00")
    easy_dondaful["delta"].update({"clearUnlocked": True, "fullComboUnlocked": True, "dondafulUnlocked": True})
    hard_full_combo = _canonical_event(2, 24, "2026-01-03T10:00:00")
    hard_full_combo["delta"].update({"clearUnlocked": True, "fullComboUnlocked": True, "dondafulUnlocked": False})
    end_state = {
        "songs": [
            _song(1, stage=2, updated_at="2026-01-02 10:00:00", clear=1, full_combo=1, dondaful=1),
            _song(2, stage=67, updated_at="2026-01-03 10:00:00", clear=1, full_combo=1),
        ]
    }
    song_meta = {
        1: {"id": 1, "song_name": "入门曲", "level_4": 1},
        2: {"id": 2, "song_name": "高难曲", "level_4": 10},
    }
    achievements, breakthrough = build_achievements_and_breakthrough(
        [easy_dondaful, hard_full_combo],
        {"profile": {"gameCostume": {"got_dan_max": 1}}},
        end_state,
        song_meta,
    )
    assert breakthrough["data"]["type"] == "ten_star_full_combo"
    assert breakthrough["data"]["playCount"] == 67
    assert breakthrough["data"]["achievementCount"] == 1
    full_combo_highlight = next(item for item in achievements["highlights"] if item["type"] == "full_combo")
    assert full_combo_highlight["song"]["songNo"] == 2


def test_single_snapshot_switches_to_current_archive(tmp_path: Path):
    userdata = tmp_path / "userdata"
    songs = [_song(1, stage=20, updated_at="2026-01-02 10:00:00", clear=1, full_combo=1, dondaful=1, rank=8)]
    _snapshot(userdata, "archive", "20260102_120000_000000", _payload("wahlap", songs))
    result = build_annual_result("archive", TEST_VERSION, userdata_dir=userdata, song_data_path=tmp_path / "missing.json", rating_path=None, generated_at=datetime(2026, 1, 31))
    summary = result["summary"]
    assert summary["mode"] == "current_archive"
    assert summary["overview"]["data"]["playCount"] == 20
    assert summary["overview"]["data"]["currentKiwamiCharts"] == 1
    assert summary["sections"]["timeOfDay"]["status"] == "unavailable"
    assert result["events"] == []


def test_current_full_file_without_history_builds_archive(tmp_path: Path):
    userdata = tmp_path / "userdata"
    payload = _payload(
        "wahlap",
        [_song(1, stage=7, updated_at="2026-01-02 10:00:00", clear=1)],
    )
    payload["_meta"]["observed_at"] = "2026-01-02T12:00:00+08:00"
    _write_json(userdata / "current-onlydata.json", payload)

    result = build_annual_result(
        "current-only",
        TEST_VERSION,
        userdata_dir=userdata,
        song_data_path=tmp_path / "missing.json",
        rating_path=None,
        generated_at=datetime(2026, 1, 31),
    )

    assert result["summary"]["mode"] == "current_archive"
    assert result["summary"]["overview"]["data"]["playCount"] == 7
    assert result["summary"]["sections"]["timeOfDay"]["status"] == "unavailable"
    assert result["events"] == []


def test_summary_v4_contract_schema_and_public_redaction(tmp_path: Path):
    userdata = tmp_path / "userdata"
    song_data = tmp_path / "song_data.json"
    rating_data = tmp_path / "rating.json"
    _write_json(song_data, _song_data())
    _write_json(rating_data, _rating_data())
    baseline = [_song(i, stage=1, updated_at="2026-01-01 00:00:00", score=900_000) for i in range(1, 13)]
    current = [_song(i, stage=3, updated_at="2026-01-01 10:00:00" if i <= 6 else "2026-01-02 10:00:00", score=1_000_000, speed=1.5, pound=i, clear=1 if i == 1 else 0) for i in range(1, 13)]
    _snapshot(userdata, "summary", "20260101_000000_000000", _payload("wahlap", baseline, dan=1))
    _snapshot(userdata, "summary", "20260103_000000_000000", _payload("wahlap", current, dan=2))
    result = build_annual_result("summary", TEST_VERSION, userdata_dir=userdata, song_data_path=song_data, rating_path=rating_data, generated_at=datetime(2026, 1, 31))
    summary = result["summary"]
    schema = json.loads((Path(__import__("taiko_bot.offline", fromlist=["x"]).__file__).parent / "schemas" / "annual-summary-v4.schema.json").read_text(encoding="utf-8"))
    assert summary["schemaVersion"] == 4
    assert summary["generatedAt"].endswith("+08:00")
    assert summary["coverage"]["firstSnapshotAt"].endswith("+08:00")
    assert all(event["observedBetween"]["from"].endswith("+08:00") for event in result["events"])
    assert all(not event["representativeAt"] or event["representativeAt"].endswith("+08:00") for event in result["events"])
    assert set(schema["required"]).issubset(summary)
    assert set(summary["sections"]) == set(schema["properties"]["sections"]["required"])
    assert summary["coverage"]["time"]["eligible"] is True
    assert summary["overview"]["data"]["playCount"] == sum(event["delta"]["playCount"] for event in result["events"] if event["type"] == "play_delta")
    assert summary["sections"]["breakthrough"]["data"]["type"] == "dan"
    event_required = set(schema["$defs"]["annualObservationEvent"]["required"])
    assert all(event_required.issubset(event) for event in result["events"])
    assert not any(key.lower().endswith("id") and key == "taikoId" for key in summary)
    public = build_public_summary(summary)
    assert "sourceSnapshotRange" not in public["provenance"]
    assert "inputFingerprint" not in public["provenance"]
    assert set(public["sections"]["ratingRank"].get("data") or {}) <= {"tier"}


def test_cli_build_outputs_single_envelope(tmp_path: Path):
    userdata = tmp_path / "userdata"
    _snapshot(userdata, "cli", "20260102_000000_000000", _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-01 10:00:00")]))
    command = [
        sys.executable,
        "-m",
        "taiko_bot.offline.annual_summary",
        "build",
        "--taiko-id",
        "cli",
        "--version",
        "annual_2026",
        "--version-json",
        json.dumps(TEST_VERSION, ensure_ascii=False),
        "--userdata-dir",
        str(userdata),
        "--song-data",
        str(tmp_path / "missing-songs.json"),
        "--rating-data",
        str(tmp_path / "missing-rating.json"),
        "--generated-at",
        "2026-01-31T12:00:00",
        "--output",
        "-",
    ]
    # Execute the real module under the same network/SQL/file audit guard.
    import contextlib, io, runpy
    from unittest.mock import patch
    from types import SimpleNamespace
    stdout, stderr = io.StringIO(), io.StringIO()
    with patch.object(sys, "argv", command[2:]), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_module(command[2], run_name="__main__")
        assert exit_info.value.code in (0, None)
    completed = SimpleNamespace(stdout=stdout.getvalue(), stderr=stderr.getvalue())
    progress = [json.loads(line) for line in completed.stderr.splitlines()]
    assert [item["stage"] for item in progress] == ["history", "events", "summaries", "personal_complete"]
    assert [item["percent"] for item in progress] == [15, 42, 68, 80]
    payload = json.loads(completed.stdout)
    assert set(payload) == {"summary", "events"}
    assert payload["summary"]["schemaVersion"] == 4


def test_anonymous_rating_distribution_uses_real_top20_aggregator(tmp_path: Path):
    userdata = tmp_path / "userdata"
    rating_data = tmp_path / "rating.json"
    _write_json(rating_data, _rating_data())
    _write_json(userdata / "firstdata.json", {"songs": [_song(i, stage=1, updated_at="2026-01-01 10:00:00") for i in range(1, 25)]})
    _write_json(userdata / "brokendata.json", {"songs": "invalid"})
    distribution = build_rating_distribution(userdata, rating_data, generated_at=datetime(2026, 1, 31, 12, 0, 0))
    assert distribution["scannedCount"] == 2
    assert distribution["discardedCount"] == 1
    assert len(distribution["ratings"]) == 1
    assert distribution["ratings"][0] == round(distribution["ratings"][0], 4)
    assert not any("id" in key.lower() or "account" in key.lower() for key in distribution)


def test_keyword_uses_taikob20_dimension_values(monkeypatch: pytest.MonkeyPatch):
    results = [object(), object()]
    calls: list[tuple[str, int]] = []
    values = {
        "AI_rating": 12.34567,
        "大歌力": 11.1,
        "体力": 12.2,
        "高速处理": 13.3,
        "精度力": 14.4,
        "节奏处理": 10.5,
        "复合处理": 9.6,
    }

    monkeypatch.setattr(
        "taiko_bot.offline.annual_summary.aggregates.compute_all_from_userdata_records",
        lambda records, json_path: results,
    )

    def fake_aggregate(_results: list[object], label: str, top_n: int) -> float:
        assert _results is results
        calls.append((label, top_n))
        return values[label]

    monkeypatch.setattr(
        "taiko_bot.offline.annual_summary.aggregates.aggregate_topN_value",
        fake_aggregate,
    )
    keyword, rating, rating_value = build_keyword_and_rating(
        "version_observed",
        [],
        {"songs": [_song(1, stage=99, updated_at="2026-01-01 10:00:00")]},
        rating_path="rating.json",
    )

    assert calls == [(label, 20) for label in values]
    assert keyword["status"] == "exact"
    assert keyword["data"]["dimensionKey"] == "accuracy"
    assert keyword["data"]["score"] == 14.4
    assert keyword["data"]["radarValues"] == {
        "big_song": 11.1,
        "stamina": 12.2,
        "speed": 13.3,
        "accuracy": 14.4,
        "rhythm": 10.5,
        "complex": 9.6,
    }
    assert rating["data"]["rating"] == 12.3457
    assert rating_value == values["AI_rating"]


def test_shadow_report_is_anonymous_and_bad_accounts_do_not_stop_batch(tmp_path: Path):
    userdata = tmp_path / "userdata"
    good_payload = _payload("wahlap", [_song(1, stage=1, updated_at="2026-01-01 10:00:00")])
    _write_json(userdata / "gooddata.json", good_payload)
    _snapshot(userdata, "good", "20260102_000000_000000", good_payload)
    (userdata / "brokendata.json").write_text("{", encoding="utf-8")
    report = build_shadow_report(userdata, TEST_VERSION, generated_at=datetime(2026, 1, 31, 12, 0, 0))
    assert report["scannedCount"] == 2
    assert report["builtCount"] == 1
    assert report["failedCount"] == 1
    assert report["failureTypeCounts"]["reason:invalid_snapshot_json"] == 1
    assert report["cacheStats"]["disabled"] > 0
    serialized = json.dumps(report, ensure_ascii=False)
    assert "good" not in serialized and "broken" not in serialized


def test_userdata_storage_writes_source_and_content_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from taiko_bot.runtime.player.center import userdata_storage

    monkeypatch.setenv("TAIKO_USERDATA_DIR", str(tmp_path / "userdata"))
    monkeypatch.setattr(userdata_storage, "TAIKO_SONG_DIR", str(tmp_path / "userdata"))
    monkeypatch.setattr(userdata_storage, "_load_locked_song_keys", lambda _user_id: set())
    userdata_storage.save_userdata("42", _payload(None, [_song(1, stage=1, updated_at="2026-01-01 10:00:00")]), source="wahlap")
    userdata_storage.save_userdata("42", _payload(None, [_song(1, stage=2, updated_at="2026-01-02 10:00:00")]), source="wahlap")
    current = json.loads((tmp_path / "userdata" / "42data.json").read_text(encoding="utf-8"))
    history = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((tmp_path / "userdata" / "42").glob("data_*.json"))]
    assert current["_meta"]["source"] == "wahlap"
    assert current["_meta"]["schema_version"] == 2
    assert len(current["_meta"]["content_sha256"]) == 64
    assert all(item["_meta"]["source"] == "wahlap" for item in history)
    assert all(len(item["_meta"]["content_sha256"]) == 64 for item in history)
