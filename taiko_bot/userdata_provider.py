from __future__ import annotations

import time
from typing import Any, Dict, Iterable, Optional

from .settings import Settings, get_settings
from .viewer_client import (
    ViewerClientError,
    fetch_remote_userdata,
    fetch_remote_userdata_history,
)


class UserdataProviderError(RuntimeError):
    pass


REMOTE_USERDATA_CACHE_TTL_SECONDS = 30
_REMOTE_REFRESH_TS: Dict[str, float] = {}
_REMOTE_USERDATA_CACHE: Dict[str, Dict[str, Any]] = {}
_REMOTE_HISTORY_CACHE: Dict[str, list[Dict[str, Any]]] = {}
_REMOTE_HISTORY_REFRESH_TS: Dict[str, float] = {}


def _get_settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def uses_center_userdata(settings: Settings | None = None) -> bool:
    return bool(_get_settings(settings).viewer_base_url.strip())


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    if not isinstance(normalized.get("songs"), list):
        normalized["songs"] = []
    return normalized


def update_userdata_cache_from_payload(
    user_id: str,
    payload: Dict[str, Any],
    *,
    source: str = "viewer-cache",
    settings: Settings | None = None,
) -> Dict[str, Any]:
    normalized = _normalize_payload(payload)
    _ = (_get_settings(settings), source)
    _REMOTE_USERDATA_CACHE[str(user_id).strip()] = normalized
    _REMOTE_REFRESH_TS[str(user_id).strip()] = time.monotonic()
    return normalized


def ensure_userdata_available(
    user_id: str,
    *,
    force_refresh: bool = False,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    normalized_user_id = str(user_id).strip()
    cached = _REMOTE_USERDATA_CACHE.get(normalized_user_id)
    if cached is not None and not force_refresh and uses_center_userdata(cfg):
        refreshed_at = _REMOTE_REFRESH_TS.get(normalized_user_id, 0.0)
        if time.monotonic() - refreshed_at < REMOTE_USERDATA_CACHE_TTL_SECONDS:
            return cached
    if not uses_center_userdata(cfg):
        if cached is not None:
            return cached
        raise UserdataProviderError("未配置可用的 viewer 地址，且当前没有可用的中心成绩缓存。")
    try:
        remote_payload = fetch_remote_userdata(user_id, settings=cfg)
    except ViewerClientError as exc:
        if cached is not None:
            return cached
        raise UserdataProviderError(str(exc)) from exc
    normalized = update_userdata_cache_from_payload(
        user_id, remote_payload, source="viewer-cache", settings=cfg
    )
    _REMOTE_REFRESH_TS[normalized_user_id] = time.monotonic()
    return normalized


def ensure_multiple_userdatas_available(
    user_ids: Iterable[str],
    *,
    force_refresh: bool = False,
    settings: Settings | None = None,
) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for raw_user_id in user_ids:
        user_id = str(raw_user_id or "").strip()
        if not user_id or user_id in results:
            continue
        results[user_id] = ensure_userdata_available(
            user_id,
            force_refresh=force_refresh,
            settings=settings,
        )
    return results


def get_cached_userdata(
    user_id: str, settings: Settings | None = None
) -> Optional[Dict[str, Any]]:
    _ = _get_settings(settings)
    return _REMOTE_USERDATA_CACHE.get(str(user_id).strip())


def ensure_userdata_history_available(
    user_id: str,
    *,
    force_refresh: bool = False,
    settings: Settings | None = None,
) -> list[Dict[str, Any]]:
    cfg = _get_settings(settings)
    normalized_user_id = str(user_id).strip()
    cached = _REMOTE_HISTORY_CACHE.get(normalized_user_id)
    if cached is not None and not force_refresh and uses_center_userdata(cfg):
        refreshed_at = _REMOTE_HISTORY_REFRESH_TS.get(normalized_user_id, 0.0)
        if time.monotonic() - refreshed_at < REMOTE_USERDATA_CACHE_TTL_SECONDS:
            return cached
    if not uses_center_userdata(cfg):
        if cached is not None:
            return cached
        raise UserdataProviderError("未配置可用的 viewer 地址，且当前没有可用的中心历史缓存。")
    try:
        history = fetch_remote_userdata_history(user_id, settings=cfg)
    except ViewerClientError as exc:
        if cached is not None:
            return cached
        raise UserdataProviderError(str(exc)) from exc
    _REMOTE_HISTORY_CACHE[normalized_user_id] = history
    _REMOTE_HISTORY_REFRESH_TS[normalized_user_id] = time.monotonic()
    return history
