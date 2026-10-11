from __future__ import annotations

from pathlib import Path
import asyncio

import pytest

from taiko_bot import manual_account, userdata_provider, viewer_client
from taiko_bot.settings import Settings


def _make_settings(tmp_path: Path, *, viewer_developer_token: str = "") -> Settings:
    root_dir = tmp_path / "repo"
    storage_dir = root_dir / "storage"
    songs_dir = root_dir / "songs"
    assets_dir = root_dir / "assets"
    runtime_data_dir = storage_dir / "data"
    logs_dir = storage_dir / "logs"
    output_dir = storage_dir / "output"
    secrets_dir = storage_dir / "secrets"
    for path in (
        root_dir,
        storage_dir,
        songs_dir,
        assets_dir,
        runtime_data_dir,
        logs_dir,
        output_dir,
        secrets_dir,
    ):
        path.mkdir(parents=True, exist_ok=True)
    return Settings(
        root_dir=root_dir,
        storage_dir=storage_dir,
        songs_dir=songs_dir,
        assets_dir=assets_dir,
        userdata_dir=storage_dir / "cache" / "userdata",
        runtime_data_dir=runtime_data_dir,
        logs_dir=logs_dir,
        output_dir=output_dir,
        secrets_dir=secrets_dir,
        sqlite_path=runtime_data_dir / "taiko.sqlite3",
        multi_bind_path=runtime_data_dir / "taiko_multi_bind.json",
        draw_guess_dir=runtime_data_dir / "draw_guess",
        draw_guess_db_path=runtime_data_dir / "draw_guess" / "records.json",
        alias_log_path=logs_dir / "alias_action_log.json",
        hiroba_token_dir=secrets_dir / "hiroba_tokens",
        hiroba_cooldown_path=runtime_data_dir / "hiroba_sync_cooldown.json",
        qq_markdown_cache_dir=output_dir / "qq_markdown_cache",
        viewer_base_url="https://viewer.example.com",
        public_data_base_url="https://viewer.example.com/api/taiko",
        viewer_developer_token=viewer_developer_token,
        local_data_api_host="127.0.0.1",
        local_data_api_port=37565,
        local_data_api_base_url="http://127.0.0.1:37565",
        qq_markdown_image_base_url="https://viewer.example.com/qqbot-cache/taiko",
    )


