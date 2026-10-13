"""Installed Developer API provider rejects revoked/expired/cache fallback offline."""

import argparse, json, os, sys
from pathlib import Path
from dataclasses import replace

p = argparse.ArgumentParser()
p.add_argument("--sandbox", type=Path, required=True)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
os.environ["TAIKO_BOT_ROOT"] = str(a.sandbox)
from taiko_bot.settings import get_settings
from taiko_bot import userdata_provider as provider, private_read_client as client
from taiko_bot.private_read_cache import PrivateReadCache
import httpx

cfg = replace(
    get_settings(),
    viewer_base_url="https://fixture.invalid",
    viewer_developer_token="synthetic-only",
)
real_client = httpx.Client
calls = []
state = {}


def response(request):
    calls.append(request.url.path)
    if state.get("timeout"):
        raise httpx.ReadTimeout("synthetic timeout")
    return httpx.Response(
        state.get("status", 200),
        json={"songs": [{"song_no": 1, "level": 4, "high_score": 900000}]},
        headers={"etag": '"taiko-current-v1-' + "a" * 64 + '"'},
    )


client.httpx.Client = lambda **kw: real_client(
    transport=httpx.MockTransport(response), **kw
)


def guard(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        raise AssertionError("Forbidden IO " + event)


sys.addaudithook(guard)
rows = []
for failure in (
    401,
    403,
    404,
    429,
    500,
    503,
    "timeout",
    "missing-token",
    "invalid-identity",
):
    provider._PRIVATE_READ_CACHE = PrivateReadCache()
    state.clear()
    calls.clear()
    assert provider.ensure_userdata_available("1001", settings=cfg)["songs"]
    if isinstance(failure, int):
        state["status"] = failure
    if failure == "timeout":
        state["timeout"] = True
    changed = (
        replace(cfg, viewer_developer_token="") if failure == "missing-token" else cfg
    )
    identity = "../invalid" if failure == "invalid-identity" else "1001"
    try:
        provider.ensure_userdata_available(identity, settings=changed)
    except provider.UserdataProviderError as e:
        rows.append(
            {
                "failure": failure,
                "status_code": e.status_code,
                "requests": len(calls),
                "result": "denied",
            }
        )
    else:
        raise AssertionError("Private fallback accepted " + str(failure))
    if failure not in ("missing-token", "invalid-identity"):
        assert provider._PRIVATE_READ_CACHE.diagnostics()["entries"] == 0
    assert not cfg.userdata_dir.exists()
a.output.write_text(
    json.dumps({"status": "PASS", "count": len(rows), "cases": rows}, indent=2)
)
print("PRIVATE_TRANSPORT_PASS", len(rows))
