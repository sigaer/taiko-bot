from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import httpx
import websockets
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from websockets.exceptions import ConnectionClosed, InvalidStatusCode


logger = logging.getLogger("onebot_runtime.gateway")

HOP_BY_HOP_HEADERS = {
    b"connection",
    b"keep-alive",
    b"proxy-authenticate",
    b"proxy-authorization",
    b"te",
    b"trailer",
    b"transfer-encoding",
    b"upgrade",
}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _derive_core_http_url(core_ws_url: str) -> str:
    parsed = urlsplit(core_ws_url)
    scheme = "https" if parsed.scheme == "wss" else "http"
    path = parsed.path
    suffix = "/onebot/v11/ws"
    if path.endswith(suffix):
        path = path[: -len(suffix)]
    return urlunsplit((scheme, parsed.netloc, path.rstrip("/"), "", ""))


@dataclass
class GatewayConfig:
    core_ws_url: str = os.getenv(
        "ONEBOT_GATEWAY_CORE_WS_URL", "ws://127.0.0.1:13998/onebot/v11/ws"
    )
    core_http_url: str = os.getenv("ONEBOT_GATEWAY_CORE_HTTP_URL", "").strip()
    service_name: str = os.getenv("ONEBOT_GATEWAY_SERVICE_NAME", "onebot-gateway")
    duplicate_takeover_idle: float = _env_float(
        "ONEBOT_GATEWAY_DUPLICATE_TAKEOVER_IDLE", 0.0
    )
    allow_cross_host_takeover: bool = _env_bool(
        "ONEBOT_GATEWAY_ALLOW_CROSS_HOST_TAKEOVER", True
    )
    rebind_grace: float = _env_float("ONEBOT_GATEWAY_REBIND_GRACE", 8.0)
    pending_max_age: float = _env_float("ONEBOT_GATEWAY_PENDING_MAX_AGE", 65.0)
    upstream_open_timeout: float = _env_float(
        "ONEBOT_GATEWAY_UPSTREAM_OPEN_TIMEOUT", 30.0
    )
    upstream_retry_base: float = _env_float(
        "ONEBOT_GATEWAY_UPSTREAM_RETRY_BASE", 0.25
    )
    upstream_retry_max: float = _env_float("ONEBOT_GATEWAY_UPSTREAM_RETRY_MAX", 5.0)
    http_proxy_timeout: float = _env_float("ONEBOT_GATEWAY_HTTP_PROXY_TIMEOUT", 30.0)
    upstream_max_size: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.core_http_url:
            self.core_http_url = _derive_core_http_url(self.core_ws_url)
        raw_max_size = os.getenv("ONEBOT_GATEWAY_UPSTREAM_MAX_SIZE", "").strip()
        if raw_max_size and raw_max_size.lower() not in {"none", "null"}:
            try:
                self.upstream_max_size = int(raw_max_size)
            except ValueError:
                self.upstream_max_size = None


@dataclass
class ActiveExternalConnection:
    connection_id: str
    peer: str
    peer_host: str
    websocket: WebSocket
    accepted_at: float
    last_activity: float
    headers: List[Tuple[str, str]]


@dataclass
class GatewayFlowState:
    forwarded_in: int = 0
    forwarded_out: int = 0
    connected_at: float = field(default_factory=time.monotonic)

    def reset(self) -> None:
        self.forwarded_in = 0
        self.forwarded_out = 0
        self.connected_at = time.monotonic()


def get_peer(websocket: WebSocket) -> str:
    host = getattr(websocket.client, "host", "unknown")
    port = getattr(websocket.client, "port", None)
    return f"{host}:{port}" if port is not None else host


def get_peer_host(websocket: WebSocket) -> str:
    return getattr(websocket.client, "host", "unknown")


def normalize_self_id(self_id: Optional[str]) -> str:
    return self_id.strip() if isinstance(self_id, str) else ""


def is_valid_self_id(self_id: str) -> bool:
    return bool(self_id) and self_id.isdigit() and self_id != "0"


def build_upstream_headers(websocket: WebSocket) -> List[Tuple[str, str]]:
    headers: List[Tuple[str, str]] = [
        ("x-self-id", normalize_self_id(websocket.headers.get("x-self-id")))
    ]
    for name in ("authorization", "x-client-role", "user-agent"):
        value = websocket.headers.get(name)
        if value:
            headers.append((name, value))
    return headers


async def close_external(
    websocket: WebSocket, code: int = 1000, reason: str = ""
) -> None:
    try:
        await websocket.close(code=code, reason=reason)
    except Exception:
        pass


async def close_internal(upstream) -> None:
    try:
        await upstream.close()
    except Exception:
        pass


