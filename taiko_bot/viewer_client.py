from __future__ import annotations

import base64
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .settings import Settings, get_settings


class ViewerClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = int(status_code or 500)
        self.message = str(message)


@dataclass(frozen=True)
class CenterBindSlot:
    slot: int
    taiko_id: str
    visible: int
    is_current: bool
    source: str


def _get_settings(settings: Settings | None = None) -> Settings:
    return settings or get_settings()


def _build_headers(
    settings: Settings,
    *,
    require_developer_token: bool = False,
) -> Dict[str, str]:
    headers = {"Accept": "application/json"}
    token = settings.viewer_developer_token.strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif require_developer_token:
        raise ViewerClientError(
            "未配置 TAIKO_VIEWER_DEVELOPER_TOKEN，无法访问中心受限接口。",
            status_code=500,
        )
    return headers


def _raise_response_error(response: httpx.Response) -> None:
    message = ""
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if isinstance(payload, dict):
        message = str(
            payload.get("statusMessage")
            or payload.get("message")
            or payload.get("detail")
            or ""
        ).strip()
    if not message:
        message = f"请求中心接口失败，HTTP {response.status_code}"
    raise ViewerClientError(message, status_code=response.status_code)


def _request_json(
    method: str,
    url: str,
    *,
    settings: Settings,
    require_developer_token: bool = False,
    params: Optional[Dict[str, Any]] = None,
    json_payload: Optional[Dict[str, Any]] = None,
    timeout: float = 90.0,
) -> Dict[str, Any]:
    headers = _build_headers(
        settings, require_developer_token=require_developer_token
    )
    try:
        with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=True) as client:
            response = client.request(
                method,
                url,
                headers=headers,
                params=params,
                json=json_payload,
            )
    except ViewerClientError:
        raise
    except Exception as exc:
        raise ViewerClientError(f"无法连接中心接口：{exc}", status_code=502) from exc
    if response.status_code >= 400:
        _raise_response_error(response)
    try:
        payload = response.json()
    except Exception as exc:
        raise ViewerClientError("中心接口返回的 JSON 无法解析。") from exc
    if not isinstance(payload, dict):
        raise ViewerClientError("中心接口返回的内容不是对象 JSON。")
    return payload


def viewer_base_url(settings: Settings | None = None) -> str:
    return _get_settings(settings).viewer_base_url.rstrip("/")


def taiko_api_base_url(settings: Settings | None = None) -> str:
    return _get_settings(settings).public_data_base_url.rstrip("/")


def fetch_remote_userdata(
    user_id: str, settings: Settings | None = None
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/developer/userdata/{str(user_id).strip()}",
        settings=cfg,
    )


def proxy_center_userdata_update(
    user_id: str,
    *,
    show_all: bool = False,
    include_image: bool = True,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/userdata/{str(user_id).strip()}/update",
        settings=cfg,
        json_payload={"showAll": show_all, "includeImage": include_image},
        timeout=300.0,
    )


def proxy_center_hiroba_sync(
    user_id: str,
    *,
    email: str = "",
    password: str = "",
    show_all: bool = False,
    include_image: bool = True,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/userdata/{str(user_id).strip()}/sync-hiroba",
        settings=cfg,
        json_payload={
            "email": email,
            "password": password,
            "showAll": show_all,
            "includeImage": include_image,
        },
        timeout=300.0,
    )


def bind_hiroba_credentials(
    *,
    email: str,
    password: str,
    target_taiko_no: str = "",
    configured_by_qq: str = "",
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/hiroba/bind",
        settings=cfg,
        json_payload={
            "email": str(email or "").strip(),
            "password": str(password or "").strip(),
            "targetTaikoNo": str(target_taiko_no or "").strip(),
            "configuredByQq": str(configured_by_qq or "").strip(),
        },
        timeout=180.0,
    )
    taiko_ids = payload.get("taikoIds")
    if not isinstance(taiko_ids, list):
        raise ViewerClientError("中心返回的 Hiroba 绑定结果格式无效。")
    return {
        "taikoIds": [
            str(item or "").strip()
            for item in taiko_ids
            if str(item or "").strip()
        ],
        "bind": _normalize_center_bind_payload(payload.get("bind"))
        if isinstance(payload.get("bind"), dict)
        else None,
    }


def _normalize_center_bind_payload(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not payload.get("found"):
        return None
    current_taiko_id = str(
        payload.get("currentTaikoId") or payload.get("taikoId") or ""
    ).strip()
    if not current_taiko_id:
        return None
    bindings_payload = payload.get("bindings")
    bindings: list[CenterBindSlot] = []
    if isinstance(bindings_payload, list):
        for item in bindings_payload:
            if not isinstance(item, dict):
                continue
            taiko_id = str(item.get("taikoId") or "").strip()
            if not taiko_id:
                continue
            try:
                slot = int(item.get("slot") or 0)
            except Exception:
                slot = 0
            bindings.append(
                CenterBindSlot(
                    slot=max(1, slot),
                    taiko_id=taiko_id,
                    visible=int(item.get("visible") or 0),
                    is_current=bool(item.get("isCurrent")),
                    source=str(item.get("source") or "wahlap").strip().lower()
                    or "wahlap",
                )
            )
    current_source = (
        str(payload.get("currentSource") or "").strip().lower()
        or next(
            (
                item.source
                for item in bindings
                if item.taiko_id == current_taiko_id and item.is_current
            ),
            "wahlap",
        )
    )
    try:
        current_slot = int(payload.get("currentSlot") or 0)
    except Exception:
        current_slot = 0
    if current_slot <= 0:
        current_slot = next(
            (item.slot for item in bindings if item.taiko_id == current_taiko_id),
            1,
        )
    return {
        "id": current_taiko_id,
        "visible": int(payload.get("visible") or 0),
        "currentSlot": max(1, current_slot),
        "currentSource": current_source,
        "bindings": bindings,
    }


def fetch_center_bind_info(
    identity_key: str,
    settings: Settings | None = None,
) -> Optional[Dict[str, Any]]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/bind",
        settings=cfg,
        params={"identityKey": str(identity_key or "").strip()},
        timeout=60.0,
    )
    return _normalize_center_bind_payload(payload)


