from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from nonebot import get_bots, get_driver
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from pydantic import BaseModel

__plugin_meta__ = PluginMetadata(
    name="bot-pool-metrics",
    description="Expose a loopback-only bot pool snapshot for health checks.",
    usage="",
    type="application",
    extra={},
)


class BotPoolMetricsConfig(BaseModel):
    bot_pool_metrics_service_name: str = "taiko-bot"


config = get_plugin_config(BotPoolMetricsConfig)
SERVICE_NAME = config.bot_pool_metrics_service_name.strip() or "taiko-bot"

driver = get_driver()
router = APIRouter()


def is_loopback_host(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1", "localhost"}


def normalize_self_ids(values: list[object]) -> list[str]:
    normalized = []
    for value in values:
        self_id = str(value).strip()
        if not self_id or not self_id.isdigit() or self_id == "0":
            continue
        if self_id not in normalized:
            normalized.append(self_id)
    normalized.sort()
    return normalized


@router.get("/internal/bot-pool")
async def handle_bot_pool(request: Request):
    host = getattr(request.client, "host", None)
    if not is_loopback_host(host):
        raise HTTPException(status_code=403, detail="loopback only")

    connected_self_ids = normalize_self_ids(list(get_bots().keys()))
    return {
        "service": SERVICE_NAME,
        "connected_self_ids": connected_self_ids,
        "count": len(connected_self_ids),
        "generated_at": datetime.now().astimezone().isoformat(),
    }


driver.server_app.include_router(router)
