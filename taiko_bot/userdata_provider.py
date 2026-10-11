from __future__ import annotations

from typing import Any, Dict, Iterable, Optional
import time

from .settings import Settings, get_settings
from .private_read_client import fetch_private_read
from .private_read_cache import PrivateReadCache, private_cache_key
from .viewer_client import ViewerClientError, normalize_userdata_history


class UserdataProviderError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 503):
        super().__init__(message)
        self.status_code = status_code


REMOTE_USERDATA_CACHE_TTL_SECONDS = 30
_PRIVATE_READ_CACHE = PrivateReadCache(ttl_seconds=REMOTE_USERDATA_CACHE_TTL_SECONDS)


def _get_settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def uses_center_userdata(settings: Settings | None = None) -> bool:
    return bool(_get_settings(settings).viewer_base_url.strip())


def _normalize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    if not isinstance(normalized.get("songs"), list):
        normalized["songs"] = []
    return normalized


def update_userdata_cache_from_payload(user_id: str, payload: Dict[str, Any], *, source: str = "viewer-cache", settings: Settings | None = None) -> Dict[str, Any]:
    # Mutation responses remain available to their caller. They do not create a
    # reusable authority claim or a Source-ID disk cache for other requests.
    _ = user_id, source, settings
    return _normalize_payload(payload)


def _private_history(payload):
    snapshots = normalize_userdata_history(payload)
    if snapshots and payload.get("historyFormat") != "raw-v1":
        raise ViewerClientError("中心历史格式暂不兼容，请更新中心服务。", status_code=503)
    return snapshots


def _read(kind: str, user_id: str, *, force_refresh: bool, settings: Settings, with_view=False, deadline=None):
    source = str(user_id).strip()
    key = private_cache_key(kind, source, settings)
    if not uses_center_userdata(settings) or not settings.viewer_developer_token.strip():
        _PRIVATE_READ_CACHE.discard(key)
        raise UserdataProviderError("请配置中心成绩地址和有效访问凭据。", status_code=401)
    cached = None if force_refresh else _PRIVATE_READ_CACHE.get(key)
    try:
        reply = fetch_private_read(kind, source, settings=settings, etag=cached.etag if cached else None, **({"deadline": deadline} if deadline is not None else {}))
        if reply.not_modified:
            if cached is None or reply.etag != cached.etag:
                raise ViewerClientError("中心成绩缓存确认无效。", status_code=503)
            payload = cached.payload()
        else:
            payload = reply.payload
        if not isinstance(payload, dict):
            raise ViewerClientError("中心成绩响应无效。", status_code=503)
        if kind == "history":
            _private_history(payload)
        if reply.etag:
            _PRIVATE_READ_CACHE.put(key, reply.etag, payload)
        else:
            _PRIVATE_READ_CACHE.discard(key)
        return (payload, reply.source_view) if with_view else payload
    except ViewerClientError as error:
        _PRIVATE_READ_CACHE.discard(key)
        raise UserdataProviderError(str(error), status_code=error.status_code) from error
    except Exception:
        _PRIVATE_READ_CACHE.discard(key)
        raise UserdataProviderError("中心成绩响应无效。", status_code=503) from None


def ensure_userdata_available(user_id: str, *, force_refresh: bool = False, settings: Settings | None = None) -> Dict[str, Any]:
    return _normalize_payload(_read("current", user_id, force_refresh=force_refresh, settings=_get_settings(settings)))


def ensure_multiple_userdatas_available(user_ids: Iterable[str], *, force_refresh: bool = False, settings: Settings | None = None) -> Dict[str, Dict[str, Any]]:
    results: Dict[str, Dict[str, Any]] = {}
    for raw_user_id in user_ids:
        user_id = str(raw_user_id or "").strip()
        if user_id and user_id not in results:
            results[user_id] = ensure_userdata_available(user_id, force_refresh=force_refresh, settings=settings)
    return results


def get_cached_userdata(user_id: str, settings: Settings | None = None) -> Dict[str, Any]:
    """Legacy name, same live-authorized read. Never return an offline snapshot."""
    return ensure_userdata_available(user_id, settings=settings)


def ensure_userdata_history_available(user_id: str, *, force_refresh: bool = False, settings: Settings | None = None) -> list[Dict[str, Any]]:
    return _private_history(_read("history", user_id, force_refresh=force_refresh, settings=_get_settings(settings)))


def ensure_userdata_view_available(user_id: str, *, settings: Settings | None = None) -> Dict[str, Any]:
    """A bounded current/history pair from one verified center publication."""
    cfg = _get_settings(settings)
    deadline = time.monotonic() + 180
    for attempt in range(2):
        current, current_view = _read("current", user_id, force_refresh=bool(attempt), settings=cfg, with_view=True, deadline=deadline)
        history, history_view = _read("history", user_id, force_refresh=bool(attempt), settings=cfg, with_view=True, deadline=deadline)
        if current_view and current_view == history_view:
            return {"userdata": _normalize_payload(current), "snapshots": _private_history(history), "sourceView": current_view}
        if not current_view or not history_view:
            break
    raise UserdataProviderError("中心成绩暂不可用，请稍后重试。", status_code=503)
