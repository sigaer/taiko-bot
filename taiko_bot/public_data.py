from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict

import httpx

from .settings import PUBLIC_DATA_FILES, Settings, ensure_runtime_dirs, get_settings
from .viewer_client import (
    ViewerClientError,
    download_asset_bundle,
    fetch_asset_bundle_metadata,
)


class PublicDataSyncError(RuntimeError):
    pass


_SUCCESSFUL_SYNC_ROOTS: set[str] = set()
_SUCCESSFUL_ASSET_SYNC_ROOTS: set[str] = set()


def _manifest_cache_path(settings: Settings) -> Path:
    return settings.songs_dir / ".manifest.json"


def _dataset_path(settings: Settings, filename: str) -> Path:
    if filename == "city.json":
        return settings.root_dir / filename
    return settings.songs_dir / filename


def _asset_bundle_hash_path(settings: Settings) -> Path:
    return settings.assets_dir / ".bundle.sha256"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(path)


def _has_local_asset_bundle(settings: Settings) -> bool:
    required_paths = (
        settings.assets_dir / "fonts",
        settings.assets_dir / "templates",
        settings.assets_dir / "icons",
    )
    return all(path.exists() for path in required_paths)


def load_manifest(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    client = httpx.Client(timeout=60.0, trust_env=False)
    try:
        response = client.get(f"{cfg.public_data_base_url}/manifest")
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise PublicDataSyncError(f"拉取 manifest 失败：{exc}") from exc
    finally:
        client.close()
    if not isinstance(payload, dict):
        raise PublicDataSyncError("manifest 不是对象 JSON")
    return payload


def load_cached_manifest(settings: Settings | None = None) -> Dict[str, Any] | None:
    cfg = settings or get_settings()
    path = _manifest_cache_path(cfg)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def sync_public_datasets(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_runtime_dirs(cfg)
    manifest = load_manifest(cfg)
    datasets = manifest.get("datasets")
    if not isinstance(datasets, dict):
        raise PublicDataSyncError("manifest 缺少 datasets")

    downloaded: list[str] = []
    client = httpx.Client(timeout=120.0, trust_env=False)
    try:
        for dataset_name, default_filename in PUBLIC_DATA_FILES.items():
            spec = datasets.get(dataset_name)
            if not isinstance(spec, dict):
                raise PublicDataSyncError(f"manifest 缺少数据集：{dataset_name}")
            filename = str(spec.get("filename") or default_filename).strip() or default_filename
            url = str(spec.get("url") or "").strip()
            sha256 = str(spec.get("sha256") or "").strip().lower()
            if not url:
                raise PublicDataSyncError(f"数据集 {dataset_name} 缺少 url")
            target_path = _dataset_path(cfg, filename)
            if target_path.exists() and sha256:
                current_hash = _sha256_bytes(target_path.read_bytes())
                if current_hash == sha256:
                    continue
            response = client.get(url)
            response.raise_for_status()
            payload = response.content
            if sha256 and _sha256_bytes(payload) != sha256:
                raise PublicDataSyncError(f"数据集 {dataset_name} 校验失败")
            _write_bytes(target_path, payload)
            downloaded.append(dataset_name)
    except PublicDataSyncError:
        raise
    except Exception as exc:
        missing = [
            name
            for name, filename in PUBLIC_DATA_FILES.items()
            if not _dataset_path(cfg, filename).exists()
        ]
        if missing:
            raise PublicDataSyncError(f"同步公共数据失败，且本地缺少缓存：{exc}") from exc
    finally:
        client.close()

    _manifest_cache_path(cfg).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return {"downloaded": downloaded, "manifest": manifest}


def sync_public_datasets_once(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    cache_key = str(cfg.root_dir)
    if cache_key in _SUCCESSFUL_SYNC_ROOTS:
        return {
            "downloaded": [],
            "manifest": load_cached_manifest(cfg) or {},
            "skipped": True,
        }
    result = sync_public_datasets(cfg)
    _SUCCESSFUL_SYNC_ROOTS.add(cache_key)
    return result


def sync_asset_bundle(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_runtime_dirs(cfg)
    has_local_assets = _has_local_asset_bundle(cfg)
    current_sha = ""
    marker_path = _asset_bundle_hash_path(cfg)
    if marker_path.exists():
        current_sha = marker_path.read_text(encoding="utf-8").strip().lower()

    try:
        metadata = fetch_asset_bundle_metadata(cfg)
    except ViewerClientError as exc:
        if not has_local_assets:
            raise PublicDataSyncError(f"首次启动拉取资源包失败：{exc}") from exc
        return {
            "updated": False,
            "degraded": True,
            "message": str(exc),
            "sha256": current_sha,
        }

    remote_sha = str(metadata.get("sha256") or "").strip().lower()
    if has_local_assets and current_sha and remote_sha and current_sha == remote_sha:
        return {
            "updated": False,
            "sha256": current_sha,
            "skipped": True,
        }

    temp_root = Path(tempfile.mkdtemp(prefix="taiko-assets-", dir=str(cfg.storage_dir)))
    archive_path = temp_root / "bundle.zip"
    extracted_path = temp_root / "assets"
    backup_path = cfg.assets_dir.with_name(f"{cfg.assets_dir.name}.bak")

    try:
        download_result = download_asset_bundle(archive_path, cfg)
        archive_sha = _sha256_bytes(archive_path.read_bytes())
        expected_sha = str(download_result.get("sha256") or remote_sha).strip().lower()
        if expected_sha and archive_sha != expected_sha:
            raise PublicDataSyncError("资源包校验失败。")

        extracted_path.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extracted_path)
        _write_bytes(
            extracted_path / ".bundle.sha256",
            (expected_sha or archive_sha).encode("utf-8"),
        )

        if backup_path.exists():
            shutil.rmtree(backup_path, ignore_errors=True)
        if cfg.assets_dir.exists():
            cfg.assets_dir.replace(backup_path)
        extracted_path.replace(cfg.assets_dir)
        shutil.rmtree(backup_path, ignore_errors=True)
        return {
            "updated": True,
            "sha256": expected_sha or archive_sha,
            "updated_at": download_result.get("updatedAt") or metadata.get("updatedAt") or "",
        }
    except Exception as exc:
        if backup_path.exists() and not cfg.assets_dir.exists():
            backup_path.replace(cfg.assets_dir)
        if not has_local_assets:
            raise PublicDataSyncError(f"首次启动拉取资源包失败：{exc}") from exc
        return {
            "updated": False,
            "degraded": True,
            "message": str(exc),
            "sha256": current_sha,
        }
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def sync_asset_bundle_once(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    cache_key = str(cfg.root_dir)
    if cache_key in _SUCCESSFUL_ASSET_SYNC_ROOTS:
        return {"updated": False, "skipped": True}
    result = sync_asset_bundle(cfg)
    _SUCCESSFUL_ASSET_SYNC_ROOTS.add(cache_key)
    return result
