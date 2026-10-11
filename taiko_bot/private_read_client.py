"""Bounded conditional private reads. Every request reaches live center authority."""
from dataclasses import dataclass
import json
import re
import time
from urllib.parse import quote, urlsplit

import httpx

from .settings import Settings
from .viewer_client import ViewerClientError, _build_headers

MAX_RESPONSE_BYTES = 32 * 1024 * 1024
READ_DEADLINE_SECONDS = 90


@dataclass(frozen=True)
class PrivateReadReply:
    payload: dict | None
    etag: str | None
    not_modified: bool = False
    source_view: str | None = None


def valid_etag(kind: str, etag: object) -> bool:
    return isinstance(etag, str) and bool(re.fullmatch(r'"taiko-' + kind + r'-v1-[a-f0-9]{64}"', etag))


def valid_source_view(value: object) -> bool:
    if isinstance(value, str) and re.fullmatch(r"merged-v1-[a-f0-9]{64}", value):
        return True
    match = re.fullmatch(r"v1-[a-f0-9]{32}-(0|[1-9][0-9]{0,15})", value) if isinstance(value, str) else None
    return bool(match and int(match[1]) <= 9007199254740991)


def fetch_private_read(kind: str, source: str, *, settings: Settings, etag: str | None = None, deadline: float | None = None) -> PrivateReadReply:
    if kind not in {"current", "history"} or not re.fullmatch(r"(?:[A-Za-z0-9_-]{1,128}|u0v1_[A-Za-z0-9_-]{1,192})", source):
        raise ViewerClientError("成绩账号标识无效。", status_code=400)
    base = settings.viewer_base_url.strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ViewerClientError("中心成绩地址无效。", status_code=500)
    headers = _build_headers(settings, require_developer_token=True)
    if etag is not None:
        if not valid_etag(kind, etag):
            raise ViewerClientError("中心成绩缓存标识无效。", status_code=503)
        headers["If-None-Match"] = etag
    path = "/api/developer/userdata/" + quote(source, safe="") if kind == "current" else "/api/taiko/proxy/userdata/" + quote(source, safe="") + "/history"
    if kind == "history":
        path += "?format=raw-v1"
    started = time.monotonic()
    ends_at = min(started + READ_DEADLINE_SECONDS, deadline) if deadline is not None else started + READ_DEADLINE_SECONDS
    if ends_at <= started:
        raise ViewerClientError("中心成绩响应超出读取上限。", status_code=503)
    try:
        with httpx.Client(timeout=httpx.Timeout(min(10, ends_at - started), connect=min(5, ends_at - started)), trust_env=False, follow_redirects=False) as client:
            with client.stream("GET", base + path, headers=headers) as response:
                if time.monotonic() >= ends_at:
                    raise ViewerClientError("中心成绩响应超出读取上限。", status_code=503)
                tag = response.headers.get("etag")
                observed = response.headers.get("x-taiko-source-view")
                source_view = observed if valid_source_view(observed) else None
                if response.status_code == 304:
                    if etag is None or tag != etag or not valid_etag(kind, tag):
                        raise ViewerClientError("中心成绩缓存确认无效。", status_code=503)
                    return PrivateReadReply(None, tag, True, source_view)
                if response.status_code != 200:
                    messages = {401: "中心访问凭据已失效。", 403: "没有访问该账号成绩的权限。", 404: "未找到该账号的成绩。", 429: "中心请求额度已用尽。"}
                    raise ViewerClientError(messages.get(response.status_code, "中心成绩暂不可用，请稍后重试。"), status_code=response.status_code if response.status_code >= 400 else 502)
                raw = bytearray()
                for chunk in response.iter_bytes(chunk_size=65536):
                    if len(raw) + len(chunk) > MAX_RESPONSE_BYTES or time.monotonic() >= ends_at:
                        raise ViewerClientError("中心成绩响应超出读取上限。", status_code=503)
                    raw.extend(chunk)
                try:
                    payload = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ViewerClientError("中心成绩响应无效。", status_code=503) from None
                if not isinstance(payload, dict):
                    raise ViewerClientError("中心成绩响应无效。", status_code=503)
                return PrivateReadReply(payload, tag if valid_etag(kind, tag) else None, source_view=source_view)
    except ViewerClientError:
        raise
    except Exception:
        raise ViewerClientError("无法连接中心成绩接口。", status_code=502) from None
