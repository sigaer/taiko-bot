"""Use installed QQ parameter builders; no global patches and no send retry."""
from __future__ import annotations

import asyncio
from importlib.metadata import PackageNotFoundError, version
import hashlib
import inspect
import json
from pathlib import Path
import platform
from time import perf_counter
import time
from types import SimpleNamespace

from .config import Blocked


def inventory():
    from nonebot.adapters.qq import Bot
    packages = {}
    for name in ("taiko-bot", "taiko-application", "nonebot2", "nonebot-adapter-qq", "httpx", "httpcore", "Pillow"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return dict(packages=packages,
                python=platform.python_version(),
                installed_source_sha256={name:hashlib.sha256(Path(inspect.getsourcefile(obj)).read_bytes()).hexdigest()
                    for name,obj in {"qq_api_builders":Bot,"httpx_driver_session":__import__('nonebot.drivers.httpx',fromlist=['Session']).Session}.items()},
                post_group_files=str(inspect.signature(Bot.post_group_files.func)),
                post_group_messages=str(inspect.signature(Bot.post_group_messages.func)),
                source="installed_environment",
                adapter_httpx_connection_policy="installed driver creates one Session/AsyncClient per request; no shared HTTP pool",
                file_data="accepted by installed signature; platform support requires live preflight",
                upload_response_id="installed PostGroupFilesReturn omits id; probe inspects raw response for presence only")


class ApiFailure(Exception):
    def __init__(self, category, *, code=None, http_status=None, unknown=False):
        self.category, self.code, self.http_status, self.unknown = category, code, http_status, unknown

    def public(self):
        return dict(category=self.category, code=self.code, http_status=self.http_status,
                    result_unknown=self.unknown)


class HttpTrace:
    """Ignore all trace info payloads: they contain sockets, bodies and URLs."""
    def __init__(self):
        self.open = {}
        self.intervals = []
        self.connects = 0

    async def __call__(self, name, info):
        now = perf_counter()
        base, _, outcome = name.rpartition(".")
        if outcome == "started":
            self.open[base] = now
        elif outcome in ("complete", "failed") and base in self.open:
            start = self.open.pop(base)
            allowed = ("connect_tcp", "start_tls", "send_request_headers", "send_request_body",
                       "receive_response_headers", "receive_response_body")
            if base.endswith(allowed):
                self.intervals.append(dict(phase=base, duration_ms=round((now - start) * 1000, 3), outcome=outcome))
            if base.endswith("connect_tcp"):
                self.connects += 1


class Transport:
    def __init__(self, bot, config, *, connected=True):
        self.bot, self.config = bot, config
        self.connected = connected
        self.raw = None
        self.call_record = None

    async def call(self, api, arguments, record, persist):
        from nonebot.adapters.qq import Bot
        self.call_record = record
        self._persist = persist
        self.raw = None
        started = perf_counter()
        record.update(api=api, status="pending", started_at=time.time(), http_requests=0, timings={}, http_trace=[],
                      auth_source="connected_bot" if self.connected else "isolated_bot_existing_config",
                      unmeasurable=["pool_wait", "dns_separate_from_tcp", "exact_first_response_byte"])
        persist()
        facade = SimpleNamespace(adapter=self.bot.adapter, _request=self._request)
        try:
            # Class-level descriptor invokes the actual installed parameter builder,
            # without touching the live Bot or invoking global API hooks/loggers.
            result = await asyncio.wait_for(getattr(Bot, api)(facade, **arguments), self.config.timeout_seconds)
            record["status"] = "acknowledged"
            return result
        except ApiFailure:
            record["status"] = "error"
            raise
        except asyncio.CancelledError:
            record["status"] = "unknown"
            raise
        except (TimeoutError, OSError):
            record["status"] = "unknown"
            raise ApiFailure("timeout_or_network", unknown=True) from None
        except Exception:
            record["status"] = "unknown" if record["http_requests"] else "error"
            raise ApiFailure("adapter_or_transport_error", unknown=bool(record["http_requests"])) from None
        finally:
            record["total_ms"] = round((perf_counter() - started) * 1000, 3)
            record["finished_at"] = time.time()
            persist()

    async def _request(self, setup):
        r = self.call_record
        before_token = getattr(self.bot, "_access_token", None)
        started = perf_counter()
        headers = await self.bot.get_authorization_header()
        r["timings"]["authorization_ms"] = round((perf_counter() - started) * 1000, 3)
        r["access_token_changed"] = before_token != getattr(self.bot, "_access_token", None)
        setup.headers.update(headers)
        r["http_requests"] += 1  # Write-ahead API accounting, even if process dies next.
        self.persist()
        started = perf_counter()
        if self.config.transport == "adapter":
            response = await self.bot.adapter.request(setup)
            r["unmeasurable"].extend(["client_creation", "tcp_tls", "body_encode_and_send", "response_headers_wait", "body_read"])
            content, status = response.content, response.status_code
        else:
            # Same installed driver session factory, proxy, version and timeout.
            # Only this private session is instrumented, never the production pool.
            trace = HttpTrace()
            session = self.bot.adapter.driver.get_session(version=setup.version, proxy=setup.proxy)
            created = perf_counter()
            await session.setup()
            r["timings"]["client_creation_ms"] = round((perf_counter() - created) * 1000, 3)
            try:
                client = session.client
                built = perf_counter()
                request = client.build_request(setup.method, str(setup.url), content=setup.content,
                    data=setup.data, files=setup.files, json=setup.json,
                    params=setup.url.raw_query_string, headers=tuple(setup.headers.items()),
                    cookies=setup.cookies.jar, timeout=session._get_timeout(setup.timeout),
                    extensions={"trace": trace})
                r["timings"]["request_build_ms"] = round((perf_counter() - built) * 1000, 3)
                response = await client.send(request, stream=True, follow_redirects=False)
                try:
                    status = response.status_code
                    content = await response.aread()
                finally:
                    await response.aclose()
            finally:
                r["http_trace"] = trace.intervals
                r["connection_sample"] = "new_connection" if trace.connects else "reused_or_unobserved"
                await session.close()
        r["timings"]["http_complete_ms"] = round((perf_counter() - started) * 1000, 3)
        r["http_status"] = status
        decoded = perf_counter()
        try:
            body = json.loads(content) if content else {}
        except (ValueError, TypeError):
            raise ApiFailure("invalid_json_response", http_status=status, unknown=True) from None
        finally:
            r["timings"]["json_decode_ms"] = round((perf_counter() - decoded) * 1000, 3)
        self.raw = body if isinstance(body, dict) else {}
        if not 200 <= status < 300 or status in (201, 202) or self.raw.get("code", 0) not in (0, None):
            code = self.raw.get("code")
            code = code if type(code) is int else None
            category = "permission_or_auth" if status in (401, 403) else "rate_or_quota" if status == 429 or code == 22009 else "platform_rejection"
            # Ambiguous server failures may have delivered a message already.
            raise ApiFailure(category, code=code, http_status=status, unknown=status >= 500 or status in (201, 202))
        return body

    def persist(self):
        self._persist()
