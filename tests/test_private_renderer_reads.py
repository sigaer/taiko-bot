"""Execute actual implicit loaders with center replies and no personal disk IO."""
import ast
import importlib
from pathlib import Path
from typing import Any, Dict, List

import httpx
import pytest

from taiko_bot import userdata_provider as provider
from taiko_bot.viewer_client import ViewerClientError
from test_private_read_cache import cfg, transport


@pytest.mark.parametrize("module,name", [
    ("target_recommend", "_load_userdata_payload"),
    ("taikob_v2", "_load_userdata_payload"),
    ("draw_summary", "load_userdata"),
])
def test_native_current_loaders_return_full_center_payload_without_disk(cfg, monkeypatch, module, name):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    payload = {"songs": [{"song_no": 7}], "unknown": {"nested": [1]}}
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    loader = getattr(importlib.import_module("plugins.utils." + module), name)
    assert loader(1001) == payload and len(calls) == 1
    assert not cfg.userdata_dir.exists()


@pytest.mark.parametrize("module,name,args", [
    ("score_calculator", "compute_all_from_userdata", (1001,)),
    ("score_calculator", "build_all_stats_for_user", (1001,)),
    ("score_calculator", "getUtime", (1001,)),
    ("tcloud", "_load_user_play_counts", (1001,)),
    ("drawinfo", "get_score_by_id_and_level", (7, 1001, 4)),
    ("drawinfo", "generate_score_image", (7, 1001)),
    ("draw_dress", "build_dress_image", (1001,)),
    ("draw_dress", "render_my_don_image", (1001,)),
    ("draw_dress", "render_update_changes_image", (1001,)),
    ("b30_render", "render_b30_image", (1001,)),
])
def test_native_implicit_products_reject_revoked_access_before_private_disk_or_assets(cfg, monkeypatch, module, name, args):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    calls = transport(monkeypatch, lambda request: httpx.Response(403))
    function = getattr(importlib.import_module("plugins.utils." + module), name)
    with pytest.raises(provider.UserdataProviderError) as error:
        function(*args)
    assert error.value.status_code == 403 and len(calls) == 1
    assert not cfg.userdata_dir.exists()


def command_function(name, namespace):
    # Run the actual changed body without registering the untouched full Bot.
    file = Path(__file__).resolve().parents[1] / "plugins/taiko.py"
    node = next(node for node in ast.parse(file.read_text()).body if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(file), "exec"), namespace)
    return namespace[name]


def test_actual_command_song_loader_uses_center_and_rejects_invalid_rows(cfg, monkeypatch):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [{"song_no": 7}, None, 1]}))
    function = command_function("_load_user_song_records", {"List": List, "Dict": Dict, "Any": Any, "ensure_userdata_available": provider.ensure_userdata_available})
    assert function(1001) == [{"song_no": 7}]
    assert not cfg.userdata_dir.exists()


def test_actual_hiroba_command_helper_has_no_ttl_and_propagates_revocation():
    calls = []
    def status(source):
        calls.append(source)
        if len(calls) > 1:
            raise ViewerClientError("Denied", status_code=403)
        return True
    function = command_function("_has_center_hiroba_credentials_cached", {"has_center_hiroba_credentials": status})
    assert function("1001") is True
    with pytest.raises(ViewerClientError) as error:
        function("1001")
    assert error.value.status_code == 403 and calls == ["1001", "1001"]


def pair_transport(cfg, monkeypatch):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    current = {"songs": [{"song_no": 7, "level": 4, "high_score": 900000}], "profile": {"mydon_name": "fresh"}}
    raw = [{"fileName": "data_20250101_000000_000001.json", "capturedAt": "", "payload": {"profile": {}, "achievement": {}, "songs": [{"song_no": 7, "level": 4, "high_score": 800000}], "dojo": {"tag": "previous"}}},
           {"fileName": "data_20250102_000000_000001.json", "capturedAt": "", "payload": {"_meta": {"full": False}, "songs": current["songs"]}}]
    def answer(request):
        body = {"historyFormat": "raw-v1", "snapshots": raw} if request.url.path.endswith("/history") else current
        return httpx.Response(200, json=body, headers={"x-taiko-source-view": "v1-" + "a" * 32 + "-1"})
    return current, raw, transport(monkeypatch, answer)