def _websockets_connect_kwargs(headers: List[Tuple[str, str]]) -> dict:
    params = inspect.signature(websockets.connect).parameters
    key = "additional_headers" if "additional_headers" in params else "extra_headers"
    kwargs: dict = {key: headers}
    if "proxy" in params:
        kwargs["proxy"] = None
    return kwargs


class GatewaySlot:
    def __init__(self, self_id: str, config: GatewayConfig):
        self.self_id = self_id
        self.config = config
        self.lock = asyncio.Lock()
        self.external: Optional[ActiveExternalConnection] = None
        self.last_peer = ""
        self.last_peer_host = ""
        self.last_disconnect_at = 0.0
        self.waiting_rebind = False
        self.rebind_deadline = 0.0
        self.rebind_timer_task: Optional[asyncio.Task] = None
        self.upstream_headers: List[Tuple[str, str]] = [("x-self-id", self_id)]
        self.upstream = None
        self.upstream_ready = asyncio.Event()
        self.upstream_connect_task: Optional[asyncio.Task] = None
        self.upstream_reader_task: Optional[asyncio.Task] = None
        self.flow_state = GatewayFlowState()

    def _connect_task_active_locked(self) -> bool:
        return self.upstream_connect_task is not None and not self.upstream_connect_task.done()

    def _takeover_reason_locked(
        self, existing: ActiveExternalConnection, peer_host: str, now: float
    ) -> Optional[str]:
        if existing.peer_host == peer_host:
            return "same_host"
        if not self.config.allow_cross_host_takeover:
            return None
        if self.config.duplicate_takeover_idle <= 0:
            return "cross_host"
        idle_for = now - existing.last_activity
        if idle_for >= self.config.duplicate_takeover_idle:
            return f"idle_{idle_for:.1f}s"
        return None

    def _should_keepalive_locked(self) -> bool:
        return self.external is not None or self.waiting_rebind

    def _cancel_rebind_timer_locked(self) -> None:
        if self.rebind_timer_task is not None and not self.rebind_timer_task.done():
            self.rebind_timer_task.cancel()
        self.rebind_timer_task = None

    def _schedule_rebind_timer_locked(self) -> None:
        if self.rebind_deadline <= 0:
            return
        if self.rebind_timer_task is None or self.rebind_timer_task.done():
            self.rebind_timer_task = asyncio.create_task(
                self._rebind_timeout_loop(self.rebind_deadline)
            )

    async def bind_external(
        self, external: ActiveExternalConnection
    ) -> Tuple[bool, Optional[ActiveExternalConnection], Optional[str], str, bool]:
        now = time.monotonic()
        replaced = None
        reject_reason = None
        existing_peer = self.last_peer or "<unknown>"
        should_connect = False
        async with self.lock:
            if self.external is not None:
                existing_peer = self.external.peer
                reject_reason = self._takeover_reason_locked(
                    self.external, external.peer_host, now
                )
                if reject_reason is None:
                    reject_reason = (
                        "cross_host_conflict"
                        if self.external.peer_host != external.peer_host
                        else "active_conflict"
                    )
                    return False, None, reject_reason, existing_peer, False
                replaced = self.external
            elif (
                self.waiting_rebind
                and self.last_peer_host
                and self.last_peer_host != external.peer_host
            ):
                return False, None, "cross_host_conflict", existing_peer, False

            self.external = external
            self.last_peer = external.peer
            self.last_peer_host = external.peer_host
            self.upstream_headers = list(external.headers)
            self.waiting_rebind = False
            self.rebind_deadline = 0.0
            self._cancel_rebind_timer_locked()
            should_connect = self.upstream is None and not self._connect_task_active_locked()
        return True, replaced, reject_reason, existing_peer, should_connect

    async def external_disconnected(self, connection_id: str) -> bool:
        upstream_to_close = None
        async with self.lock:
            if self.external is None or self.external.connection_id != connection_id:
                return False
            current = self.external
            self.external = None
            self.last_peer = current.peer
            self.last_peer_host = current.peer_host
            self.last_disconnect_at = time.monotonic()
            if self.upstream is not None and self.config.rebind_grace > 0:
                self.waiting_rebind = True
                self.rebind_deadline = self.last_disconnect_at + self.config.rebind_grace
                self._schedule_rebind_timer_locked()
            else:
                self.waiting_rebind = False
                self.rebind_deadline = 0.0
                self._cancel_rebind_timer_locked()
                upstream_to_close = self.upstream
        if upstream_to_close is not None:
            await close_internal(upstream_to_close)
        return True

    async def ensure_upstream_connect(self) -> None:
        async with self.lock:
            if self.upstream is not None or self._connect_task_active_locked():
                return
            if not self._should_keepalive_locked():
                return
            self.upstream_connect_task = asyncio.create_task(self._connect_upstream_loop())

    async def wait_for_upstream(self, connection_id: str):
        while True:
            stale_external = None
            timeout = 1.0
            async with self.lock:
                current = self.external
                if current is None or current.connection_id != connection_id:
                    return None
                if self.upstream is not None and self.upstream_ready.is_set():
                    return self.upstream
                if self.config.pending_max_age > 0:
                    remaining = self.config.pending_max_age - (
                        time.monotonic() - current.accepted_at
                    )
                    if remaining <= 0:
                        stale_external = current
                        self.external = None
                        self.waiting_rebind = False
                        self.rebind_deadline = 0.0
                        self._cancel_rebind_timer_locked()
                    else:
                        timeout = min(1.0, max(0.05, remaining))
            if stale_external is not None:
                await close_external(
                    stale_external.websocket, code=1013, reason="Upstream unavailable"
                )
                return None
            await self.ensure_upstream_connect()
            try:
                await asyncio.wait_for(self.upstream_ready.wait(), timeout=timeout)
            except asyncio.TimeoutError:
                continue

    async def run_external_session(
        self, external: ActiveExternalConnection
    ) -> None:
        try:
            while True:
                try:
                    data = await external.websocket.receive_text()
                except WebSocketDisconnect:
                    return
                except Exception:
                    return

                async with self.lock:
                    current = self.external
                    if current is None or current.connection_id != external.connection_id:
                        return
                    current.last_activity = time.monotonic()

                upstream = await self.wait_for_upstream(external.connection_id)
                if upstream is None:
                    return
                try:
                    await upstream.send(data)
                    self.flow_state.forwarded_in += 1
                except Exception:
                    logger.warning("upstream send failed self_id=%s", self.self_id)
                    await close_internal(upstream)
        finally:
            await self.external_disconnected(external.connection_id)

    async def _connect_upstream_loop(self) -> None:
        retry_delay = max(0.05, self.config.upstream_retry_base)
        while True:
            async with self.lock:
                if self.upstream is not None:
                    self.upstream_connect_task = None
                    return
                if not self._should_keepalive_locked():
                    self.upstream_connect_task = None
                    return
                headers = list(self.upstream_headers)
            try:
                upstream = await websockets.connect(
                    self.config.core_ws_url,
                    open_timeout=self.config.upstream_open_timeout,
                    ping_interval=40,
                    ping_timeout=40,
                    max_queue=64,
                    max_size=self.config.upstream_max_size,
                    **_websockets_connect_kwargs(headers),
                )
            except InvalidStatusCode as exc:
                logger.warning(
                    "upstream rejected self_id=%s status=%s",
                    self.self_id,
                    exc.status_code,
                )
            except Exception:
                logger.exception("upstream connect failed self_id=%s", self.self_id)
            else:
                async with self.lock:
                    if not self._should_keepalive_locked():
                        close_now = True
                        self.upstream_connect_task = None
                    else:
                        close_now = False
                        self.upstream = upstream
                        self.upstream_ready.set()
                        self.upstream_connect_task = None
                        self.flow_state.reset()
                        self.upstream_reader_task = asyncio.create_task(
                            self._run_upstream_reader(upstream)
                        )
                        logger.info(
                            "gateway connected self_id=%s upstream=%s",
                            self.self_id,
                            self.config.core_ws_url,
                        )
                if close_now:
                    await close_internal(upstream)
                    return
                return
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, max(retry_delay, self.config.upstream_retry_max))

    async def _run_upstream_reader(self, upstream) -> None:
        try:
            async for data in upstream:
                async with self.lock:
                    if self.upstream is not upstream:
                        return
                    external = self.external
                    if external is not None:
                        external.last_activity = time.monotonic()
                if external is None:
                    continue
                try:
                    await external.websocket.send_text(data)
                    self.flow_state.forwarded_out += 1
                except Exception:
                    await self.external_disconnected(external.connection_id)
        except ConnectionClosed:
            pass
        except Exception:
            logger.exception("upstream reader failed self_id=%s", self.self_id)
        finally:
            was_current = False
            should_retry = False
            async with self.lock:
                if self.upstream is upstream:
                    was_current = True
                    self.upstream = None
                    self.upstream_ready.clear()
                    self.upstream_reader_task = None
                    should_retry = self._should_keepalive_locked()
            if was_current:
                logger.info("gateway disconnected self_id=%s", self.self_id)
            if was_current and should_retry:
                await self.ensure_upstream_connect()

    async def _rebind_timeout_loop(self, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.monotonic()))
        except asyncio.CancelledError:
            return
        upstream_to_close = None
        async with self.lock:
            if (
                not self.waiting_rebind
                or self.external is not None
                or self.rebind_deadline != deadline
            ):
                return
            self.waiting_rebind = False
            self.rebind_deadline = 0.0
            self.rebind_timer_task = None
            upstream_to_close = self.upstream
        if upstream_to_close is not None:
            await close_internal(upstream_to_close)

    async def snapshot(self) -> dict:
        async with self.lock:
            return {
                "self_id": self.self_id,
                "external": self.external.peer if self.external else None,
                "upstream_connected": self.upstream is not None,
                "waiting_rebind": self.waiting_rebind,
                "forwarded_in": self.flow_state.forwarded_in,
                "forwarded_out": self.flow_state.forwarded_out,
            }


