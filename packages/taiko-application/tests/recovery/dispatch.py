"""Dispatch actual host matchers with offline provider fixtures."""

import argparse, asyncio, base64, hashlib, io, json, os, sys, types
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("sandbox", "installed", "images", "output"):
    p.add_argument("--" + name, type=Path, required=True)
p.add_argument('--host', choices=['center','client'], required=True)
p.add_argument('--source', type=Path)
p.add_argument('--support', type=Path)
a = p.parse_args()
if a.host == 'center':
    sys.path[:0] = [str(a.source), str(a.support)]
    os.environ.update(PYTHON_MEMORY_RUNTIME_ROOT=str(a.support),
                      PYTHON_MEMORY_METRICS_DIR=str(a.sandbox / 'metrics'),
                      TAIKO_RUNTIME_ENV_FILE=str(a.sandbox / 'absent.env'))
a.sandbox.mkdir(parents=True, exist_ok=True)
os.chdir(a.source if a.host == 'center' else a.sandbox)
os.environ.update(
    TAIKO_BOT_ROOT=str(a.sandbox),
    TAIKO_VIEWER_BASE_URL="https://fixture.invalid",
    TAIKO_PUBLIC_DATA_BASE_URL="https://fixture.invalid",
    MPLCONFIGDIR=str(a.sandbox / "mpl"),
)


io_violations = []

