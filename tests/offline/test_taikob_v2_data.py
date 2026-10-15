from __future__ import annotations

import pytest

from taiko_bot.runtime.player.center import taikob_v2_data as source


HEADER = (
    "id,title,difficulty,totalNotes,sub_constant_1,main_constant,sub_constant_2,"
    "stamina,handspeed,burst,complex,rhythm"
)


def _dataset(*rows: str) -> str:
    return "\n".join((HEADER, *rows, ""))


def _row(
    song_id: str = "1",
    title: str = "てんぢく2000",
    difficulty: str = "oni",
    total_notes: str = "200",
    main_constant: str = "10.2",
) -> str:
    return (
        f"{song_id},{title},{difficulty},{total_notes},9.1,{main_constant},11.3,"
        "8.1,8.2,8.3,8.4,8.5"
    )


def test_parse_v2_dataset_csv_filters_invalid_rows() -> None:
    snapshot = source.parse_v2_dataset_csv(
        _dataset(
            _row(difficulty="hard", total_notes="100"),
            _row(),
            _row(song_id="900"),
            _row(song_id="bad-id"),
            _row(song_id="2", difficulty="edit", total_notes="0"),
            _row(song_id="2", main_constant="nan"),
        )
    )

    assert set(snapshot.song_map) == {(1, 3), (1, 4), (2, 5)}
    assert snapshot.song_map[(1, 4)].title == "てんぢく2000"
    assert snapshot.song_map[(1, 4)].total_notes == 200
    assert snapshot.song_map[(1, 4)].main_constant == pytest.approx(10.2)
    assert snapshot.song_map[(2, 5)].total_notes == 0
    assert len(snapshot.revision) == 64


def test_parse_v2_dataset_csv_requires_usable_constants() -> None:
    with pytest.raises(source.V2DataSourceError, match="没有可用"):
        source.parse_v2_dataset_csv(_dataset())


def test_load_v2_snapshot_prefers_local_cache(monkeypatch, tmp_path) -> None:
    fallback_path = tmp_path / "constants_id_v2.csv"
    fallback_path.write_text(_dataset(_row()), encoding="utf-8")
    source.clear_v2_source_cache()
    fetch_calls = []
    refresh_targets = []

    def fake_fetch():
        fetch_calls.append(True)
        return source.parse_v2_dataset_csv(_dataset(_row()))

    class DeferredThread:
        def __init__(self, *, target, **kwargs):
            refresh_targets.append(target)

        @staticmethod
        def start() -> None:
            return None

    monkeypatch.setattr(source, "V2_DATASET_FALLBACK_PATH", fallback_path)
    monkeypatch.setattr(source, "_fetch_snapshot", fake_fetch)
    monkeypatch.setattr(source.threading, "Thread", DeferredThread)

    first = source.load_v2_snapshot()
    second = source.load_v2_snapshot()

    assert first is second
    assert fetch_calls == []
    assert len(refresh_targets) == 1
    source.clear_v2_source_cache()


def test_load_v2_snapshot_force_refreshes(monkeypatch) -> None:
    source.clear_v2_source_cache()
    calls = []

    def fake_fetch():
        calls.append(True)
        return source.parse_v2_dataset_csv(
            _dataset(_row(main_constant=str(10.0 + len(calls))))
        )

    monkeypatch.setattr(source, "_fetch_snapshot", fake_fetch)

    first = source.load_v2_snapshot(force_refresh=True)
    second = source.load_v2_snapshot(force_refresh=True)

    assert first is not second
    assert first.revision != second.revision
    assert len(calls) == 2
    source.clear_v2_source_cache()


def test_fetch_snapshot_updates_local_dataset(monkeypatch, tmp_path) -> None:
    content = _dataset(_row())
    fallback_path = tmp_path / "constants_id_v2.csv"

    class Response:
        text = content

        @staticmethod
        def raise_for_status() -> None:
            return None

    monkeypatch.setattr(source.requests, "get", lambda *args, **kwargs: Response())
    monkeypatch.setattr(source, "V2_DATASET_FALLBACK_PATH", fallback_path)

    snapshot = source._fetch_snapshot()

    assert set(snapshot.song_map) == {(1, 4)}
    assert fallback_path.read_text(encoding="utf-8") == content


def test_load_v2_snapshot_falls_back_to_local_dataset(monkeypatch, tmp_path) -> None:
    fallback_path = tmp_path / "constants_id_v2.csv"
    fallback_path.write_text(_dataset(_row()), encoding="utf-8")
    source.clear_v2_source_cache()
    monkeypatch.setattr(source, "V2_DATASET_FALLBACK_PATH", fallback_path)

    monkeypatch.setattr(source, "_start_background_refresh_locked", lambda now: None)
    snapshot = source.load_v2_snapshot()

    assert set(snapshot.song_map) == {(1, 4)}
    source.clear_v2_source_cache()


def test_load_v2_snapshot_recovers_after_fallback(monkeypatch, tmp_path) -> None:
    fallback_path = tmp_path / "constants_id_v2.csv"
    fallback_path.write_text(_dataset(_row(main_constant="10.2")), encoding="utf-8")
    source.clear_v2_source_cache()
    calls = []

    def recovering_fetch():
        calls.append(True)
        if len(calls) == 1:
            raise source.V2DataSourceError("remote unavailable")
        return source.parse_v2_dataset_csv(
            _dataset(_row(main_constant="11.2"))
        )

    monkeypatch.setattr(source, "V2_DATASET_FALLBACK_PATH", fallback_path)
    monkeypatch.setattr(source, "_fetch_snapshot", recovering_fetch)
    monkeypatch.setattr(source, "_start_background_refresh_locked", lambda now: None)
    fallback = source.load_v2_snapshot()
    source._run_background_refresh()
    source._run_background_refresh()
    recovered = source.load_v2_snapshot()

    assert recovered is not fallback
    assert recovered.song_map[(1, 4)].main_constant == pytest.approx(11.2)
    assert len(calls) == 2
    source.clear_v2_source_cache()


def test_load_v2_snapshot_keeps_stale_memory_cache(monkeypatch) -> None:
    source.clear_v2_source_cache()
    calls = []

    def fetch_once():
        calls.append(True)
        if len(calls) > 1:
            raise source.V2DataSourceError("remote unavailable")
        return source.parse_v2_dataset_csv(_dataset(_row()))

    monkeypatch.setattr(source, "_fetch_snapshot", fetch_once)
    monkeypatch.setattr(source, "V2_SOURCE_CACHE_TTL_SECONDS", -1.0)
    first = source.load_v2_snapshot(force_refresh=True)
    source._run_background_refresh()
    second = source.load_v2_snapshot()

    assert second is first
    assert len(calls) == 2
    source.clear_v2_source_cache()
