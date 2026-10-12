"""Replay prepared contexts through an installed wheel without Sakura or data IO."""

import argparse, hashlib, importlib.abc, io, json, os, resource, sys, time, types
from pathlib import Path
from PIL import Image, ImageFont
from importlib.metadata import version

parser = argparse.ArgumentParser()
parser.add_argument("--evidence", type=Path, required=True)
parser.add_argument("--installed", type=Path, required=True)
args = parser.parse_args()
started = time.monotonic()
sys.dont_write_bytecode = True
blocked = {
    "plugins",
    "taiko_store",
    "taiko_runtime",
    "nonebot",
    "pymysql",
    "requests",
    "httpx",
    "socket",
    "sqlite3",
}


class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *a, **k):
        if fullname.split(".")[0] in blocked:
            raise AssertionError("host/network dependency: " + fullname)


sys.meta_path.insert(0, NoHost())
from taiko_application.score import (
    ScorePresentationContext,
    B30SingleRenderer,
    B30Renderer,
    ScoreInfoRenderer,
    RecommendationRenderer,
)
import taiko_application

assert Path(taiko_application.__file__).is_relative_to(args.installed.resolve())
assert version("sakura-taiko-core") == "0.1.1"
assert version("sakura-taiko-contract") == "0.1.0"
assert version("taiko-application") == "0.2.0"
classes = {
    "b30_single": B30SingleRenderer,
    "b30_render": B30Renderer,
    "drawinfo": ScoreInfoRenderer,
    "recommend_image": RecommendationRenderer,
}
owned = []


def decode(v):
    if isinstance(v, list):
        return [decode(x) for x in v]
    if not isinstance(v, dict):
        return v
    if "__path__" in v:
        return Path(v["__path__"])
    if "__image__" in v:
        with Image.open(v["__image__"]) as image:
            out = image.copy()
        owned.append(out)
        return out
    if "__dict__" in v:
        return {decode(k): decode(value) for k, value in v["__dict__"]}
    if "__tuple__" in v:
        return tuple(decode(x) for x in v["__tuple__"])
    if "__set__" in v:
        return set(decode(x) for x in v["__set__"])
    if "__object__" in v:
        return types.SimpleNamespace(
            **{k: decode(x) for k, x in v["__object__"].items()}
        )
    raise AssertionError("unexpected encoded value")


encoded = json.loads((args.evidence / "contexts.json").read_text())
contexts = {
    name: ScorePresentationContext(**{k: decode(v) for k, v in data.items()})
    for name, data in encoded.items()
}
expected = {
    r["renderer"]: r
    for r in json.loads((args.evidence / "parity.json").read_text())["cases"]
    if r["case"] == "ordinary"
}
roots = {c.assets_base.resolve() for c in contexts.values()}
roots.update(
    {c.layout_assets_base.resolve() for c in contexts.values() if c.layout_assets_base}
)
cgroup = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]


def guard(event, values):
    if event.startswith(("socket.", "subprocess.")):
        raise AssertionError("network/process forbidden")
    if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
        flags = values[2] if len(values) > 2 else 0
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC):
            raise AssertionError("all writes forbidden")
        p = Path(os.fsdecode(values[0])).resolve()
        if not any(p.is_relative_to(root) for root in roots):
            raise AssertionError("read outside resources: " + str(p))


# Resolve Pillow's own lazy font dependencies before locking resource-only reads.
# Host/network/SQL imports are already blocked by NoHost above.
for root in roots:
    ImageFont.truetype(str(root / "fonts/FZPW_GBK.ttf"), 16)
    ImageFont.truetype(str(root / "fonts/DDFont.ttf"), 16)
sys.addaudithook(guard)
results = []
try:
    for name, cls in classes.items():
        renderer = cls(contexts[name])
        result = renderer.render()
        data = result.getvalue() if isinstance(result, io.BytesIO) else result
        with Image.open(io.BytesIO(data)) as im:
            actual = {
                "png_sha256": hashlib.sha256(data).hexdigest(),
                "pixel_sha256": hashlib.sha256(im.tobytes()).hexdigest(),
                "dimensions": list(im.size),
                "mode": im.mode,
            }
        assert all(actual[k] == expected[name][k] for k in actual), name + " parity"
        assert not renderer._owned and not renderer._ICON_CACHE
        results.append({"renderer": name, "status": "PASS", **actual})
finally:
    for image in owned:
        image.close()
print(
    json.dumps(
        {
            "status": "PASS",
            "cases": results,
            "installed": str(args.installed),
            "writes": 0,
            "network": 0,
            "host_dependencies": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "cgroup": cgroup,
        },
        ensure_ascii=False,
    )
)
