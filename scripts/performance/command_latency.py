"""Synthetic update/progress replay; public assets only, no SQL or transport."""
import argparse
import copy
import hashlib
import importlib
import inspect
import io
import json
import os
from pathlib import Path
import resource
import statistics
import sys
import time

parser = argparse.ArgumentParser()
parser.add_argument("--fixture", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--profile", choices=("center", "client"), default="center")
parser.add_argument("--png-level", type=int, choices=range(10))
parser.add_argument("--progress-only", action="store_true")
parser.add_argument("--updates-only", action="store_true")
parser.add_argument("--repetitions", type=int, choices=range(3, 11), default=3)
args = parser.parse_args()
assert os.environ.get("QA_RUN_ID"), "Use the bounded QA runner"
sys.dont_write_bytecode = True
root = args.fixture.resolve()
os.chdir(root)
os.environ.update(TAIKO_CENTER_ROOT=str(root), TAIKO_BOT_ROOT=str(root),
    TAIKO_RUNTIME_ROOT=str(root), TAIKO_USERDATA_DIR=str(root/"userdata"),
    TAIKO_RUNTIME_ENV_FILE=str(root/"absent.env"), MPLBACKEND="Agg", MPLCONFIGDIR=str(root/"mpl"))
if args.profile == "client":
    sys.path.insert(0, "/var/tmp/taiko-b30-performance/core-client")
def guard(event, values):
    if event in ("socket.connect", "socket.getaddrinfo", "sqlite3.connect"):
        raise AssertionError("Benchmark external IO prohibited")
    if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(values[0])).absolute()
        if str(path).startswith(("/home/sigaer/taiko/", "/etc/taiko", "/home/sigaer/config/")):
            raise AssertionError("Benchmark production input prohibited")
sys.addaudithook(guard)
import nonebot
nonebot.init(driver="~fastapi", log_level="CRITICAL", taiko_song_profile=args.profile,
    taiko_song_public_root=str(root))
from PIL import Image
Image.init()
encode_times = []
original_save = Image.Image.save
def timed_save(image, fp, format=None, **kwargs):
    if format == "PNG" and args.png_level is not None:
        kwargs.pop("optimize", None)
        kwargs["compress_level"] = args.png_level
    started = time.perf_counter()
    try:
        return original_save(image, fp, format=format, **kwargs)
    finally:
        if format == "PNG":
            encode_times.append(round((time.perf_counter()-started)*1000, 3))
Image.Image.save = timed_save
from taiko_bot.runtime.player.render_resources import request_resources
render = importlib.import_module(f"taiko_bot.runtime.player.{args.profile}.progress_support.render")
catalog = importlib.import_module(f"taiko_bot.runtime.player.{args.profile}.progress_support.progress_catalog")
current = json.loads((root/"current.json").read_text())
rows = []
def measure(name, function, *, history=None):
    encode_times.clear()
    if history is not None:
        history.reads = 0
    samples = []
    signatures = []
    for _ in range(args.repetitions):
        started = time.perf_counter()
        png = function()
        samples.append(round((time.perf_counter()-started)*1000, 3))
        with Image.open(io.BytesIO(png)) as image:
            rgb = image.convert("RGB")
            try:
                signatures.append((image.size, hashlib.sha256(rgb.tobytes()).hexdigest()))
            finally:
                rgb.close()
    assert len(set(signatures)) == 1, "Unstable image content"
    row = dict(command=name, milliseconds=samples, warm_median_ms=statistics.median(samples[1:]),
        pixels=signatures[0], png_bytes=len(png), encode_ms=list(encode_times))
    if history is not None:
        row["history_decode_calls"] = history.reads
    rows.append(row)
    print(json.dumps(row, ensure_ascii=False), flush=True)

pass_keys = catalog.available_pass_progress_keys()
pass_key = min(pass_keys, key=lambda x:abs(float(x)-9)) if pass_keys else "9.0"
progress_cases = [
    ("10星进度", render.render_star_progress_image_bytes, dict(star_value=10)),
    ("10星进度 2", render.render_star_progress_image_bytes, dict(star_value=10, page=2)),
    (pass_key+"过关进度", render.render_pass_progress_image_bytes, dict(decimal=pass_key)),
    ("9.0综合进度", render.render_progress_image_bytes, dict(decimal="9.0")),
]
for name, function, kwargs in ([] if args.updates_only else progress_cases):
    # Same request-owned resources used by the command; old renderers ignore it.
    wrapped = request_resources(function)
    measure(name, lambda wrapped=wrapped, kwargs=kwargs: wrapped(111, userdata=current, **kwargs))

if not args.updates_only:
    custom = json.loads((root/"songs/music_donda_list.json").read_text())
    custom_name = "SS" if "SS" in custom else next(iter(custom))
    measure(custom_name+"进度", lambda: request_resources(render.render_progress_image_bytes_by_list)(
        111, progress_name=custom_name, userdata=current))
    dani = importlib.import_module(f"taiko_bot.runtime.player.{args.profile}.progress_support.dani_progress")
    measure("虹2025六段进度", lambda: request_resources(dani.render_dani_progress_image_bytes)(
        111, grade_name="六段", version="2025", explicit_version=True, userdata=current))

if args.profile == "center" and not args.progress_only:
    from taiko_bot.runtime.player.center import draw_dress as dress
    # Synthetic profile has no earned titles; exclude custom-title DB/API discovery.
    dress.infer_song_title_showcase = lambda *a, **kw: []
    before = copy.deepcopy(current)
    for song in before["songs"][:6]:
        song.update(full_combo_cnt=0, dondaful_combo_cnt=0, ng_cnt=2, ok_cnt=20)
    after = copy.deepcopy(before)
    for song in after["songs"][:6]:
        song.update(full_combo_cnt=1, ng_cnt=0)
    class View:
        def __init__(self, history_count):
            self.reads = 0
            self.current = json.dumps(after)
            snapshots = [dict(before, _meta={"full":True})]
            snapshots += [dict(_meta={"full":False}, songs=[])]*(history_count-2)
            snapshots.append(dict(_meta={"full":False}, songs=after["songs"][:6]))
            self.history = {f"data_20260101_{i//3600:02}{i//60%60:02}{i%60:02}_000000.json":json.dumps(p)
                for i,p in enumerate(snapshots)}
        def decoded(self, key="current"):
            if key == "current":
                return json.loads(self.current)
            self.reads += 1
            return json.loads(self.history[key.split("/",1)[1]])
        def history_names(self):
            return list(self.history)
    direct = "previous_userdata" in inspect.signature(dress.render_update_changes_image).parameters
    for count in (2, 100):
        view = View(count)
        for show_all in (False, True):
            kwargs = dict(score_view=view, show_all=show_all)
            if direct:
                kwargs["previous_userdata"] = before
            measure(f"更新广场{' 全部' if show_all else ''} / {count} history",
                lambda kwargs=kwargs: dress.render_update_changes_image(111, **kwargs), history=view)

report = dict(profile=args.profile, synthetic=True, repetitions=args.repetitions, cases=rows,
    peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