def proxy_center_bind_upsert(
    identity_key: str,
    taiko_id: str,
    *,
    visible: int = 0,
    source: str = "wahlap",
    settings: Settings | None = None,
) -> Optional[Dict[str, Any]]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/bind",
        settings=cfg,
        json_payload={
            "identityKey": str(identity_key or "").strip(),
            "taikoId": str(taiko_id or "").strip(),
            "visible": int(visible or 0),
            "source": str(source or "").strip().lower() or "wahlap",
        },
        timeout=90.0,
    )
    return _normalize_center_bind_payload(payload)


def proxy_center_bind_switch_current(
    identity_key: str,
    slot: int,
    settings: Settings | None = None,
) -> Optional[Dict[str, Any]]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/bind/current",
        settings=cfg,
        json_payload={
            "identityKey": str(identity_key or "").strip(),
            "slot": int(slot),
        },
        timeout=90.0,
    )
    return _normalize_center_bind_payload(payload)


def fetch_remote_userdata_history(
    user_id: str,
    settings: Settings | None = None,
) -> list[Dict[str, Any]]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/userdata/{str(user_id).strip()}/history",
        settings=cfg,
        timeout=90.0,
    )
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, list):
        raise ViewerClientError("中心返回的历史快照格式无效。")
    normalized: list[Dict[str, Any]] = []
    for item in snapshots:
        if not isinstance(item, dict):
            continue
        captured_at = str(item.get("capturedAt") or "").strip()
        snapshot_payload = item.get("payload")
        if not captured_at or not isinstance(snapshot_payload, dict):
            continue
        normalized.append({"capturedAt": captured_at, "payload": snapshot_payload})
    return normalized


def has_center_hiroba_credentials(
    taiko_id: str, settings: Settings | None = None
) -> bool:
    cfg = _get_settings(settings)
    payload = _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/hiroba/credentials/{str(taiko_id).strip()}",
        settings=cfg,
        timeout=60.0,
    )
    return bool(payload.get("hasCredentials"))


def fetch_wahlap_player_profile(
    user_id: str, settings: Settings | None = None
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/wahlap/player/{str(user_id).strip()}",
        settings=cfg,
    )


def fetch_wahlap_ranking(
    song_id: int,
    diff: int,
    *,
    province_id: int | None = None,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    params: Dict[str, Any] = {}
    if province_id is not None:
        params["provinceId"] = province_id
    return _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/wahlap/ranking/{int(song_id)}/{int(diff)}",
        settings=cfg,
        params=params,
    )


def fetch_arcade_snapshot(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/arcades/snapshot",
        settings=cfg,
        require_developer_token=False,
        timeout=120.0,
    )


def fetch_asset_bundle_metadata(settings: Settings | None = None) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    headers = _build_headers(cfg, require_developer_token=False)
    try:
        with httpx.Client(timeout=30.0, trust_env=False, follow_redirects=True) as client:
            response = client.head(
                f"{cfg.viewer_base_url}/api/taiko/assets/latest", headers=headers
            )
    except Exception as exc:
        raise ViewerClientError(f"获取资源包元信息失败：{exc}", status_code=502) from exc
    if response.status_code >= 400:
        _raise_response_error(response)
    sha256 = str(response.headers.get("X-Taiko-Bundle-Sha256") or "").strip().lower()
    if not sha256:
        raise ViewerClientError("中心资源包响应缺少 X-Taiko-Bundle-Sha256。")
    return {
        "sha256": sha256,
        "size": int(response.headers.get("Content-Length") or 0),
        "updatedAt": str(response.headers.get("X-Taiko-Bundle-Updated-At") or "").strip(),
    }


def download_asset_bundle(
    target_path: Path, settings: Settings | None = None
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    headers = _build_headers(cfg, require_developer_token=False)
    try:
        with httpx.Client(timeout=300.0, trust_env=False, follow_redirects=True) as client:
            with client.stream(
                "GET", f"{cfg.viewer_base_url}/api/taiko/assets/latest", headers=headers
            ) as response:
                if response.status_code >= 400:
                    _raise_response_error(response)
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with target_path.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        if chunk:
                            handle.write(chunk)
                return {
                    "sha256": str(
                        response.headers.get("X-Taiko-Bundle-Sha256") or ""
                    ).strip().lower(),
                    "updatedAt": str(
                        response.headers.get("X-Taiko-Bundle-Updated-At") or ""
                    ).strip(),
                }
    except ViewerClientError:
        raise
    except Exception as exc:
        raise ViewerClientError(f"下载资源包失败：{exc}", status_code=502) from exc


def decode_image_bytes(payload: Dict[str, Any]) -> Optional[bytes]:
    raw = str(payload.get("imageBase64") or "").strip()
    if not raw:
        return None
    try:
        return base64.b64decode(raw)
    except Exception as exc:
        raise ViewerClientError("中心返回的图片数据无法解码。") from exc
