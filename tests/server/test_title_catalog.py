import contextlib
import http.client
import importlib
import json
import os
import threading
from types import SimpleNamespace

import pytest
import requests

from taiko_bot.services import title_catalog as catalog
from taiko_bot.services import public_api, title_content


def title(uid, subtitle="？？？"):
    return {"uid": uid, "name": f"称号{uid}", "rarity": 2, "subtitle": subtitle,
            "subtitle_got": "已获得时的私有说明", "sort_no": uid, "unlock": True}


@pytest.fixture
def storage(tmp_path, monkeypatch):
    config = tmp_path / "config.json"
    config.write_text('{"cookie":"synthetic"}')
    cache = tmp_path / "titles.json"
    monkeypatch.setattr(catalog, "TITLE_API_CONFIG_PATH", config)
    monkeypatch.setattr(catalog, "TITLE_API_CACHE_PATH", cache)
    monkeypatch.setattr(catalog, "_next_refresh_attempt", 0)
    catalog.load_title_catalog_items.cache_clear()
    yield config, cache
    catalog.load_title_catalog_items.cache_clear()


def upstream(monkeypatch, pages):
    calls = []

    def post(url, *, headers, json, timeout):
        calls.append(json)
        page = pages[json["page"] - 1]
        if isinstance(page, Exception):
            raise page
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: page)

    monkeypatch.setattr(catalog.requests, "post", post)
    return calls


def test_fetch_all_pages_even_when_server_caps_page_size(storage, monkeypatch):
    config, _ = storage
    calls = upstream(monkeypatch, [
        {"data": {"list": [title(1)], "total": 3}},
        {"data": {"list": [title(2)], "total": 3}},
        {"data": {"list": [title(3)], "total": 3}},
    ])
    assert [row["uid"] for row in catalog.fetch_title_catalog_items(config_path=config)] == [1, 2, 3]
    assert [call["page"] for call in calls] == [1, 2, 3]
    assert all(call["unlock"] == 0 for call in calls)


def test_missing_total_continues_until_empty_page(storage, monkeypatch):
    config, _ = storage
    upstream(monkeypatch, [{"data": {"list": [title(1)]}}, {"data": {"list": []}}])
    assert len(catalog.fetch_title_catalog_items(config_path=config)) == 1


@pytest.mark.parametrize("second_page", [
    {"data": {"list": [], "total": 2}},
    {"data": {"list": [title(1)], "total": 2}},
    {"data": {"list": [title(2)], "total": 3}},
    {"statusCode": 401, "data": {"list": [title(2)], "total": 2}},
    requests.HTTPError(response=SimpleNamespace(status_code=401)),
])
def test_partial_or_failed_refresh_preserves_last_good(storage, monkeypatch, second_page):
    config, cache = storage
    catalog.write_title_catalog_cache([title(99)], cache_path=cache)
    original = cache.read_bytes()
    upstream(monkeypatch, [{"data": {"list": [title(1)], "total": 2}}, second_page])
    assert catalog.refresh_title_catalog_cache(config_path=config, cache_path=cache) == []
    assert cache.read_bytes() == original


def test_readers_reload_after_another_process_replaces_file(storage, monkeypatch):
    _, cache = storage
    catalog.write_title_catalog_cache([title(1)], cache_path=cache)
    derived_calls = []

    @catalog.title_catalog_cache
    def derived():
        derived_calls.append(True)
        return catalog.load_title_catalog_items()[0]["uid"]

    assert derived() == derived() == 1
    catalog.write_title_catalog_cache([title(2)], cache_path=cache)
    assert derived() == 2
    assert len(derived_calls) == 2


def test_failed_atomic_publication_keeps_previous_generation(storage, monkeypatch):
    config, cache = storage
    catalog.write_title_catalog_cache([title(1)], cache_path=cache)
    original = cache.read_bytes()
    upstream(monkeypatch, [{"data": {"list": [title(2)], "total": 1}}])

    def denied(*args):
        raise PermissionError("synthetic publication failure")

    monkeypatch.setattr(catalog.os, "replace", denied)
    assert catalog.refresh_title_catalog_cache(config_path=config, cache_path=cache) == []
    assert cache.read_bytes() == original
    assert not list(cache.parent.glob(".title-catalog-*"))


def test_failed_refresh_is_throttled_and_keeps_serving_cache(storage, monkeypatch):
    _, cache = storage
    catalog.write_title_catalog_cache([title(1)], cache_path=cache)
    os.utime(cache, (1, 1))
    calls = upstream(monkeypatch, [requests.HTTPError(response=SimpleNamespace(status_code=401))])
    assert catalog.load_title_catalog_items()[0]["uid"] == 1
    assert catalog.load_title_catalog_items()[0]["uid"] == 1
    assert len(calls) == 1


def test_public_catalog_only_exposes_official_conditions(storage, monkeypatch):
    monkeypatch.setattr(title_content, "load_title_catalog_items", lambda: (
        title(1), title(2, "用任意难度通关《测试曲》吧"), title(3, "? ? ?"), title(4, ""),
    ))
    payload = title_content.get_official_titles_content()
    assert payload["total"] == 4
    assert [row["condition"] for row in payload["titles"]] == ["", "用任意难度通关《测试曲》吧", "", ""]
    assert all(set(row) == {"id", "name", "rarity", "condition", "songIds"} for row in payload["titles"])
    assert all(row["songIds"] == [] for row in payload["titles"])


def test_bot_and_display_host_share_the_same_catalog_owner():
    from taiko_bot.runtime.player.center import title_catalog as bot
    from taiko_bot.runtime.player.center.display_host_support import title_catalog as host
    assert bot.load_title_catalog_items is host.load_title_catalog_items is catalog.load_title_catalog_items


@pytest.mark.parametrize("module_name", [
    "taiko_bot.runtime.player.center.song_title_showcase",
    "taiko_bot.runtime.player.center.display_host_support.song_title_showcase",
])
def test_actual_bot_title_relations_update_without_restart(storage, monkeypatch, module_name):
    _, cache = storage
    showcase = importlib.import_module(module_name)
    for function in ("_load_manual_hidden_relations", "_load_legacy_base_song_title_relations", "_load_legacy_all_perfect_relations"):
        monkeypatch.setattr(showcase, function, lambda: ())
    catalog.write_title_catalog_cache([title(1, "用任意难度通关《测试曲》吧")], cache_path=cache)
    assert [row.title_name for row in showcase.load_song_title_relations()] == ["称号1"]
    catalog.write_title_catalog_cache([title(2, "用任意难度通关《测试曲》吧")], cache_path=cache)
    assert [row.title_name for row in showcase.load_song_title_relations()] == ["称号2"]


def test_public_http_title_route_and_failure(storage, monkeypatch):
    _, cache = storage
    catalog.write_title_catalog_cache([title(1)], cache_path=cache)
    monkeypatch.setattr(public_api.SongDataHandler, "log_message", lambda *args: None)
    server = public_api.ThreadingHTTPServer(("127.0.0.1", 0), public_api.SongDataHandler)
    worker = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
    worker.start()
    try:
        for unavailable in (False, True):
            if unavailable:
                monkeypatch.setattr(title_content, "load_title_catalog_items", lambda: ())
            with contextlib.closing(http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)) as conn:
                conn.request("GET", "/api/titles")
                reply = conn.getresponse()
                payload = json.loads(reply.read())
                assert reply.status == (503 if unavailable else 200)
                assert reply.getheader("Cache-Control") == "no-store"
                if not unavailable:
                    assert payload["titles"][0]["condition"] == ""
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)
        assert not worker.is_alive()
