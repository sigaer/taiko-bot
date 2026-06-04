from __future__ import annotations

from pathlib import Path

from taiko_bot import userdata_provider, viewer_client
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


def test_center_accessors_do_not_require_token(tmp_path, monkeypatch):
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
    assert viewer_client.fetch_center_bind_info("qq:123", settings=settings) == {
        "id": "1001",
        "visible": 1,
        "currentSlot": 1,
        "currentSource": "wahlap",
        "bindings": [
            viewer_client.CenterBindSlot(
                slot=1,
                taiko_id="1001",
                visible=1,
                is_current=True,
                source="wahlap",
            )
        ],
    }
    assert viewer_client.proxy_center_bind_switch_current("qq:123", 2, settings=settings)[
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
        assert kwargs.get("require_developer_token", False) is False


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