def test_source_and_binding_accessors_require_token_while_hiroba_credentials_await_migration(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, viewer_developer_token="")
    calls = []

    def fake_request_json(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/api/taiko/proxy/hiroba/bind"):
            return {
                "taikoIds": ["1001", "1002"],
                "bind": {
                    "found": True,
                    "taikoId": "1001",
                    "visible": 1,
                    "currentTaikoId": "1001",
                    "currentSlot": 1,
                    "currentSource": "hiroba",
                    "bindings": [
                        {
                            "slot": 1,
                            "taikoId": "1001",
                            "visible": 1,
                            "isCurrent": True,
                            "source": "hiroba",
                        },
                        {
                            "slot": 2,
                            "taikoId": "1002",
                            "visible": 1,
                            "isCurrent": False,
                            "source": "hiroba",
                        },
                    ],
                },
            }
        if url.endswith("/api/taiko/proxy/bind"):
            return {
                "found": True,
                "taikoId": "1001",
                "visible": 1,
                "currentTaikoId": "1001",
                "currentSlot": 1,
                "currentSource": "wahlap",
                "bindings": [
                    {
                        "slot": 1,
                        "taikoId": "1001",
                        "visible": 1,
                        "isCurrent": True,
                        "source": "wahlap",
                    }
                ],
            }
        if url.endswith("/api/taiko/proxy/bind/current"):
            return {
                "found": True,
                "taikoId": "1002",
                "visible": 1,
                "currentTaikoId": "1002",
                "currentSlot": 2,
                "currentSource": "hiroba",
                "bindings": [
                    {
                        "slot": 1,
                        "taikoId": "1001",
                        "visible": 1,
                        "isCurrent": False,
                        "source": "wahlap",
                    },
                    {
                        "slot": 2,
                        "taikoId": "1002",
                        "visible": 1,
                        "isCurrent": True,
                        "source": "hiroba",
                    },
                ],
            }
        if url.endswith("/api/taiko/proxy/userdata/1001/history"):
            return {
                "snapshots": [
                    {"capturedAt": "2026-06-04T12:00:00", "payload": {"songs": []}}
                ]
            }
        if "/api/taiko/proxy/hiroba/credentials/" in url:
            return {"hasCredentials": True}
        return {"songs": [], "ok": True}

    monkeypatch.setattr(viewer_client, "_request_json", fake_request_json)

    assert viewer_client.fetch_remote_userdata("1001", settings=settings)["ok"] is True
    assert (
        viewer_client.proxy_center_userdata_update("1001", settings=settings)["ok"]
        is True
    )
    assert (
        viewer_client.proxy_center_hiroba_sync("1001", settings=settings)["ok"] is True
    )
    assert viewer_client.bind_hiroba_credentials(
        email="demo@example.com",
        password="secret",
        settings=settings,
    )["taikoIds"] == ["1001", "1002"]
    assert viewer_client.fetch_center_bind_info("onebot_v11:12345", settings=settings) == {
        "id": "1001",
        "visible": 1,
        "currentSlot": 1,
        "currentVirtual": False,
        "currentSource": "wahlap",
        "bindings": [
            viewer_client.CenterBindSlot(
                slot=1,
                taiko_id="1001",
                visible=1,
                is_current=True,
                source="wahlap",
                display_name="1001",
            )
        ],
    }
    assert viewer_client.proxy_center_bind_switch_current("onebot_v11:12345", 2, settings=settings)[
        "currentSource"
    ] == "hiroba"
    assert viewer_client.fetch_remote_userdata_history("1001", settings=settings) == [
        {"capturedAt": "2026-06-04T12:00:00", "payload": {"songs": []}}
    ]
    assert (
        viewer_client.has_center_hiroba_credentials("1001", settings=settings) is True
    )
    assert (
        viewer_client.fetch_wahlap_player_profile("1001", settings=settings)["ok"]
        is True
    )
    assert (
        viewer_client.fetch_wahlap_ranking(1, 4, settings=settings)["ok"] is True
    )

    assert len(calls) == 10
    for _method, _url, kwargs in calls:
        assert kwargs["settings"] is settings
        private_source = any(path in _url for path in ["/api/developer/userdata/", "/api/taiko/proxy/userdata/", "/api/taiko/proxy/bind"])
        assert kwargs.get("require_developer_token", False) is private_source


def test_ensure_userdata_available_fetches_remote_without_token(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, viewer_developer_token="")
    payload = {"songs": [{"song_id": 1}], "username": "demo"}
    fetch_calls = []

    def fake_fetch_remote_userdata(user_id, settings=None):
        fetch_calls.append((user_id, settings))
        return payload

    monkeypatch.setattr(
        userdata_provider, "fetch_remote_userdata", fake_fetch_remote_userdata
    )

    result = userdata_provider.ensure_userdata_available("1001", settings=settings)

    assert result == payload
    assert fetch_calls == [("1001", settings)]
    assert userdata_provider.uses_center_userdata(settings) is True
    assert userdata_provider.get_cached_userdata("1001", settings=settings) == payload
    assert (settings.userdata_dir / "1001data.json").exists()


def test_center_bind_payload_preserves_manual_display_and_u0():
    payload = viewer_client._normalize_center_bind_payload(
        {
            "found": True,
            "currentTaikoId": "1001",
            "currentSlot": 0,
            "currentVirtual": True,
            "currentSource": "wahlap",
            "bindings": [
                {
                    "slot": 1,
                    "taikoId": "1001",
                    "isCurrent": True,
                    "source": "wahlap",
                },
                {
                    "slot": 2,
                    "taikoId": "980000000000000001",
                    "source": "manual",
                    "displayName": "练习号",
                    "isManual": True,
                    "canExternalSync": False,
                },
                {
                    "slot": 3,
                    "taikoId": "1002",
                    "source": "hiroba",
                },
            ],
        }
    )
    assert payload is not None
    assert payload["currentSlot"] == 0
    assert payload["currentVirtual"] is True
    assert payload["bindings"][1].display_name == "练习号"
    assert payload["bindings"][1].is_manual is True
    assert payload["bindings"][1].can_external_sync is False


def test_manual_account_write_requires_independent_service_token(tmp_path):
    settings = _make_settings(tmp_path)
    with pytest.raises(manual_account.ManualAccountApiError, match="服务令牌未配置"):
        asyncio.run(
            manual_account.call_manual_account_api(
                "onebot-v11:123", "create", settings=settings, nickname="练习号"
            )
        )


@pytest.mark.parametrize("call", [
    lambda cfg: viewer_client.fetch_remote_userdata("1001",settings=cfg),
    lambda cfg: viewer_client.fetch_remote_userdata_history("1001",settings=cfg),
    lambda cfg: viewer_client.proxy_center_userdata_update("1001",settings=cfg),
    lambda cfg: viewer_client.proxy_center_hiroba_sync("1001",settings=cfg),
    lambda cfg: viewer_client.fetch_center_bind_info("onebot_v11:12345",settings=cfg),
    lambda cfg: viewer_client.proxy_center_bind_upsert("onebot_v11:12345","1001",settings=cfg),
    lambda cfg: viewer_client.proxy_center_bind_switch_current("onebot_v11:12345",1,settings=cfg),
])
def test_private_source_calls_without_token_fail_before_network(tmp_path,monkeypatch,call):
    settings=_make_settings(tmp_path)
    monkeypatch.setattr(viewer_client.httpx,"Client",lambda *a,**k:pytest.fail("Network attempted without source credential"))
    with pytest.raises(viewer_client.ViewerClientError) as caught:
        call(settings)
    assert caught.value.status_code==500


def test_binding_mutations_forward_retry_ids_without_changing_existing_call_signatures(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path, viewer_developer_token="synthetic")
    calls = []
    monkeypatch.setattr(viewer_client, "_request_json", lambda *args, **kwargs: calls.append(kwargs) or {"found": False})
    retry_id = "a" * 32
    viewer_client.proxy_center_bind_upsert("onebot_v11:12345", "1001", request_id=retry_id, settings=settings)
    viewer_client.proxy_center_bind_switch_current("onebot_v11:12345", 1, settings, request_id=retry_id)
    viewer_client.proxy_center_bind_switch_current("onebot_v11:12345", 1, settings)
    assert [call["json_payload"].get("requestId") for call in calls] == [retry_id, retry_id, None]
    assert all(call["require_developer_token"] for call in calls)
