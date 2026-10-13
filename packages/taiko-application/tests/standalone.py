"""Exercise the installed distribution with forbidden host imports and IO."""

import argparse
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import resource
import sys
from fixture import FIXTURE

parser = argparse.ArgumentParser()
parser.add_argument("--asset-root", type=Path, required=True)
parser.add_argument("--installed-root", type=Path, required=True)
args = parser.parse_args()
sys.dont_write_bytecode = True
blocked = {
    "plugins",
    "nonebot",
    "taiko_store",
    "taiko_runtime",
    "pymysql",
    "requests",
    "httpx",
    "socket",
}


class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in blocked:
            raise AssertionError(
                "Application imported forbidden host/network dependency: " + fullname
            )


sys.meta_path.insert(0, NoHost())
allowed = [
    Path(sys.prefix).resolve(),
    Path(sys.base_prefix).resolve(),
    args.installed_root.resolve(),
    args.asset_root.resolve(),
]


def guard(event, values):
    if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system"}:
        raise AssertionError("Application attempted external IO")
    if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(values[0])).resolve()
        mode = values[1] or ""
        flags = values[2] or 0
        if any(x in mode for x in "wax+") or flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT
        ):
            raise AssertionError("Application attempted a filesystem write")
        if not any(path.is_relative_to(root) for root in allowed):
            raise AssertionError(
                "Application attempted unprovided file input: " + str(path)
            )


sys.addaudithook(guard)
from taiko_application.dani import (
    DaniAssets,
    DaniInputs,
    DaniProgressService,
    DaniProgressRenderer,
)
from taiko_application.dani.rating import build_rating_context
import taiko_application

assert (
    Path(taiko_application.__file__)
    .resolve()
    .is_relative_to(args.installed_root.resolve())
)
from sakura_taiko_core.chart.identity import build_group_maps

groups = build_group_maps(FIXTURE["song_catalog"])
default_ids = {sid: group.default_id for sid, group in groups[1].items()}
duplicates = sorted(g.ids for g in groups[0].values() if len(g.ids) > 1)
inputs = DaniInputs(
    {"2025": FIXTURE["grade_payload"]},
    FIXTURE["song_catalog"],
    FIXTURE["roll_catalog"],
    build_rating_context(
        FIXTURE["rating_config"], default_ids=default_ids, duplicate_groups=duplicates
    ),
)
model = DaniProgressService(inputs).prepare(
    900001,
    "六段",
    version="2025",
    explicit_version=True,
    userdata=FIXTURE["userdata"],
    dojo_payload=FIXTURE["userdata"]["dojo"],
    dan_id=FIXTURE["dan_id"],
)
assets = DaniAssets(
    args.asset_root / "templates/dani_up.png",
    args.asset_root / "templates/dani_down.png",
    args.asset_root / "icons/diff",
    args.asset_root / "icons/dani",
    args.asset_root / "fonts/FZPW_GBK.ttf",
    args.asset_root / "fonts/DDFont.ttf",
)
renderer = DaniProgressRenderer(assets)
png = renderer.render(model)
assert not renderer._images, "Renderer retained images after render"
assert model.derived["dynamic_rate_enabled"] is True
assert (
    hashlib.sha256(png).hexdigest()
    == "474e31251e977817840770198769d5b63d8ef9228414ffd48629992f2b2fc4df"
)
assert not blocked.intersection(sys.modules), "Host dependency escaped import guard"
print(
    json.dumps(
        {
            "standalone": "PASS",
            "source": taiko_application.__file__,
            "dynamic_rate": True,
            "png_sha256": hashlib.sha256(png).hexdigest(),
            "writes": 0,
            "network": 0,
            "host_dependencies": 0,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        }
    )
)
