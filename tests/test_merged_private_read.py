import base64
from typing import Any, Dict, List
import httpx
import pytest

from taiko_bot.merged_source_id import build_center_virtual_user_id
from taiko_bot import userdata_provider as provider
from taiko_bot.private_read_client import valid_source_view
from test_private_read_cache import cfg, transport, tag
from test_private_renderer_reads import command_function


@pytest.mark.parametrize("principal", ["12345", "onebot_v11:12345", "qq_official:_abc-XYZ_", "qq_official:" + "a" * 128])
def test_virtual_identity_is_lossless_and_center_read_has_no_disk_materialization(cfg, monkeypatch, principal):
    identity = build_center_virtual_user_id(principal)
    assert base64.urlsafe_b64decode(identity[5:] + "=" * (-len(identity[5:]) % 4)).decode() == principal
    view = "merged-v1-" + "a" * 64
    payload = {"profile": {"mydon_name": "Merged"}, "songs": [], "unknown": 1}
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json=payload, headers={"etag": tag(), "x-taiko-source-view": view}))
    assert provider.ensure_userdata_available(identity, settings=cfg) == payload
    assert str(calls[0].url).endswith("/api/developer/userdata/" + identity)
    assert not cfg.userdata_dir.exists() and valid_source_view(view)


def test_u0_command_resolves_to_center_and_rechecks_without_loading_member_files(cfg, monkeypatch):
    monkeypatch.setattr(provider, "get_settings", lambda: cfg)
    principal = "onebot_v11:12345"
    entry = {"current_slot": 0, "ids": ["111", "222"]}
    namespace = {"MessageEvent": object, "_resolve_requested_identity_key": lambda event: (principal, True),
                 "_get_taiko_bind_info_from_center": lambda principal: {"visible": 0}, "_center_bind_info_to_entry": lambda info: entry,
                 "_get_selected_bind_slot_number": lambda entry: 0, "build_center_virtual_user_id": build_center_virtual_user_id,
                 "ensure_userdata_available": provider.ensure_userdata_available}
    function = command_function("_resolve_read_bind_target", namespace)
    calls = transport(monkeypatch, lambda request: httpx.Response(200, json={"songs": []}))
    result = function(object())
    assert result["is_virtual"] and result["user_id"] == build_center_virtual_user_id(principal)
    assert len(calls) == 1 and "materialized" not in result and not cfg.userdata_dir.exists()
    transport(monkeypatch, lambda request: httpx.Response(403))
    with pytest.raises(provider.UserdataProviderError):
        function(object())


def test_merged_pair_requires_the_same_full_member_vector(cfg, monkeypatch):
    sequence = iter(["a", "b", "c", "c"])
    def reply(request):
        marker = next(sequence)
        payload = {"snapshots": []} if request.url.path.endswith("/history") else {"songs": []}
        return httpx.Response(200, json=payload, headers={"x-taiko-source-view": "merged-v1-" + marker * 64})
    calls = transport(monkeypatch, reply)
    result = provider.ensure_userdata_view_available(build_center_virtual_user_id("12345"), settings=cfg)
    assert result["sourceView"] == "merged-v1-" + "c" * 64 and len(calls) == 4


def test_adopted_sequence_zero_is_a_verified_canonical_pair(cfg, monkeypatch):
    view = "v1-" + "a" * 32 + "-0"
    calls = transport(monkeypatch, lambda request: httpx.Response(200,
        json={"snapshots": []} if request.url.path.endswith("/history") else {"songs": []},
        headers={"x-taiko-source-view": view}))
    assert provider.ensure_userdata_view_available("111", settings=cfg)["sourceView"] == view
    assert len(calls) == 2 and not valid_source_view("v1-" + "a" * 32 + "-00")
