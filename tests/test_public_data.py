from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

from taiko_bot import public_data
from taiko_bot.settings import Settings


def _make_settings(tmp_path: Path) -> Settings:
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
        viewer_developer_token="",
        local_data_api_host="127.0.0.1",
        local_data_api_port=37565,
        local_data_api_base_url="http://127.0.0.1:37565",
        qq_markdown_image_base_url="https://viewer.example.com/qqbot-cache/taiko",
    )


def _build_zip(path: Path, entries: dict[str, bytes]) -> str:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return public_data._sha256_bytes(path.read_bytes())


def test_sync_asset_resource_installs_split_archive(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    archive_path = tmp_path / "core-assets.zip"
    sha256 = _build_zip(
        archive_path,
        {
            "fonts/DDFont.ttf": b"font",
            "templates/a.png": b"tpl",
            "icons/x.png": b"icon",
        },
    )

    def fake_manifest(_settings):
        return {
            "resources": {
                "core-assets": {
                    "url": "https://viewer.example.com/core-assets.zip",
                    "sha256": sha256,
                    "updatedAt": "2026-06-02T00:00:00Z",
                }
            }
        }

    def fake_download(target_path: Path, _url: str) -> bytes:
        target_path.write_bytes(archive_path.read_bytes())
        return archive_path.read_bytes()

    monkeypatch.setattr(public_data, "load_manifest", fake_manifest)
    monkeypatch.setattr(public_data, "_download_resource_archive", fake_download)

    result = public_data.sync_asset_resource("core-assets", settings)

    assert result["updated"] is True
    assert (settings.assets_dir / "fonts" / "DDFont.ttf").read_bytes() == b"font"
    assert (settings.assets_dir / "templates" / "a.png").read_bytes() == b"tpl"
    assert (settings.assets_dir / "icons" / "x.png").read_bytes() == b"icon"

    summary = public_data.get_asset_sync_summary(settings)
    assert summary["coreReady"] is True
    assert "core-assets" in summary["installedResources"]
    assert summary["resources"]["core-assets"]["sha256"] == sha256
    assert summary["resources"]["core-assets"]["state"] == "installed"


def test_get_asset_sync_summary_reports_status(tmp_path):
    settings = _make_settings(tmp_path)
    public_data._save_asset_resource_state(
        settings,
        {
            "core-assets": {
                "sha256": "",
                "state": "syncing",
                "lastError": "",
                "updatedAt": "",
            },
            "cover-assets": {
                "sha256": "",
                "state": "failed",
                "lastError": "boom",
                "updatedAt": "",
            },
        },
    )

    summary = public_data.get_asset_sync_summary(settings)

    assert summary["coreReady"] is False
    assert summary["syncingResources"] == ["core-assets"]
    assert summary["failedResources"] == ["cover-assets"]


def test_sync_asset_resource_falls_back_to_legacy_bundle(tmp_path, monkeypatch):
    settings = _make_settings(tmp_path)
    bundle_path = tmp_path / "bundle.zip"
    bundle_sha = _build_zip(
        bundle_path,
        {
            "fonts/DDFont.ttf": b"font",
            "templates/a.png": b"tpl",
            "icons/x.png": b"icon",
            "cover/1.png": b"cover",
            "dress/a.png": b"dress",
            "name_plate/a.png": b"plate",
            "name_plate_dani/a.png": b"dani",
            "fumens/Oni/1.png": b"fumen",
        },
    )

    def fake_manifest(_settings):
        return {"resources": {}}

    def fake_fetch_bundle_metadata(_settings):
        return {
            "sha256": bundle_sha,
            "size": bundle_path.stat().st_size,
            "updatedAt": "2026-06-02T00:00:00Z",
        }

    def fake_download_bundle(target_path: Path, _settings):
        target_path.write_bytes(bundle_path.read_bytes())
        return {
            "sha256": bundle_sha,
            "updatedAt": "2026-06-02T00:00:00Z",
        }

    monkeypatch.setattr(public_data, "load_manifest", fake_manifest)
    monkeypatch.setattr(public_data, "fetch_asset_bundle_metadata", fake_fetch_bundle_metadata)
    monkeypatch.setattr(public_data, "download_asset_bundle", fake_download_bundle)

    result = public_data.sync_asset_resource("fumens-assets", settings)

    assert result["legacyBundle"] is True
    assert (settings.assets_dir / "fumens" / "Oni" / "1.png").read_bytes() == b"fumen"

    summary = public_data.get_asset_sync_summary(settings)
    assert "fumens-assets" in summary["installedResources"]
    assert summary["resources"]["fumens-assets"]["state"] == "installed"
