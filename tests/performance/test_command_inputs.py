"""Real publications and render branches over synthetic scores only."""
import ast
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from taiko_store import PublicationStore, PublicationError
from taiko_bot.runtime.player.center.update_comparison import capture_previous_userdata


def payload(count=0):
    return dict(profile={"userid": "111"}, achievement={}, dojo={}, songs=[
        dict(song_no=1, level=4, high_score=800000, full_combo_cnt=count,
             good_cnt=99, ok_cnt=1, ng_cnt=0)])


def publish(store, value):
    store.commit({"current": json.dumps(value).encode()})


def test_capture_complete_current_survives_write_without_history(tmp_path):
    store = PublicationStore(tmp_path, "111")
    with store.exclusive():
        assert capture_previous_userdata(store) is None
        publish(store, payload())
        previous = capture_previous_userdata(store)
        publish(store, payload(1))
        assert previous == payload() and store.reader().decoded() == payload(1)
        assert store.reader().history_names() == []
    with pytest.raises(PublicationError):
        capture_previous_userdata(store)


def test_corrupt_committed_current_is_not_treated_as_first_update(tmp_path):
    store = PublicationStore(tmp_path, "111")
    with store.exclusive():
        store.commit({"current": b"invalid-json"})
        with pytest.raises(PublicationError):
            capture_previous_userdata(store)


@pytest.mark.parametrize("engine", ["wahlap", "hiroba"])
@pytest.mark.parametrize("initial", [False, True])
@pytest.mark.parametrize("include_image", [False, True])
def test_native_update_captures_before_sync_and_renders_published_current(
        tmp_path, monkeypatch, engine, initial, include_image):
    from taiko_bot.runtime.player.center import native_wahlap_update as wahlap
    from taiko_bot.runtime.player.center.hiroba import native_binding as hiroba
    module = wahlap if engine == "wahlap" else hiroba
    row = SimpleNamespace(current=True, identity="111", source=engine)
    monkeypatch.setattr(module, "_read", lambda *a, **kw: ([row], False))
    if engine == "hiroba":
        monkeypatch.setattr(module, "_credentials", lambda *a, **kw: None)
    connection = SimpleNamespace(cursor=lambda: SimpleNamespace(
        execute=lambda *a: None, fetchone=lambda: (1,), close=lambda: None),
        commit=lambda: None, begin=lambda: None, rollback=lambda: None, close=lambda: None)
    if initial:
        with PublicationStore(tmp_path, "111").exclusive() as store:
            publish(store, payload())
    renders = []
    def sync(identity, *, publication_store, **kwargs):
        publish(publication_store, payload(1))
        return 0 if engine == "wahlap" else identity
    def render(identity, *, previous_userdata, score_view, show_all):
        assert identity == 111 and show_all
        assert previous_userdata == (payload() if initial else None)
        assert score_view.decoded() == payload(1)
        renders.append(True)
        return b"synthetic-image"
    function = wahlap.update_native_wahlap if engine == "wahlap" else hiroba.sync_native_hiroba
    result = function("onebot_v11:12345", "111", connection_factory=lambda: connection,
        userdata_root=tmp_path, sync=sync, render=render, include_image=include_image, show_all=True)
    assert result["ok"] and len(renders) == int(include_image)
    assert (result["image"] is not None) == include_image


def renderer_namespace():
    """Compile the actual diff renderer, avoiding unrelated public/SQL startup."""
    path = Path(__file__).resolve().parents[2]/"taiko_bot/runtime/player/center/draw_dress.py"
    names = {"render_update_changes_image", "_collect_change_sections", "_song_key",
        "_build_song_map", "_sorted_changed_entries", "_safe_int", "_to_int",
        "_difficulty_group", "_song_diff_sort_key", "_combined_low_miss_count"}
    tree = ast.parse(path.read_text())
    nodes = [ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)]
    nodes += [node for node in tree.body if getattr(node, "name", "") in names]
    from io import BytesIO
    sections = []
    def column(**kwargs):
        sections.append(copy.deepcopy(kwargs["sections"]))
        return Image.new("RGB", (1, 1), "white")
    def history(*a, **kw):
        pytest.fail("Live update renderer read history")
    ns = dict(BytesIO=BytesIO, Path=Path, FONT_PATH=None, TITLE_FONT_PATH=None,
        ICONS_DIR=Path("/synthetic/icons"), _PREVIOUS_FROM_HISTORY=object(),
        _load_previous_song_map=history, _load_previous_dojo_state=history,
        _load_song_display_map=lambda: {}, normalize_versioned_dojo_scores=lambda x: x,
        _collect_dojo_change_sections=lambda *a, **kw: ([], []),
        _render_my_don_base_panel=lambda *a, **kw: Image.new("RGB", (1, 1), "white"),
        _render_change_column=column, _compose_columns=lambda *a, **kw: Image.new("RGB", (1, 1), "white"))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])), str(path), "exec"), ns)
    return ns, sections


@pytest.mark.parametrize("show_all", [False, True])
def test_live_renderer_never_replays_history_and_keeps_item_limits(show_all):
    ns, sections = renderer_namespace()
    before, after = payload(), payload(1)
    before["songs"] = [dict(before["songs"][0], song_no=i) for i in range(1, 7)]
    after["songs"] = [dict(after["songs"][0], song_no=i) for i in range(1, 7)]
    result = ns["render_update_changes_image"](111, show_all=show_all,
        score_view=SimpleNamespace(decoded=lambda: after), previous_userdata=before)
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(sections[0][0]["items"]) == (6 if show_all else 5)


@pytest.mark.parametrize("previous", [None, payload(1)])
def test_first_and_unchanged_updates_have_no_fabricated_changes(previous):
    ns, sections = renderer_namespace()
    ns["render_update_changes_image"](111, score_view=SimpleNamespace(decoded=lambda: payload(1)),
        previous_userdata=previous)
    assert sections == [[], []]
