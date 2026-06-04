from __future__ import annotations

from dataclasses import asdict
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from plugins.utils.arcade_map import query_taiko_shops_by_city, sync_taiko_arcade_snapshot
from .public_data import get_asset_sync_summary, sync_public_datasets
from .settings import get_settings
from .sqlite_db import ensure_schema
from .storage import (
    ensure_storage_layout,
    read_draw_guess_db,
    write_draw_guess_db,
)
from .userdata_provider import (
    UserdataProviderError,
    ensure_userdata_available,
    ensure_userdata_history_available,
)


class JsonPayload(BaseModel):
    payload: Dict[str, Any]


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_storage_layout(settings)
    ensure_schema()

    app = FastAPI(title="taiko-bot local data api")

    @app.get("/health")
    async def health(request: Request) -> Dict[str, Any]:
        base_url = str(request.base_url).rstrip("/")
        root_path = str(request.scope.get("root_path") or "").rstrip("/")
        asset_summary = get_asset_sync_summary(settings)
        return {
            "ok": True,
            "baseUrl": f"{base_url}{root_path}" if root_path else base_url,
            "coreReady": bool(asset_summary.get("coreReady")),
            "installedResources": asset_summary.get("installedResources") or [],
            "syncingResources": asset_summary.get("syncingResources") or [],
            "failedResources": asset_summary.get("failedResources") or [],
        }

    @app.post("/v1/public/sync")
    async def sync_public() -> Dict[str, Any]:
        return sync_public_datasets(settings)

    @app.get("/v1/runtime/multi-bind")
    async def get_multi_bind() -> Dict[str, Any]:
        raise HTTPException(
            status_code=410, detail="当前槽位已由 viewer 中心管理，本地 multi-bind 接口已停用。"
        )

    @app.put("/v1/runtime/multi-bind")
    async def put_multi_bind(payload: JsonPayload) -> Dict[str, Any]:
        _ = payload
        raise HTTPException(
            status_code=410, detail="当前槽位已由 viewer 中心管理，本地 multi-bind 接口已停用。"
        )

    @app.get("/v1/runtime/draw-guess")
    async def get_draw_guess() -> Dict[str, Any]:
        return read_draw_guess_db(settings)

    @app.put("/v1/runtime/draw-guess")
    async def put_draw_guess(payload: JsonPayload) -> Dict[str, Any]:
        write_draw_guess_db(payload.payload, settings)
        return {"ok": True}

    @app.get("/v1/userdata/{user_id}")
    async def get_userdata(user_id: str) -> Dict[str, Any]:
        try:
            return ensure_userdata_available(user_id, settings=settings)
        except UserdataProviderError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.put("/v1/userdata/{user_id}")
    async def put_userdata(user_id: str, payload: JsonPayload) -> Dict[str, Any]:
        _ = (user_id, payload)
        raise HTTPException(
            status_code=410, detail="本地 userdata 写入已移除，请使用 viewer 中心作为权威数据源。"
        )

    @app.get("/v1/userdata/{user_id}/history")
    async def get_userdata_history(user_id: str) -> Dict[str, Any]:
        try:
            snapshots = ensure_userdata_history_available(user_id, settings=settings)
        except UserdataProviderError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"userId": user_id, "snapshots": snapshots}

    @app.post("/v1/arcades/sync")
    async def sync_arcades() -> Dict[str, Any]:
        try:
            return sync_taiko_arcade_snapshot(force=True)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.get("/v1/arcades/query")
    async def query_arcades(city: str) -> Dict[str, Any]:
        try:
            result = await query_taiko_shops_by_city(city)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return asdict(result)

    return app


app = create_app()
