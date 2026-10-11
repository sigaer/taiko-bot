from dataclasses import replace
import json

import httpx
import pytest

from taiko_bot import userdata_provider as provider
from taiko_bot import private_read_client as client
from taiko_bot.private_read_cache import PrivateReadCache, private_cache_key
from taiko_bot.viewer_client import ViewerClientError
from test_viewer_access import _make_settings
REAL_HTTPX_CLIENT = httpx.Client


def tag(kind="current", value="a"):
    return '"taiko-' + kind + '-v1-' + value * 64 + '"'


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(provider, "_PRIVATE_READ_CACHE", PrivateReadCache())
    return _make_settings(tmp_path, viewer_developer_token="synthetic-private-token")


def transport(monkeypatch, callback):
    calls = []
    def handler(request):
        calls.append(request)
        return callback(request)
    class OfflineClient(REAL_HTTPX_CLIENT):
        def send(self, request, **kwargs):
            # The validator blocks Client.send globally. Only this explicitly
            # owned in-memory transport may bypass it; no socket path exists.
            assert isinstance(self._transport, httpx.MockTransport)
            return self._send_single_request(request)
    monkeypatch.setattr(client.httpx, "Client", lambda **kwargs: OfflineClient(transport=httpx.MockTransport(handler), **kwargs))
    return calls


def test_fresh_200_then_304_each_performs_authorized_http_and_returns_owned_objects(cfg, monkeypatch):
    payload = {"songs": [{"song_no": 7}], "unknown": {"nested": [1]}}
    calls = transport(monkeypatch, lambda request: httpx.Response(304, headers={"etag": tag()}) if request.headers.get("if-none-match") == tag() else httpx.Response(200, json=payload, headers={"etag": tag()}))
    first = provider.ensure_userdata_available("1001", settings=cfg)
    first["unknown"]["nested"].append(2)
    second = provider.get_cached_userdata("1001", settings=cfg)
    assert second == payload and len(calls) == 2
    assert calls[0].headers["authorization"] == "Bearer synthetic-private-token"
    assert calls[1].headers["if-none-match"] == tag()
    assert not cfg.userdata_dir.exists()


@pytest.mark.parametrize("status", [401, 403, 404, 429, 500, 503])
def test_any_center_error_discards_cache_and_never_uses_disk_or_old_payload(cfg, monkeypatch, status):
    state = {"status": 200}
    transport(monkeypatch, lambda request: httpx.Response(state["status"], json={"songs": [], "private": "old"}, headers={"etag": tag()}))
    assert provider.ensure_userdata_available("1001", settings=cfg)["private"] == "old"
    state["status"] = status
    with pytest.raises(provider.UserdataProviderError) as error:
        provider.ensure_userdata_available("1001", settings=cfg)
    assert error.value.status_code == status
    assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0


def test_network_failure_cannot_return_cached_bytes_or_private_diagnostics(cfg, monkeypatch):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": []}, headers={"etag": tag()}))
    provider.ensure_userdata_available("1001", settings=cfg)
    monkeypatch.setattr(client.httpx, "Client", lambda **kwargs: (_ for _ in ()).throw(RuntimeError("/private/password/token")))
    with pytest.raises(provider.UserdataProviderError) as error:
        provider.get_cached_userdata("1001", settings=cfg)
    assert error.value.status_code == 502 and "password" not in str(error.value)
    assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0


def test_missing_token_and_url_fail_before_network_even_after_cache(cfg, monkeypatch):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": []}, headers={"etag": tag()}))
    provider.ensure_userdata_available("1001", settings=cfg)
    for changed in [replace(cfg, viewer_developer_token=""), replace(cfg, viewer_base_url="")]:
        with pytest.raises(provider.UserdataProviderError):
            provider.ensure_userdata_available("1001", settings=changed)
    assert len(calls) == 1


def test_cache_identity_separates_url_token_source_and_kind(cfg):
    key = private_cache_key("current", "1001", cfg)
    assert len({key, private_cache_key("history", "1001", cfg), private_cache_key("current", "1002", cfg), private_cache_key("current", "1001", replace(cfg, viewer_developer_token="another")), private_cache_key("current", "1001", replace(cfg, viewer_base_url="https://different.test"))}) == 5
    assert cfg.viewer_developer_token not in repr(key)


