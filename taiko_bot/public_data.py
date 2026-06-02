from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import httpx
from nonebot import logger

from .settings import PUBLIC_DATA_FILES, Settings, ensure_runtime_dirs, get_settings
from .viewer_client import (
    ViewerClientError,
    download_asset_bundle,
    fetch_asset_bundle_metadata,
)


class PublicDataSyncError(RuntimeError):
    pass


@dataclass(frozen=True)
class AssetResourceSpec:
    name: str
    paths: tuple[str, ...]
    aliases: tuple[str, ...] = ()


ASSET_RESOURCE_SPECS: dict[str, AssetResourceSpec] = {
    "core-assets": AssetResourceSpec(
        name="core-assets",
        paths=("fonts", "templates", "icons"),
    ),
    "cover-assets": AssetResourceSpec(
        name="cover-assets",
        paths=("cover",),
    ),
    "dress-assets": AssetResourceSpec(
        name="dress-assets",
        paths=("dress",),
    ),
    "nameplate-assets": AssetResourceSpec(
        name="nameplate-assets",
        paths=("name_plate", "name_plate_dani"),
    ),
    "fumens-assets": AssetResourceSpec(
        name="fumens-assets",
        paths=("fumens",),
        aliases=("fumens-renamed",),
    ),
}
ASSET_RESOURCE_LABELS = {
    "core-assets": "核心资源",
    "cover-assets": "曲绘资源",
    "dress-assets": "穿搭资源",
    "nameplate-assets": "名牌资源",
    "fumens-assets": "谱面资源",
}

_SUCCESSFUL_SYNC_ROOTS: set[str] = set()
_ASSET_SYNC_TASKS: dict[str, asyncio.Task[None]] = {}
_ASSET_STATE_LOCK = threading.Lock()


def _manifest_cache_path(settings: Settings) -> Path:
    return settings.songs_dir / ".manifest.json"


def _dataset_path(settings: Settings, filename: str) -> Path:
    if filename == "city.json":
        return settings.root_dir / filename
    return settings.songs_dir / filename


def _asset_bundle_hash_path(settings: Settings) -> Path:
    return settings.assets_dir / ".bundle.sha256"


