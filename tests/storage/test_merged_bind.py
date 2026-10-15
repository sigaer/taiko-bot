from __future__ import annotations

import json
import os
from pathlib import Path

from taiko_bot.offline import merged_bind
from taiko_store import merge_reference
from taiko_store import PublicationStore


def _adopt(root, identities):
    for identity in identities:
        store = PublicationStore(root, identity)
        with store.exclusive():
            store._adopt()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_materialize_merged_bind_userdata_merges_scores_and_history(tmp_path, monkeypatch):
    userdata_dir = tmp_path / "userdata"
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text(
        json.dumps(
            [
                {"id": 100, "max_combo": [0, 0, 0, 100, 0]},
                {"id": 200, "max_combo": [0, 0, 0, 100, 0]},
                {"id": 300, "max_combo": [0, 0, 0, 100, 0]},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(merged_bind, "USERDATA_DIR", userdata_dir)
    monkeypatch.setattr(merge_reference, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(merge_reference, "_SONG_COMBO_MAP_CACHE", None)

    payload_a = {
        "profile": {"mydon_name": "A", "gameCostume": {"title": "Alpha"}},
        "songs": [
            {
                "song_no": 100,
                "level": 4,
                "high_score": 980000,
                "good_cnt": 98,
                "ok_cnt": 2,
                "full_combo_cnt": 1,
                "dondaful_combo_cnt": 0,
                "stage_cnt": 3,
                "best_score_rank": 7,
                "update_datetime": "2026-05-25 10:00:00",
            },
            {
                "song_no": 200,
                "level": 4,
                "high_score": 900000,
                "good_cnt": 95,
                "ok_cnt": 5,
                "full_combo_cnt": 0,
                "dondaful_combo_cnt": 0,
                "stage_cnt": 2,
                "best_score_rank": 5,
                "update_datetime": "2026-05-25 11:00:00",
            },
        ],
        "achievement": {},
        "dojo": {"source": "a"},
    }
    payload_b = {
        "profile": {"mydon_name": "B", "gameCostume": {"title": "Beta"}},
        "songs": [
            {
                "song_no": 100,
                "level": 4,
                "high_score": 970000,
                "good_cnt": 90,
                "ok_cnt": 10,
                "full_combo_cnt": 1,
                "dondaful_combo_cnt": 1,
                "stage_cnt": 5,
                "best_score_rank": 8,
                "update_datetime": "2026-05-25 12:00:00",
            },
            {
                "song_no": 200,
                "level": 4,
                "high_score": 910000,
                "good_cnt": 95,
                "ok_cnt": 5,
                "full_combo_cnt": 1,
                "dondaful_combo_cnt": 0,
                "stage_cnt": 7,
                "best_score_rank": 6,
                "update_datetime": "2026-05-25 12:30:00",
            },
            {
                "song_no": 300,
                "level": 4,
                "high_score": 930000,
                "good_cnt": 93,
                "ok_cnt": 7,
                "full_combo_cnt": 0,
                "dondaful_combo_cnt": 0,
                "stage_cnt": 4,
                "best_score_rank": 6,
                "update_datetime": "2026-05-25 13:00:00",
            },
        ],
        "achievement": {},
        "dojo": {"source": "b"},
    }
    _write_json(userdata_dir / "111data.json", payload_a)
    _write_json(userdata_dir / "222data.json", payload_b)
    _write_json(
        userdata_dir / "111" / "data_20260524_100000_000000_test.json",
        {"_meta": {"full": True}, **payload_a},
    )
    _write_json(
        userdata_dir / "222" / "data_20260524_120000_000000_test.json",
        {"_meta": {"full": True}, **payload_b},
    )

    _adopt(userdata_dir, ["111", "222"])
    entry = {"ids": ["111", "222"], "current_index": 0, "current_slot": 0}
    result = merged_bind.materialize_merged_bind_userdata(
        "onebot_v11:12345", entry, userdata_dir=userdata_dir
    )

    merged_payload = json.loads(result.current_path.read_text(encoding="utf-8"))
    songs = {
        (int(song["song_no"]), int(song["level"])): song
        for song in merged_payload["songs"]
    }
    assert result.virtual_user_id == "u0_onebot_v11_12345"
    assert merged_payload["profile"]["mydon_name"] == "A"
    assert songs[(100, 4)]["dondaful_combo_cnt"] == 1
    assert songs[(100, 4)]["stage_cnt"] == 8
    assert songs[(200, 4)]["full_combo_cnt"] == 1
    assert songs[(200, 4)]["stage_cnt"] == 9
    assert songs[(300, 4)]["high_score"] == 930000
    assert merged_payload["achievement"]["ary_crown_count"] == [2, 2, 1]
    assert len(list(result.history_dir.glob("data_*.json"))) >= 2


def test_materialize_merged_bind_userdata_reports_missing_source(tmp_path, monkeypatch):
    userdata_dir = tmp_path / "userdata"
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(merged_bind, "USERDATA_DIR", userdata_dir)
    monkeypatch.setattr(merge_reference, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(merge_reference, "_SONG_COMBO_MAP_CACHE", None)

    _write_json(
        userdata_dir / "111data.json",
        {"profile": {}, "songs": [], "achievement": {}, "dojo": {}},
    )

    _adopt(userdata_dir, ["111", "222"])
    entry = {"ids": ["111", "222"], "current_index": 0, "current_slot": 0}
    try:
        merged_bind.materialize_merged_bind_userdata(
            "onebot_v11:12345", entry, userdata_dir=userdata_dir
        )
    except merged_bind.MergedBindMissingUserdataError as error:
        assert "u2:222" in str(error)
    else:
        raise AssertionError("expected MergedBindMissingUserdataError")


def test_reconstruct_full_snapshots_keeps_state_for_explicit_delta(tmp_path):
    history_dir = tmp_path / "history"
    base_song = {"song_no": 100, "level": 4, "high_score": 800_000}
    changed_song = {"song_no": 200, "level": 4, "high_score": 900_000}
    _write_json(
        history_dir / "data_20260901_120000_000000.json",
        {
            "_meta": {"full": True},
            "profile": {"mydon_name": "player"},
            "achievement": {},
            "dojo": {},
            "songs": [base_song],
        },
    )
    _write_json(
        history_dir / "data_20260902_120000_000000.json",
        {
            "_meta": {"full": False},
            "profile": {"mydon_name": "player"},
            "achievement": {},
            "dojo": {},
            "songs": [changed_song],
        },
    )

    snapshots = merged_bind._reconstruct_full_snapshots(history_dir)

    assert len(snapshots) == 2
    assert {
        (song["song_no"], song["level"])
        for song in snapshots[-1][1]["songs"]
    } == {(100, 4), (200, 4)}


def test_materialize_merged_bind_userdata_appends_only_changed_point(
    tmp_path, monkeypatch
):
    userdata_dir = tmp_path / "userdata"
    song_data_path = tmp_path / "song_data.json"
    song_data_path.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(merge_reference, "SONG_DATA_PATH", song_data_path)
    monkeypatch.setattr(merge_reference, "_SONG_COMBO_MAP_CACHE", None)

    def payload(name: str, score: int, stages: int) -> dict:
        return {
            "profile": {"mydon_name": name},
            "songs": [
                {
                    "song_no": 100,
                    "level": 4,
                    "high_score": score,
                    "good_cnt": score,
                    "ok_cnt": 0,
                    "ng_cnt": 0,
                    "stage_cnt": stages,
                    "best_score_rank": 6,
                    "update_datetime": "2026-09-02 20:00:00",
                }
            ],
            "achievement": {},
            "dojo": {},
        }

    payload_a = payload("A", 900_000, 2)
    payload_b = payload("B", 800_000, 3)
    _write_json(userdata_dir / "111data.json", payload_a)
    _write_json(userdata_dir / "222data.json", payload_b)
    _write_json(
        userdata_dir / "111" / "data_20260902_200000_000000_test.json",
        {"_meta": {"full": True}, **payload_a},
    )
    _write_json(
        userdata_dir / "222" / "data_20260902_200000_000000_test.json",
        {"_meta": {"full": True}, **payload_b},
    )

    _adopt(userdata_dir, ["111", "222"])
    entry = {"ids": ["111", "222"], "current_index": 0, "current_slot": 0}
    first = merged_bind.materialize_merged_bind_userdata(
        "onebot_v11:incremental", entry, userdata_dir=userdata_dir
    )
    old_snapshots = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in first.history_dir.glob("data_*.json")
    }

    updated_a = payload("A", 950_000, 4)
    _write_json(userdata_dir / "111data.json", updated_a)
    updated_ns = max(
        (userdata_dir / "111data.json").stat().st_mtime_ns,
        (userdata_dir / "222data.json").stat().st_mtime_ns,
    ) + 2_000_000_000
    store = PublicationStore(userdata_dir, "111")
    with store.exclusive():
        ref = store.stage(json.dumps(updated_a, ensure_ascii=False, indent=2).encode())
        store.publish({"current": ref}, filesystem_times={"fileMtimes": {"current": updated_ns / 1_000_000_000}})

    def fail_full_rebuild(*args, **kwargs):
        raise AssertionError("incremental refresh must not rebuild source histories")

    monkeypatch.setattr(merged_bind, "_merge_snapshot_histories", fail_full_rebuild)
    second = merged_bind.materialize_merged_bind_userdata(
        "onebot_v11:incremental", entry, userdata_dir=userdata_dir
    )

    new_snapshots = list(second.history_dir.glob("data_*.json"))
    assert len(new_snapshots) == len(old_snapshots) + 1
    for path in new_snapshots:
        if path.name in old_snapshots:
            old_bytes, old_mtime_ns = old_snapshots[path.name]
            assert path.read_bytes() == old_bytes
            assert path.stat().st_mtime_ns == old_mtime_ns

    merged_payload = json.loads(second.current_path.read_text(encoding="utf-8"))
    assert merged_payload["songs"][0]["high_score"] == 950_000
    assert merged_payload["songs"][0]["stage_cnt"] == 7

    snapshot_names = {path.name for path in new_snapshots}
    third = merged_bind.materialize_merged_bind_userdata(
        "onebot_v11:incremental", entry, userdata_dir=userdata_dir
    )
    assert {path.name for path in third.history_dir.glob("data_*.json")} == snapshot_names
