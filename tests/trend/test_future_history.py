"""Old imported future evidence must not anchor windows or feed replay/daily writes."""
import copy
import datetime as dt
import json

from taiko_store import PublicationStore
from taiko_bot.runtime.player.center import b30_daily, b30_history
from taiko_bot.runtime.player.center.history_time import (
    admit_history_snapshot, history_time_ceiling, is_future_history_time,
)

NOW = dt.datetime(2026, 11, 1, 12)
PAST = dt.datetime(2026, 10, 31, 19, 49)
FUTURE = dt.datetime(2765, 1, 1)


def song(number=1, **extra):
    return {"song_no": number, "level": 4, "high_score": 900000,
            "update_datetime": "2026-10-31 19:49:00", **extra}


def test_future_admission_uses_shanghai_offsets_and_inclusive_tolerance():
    ceiling = history_time_ceiling(NOW)
    for value in ("2026-11-01 12:05:00", "2026-11-01T04:05:00Z"):
        assert not is_future_history_time(value, ceiling)
    for value in ("2026-11-01 12:05:00.000001", "2099-01-01 00:00:00", FUTURE):
        assert is_future_history_time(value, ceiling)
    assert not is_future_history_time(None, ceiling)


def test_future_events_and_metadata_are_excluded_without_mutating_history():
    payload = {"_meta": {"full": True}, "songs": [song(), song(2, highscore_datetime="2765-01-01 00:00:00")]}
    original = copy.deepcopy(payload)
    admitted = admit_history_snapshot(PAST, payload, history_time_ceiling(NOW))
    assert admitted["songs"] == [song()]
    assert payload == original
    for value in ("2765-01-01 00:00:00", "27650101_000000_000001"):
        assert admit_history_snapshot(PAST, {"_meta": {"observed_at": value}, "songs": [song()]}, history_time_ceiling(NOW)) is None


def test_canonical_replay_skips_future_delta_and_preserves_valid_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(b30_history, "history_time_ceiling", lambda: history_time_ceiling(NOW))
    store = PublicationStore(tmp_path, "123")
    full = {"_meta": {"full": True}, "songs": [song(), song(2, highscore_datetime="2765-01-01 00:00:00")]}
    delta = {"_meta": {"full": False}, "songs": [song(high_score=9999999)]}
    with store.exclusive():
        store.commit({"current": b"{}",
                      "history/data_20261031_194900_000000.json": json.dumps(full).encode(),
                      "history/data_27650101_000000_000001_kinoko-history_fixture.json": json.dumps(delta).encode()})
    with store.shared():
        view = store.reader()
        before = view.publication
        snapshots = b30_history._reconstruct_user_snapshots(b30_history._history_snapshot_inputs(view))
        assert [(when, data["songs"]) for when, data in snapshots] == [(PAST, [song()])]
        assert json.loads(view.history_raw("data_20261031_194900_000000.json")) == full
        assert view.publication == before


def test_future_daily_points_never_hide_valid_recent_points(monkeypatch):
    monkeypatch.setattr(b30_history, "history_time_ceiling", lambda: history_time_ceiling(NOW))
    points = [(PAST, {}, 10), (FUTURE, {}, 99)]
    assert b30_history._limit_trend_points_to_recent_days(points, 30) == points[:1]
    assert b30_history._limit_trend_points_to_recent_days(points, None) == points[:1]


def test_daily_builder_excludes_future_before_measurement_and_keeps_archive(tmp_path, monkeypatch):
    monkeypatch.setattr(b30_history, "history_time_ceiling", lambda: history_time_ceiling(NOW))
    store = PublicationStore(tmp_path, "123")
    with store.exclusive():
        store.commit({"current": b"{}"})
    measured = []
    def results(records):
        measured.append(records)
        return [object()]
    def build(snapshots):
        with store.shared():
            return b30_history._build_daily_rating_points_from_view(
                "123", snapshots=snapshots, archive_namespace="v1-top20", _publication_store=store,
                results_from_records_fn=results, compute_dim_topn_means_fn=lambda *_: {"精度力": 10},
                aggregate_topn_value_fn=lambda *_: 10)
    snapshots = [(PAST, {"_meta": {"full": True}, "songs": [song(), song(2, highscore_datetime="2765-01-01 00:00:00")]}),
                 (FUTURE, {"songs": [song(high_score=9999999)]})]
    assert build(snapshots) == ("ok", [(PAST, {"精度力": 10}, 10)])
    assert measured == [[song()]]
    with store.shared():
        with b30_daily.archive("123", userdata_dir=tmp_path, publication_store=store) as days:
            days["2765-01-01"] = {**days["2026-10-31"], "capturedAt": "2765-01-01T00:00:00+08:00"}
    path = b30_daily.archive_path("123", userdata_dir=tmp_path)
    before = path.read_bytes()
    for retained in (snapshots, []):
        assert build(retained) == ("ok", [(PAST, {"精度力": 10}, 10)])
        assert path.read_bytes() == before
    assert measured == [[song()]]