def test_native_update_renderer_uses_one_pair_for_previous_scores_dojo_and_current_panel(cfg, monkeypatch):
    from PIL import Image
    from plugins.utils import draw_dress as renderer
    current, raw, calls = pair_transport(cfg, monkeypatch)
    observed = {}
    def collect(previous, latest, **kwargs):
        observed["previous"], observed["latest"] = previous, latest
        return [], []
    def panel(user, userdata, **kwargs):
        observed["userdata"] = userdata
        return Image.new("RGBA", (8, 8))
    monkeypatch.setattr(renderer, "_collect_change_sections", collect)
    monkeypatch.setattr(renderer, "_render_my_don_base_panel", panel)
    monkeypatch.setattr(renderer, "_render_change_column", lambda **kwargs: Image.new("RGBA", (8, 8)))
    image = renderer.render_update_changes_image(1001)
    assert image[:8] == b'\x89PNG\r\n\x1a\n'
    assert observed["userdata"] == current and observed["previous"][(7, 4)]["high_score"] == 800000
    assert observed["latest"][(7, 4)]["high_score"] == 900000 and len(calls) == 2
    assert not cfg.userdata_dir.exists()


def test_native_b30_preparation_replaces_unpaired_current_and_passes_same_history_to_diff(cfg, monkeypatch):
    from PIL import Image
    from plugins.utils import b30_render as renderer
    current, raw, calls = pair_transport(cfg, monkeypatch)
    observed = {}
    class ReachedDiff(Exception): pass
    monkeypatch.setattr(renderer.Image, "open", lambda path: Image.new("RGBA", (8, 8)))
    monkeypatch.setattr(renderer, "_load_json", lambda path: [])
    monkeypatch.setattr(renderer, "build_song_index", lambda rows: {})
    monkeypatch.setattr(renderer, "_load_rating_resources", lambda path: ({}, {}, []))
    monkeypatch.setattr(renderer, "_pick_top_entries", lambda entries, *args: entries)
    def calculate(entries):
        observed["entries"] = entries
        return []
    monkeypatch.setattr(renderer, "compute_all_from_userdata_records", calculate)
    monkeypatch.setattr(renderer, "aggregate_topN_value", lambda *args: 0)
    def diff(user, n, **kwargs):
        observed.update(kwargs)
        raise ReachedDiff()
    monkeypatch.setattr(renderer, "compute_b30_update_diff", diff)
    with pytest.raises(ReachedDiff):
        renderer.render_b30_image(1001, userdata={"songs": [{"private": "stale"}]})
    assert observed["entries"] == current["songs"] == observed["current_top_entries"]
    assert [row["payload"] for row in observed["history_snapshots"]] == [row["payload"] for row in raw]
    assert len(calls) == 2 and not cfg.userdata_dir.exists()


def test_native_current_dani_preparation_and_dojo_fallback_use_one_pair(cfg, monkeypatch):
    from taiko_bot.runtime.player.client.progress_support import dani_progress as renderer
    current, raw, calls = pair_transport(cfg, monkeypatch)
    observed = {}
    class ReachedDojo(Exception): pass
    monkeypatch.setattr(renderer, "_load_grade_index", lambda version: {"三段": {"grade": "三段"}})
    def best(entries):
        observed["entries"] = entries
        return {}
    monkeypatch.setattr(renderer, "_build_best_entry_map", best)
    monkeypatch.setattr(renderer, "_build_song_runtime", lambda *args: ([{}], {}))
    monkeypatch.setattr(renderer, "_footer_rows", lambda *args: [])
    monkeypatch.setattr(renderer, "_section_height", lambda *args, **kwargs: 8)
    monkeypatch.setattr(renderer, "get_dan_id_by_grade_name", lambda grade: 3)
    monkeypatch.setattr(renderer, "normalize_dojo_scores", lambda payload: payload)
    monkeypatch.setattr(renderer, "build_dojo_score_map", lambda payload: {3: payload} if payload else {})
    def dojo(grade, entry):
        observed["dojo"] = entry
        raise ReachedDojo()
    monkeypatch.setattr(renderer, "_build_dojo_runtime", dojo)
    with pytest.raises(ReachedDojo):
        renderer.render_dani_progress_image_bytes(1001, "三段", userdata=current, history_snapshots=provider._private_history({"historyFormat":"raw-v1", "snapshots":raw}))
    assert observed == {"entries": current["songs"], "dojo": {"tag": "previous"}}
    assert len(calls) == 0 and not cfg.userdata_dir.exists()


@pytest.mark.parametrize("module,name,args", [
    ("plugins.utils.userdata_storage", "save_userdata", ("1001", {"songs": []})),
    ("plugins.utils.hiroba.sync", "sync_hiroba_userdata", ("synthetic@example.test", "synthetic")),
    ("plugins.utils.hiroba.sync", "sync_multiple_hiroba_userdatas", ("synthetic@example.test", "synthetic")),
])
def test_obsolete_local_score_writers_fail_before_io(cfg, monkeypatch, module, name, args):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={}))
    with pytest.raises(ViewerClientError) as error:
        getattr(importlib.import_module(module), name)(*args)
    assert error.value.status_code == 410 and not calls and not cfg.userdata_dir.exists()