def test_expiry_force_refresh_and_remote_change_always_get_fresh_result(cfg, monkeypatch):
    clock = [10]
    monkeypatch.setattr(provider, "_PRIVATE_READ_CACHE", PrivateReadCache(now=lambda: clock[0]))
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "counter": len(request.headers)}, headers={"etag": tag()}))
    provider.ensure_userdata_available("1001", settings=cfg)
    clock[0] = 41
    provider.ensure_userdata_available("1001", settings=cfg)
    provider.ensure_userdata_available("1001", force_refresh=True, settings=cfg)
    assert all("if-none-match" not in request.headers for request in calls)
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "changed": 1}, headers={"etag": tag(value="b")}))
    assert provider.ensure_userdata_available("1001", settings=cfg)["changed"] == 1
    assert calls[0].headers["if-none-match"] == tag()


@pytest.mark.parametrize("header", [None, tag(value="b"), "W/" + tag(), "*"])
def test_invalid_304_cannot_claim_cached_success(cfg, monkeypatch, header):
    transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": []}, headers={"etag": tag()}))
    provider.ensure_userdata_available("1001", settings=cfg)
    transport(monkeypatch, lambda request: httpx.Response(304, headers={"etag": header} if header else {}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)
    assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0


def test_304_without_any_candidate_and_post_payload_cannot_create_authority(cfg, monkeypatch):
    provider.update_userdata_cache_from_payload("1001", {"songs": [], "secret": 7}, settings=cfg)
    assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0
    transport(monkeypatch, lambda request: httpx.Response(304, headers={"etag": tag()}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)
    assert not cfg.userdata_dir.exists()


def test_legacy_sdk_history_remains_compatible_but_private_loader_requires_ordering_metadata(cfg, monkeypatch):
    from taiko_bot.viewer_client import normalize_userdata_history
    payload = {"snapshots": [{"capturedAt": " data_0000.json ", "payload": {"unknown": [1]}}, {"capturedAt": "", "payload": {}}, None]}
    assert normalize_userdata_history(payload) == [{"capturedAt": "data_0000.json", "payload": {"unknown": [1]}}]
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=payload))
    for _ in range(2):
        with pytest.raises(provider.UserdataProviderError) as error:
            provider.ensure_userdata_history_available("1001", settings=cfg)
        assert error.value.status_code == 503
    assert len(calls) == 2 and provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0


@pytest.mark.parametrize("response", [b"[1]", b"{", b'"hello"'])
def test_invalid_json_and_nonobject_fail_closed(cfg, monkeypatch, response):
    transport(monkeypatch, lambda request: httpx.Response(200, content=response))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)


def test_response_byte_and_runtime_bounds(cfg, monkeypatch):
    monkeypatch.setattr(client, "MAX_RESPONSE_BYTES", 5)
    transport(monkeypatch, lambda request: httpx.Response(200, content=b'{"songs":[]}'))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)
    monkeypatch.setattr(client, "MAX_RESPONSE_BYTES", 1000)
    clock = [0]
    monkeypatch.setattr(client.time, "monotonic", lambda: clock[0])
    def slow(request):
        clock[0] = 91
        return httpx.Response(200, json={"songs": []})
    transport(monkeypatch, slow)
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)


@pytest.mark.parametrize("source", ["../other", "x" * 129, "a/b", ""])
def test_unsafe_source_fails_before_http(cfg, monkeypatch, source):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available(source, settings=cfg)
    assert not calls


def test_count_byte_lru_and_single_entry_budgets_and_ttl():
    clock = [0]
    cache = PrivateReadCache(max_entries=2, max_bytes=30, max_entry_bytes=20, ttl_seconds=30, now=lambda: clock[0])
    cache.put("a", tag(), {"x": "a"})
    cache.put("b", tag(), {"x": "b"})
    held = cache.get("a")
    cache.put("c", tag(), {"x": "c"})
    assert cache.get("b") is None and held.payload() == {"x": "a"}
    cache.put("big", tag(), {"x": "z" * 100})
    assert cache.get("big") is None
    cache.put("d", tag(), {"x": "d" * 10})
    assert cache.diagnostics()["bytes"] <= 30 and cache.diagnostics()["entries"] <= 2
    clock[0] = 31
    assert cache.get("d") is None
    assert cache.diagnostics()["evictions"] > 0


