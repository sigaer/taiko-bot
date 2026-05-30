from __future__ import annotations

from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .public_data import sync_public_datasets
from .settings import get_settings
from .sqlite_db import ensure_schema
from .storage import (
    ensure_storage_layout,
    list_userdata_history,
    read_config,
    read_draw_guess_db,
    read_multi_bind_store,
    read_userdata,
    write_config,
    write_draw_guess_db,
    write_multi_bind_store,
    write_userdata_with_history,
)


class JsonPayload(BaseModel):
    payload: Dict[str, Any]


class UserdataPayload(BaseModel):
    payload: Dict[str, Any]
    source: str = "manual"


def create_app() -> FastAPI:
    settings = get_settings()
    ensure_storage_layout(settings)
    ensure_schema()

    app = FastAPI(title="taiko-bot local data api")

    @app.get("/health")
    async def health() -> Dict[str, Any]:
        return {"ok": True, "baseUrl": settings.local_data_api_base_url}

    @app.post("/v1/public/sync")
    async def sync_public() -> Dict[str, Any]:
        return sync_public_datasets(settings)

    @app.get("/v1/config")
    async def get_config() -> Dict[str, Any]:
        return read_config(settings)

    @app.put("/v1/config")
    async def put_config(payload: JsonPayload) -> Dict[str, Any]:
        write_config(payload.payload, settings)
        return {"ok": True}

    @app.get("/v1/runtime/multi-bind")
    async def get_multi_bind() -> Dict[str, Any]:
        return read_multi_bind_store(settings)

    @app.put("/v1/runtime/multi-bind")
    async def put_multi_bind(payload: JsonPayload) -> Dict[str, Any]:
        write_multi_bind_store(payload.payload, settings)
        return {"ok": True}

    @app.get("/v1/runtime/draw-guess")
    async def get_draw_guess() -> Dict[str, Any]:
        return read_draw_guess_db(settings)

    @app.put("/v1/runtime/draw-guess")
    async def put_draw_guess(payload: JsonPayload) -> Dict[str, Any]:
        write_draw_guess_db(payload.payload, settings)
        return {"ok": True}

    @app.get("/v1/userdata/{user_id}")
    async def get_userdata(user_id: str) -> Dict[str, Any]:
        payload = read_userdata(user_id, settings)
        if payload is None:
            raise HTTPException(status_code=404, detail="userdata not found")
        return payload

    @app.put("/v1/userdata/{user_id}")
    async def put_userdata(user_id: str, payload: UserdataPayload) -> Dict[str, Any]:
        write_userdata_with_history(
            user_id,
            payload.payload,
            source=payload.source,
            settings=settings,
        )
        return {"ok": True}

    @app.get("/v1/userdata/{user_id}/history")
    async def get_userdata_history(user_id: str) -> Dict[str, Any]:
        return {
            "userId": user_id,
            "files": [path.name for path in list_userdata_history(user_id, settings=settings)],
        }

    return app


app = create_app()
