"""Load the installed client plugin and dispatch synthetic OneBot events offline."""

import argparse, asyncio, base64, hashlib, io, json, os, sys, types
from pathlib import Path

p = argparse.ArgumentParser()
for name in ("sandbox", "installed", "images", "output"):
    p.add_argument("--" + name, type=Path, required=True)
a = p.parse_args()
a.sandbox.mkdir(parents=True, exist_ok=True)
os.chdir(a.sandbox)
os.environ.update(
    TAIKO_BOT_ROOT=str(a.sandbox),
    TAIKO_VIEWER_BASE_URL="https://fixture.invalid",
    TAIKO_PUBLIC_DATA_BASE_URL="https://fixture.invalid",
    MPLCONFIGDIR=str(a.sandbox / "mpl"),
)


def guard(event, args):
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        raise AssertionError("Forbidden integration IO: " + event)
    if (
        event == "open"
        and isinstance(args[0], str)
        and args[0].startswith("/home/sigaer/")
    ):
        raise AssertionError("Forbidden checkout/private file")


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

assert Path(module.__file__).is_relative_to(a.installed)
assert Path(app.__file__).is_relative_to(a.installed)
assert version("sakura-taiko-core") == "0.1.2"
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
module.ensure_userdata_available = lambda *a, **k: {"songs": []}
module.ensure_userdata_view_available = lambda *a, **k: {
    "userdata": {"songs": []},
    "snapshots": [],
}
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
    setattr(module, name, lambda *a, **k: png)
module.generate_recommend_image = lambda *a, **k: io.BytesIO(png)
for name in ("b30", "score", "song", "constant", "progress", "recommendation"):
    original = getattr(app, "execute_" + name)

    def counted(*args, _name=name, _fn=original, **kwargs):
        calls.append(_name)
        return _fn(*args, **kwargs)

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
    for i, (name, text, options) in enumerate(cases):
        calls.clear()
        sent.clear()
        errors.clear()
        state.clear()
        state.update(options)
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
        rows.append(
            {
                "command": name,
                "input": text,
                "options": options,
                "application_calls": list(calls),
                "sent": list(sent),
            }
        )
    a.output.write_text(
        json.dumps(
            {
                "status": "PASS",
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