class OneBotGateway:
    def __init__(self, config: Optional[GatewayConfig] = None):
        self.config = config or GatewayConfig()
        self.slots: Dict[str, GatewaySlot] = {}
        self.lock = asyncio.Lock()

    async def get_slot(self, self_id: str) -> GatewaySlot:
        async with self.lock:
            slot = self.slots.get(self_id)
            if slot is None:
                slot = GatewaySlot(self_id, self.config)
                self.slots[self_id] = slot
            return slot

    async def snapshot(self) -> dict:
        return {
            "service": self.config.service_name,
            "core_ws_url": self.config.core_ws_url,
            "core_http_url": self.config.core_http_url,
            "slots": [await slot.snapshot() for slot in self.slots.values()],
        }


def create_app(config: Optional[GatewayConfig] = None) -> FastAPI:
    gateway = OneBotGateway(config)
    app = FastAPI()

    @app.get("/gateway/health")
    async def health() -> dict:
        return {"ok": True, "service": gateway.config.service_name}

    @app.get("/gateway/status")
    async def status() -> JSONResponse:
        return JSONResponse(await gateway.snapshot())

    @app.websocket("/onebot/v11/ws")
    async def onebot_ws(websocket: WebSocket) -> None:
        self_id = normalize_self_id(websocket.headers.get("x-self-id"))
        if not is_valid_self_id(self_id):
            await websocket.close(code=1008, reason="Missing or invalid X-Self-ID")
            return
        external = ActiveExternalConnection(
            connection_id=uuid.uuid4().hex,
            peer=get_peer(websocket),
            peer_host=get_peer_host(websocket),
            websocket=websocket,
            accepted_at=time.monotonic(),
            last_activity=time.monotonic(),
            headers=build_upstream_headers(websocket),
        )
        slot = await gateway.get_slot(self_id)
        accepted, replaced, reject_reason, existing_peer, should_connect = (
            await slot.bind_external(external)
        )
        if not accepted:
            logger.warning(
                "reject duplicate self_id=%s peer=%s existing=%s reason=%s",
                self_id,
                external.peer,
                existing_peer,
                reject_reason,
            )
            await websocket.close(code=1008, reason=f"Duplicate X-Self-ID: {reject_reason}")
            return
        await websocket.accept()
        if replaced is not None:
            logger.info(
                "takeover self_id=%s new=%s old=%s reason=%s",
                self_id,
                external.peer,
                replaced.peer,
                reject_reason,
            )
            await close_external(replaced.websocket, code=1012, reason="Replaced")
        if should_connect:
            await slot.ensure_upstream_connect()
        await slot.run_external_session(external)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    )
    async def proxy_http(path: str, request: Request) -> Response:
        base = gateway.config.core_http_url.rstrip("/")
        target = f"{base}/{path}" if path else base
        if request.url.query:
            target = f"{target}?{request.url.query}"
        raw_headers = [
            (key.decode("latin-1"), value.decode("latin-1"))
            for key, value in request.headers.raw
            if key.lower() not in HOP_BY_HOP_HEADERS and key.lower() != b"host"
        ]
        try:
            async with httpx.AsyncClient(
                timeout=gateway.config.http_proxy_timeout,
                follow_redirects=False,
            ) as client:
                proxied = await client.request(
                    request.method,
                    target,
                    content=await request.body(),
                    headers=raw_headers,
                )
        except httpx.RequestError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        response_headers = {
            key: value
            for key, value in proxied.headers.items()
            if key.lower().encode("latin-1") not in HOP_BY_HOP_HEADERS
        }
        return Response(
            content=proxied.content,
            status_code=proxied.status_code,
            headers=response_headers,
            media_type=proxied.headers.get("content-type"),
        )

    return app
