from __future__ import annotations

from typing import Any, Dict

import httpx

from .settings import Settings, get_settings


class ManualAccountApiError(RuntimeError):
    pass


async def call_manual_account_api(
    identity_key: str,
    action: str,
    *,
    settings: Settings | None = None,
    **payload: Any,
) -> Dict[str, Any]:
    cfg = settings or get_settings()
    token = cfg.bot_service_token.strip()
    if not token:
        raise ManualAccountApiError("bot 服务令牌未配置")
    body = {
        "identityKey": str(identity_key or "").strip(),
        "action": action,
        **payload,
    }
    try:
        async with httpx.AsyncClient(
            timeout=30.0, trust_env=False, follow_redirects=True
        ) as client:
            response = await client.post(
                f"{cfg.viewer_base_url.rstrip('/')}/api/taiko/internal/manual",
                headers={"X-Taiko-Bot-Token": token},
                json=body,
            )
    except httpx.HTTPError as exc:
        raise ManualAccountApiError(f"中心服务暂时不可用：{exc}") from exc
    if response.is_success:
        data = response.json()
        return data if isinstance(data, dict) else {"ok": True}
    try:
        error = response.json()
    except ValueError:
        error = {}
    nested = error.get("data") if isinstance(error.get("data"), dict) else {}
    message = str(
        error.get("statusMessage")
        or error.get("message")
        or nested.get("statusMessage")
        or ""
    ).strip()
    raise ManualAccountApiError(
        message or f"中心服务返回 HTTP {response.status_code}"
    )
