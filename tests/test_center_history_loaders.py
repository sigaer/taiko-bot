"""Actual loaders compared with a Git-frozen filesystem implementation.

All files and SQLite rows belong to the test. HTTP uses MockTransport only.
"""
import ast
import datetime
import importlib
import json
import os
from pathlib import Path
import subprocess

import httpx
import pytest

from taiko_bot import userdata_provider as provider
from taiko_bot.viewer_client import ViewerClientError, normalize_userdata_history
from test_private_read_cache import cfg, transport

SOURCE = Path(__file__).resolve().parents[1]
FROZEN = "adae96ea2976347386d85b416cba9e385710b43d"


def frozen_module(relative, names=None, **namespace):
    text = subprocess.check_output(["git", "show", FROZEN + ":" + relative], cwd=SOURCE, text=True)
    if names is None:
        exec(compile(text, "<frozen-" + relative + ">", "exec"), namespace)
    else:
        nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
        nodes += [node for node in ast.parse(text).body if isinstance(node, ast.FunctionDef) and node.name in names]
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), "<frozen-" + relative + ">", "exec"), namespace)
    return namespace


@pytest.fixture
def history(tmp_path):
    root = tmp_path / "oracle"
    directory = root / "1001"
    directory.mkdir(parents=True)
    song = {"song_no": 7, "level": 4, "high_score": 800000, "stage_cnt": 2}
    rows = [
        ("data_2024-12-01_00_00_00.json", {"_meta": {"full": False}, "songs": [song]}, 1737000000.125),
        ("data_2025-01-01_00_00_00_full.json", {"profile": {"name": "A"}, "achievement": {}, "songs": [song], "dojo": {"dan": 3}}, 1737000000.125),
        ("data_20250102_000000_000001_a.json", {"_meta": {"full": False, "ts": ""}, "songs": [{**song, "stage_cnt": 4}], "achievement": {"gold": 1}}, 1737000000.125),
        ("data_20250102_000000_000001_b.json", {"_meta": {"full": False, "ts": "not-a-date"}, "songs_removed": [[7, 4]], "profile": {"name": "B"}}, 1737000000.125),
        ("data_20250103_000000_000001_full.json", {"_meta": {"full": True}, "songs": [song], "profile": {}, "achievement": {}}, 1737000000.125),
        ("data_unknown.json", {"_meta": {"full": False}, "songs": [{**song, "song_no": "8", "level": "4"}], "unknown": [1]}, 1737000000.375),
        ("data_invalid.json", "{", 1737000000.375),
    ]
    raw = []
    for name, payload, stamp in rows:
        path = directory / name
        path.write_text(payload if isinstance(payload, str) else json.dumps(payload))
        os.utime(path, (stamp, stamp))
        if isinstance(payload, dict):
            raw.append({"fileName": name, "fileMtime": stamp, "fileCtime": path.stat().st_ctime,
                        "capturedAt": payload.get("_meta", {}).get("ts", name), "payload": payload})
    return root, directory, raw


def oracles(root):
    parser = frozen_module("plugins/utils/snapshot_history.py")
    common = dict(USERDATA_DIR=root, json=json, datetime=datetime,
                  list_snapshot_files=parser["list_snapshot_files"], parse_snapshot_time=parser["parse_snapshot_time"])
    from plugins.utils.dojo_score import normalize_dojo_scores, build_dojo_score_map
    trend = frozen_module("plugins/utils/score_calculator.py", {"load_user_snapshots", "_song_key", "_parse_center_snapshot_datetime"},
                          load_json=lambda p: json.loads(p.read_text()), **common)
    update = frozen_module("plugins/utils/draw_dress.py", {"_load_previous_song_map", "_load_previous_dojo_state", "_snapshot_is_full", "_song_key", "_build_song_map", "_normalize_removed_key"},
                           normalize_dojo_scores=normalize_dojo_scores, **common)
    dani = frozen_module("plugins/utils/dani_progress.py", {"_load_history_dojo_payload_for_dan"},
                         normalize_dojo_scores=normalize_dojo_scores, build_dojo_score_map=build_dojo_score_map, **common)
    return trend, update, dani


def answer_history(monkeypatch, cfg, raw):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    return transport(monkeypatch, lambda request: httpx.Response(200, json={"historyFormat": "raw-v1", "snapshots": raw}))


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 5, 6, 7])
def test_native_trend_and_previous_loaders_match_frozen_disk_order_and_delta_profiles(history, cfg, monkeypatch, count):
    root, directory, raw = history
    files = list(directory.iterdir())
    keep = {path.name for path in files[:count]}
    for path in files[count:]:
        path.unlink()
    raw = [row for row in raw if row["fileName"] in keep]
    trend, update, dani = oracles(root)
    expected_trend = trend["load_user_snapshots"](1001)
    expected_songs = update["_load_previous_song_map"](1001)
    expected_dojo = update["_load_previous_dojo_state"](1001)
    calls = answer_history(monkeypatch, cfg, raw)
    current_trend = importlib.import_module("taiko_bot.runtime.player.client.trend_support.score_calculator")
    current_update = importlib.import_module("plugins.utils.draw_dress")
    assert list(current_trend.iter_user_snapshots(1001, provider.ensure_userdata_history_available("1001", settings=cfg))) == expected_trend
    assert current_update._load_previous_song_map(1001) == expected_songs
    assert current_update._load_previous_dojo_state(1001) == expected_dojo
    assert len(calls) == 3 and all(request.url.params.get("format") == "raw-v1" for request in calls)
    assert not cfg.userdata_dir.exists()


