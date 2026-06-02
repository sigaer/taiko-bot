from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

from .settings import Settings, get_settings


class ViewerClientError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 500) -> None:
        super().__init__(message)
        self.status_code = int(status_code or 500)
        self.message = str(message)


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
        require_developer_token=True,
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
        require_developer_token=True,
        json_payload={"showAll": show_all, "includeImage": include_image},
        timeout=300.0,
    )


def proxy_center_hiroba_sync(
    user_id: str,
    *,
    email: str,
    password: str,
    show_all: bool = False,
    include_image: bool = True,
    settings: Settings | None = None,
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/userdata/{str(user_id).strip()}/sync-hiroba",
        settings=cfg,
        require_developer_token=True,
        json_payload={
            "email": email,
            "password": password,
            "showAll": show_all,
            "includeImage": include_image,
        },
        timeout=300.0,
    )


def fetch_hiroba_playable_cards(
    *,
    email: str,
    password: str,
    settings: Settings | None = None,
) -> list[Dict[str, Any]]:
    cfg = _get_settings(settings)
    payload = _request_json(
        "POST",
        f"{cfg.viewer_base_url}/api/taiko/proxy/hiroba/cards",
        settings=cfg,
        require_developer_token=True,
        json_payload={
            "email": str(email or "").strip(),
            "password": str(password or "").strip(),
        },
        timeout=180.0,
    )
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise ViewerClientError("中心返回的 Hiroba 账号列表格式无效。")
    return [item for item in cards if isinstance(item, dict)]


def fetch_wahlap_player_profile(
    user_id: str, settings: Settings | None = None
) -> Dict[str, Any]:
    cfg = _get_settings(settings)
    return _request_json(
        "GET",
        f"{cfg.viewer_base_url}/api/taiko/proxy/wahlap/player/{str(user_id).strip()}",
        settings=cfg,
        require_developer_token=True,
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
        require_developer_token=True,
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
