import os
from typing import Any, Dict

import httpx


class ManualAccountApiError(RuntimeError):
    pass


def _base_url() -> str:
    return os.getenv("TAIKO_VIEWER_INTERNAL_BASE_URL", "http://127.0.0.1:3100").rstrip("/")


def _service_token() -> str:
    token = os.getenv("TAIKO_BOT_SERVICE_TOKEN", "").strip()
    if not token:
        raise ManualAccountApiError("bot 服务令牌未配置")
    return token


async def call_manual_account_api(
    identity_key: str, action: str, **payload: Any
) -> Dict[str, Any]:
    body = {"identityKey": str(identity_key or "").strip(), "action": action, **payload}
    try:
        # This endpoint is always the local center service. Ignoring inherited
        # proxy variables avoids sending credentials to a proxy and prevents a
        # broken desktop proxy from taking the bot-center link offline.
        async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
            response = await client.post(
                f"{_base_url()}/api/taiko/internal/manual",
                headers={"X-Taiko-Bot-Token": _service_token()},
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
    message = str(
        error.get("statusMessage")
        or error.get("message")
        or error.get("data", {}).get("statusMessage")
        or ""
    ).strip()
    raise ManualAccountApiError(message or f"中心服务返回 HTTP {response.status_code}")