def test_dani_preserves_reverse_filename_order_instead_of_trend_time(history, cfg, monkeypatch):
    root, directory, raw = history
    from taiko_bot.runtime.player.client.progress_support import dani_progress
    # Dojo normalization is unchanged; isolate selection with a real 2025 dan.
    for row, name, stamp in [(raw[1], "data_z.json", 1), (raw[2], "data_a.json", 2)]:
        row["fileName"], row["fileMtime"] = name, stamp
        row["payload"] = {"dojo": {"tag": name}}
        path = directory / name
        path.write_text(json.dumps(row["payload"]))
        os.utime(path, (stamp, stamp))
    raw = [raw[1], raw[2]]
    normalize = lambda payload: payload
    map_dojo = lambda payload: {3: payload} if "tag" in payload else {}
    old = frozen_module("plugins/utils/dani_progress.py", {"_load_history_dojo_payload_for_dan"},
                        USERDATA_DIR=root, json=json, normalize_dojo_scores=normalize, build_dojo_score_map=map_dojo)
    monkeypatch.setattr(dani_progress, "normalize_dojo_scores", normalize)
    monkeypatch.setattr(dani_progress, "build_dojo_score_map", map_dojo)
    calls = answer_history(monkeypatch, cfg, raw)
    assert dani_progress._load_history_dojo_payload_for_dan(1001, 3, provider._private_history({"historyFormat":"raw-v1", "snapshots":raw})) == old["_load_history_dojo_payload_for_dan"](1001, 3) == {"tag": "data_z.json"}
    assert len(calls) == 0


@pytest.mark.parametrize("change", ["missing-name", "unsafe-name", "bad-mtime", "bad-payload"])
def test_invalid_raw_metadata_cannot_enter_history_cache(cfg, monkeypatch, change):
    row = {"fileName": "data_unknown.json", "fileMtime": 1, "payload": {}}
    if change == "missing-name": row.pop("fileName")
    if change == "unsafe-name": row["fileName"] = "data_../other.json"
    if change == "bad-mtime": row["fileMtime"] = "1"
    if change == "bad-payload": row["payload"] = []
    answer_history(monkeypatch, cfg, [row])
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_history_available("1001", settings=cfg)
    assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0


def test_blank_meta_timestamp_keeps_filename_microseconds_and_unknown_mtime(cfg, monkeypatch):
    raw = [{"fileName": "data_20250101_000000_000001.json", "capturedAt": "", "payload": {"profile": {}, "achievement": {}, "songs": []}},
           {"fileName": "data_unknown.json", "fileMtime": 1735689600.375, "capturedAt": "wrong", "payload": {"_meta": {"full": False}, "songs": []}}]
    calls = answer_history(monkeypatch, cfg, raw)
    from taiko_bot.runtime.player.client.trend_support.score_calculator import iter_user_snapshots
    points = list(iter_user_snapshots(1001, provider.ensure_userdata_history_available("1001", settings=cfg)))
    assert [point[0] for point in points] == [datetime.datetime(2025, 1, 1, microsecond=1), datetime.datetime.fromtimestamp(1735689600.375)]
    assert len(calls) == 1


def test_explicit_legacy_history_still_uses_captured_at_profile():
    from taiko_bot.runtime.player.client.trend_support.score_calculator import iter_user_snapshots
    payload = {"songs": [], "unknown": 1}
    assert list(iter_user_snapshots(1001, [{"capturedAt": "2025-01-02 00:00:00", "payload": payload}, {"capturedAt": "invalid", "payload": {}}])) == [(datetime.datetime(2025, 1, 2), payload)]


@pytest.mark.parametrize("name", ["build_daily_rating_points", "build_playcount_rating_points"])
def test_streamed_trend_aggregation_matches_frozen_flow_with_decreasing_and_equal_counts(history, cfg, monkeypatch, name):
    root, directory, raw = history
    from taiko_bot.runtime.player.client.trend_support import score_calculator as current
    trend, update, dani = oracles(root)
    # Domain calculations have separate Core Goldens. Here deterministic,
    # nonempty values isolate history aggregation, day selection and count gaps.
    monkeypatch.setattr(current, "load_rating_config", lambda path: {"const_table": {"const_to_score": {}}})
    monkeypatch.setattr(current, "build_const_table", lambda table: [])
    monkeypatch.setattr(current, "_compute_results_from_userdata_records", lambda records, cfg, table: [{"AI_rating": float(row["stage_cnt"])} for row in records])
    monkeypatch.setattr(current, "compute_dim_topN_means", lambda results, n: {"精度力": sum(row["AI_rating"] for row in results)})
    monkeypatch.setattr(current, "aggregate_topN_value", lambda results, column, n: sum(row[column] for row in results))
    namespace = dict(vars(current))
    namespace["load_user_snapshots"] = trend["load_user_snapshots"]
    old = frozen_module("plugins/utils/score_calculator.py", {name}, **namespace)[name]
    expected = old(1001)
    assert expected
    calls = answer_history(monkeypatch, cfg, raw)
    assert getattr(current, name)(1001, history_snapshots=provider.ensure_userdata_history_available("1001", settings=cfg)) == expected and len(calls) == 1