def test_current_history_pair_has_one_fresh_verified_view(cfg, monkeypatch):
    view = "v1-" + "a" * 32 + "-1"
    def answer(request):
        kind = "history" if request.url.path.endswith("/history") else "current"
        body = {"historyFormat": "raw-v1", "snapshots": [{"capturedAt": "data_0000.json", "fileName": "data_0000.json", "fileMtime": 1737000000.125, "payload": {"unknown": 1}}]} if kind == "history" else {"songs": [], "unknown": 2}
        return httpx.Response(200, json=body, headers={"etag": tag(kind), "x-taiko-source-view": view})
    calls = transport(monkeypatch, answer)
    result = provider.ensure_userdata_view_available("1001", settings=cfg)
    assert result == {"userdata": {"songs": [], "unknown": 2}, "snapshots": [{"capturedAt": "data_0000.json", "fileName": "data_0000.json", "fileMtime": 1737000000.125, "historyFormat": "raw-v1", "payload": {"unknown": 1}}], "sourceView": view}
    assert len(calls) == 2


def test_same_current_bytes_with_new_history_view_on_304_use_fresh_view_metadata(cfg, monkeypatch):
    state = {"view": "v1-" + "a" * 32 + "-1"}
    def answer(request):
        kind = "history" if request.url.path.endswith("/history") else "current"
        headers = {"etag": tag(kind), "x-taiko-source-view": state["view"]}
        if request.headers.get("if-none-match"):
            return httpx.Response(304, headers=headers)
        return httpx.Response(200, json={"songs": []} if kind == "current" else {"snapshots": []}, headers=headers)
    calls = transport(monkeypatch, answer)
    provider.ensure_userdata_view_available("1001", settings=cfg)
    state["view"] = "v1-" + "b" * 32 + "-2"
    assert provider.ensure_userdata_view_available("1001", settings=cfg)["sourceView"] == state["view"]
    assert len(calls) == 4 and calls[2].headers["if-none-match"] == tag()


def test_pair_retries_once_on_publication_change_and_never_accepts_mixed_views(cfg, monkeypatch):
    calls = []
    def answer(request):
        calls.append(request)
        kind = "history" if request.url.path.endswith("/history") else "current"
        view = "v1-" + ("a" if len(calls) == 1 else "b") * 32 + "-1"
        return httpx.Response(200, json={"songs": []} if kind == "current" else {"snapshots": []}, headers={"etag": tag(kind), "x-taiko-source-view": view})
    transport(monkeypatch, answer)
    assert provider.ensure_userdata_view_available("1001", settings=cfg)["sourceView"] == "v1-" + "b" * 32 + "-1"
    assert len(calls) == 4 and all("if-none-match" not in req.headers for req in calls[2:])


@pytest.mark.parametrize("view", [None, "v1-bad", "v1-" + "a" * 32 + "-9007199254740992"])
def test_missing_or_invalid_view_cannot_claim_current_history_consistency(cfg, monkeypatch, view):
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "snapshots": []}, headers={"x-taiko-source-view": view} if view else {}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_view_available("1001", settings=cfg)
    assert len(calls) == 2


def test_repeated_view_change_and_absolute_deadline_fail_closed(cfg, monkeypatch):
    views = iter(["a", "b", "c", "d"])
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": [], "snapshots": []}, headers={"x-taiko-source-view": "v1-" + next(views) * 32 + "-1"}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_view_available("1001", settings=cfg)
    assert len(calls) == 4
    with pytest.raises(ViewerClientError):
        client.fetch_private_read("current", "1001", settings=cfg, deadline=0)


@pytest.mark.parametrize("location", ["https://different.test/private", "https://viewer.example.com/next"])
def test_private_read_redirects_never_forward_credentials(cfg, monkeypatch, location):
    calls = transport(monkeypatch, lambda request: httpx.Response(302, headers={"location": location}))
    with pytest.raises(provider.UserdataProviderError):
        provider.ensure_userdata_available("1001", settings=cfg)
    assert len(calls) == 1