def guard(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        io_violations.append(event)
        raise AssertionError("Forbidden integration IO: " + event)
    if (
        event == "open"
        and isinstance(args[0], str)
        and args[0].startswith(("/home/sigaer/", "/opt/", "/etc/taiko"))
    ):
        io_violations.append(str(args[0]))
        raise AssertionError("Forbidden checkout/private file")


# Redirect only outer filesystem inputs, never application functions. Physical
# opens are still subject to the production-path audit guard below.
redirected = set()
if a.host == "center":
    import builtins
    original_open, original_io_open, original_stat = builtins.open, io.open, os.stat
    def fixture_path(path):
        if isinstance(path, (str, os.PathLike)):
            raw = os.fspath(path)
            prefix = "/home/sigaer/taiko/"
            if raw.startswith(prefix):
                redirected.add(raw)
                return str(a.source / raw[len(prefix):])
        return path
    builtins.open = lambda file, *args, **kwargs: original_open(fixture_path(file), *args, **kwargs)
    io.open = lambda file, *args, **kwargs: original_io_open(fixture_path(file), *args, **kwargs)
    os.stat = lambda path, *args, **kwargs: original_stat(fixture_path(path), *args, **kwargs)
sys.addaudithook(guard)
import nonebot

nonebot.init(driver="~fastapi", log_level="ERROR")
plugin = nonebot.load_plugin("plugins.taiko")
assert plugin is not None, "Installed plugin failed to load"
module = plugin.module
from importlib.metadata import version
from nonebot.adapters.onebot.v11 import Adapter, Bot, PrivateMessageEvent, Message
from nonebot.message import handle_event, run_postprocessor
from nonebot.matcher import matchers
from taiko_application import commands as app
from PIL import Image

assert Path(module.__file__).is_relative_to(a.source if a.host == 'center' else a.installed)
assert Path(app.__file__).is_relative_to(a.installed)
assert version("sakura-taiko-core") == ("0.1.1" if a.host == "center" else "0.1.2")
assert version("sakura-taiko-contract") == "0.1.0"
assert all("/home/sigaer/git/Sakura_bot" not in x for x in sys.path)
names = ("taikob", "music_info", "what_song", "const_query", "matcher", "taikorec")
selected = {getattr(module, n) for n in names}
assert all(m.handlers for m in selected)
# Keep actual registered matcher/rule/handler objects; exclude unrelated products.
for priority, group in list(matchers.items()):
    matchers[priority] = [m for m in group if m in selected]
nonebot.get_driver().register_adapter(Adapter)
adapter = nonebot.get_adapter(Adapter)
bot = Bot(adapter, "90000")
sent = []
calls = []
errors = []
state = {}
reads = []


@run_postprocessor
async def capture_error(exception: Exception | None):
    if exception is not None:
        errors.append([type(exception).__name__, str(exception)])


def image_summary(raw):
    with Image.open(io.BytesIO(raw)) as im:
        return {
            "bytes_sha256": hashlib.sha256(raw).hexdigest(),
            "pixels_sha256": hashlib.sha256(im.tobytes()).hexdigest(),
            "dimensions": list(im.size),
            "mode": im.mode,
        }


async def call_api(self, bot, api, **data):
    segments = []
    for seg in data.get("message", []):
        value = dict(seg.data)
        if seg.type == "image" and str(value.get("file", "")).startswith("base64://"):
            value["file"] = image_summary(base64.b64decode(value["file"][9:]))
        segments.append({"type": seg.type, "data": value})
    sent.append({"api": api, "segments": segments})
    return {"message_id": 1}


adapter._call_api = types.MethodType(call_api, adapter)


async def assets(*args):
    return True


module._ensure_asset_resources_ready = assets
module._resolve_read_bind_target = lambda e: state.get("permission", {"user_id": "42"})
module._taiko_bind_usage_message = lambda e: "fixture binding help"
module.queryMusic = lambda query: [] if state.get("empty") else [[1, "Neon"]]
module._resolve_what_song_query = lambda *args: []
module._load_star_progress_set = lambda: {6}
# Inject catalogue retrieval, not the real dani request parser.
import plugins.utils.dani_progress as dani

dani._load_grade_index = lambda version: {}
module.ensure_userdata_available = lambda *a, **k: (reads.append("current") or {"songs": []})
module.ensure_userdata_view_available = lambda *a, **k: {
    "userdata": {"songs": []},
    "snapshots": [],
}
module._load_user_song_records = lambda *a: (reads.append("songs") or [])
module.compute_all_from_userdata = lambda *a, **k: [] if state.get("empty") else [{"fixture_rating":10}]
module.compute_all_from_userdata_records = lambda songs: (
    [] if state.get("empty") else [{"fixture_rating": 10}]
)
module.compute_recommendations_for_user = lambda **k: []
module.query_charts_by_const = lambda *a, **k: []
# Public fixed PNGs are renderer-provider inputs; real handler JPEG conversion and sending remain active.
png = (a.images / "ordinary-b30_render.png").read_bytes()
for name in (
    "render_b30_image",
    "generate_score_image",
    "render_const_query_notice",
    "render_star_progress_image_bytes",
):
    def render(*args, **kwargs):
        reads.append("render")
        if state.get("provider_error"): raise FileNotFoundError("synthetic missing input")
        return png
    setattr(module, name, render)
module.generate_recommend_image = lambda *a, **k: io.BytesIO(png)
for name in ("b30", "score", "song", "constant", "progress", "recommendation"):
    original = getattr(app, "execute_" + name)

    def counted(*args, _name=name, _fn=original, **kwargs):
        calls.append(_name)
        result = _fn(*args, **kwargs)
        if "revoke_after_application" in state:
            state["permission"] = state["revoke_after_application"]
        return result

    setattr(module, "execute_" + name, counted)


async def main():
    rows = []
    cases = [
        ("b30", "taikob30", {}),
        ("score", "tinfo Neon", {}),
        ("song", "Neon是什么歌", {}),
        ("constant", "查定数6.6", {}),
        ("progress", "6星进度", {}),
        ("recommendation", "taikorec", {}),
        ("b30", "taikob30", {"empty": True}),
        ("score", "tinfo Neon", {"empty": True}),
        ("score", "tinfo Neon", {"provider_error": True}),
        ("constant", "查定数6.6 0", {}),
        ("recommendation", "taikorec invalid", {}),
    ]
    for name, text in [
        ("b30", "taikob30"),
        ("score", "tinfo Neon"),
        ("progress", "6星进度"),
        ("recommendation", "taikorec"),
    ]:
        for permission in (403, 404, {"error": "fixture expired identity"}):
            cases.append((name, text, {"permission": permission}))
    if a.host == 'client':
        for name,text in [('b30','taikob30'),('score','tinfo Neon'),('progress','6星进度'),('recommendation','taikorec')]:
            for failure in (403,404,{"error":"fixture timeout"},{"user_id":"43"}):
                cases.append((name,text,{"revoke_after_application":failure}))
    for i, (name, text, options) in enumerate(cases):
        reads.clear()
        calls.clear()
        sent.clear()
        errors.clear()
        state.clear()
        state.update(options)
        if a.host == "center" and text == "taikob30": text = "taikob30 v1"
        event = PrivateMessageEvent(
            time=1,
            self_id=90000,
            post_type="message",
            message_type="private",
            sub_type="friend",
            message_id=i + 1,
            user_id=10001,
            message=Message(text),
            original_message=Message(text),
            raw_message=text,
            font=0,
            sender={"user_id": 10001, "nickname": "Fixture"},
            to_me=True,
        )
        await handle_event(bot, event)
        assert not errors, (name, errors)
        assert calls == ([] if "permission" in options else [name]), (name, calls, sent)
        assert len(sent) == 1, (name, sent)
        if "permission" in options:
            assert not reads, (name, reads)
            assert all(seg["type"] != "image" for msg in sent for seg in msg["segments"])

        if "revoke_after_application" in options:
            assert all(seg["type"] != "image" for msg in sent for seg in msg["segments"])
            assert any(seg["data"].get("text") == "授权已失效，请重新查询。" for msg in sent for seg in msg["segments"])
        rows.append(
            {
                "command": name,
                "input": text,
                "options": options,
                "application_calls": list(calls), "private_reads_and_renders":list(reads),
                "sent": list(sent),
            }
        )
    sources = {name:getattr(m, '__file__', None) for name,m in sys.modules.items() if name in ('plugins.taiko','runtime_memory','taiko_application','sakura_taiko_core','sakura_taiko_contract')}
    if a.host == 'center':
        assert Path(sources['runtime_memory']).is_relative_to(a.support)
    assert not io_violations, io_violations
    a.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "host":a.host, "sources":sources, "fixture_path_redirects": sorted(redirected), "center_wheel":"NOT_REQUIRED",
                "count": len(rows),
                "plugin": module.__file__,
                "application": app.__file__,
                "core": version("sakura-taiko-core"),
                "dispatch": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("INSTALLED_PLUGIN_DISPATCH_PASS", len(rows))


asyncio.run(main())