def _asset_resource_state_path(settings: Settings) -> Path:
    return settings.runtime_data_dir / "asset_resources.json"


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    temp_path.write_bytes(payload)
    temp_path.replace(path)


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    _write_bytes(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _resource_state_key(settings: Settings, resource_name: str) -> str:
    return f"{settings.root_dir}:{resource_name}"


def _resource_required_paths(
    settings: Settings,
    resource_name: str,
) -> tuple[Path, ...]:
    spec = ASSET_RESOURCE_SPECS[resource_name]
    return tuple(settings.assets_dir / rel_path for rel_path in spec.paths)


def _has_local_asset_bundle(settings: Settings) -> bool:
    return has_asset_resource(settings, "core-assets")


def has_asset_resource(
    settings: Settings | None,
    resource_name: str,
) -> bool:
    cfg = settings or get_settings()
    return all(path.exists() for path in _resource_required_paths(cfg, resource_name))


def _load_asset_resource_state(settings: Settings) -> Dict[str, Dict[str, Any]]:
    path = _asset_resource_state_path(settings)
    payload = _read_json(path)
    resources = payload.get("resources")
    if not isinstance(resources, dict):
        resources = {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for name, entry in resources.items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        normalized[name] = {
            "sha256": str(entry.get("sha256") or "").strip().lower(),
            "state": str(entry.get("state") or "").strip().lower() or "unknown",
            "lastError": str(entry.get("lastError") or "").strip(),
            "updatedAt": str(entry.get("updatedAt") or "").strip(),
        }
    return normalized


def _save_asset_resource_state(
    settings: Settings,
    resources: Dict[str, Dict[str, Any]],
) -> None:
    _write_json(
        _asset_resource_state_path(settings),
        {"resources": resources},
    )


def _update_asset_resource_entry(
    settings: Settings,
    resource_name: str,
    *,
    state: str,
    sha256: str = "",
    last_error: str = "",
    updated_at: str = "",
) -> Dict[str, Any]:
    with _ASSET_STATE_LOCK:
        resources = _load_asset_resource_state(settings)
        current = resources.get(resource_name, {})
        resources[resource_name] = {
            "sha256": str(sha256 or current.get("sha256") or "").strip().lower(),
            "state": str(state or current.get("state") or "unknown").strip().lower(),
            "lastError": str(last_error or "").strip(),
            "updatedAt": str(updated_at or current.get("updatedAt") or "").strip(),
        }
        _save_asset_resource_state(settings, resources)
        return resources[resource_name]


def _mark_local_assets_as_installed(settings: Settings) -> None:
    with _ASSET_STATE_LOCK:
        resources = _load_asset_resource_state(settings)
        changed = False
        for name in ASSET_RESOURCE_SPECS:
            if has_asset_resource(settings, name):
                entry = resources.get(name, {})
                if entry.get("state") != "installed":
                    changed = True
                resources[name] = {
                    "sha256": str(entry.get("sha256") or "").strip().lower(),
                    "state": "installed",
                    "lastError": "",
                    "updatedAt": str(entry.get("updatedAt") or "").strip(),
                }
        if changed:
            _save_asset_resource_state(settings, resources)


def get_asset_sync_summary(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = settings or get_settings()
    _mark_local_assets_as_installed(cfg)
    with _ASSET_STATE_LOCK:
        resources = _load_asset_resource_state(cfg)

    installed_resources = [
        name for name in ASSET_RESOURCE_SPECS if has_asset_resource(cfg, name)
    ]
    syncing_resources = sorted(
        name
        for name, entry in resources.items()
        if entry.get("state") == "syncing"
    )
    failed_resources = sorted(
        name
        for name, entry in resources.items()
        if entry.get("state") == "failed"
    )
    return {
        "coreReady": has_asset_resource(cfg, "core-assets"),
        "installedResources": installed_resources,
        "syncingResources": syncing_resources,
        "failedResources": failed_resources,
        "resources": resources,
    }


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


def _resolve_manifest_resource_spec(
    manifest: Dict[str, Any],
    resource_name: str,
) -> tuple[str, Dict[str, Any]] | tuple[None, None]:
    resources = manifest.get("resources")
    if not isinstance(resources, dict):
        return None, None
    spec = ASSET_RESOURCE_SPECS[resource_name]
    for candidate in (spec.name, *spec.aliases):
        payload = resources.get(candidate)
        if isinstance(payload, dict) and str(payload.get("url") or "").strip():
            return candidate, payload
    return None, None


def _download_resource_archive(
    target_path: Path,
    url: str,
) -> bytes:
    try:
        with httpx.Client(timeout=300.0, trust_env=False, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with target_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
    except Exception as exc:
        raise PublicDataSyncError(f"下载资源包失败：{exc}") from exc
    return target_path.read_bytes()


def _replace_asset_path(source_path: Path, target_path: Path) -> None:
    backup_path = target_path.with_name(f"{target_path.name}.bak")
    if backup_path.exists():
        if backup_path.is_dir():
            shutil.rmtree(backup_path, ignore_errors=True)
        else:
            backup_path.unlink(missing_ok=True)
    if target_path.exists():
        target_path.replace(backup_path)
    try:
        source_path.replace(target_path)
    except Exception:
        if backup_path.exists() and not target_path.exists():
            backup_path.replace(target_path)
        raise
    else:
        if backup_path.exists():
            if backup_path.is_dir():
                shutil.rmtree(backup_path, ignore_errors=True)
            else:
                backup_path.unlink(missing_ok=True)


def _extract_resource_archive(
    archive_path: Path,
    resource_name: str,
    settings: Settings,
) -> None:
    temp_root = Path(tempfile.mkdtemp(prefix="taiko-resource-", dir=str(settings.storage_dir)))
    extracted_root = temp_root / "assets"
    extracted_root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(extracted_root)
        for rel_path in ASSET_RESOURCE_SPECS[resource_name].paths:
            extracted_path = extracted_root / rel_path
            if not extracted_path.exists():
                raise PublicDataSyncError(f"资源包缺少目录：{rel_path}")
            _replace_asset_path(extracted_path, settings.assets_dir / rel_path)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _mark_all_resources_from_bundle(
    settings: Settings,
    *,
    sha256: str = "",
    updated_at: str = "",
) -> None:
    for resource_name in ASSET_RESOURCE_SPECS:
        if has_asset_resource(settings, resource_name):
            _update_asset_resource_entry(
                settings,
                resource_name,
                state="installed",
                sha256=sha256,
                updated_at=updated_at,
            )


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
        _mark_all_resources_from_bundle(
            cfg,
            sha256=current_sha,
            updated_at=str(metadata.get("updatedAt") or "").strip(),
        )
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
        _mark_all_resources_from_bundle(
            cfg,
            sha256=expected_sha or archive_sha,
            updated_at=str(download_result.get("updatedAt") or metadata.get("updatedAt") or "").strip(),
        )
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


def sync_asset_resource(
    resource_name: str,
    settings: Settings | None = None,
    *,
    force: bool = False,
) -> Dict[str, Any]:
    cfg = settings or get_settings()
    ensure_runtime_dirs(cfg)
    if resource_name not in ASSET_RESOURCE_SPECS:
        raise PublicDataSyncError(f"未知资源包：{resource_name}")

    resource_ready = has_asset_resource(cfg, resource_name)
    _update_asset_resource_entry(cfg, resource_name, state="syncing")

    try:
        manifest = load_manifest(cfg)
    except PublicDataSyncError as exc:
        if resource_ready:
            _update_asset_resource_entry(
                cfg,
                resource_name,
                state="installed",
                last_error=str(exc),
            )
            return {"updated": False, "degraded": True, "message": str(exc)}
        _update_asset_resource_entry(
            cfg,
            resource_name,
            state="failed",
            last_error=str(exc),
        )
        raise

    manifest_name, manifest_spec = _resolve_manifest_resource_spec(manifest, resource_name)
    if manifest_spec is None:
        logger.warning(
            f"taiko resource {resource_name} missing from manifest, fallback to legacy bundle"
        )
        try:
            result = sync_asset_bundle(cfg)
        except PublicDataSyncError as exc:
            _update_asset_resource_entry(
                cfg,
                resource_name,
                state="failed",
                last_error=str(exc),
            )
            raise
        if not has_asset_resource(cfg, resource_name):
            message = f"旧版总包同步完成，但资源仍缺失：{resource_name}"
            _update_asset_resource_entry(
                cfg,
                resource_name,
                state="failed",
                last_error=message,
            )
            raise PublicDataSyncError(message)
        bundle_sha = str(result.get("sha256") or "").strip().lower()
        bundle_updated_at = str(result.get("updated_at") or "").strip()
        _mark_all_resources_from_bundle(cfg, sha256=bundle_sha, updated_at=bundle_updated_at)
        return {
            "updated": bool(result.get("updated")),
            "resource": resource_name,
            "sha256": bundle_sha,
            "updatedAt": bundle_updated_at,
            "legacyBundle": True,
        }

    url = str(manifest_spec.get("url") or "").strip()
    remote_sha = str(manifest_spec.get("sha256") or "").strip().lower()
    remote_updated_at = str(manifest_spec.get("updatedAt") or "").strip()
    if not url:
        raise PublicDataSyncError(f"资源包 {manifest_name} 缺少下载地址。")

    current_state = _load_asset_resource_state(cfg).get(resource_name, {})
    current_sha = str(current_state.get("sha256") or "").strip().lower()
    if resource_ready and not force and current_sha and remote_sha and current_sha == remote_sha:
        _update_asset_resource_entry(
            cfg,
            resource_name,
            state="installed",
            sha256=current_sha,
            updated_at=remote_updated_at,
        )
        return {
            "updated": False,
            "resource": resource_name,
            "sha256": current_sha,
            "updatedAt": remote_updated_at,
            "skipped": True,
        }

    temp_root = Path(tempfile.mkdtemp(prefix="taiko-resource-", dir=str(cfg.storage_dir)))
    archive_path = temp_root / f"{resource_name}.zip"
    try:
        payload = _download_resource_archive(archive_path, url)
        archive_sha = _sha256_bytes(payload)
        if remote_sha and archive_sha != remote_sha:
            raise PublicDataSyncError(f"资源包 {resource_name} 校验失败。")
        _extract_resource_archive(archive_path, resource_name, cfg)
        _update_asset_resource_entry(
            cfg,
            resource_name,
            state="installed",
            sha256=remote_sha or archive_sha,
            updated_at=remote_updated_at,
        )
        return {
            "updated": True,
            "resource": resource_name,
            "sha256": remote_sha or archive_sha,
            "updatedAt": remote_updated_at,
        }
    except Exception as exc:
        message = str(exc)
        _update_asset_resource_entry(
            cfg,
            resource_name,
            state="failed",
            sha256=current_sha,
            last_error=message,
            updated_at=remote_updated_at,
        )
        raise PublicDataSyncError(message) from exc
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)


def _queue_sync_task(
    resource_name: str,
    settings: Settings,
    *,
    force: bool = False,
) -> None:
    task_key = _resource_state_key(settings, resource_name)
    current_task = _ASSET_SYNC_TASKS.get(task_key)
    if current_task and not current_task.done():
        return
    _update_asset_resource_entry(settings, resource_name, state="syncing")

    async def runner() -> None:
        try:
            result = await asyncio.to_thread(
                sync_asset_resource,
                resource_name,
                settings,
                force=force,
            )
            logger.info(
                f"taiko asset resource sync completed: resource={resource_name} "
                f"updated={result.get('updated')} legacy={result.get('legacyBundle', False)}"
            )
        except Exception as exc:
            logger.warning(
                f"taiko asset resource sync failed: resource={resource_name} error={exc}"
            )
        finally:
            _ASSET_SYNC_TASKS.pop(task_key, None)

    loop = asyncio.get_running_loop()
    _ASSET_SYNC_TASKS[task_key] = loop.create_task(runner())


def start_background_asset_sync(settings: Settings | None = None) -> None:
    cfg = settings or get_settings()
    _mark_local_assets_as_installed(cfg)
    _queue_sync_task("core-assets", cfg)


def ensure_asset_resource_available(
    resource_names: Iterable[str],
    settings: Settings | None = None,
) -> tuple[bool, str]:
    cfg = settings or get_settings()
    _mark_local_assets_as_installed(cfg)
    summary = get_asset_sync_summary(cfg)
    resources = summary.get("resources") or {}
    for resource_name in resource_names:
        if resource_name not in ASSET_RESOURCE_SPECS:
            continue
        if has_asset_resource(cfg, resource_name):
            continue
        _queue_sync_task(resource_name, cfg)
        entry = resources.get(resource_name, {}) if isinstance(resources, dict) else {}
        display_name = ASSET_RESOURCE_LABELS.get(resource_name, resource_name)
        if entry.get("state") == "failed":
            detail = str(entry.get("lastError") or "").strip()
            if detail:
                return False, f"{display_name}同步失败，请稍后重试。\n{detail}"
            return False, f"{display_name}同步失败，请稍后重试。"
        return False, f"{display_name}首次同步中，请稍后再试。"
    return True, ""
