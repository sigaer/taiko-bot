"""Real legacy PNG parity. Only out-of-scope acquisition/profile inputs are fixtures."""

from __future__ import annotations
import argparse, copy, datetime, hashlib, importlib.util, io, json, os, resource, sys, time, types
from dataclasses import replace, fields, is_dataclass
from pathlib import Path
from unittest.mock import patch
from importlib.metadata import version

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fixture import FIXTURE
from PIL import Image, ImageDraw, ImageFont
from sakura_taiko_core.rating import v1, v2
from sakura_taiko_core.dimension import v1 as dims
from sakura_taiko_core.score import calculation
from sakura_taiko_core.models.calculation import V2SongData
from taiko_application.score import (
    ScorePresentationContext,
    B30SingleRenderer,
    B30Renderer,
    ScoreInfoRenderer,
    RecommendationRenderer,
)

CLASSES = {
    "b30_single": B30SingleRenderer,
    "b30_render": B30Renderer,
    "drawinfo": ScoreInfoRenderer,
    "recommend_image": RecommendationRenderer,
}


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def summary(value):
    data = value.getvalue() if isinstance(value, io.BytesIO) else value
    with Image.open(io.BytesIO(data)) as image:
        image.load()
        return {
            "png_sha256": digest(data),
            "pixel_sha256": digest(image.tobytes()),
            "dimensions": list(image.size),
            "mode": image.mode,
        }


def module(name):
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    sys.dont_write_bytecode = True
    require(version("sakura-taiko-core") == "0.1.1", "Core pin")
    require(version("sakura-taiko-contract") == "0.1.0", "Contract pin")
    provenance = json.loads(Path(__file__).with_name("provenance.json").read_text())
    for name, expected in provenance["reference"].items():
        require(
            digest((args.reference / name).read_bytes()) == expected,
            "reference " + name,
        )
    for name, expected in provenance["assets"].items():
        require(digest((args.assets / name).read_bytes()) == expected, "asset " + name)
    output = args.output.resolve()
    assets = args.assets.resolve()
    state = {"application": False, "entries": [], "old_io": [], "previous": {}}

    def audit(event, values):
        if event.startswith(("socket.", "subprocess.")):
            raise AssertionError("network/process forbidden")
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(values[0])).resolve()
            flags = values[2] if len(values) > 2 else 0
            writing = isinstance(flags, int) and flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
            )
            if writing and (state["application"] or not p.is_relative_to(output)):
                raise AssertionError("unexpected write")
            if p.is_relative_to("/home/sigaer/taiko") and not p.is_relative_to(
                "/home/sigaer/taiko/.venv"
            ):
                raise AssertionError("live data read denied")
            if state["application"] and not any(
                p.is_relative_to(root)
                for root in [assets, output / "missing", Path("/usr/share/fonts")]
            ):
                raise AssertionError("Application read outside resources: " + str(p))

    sys.addaudithook(audit)
    song = {
        "id": 278,
        "song_name": "花漾",
        "song_name_jp": "花漾 ～Flourishing Blossoms～",
        "type": "南梦宫原创音乐",
        "bpm": "140",
        **{f"level_{i}": ("9" if i == 5 else "-") for i in range(1, 6)},
    }
    cfg = copy.deepcopy(FIXTURE["rating_config"])
    chart = next(
        v for v in cfg["songs"].values() if int(v["id"]) == 278 and int(v["level"]) == 5
    )
    cfg["songs"] = {"278-5": chart}
    consts = v1.build_const_table(cfg["const_table"]["const_to_score"])
    rating_index = {(278, 5): chart}
    v2_chart = V2SongData(
        278, 5, "花漾", 541, 8.5, 9.3, 9.8, 35.0, 34.0, 37.0, 30.0, 25.0
    )
    v2map = {(278, 5): v2_chart}
    (output / "songs").mkdir(exist_ok=True)
    (output / "userdata").mkdir(exist_ok=True)
    (output / "songs/song_data.json").write_text(json.dumps([song]))
    (output / "songs/rating_structured_with_ids.json").write_text(json.dumps(cfg))

    # Shared profile/dress images are fixture inputs from the unextracted draw_dress boundary.
    # No migrated renderer function is stubbed.
    def profile(*, base, draw, **kw):
        draw.rounded_rectangle((12, 14, 380, 98), 8, fill=(28, 95, 148, 230))
        draw.text(
            (24, 30), "Synthetic Player", font=ImageFont.load_default(), fill="white"
        )
        return (12, 14, 380, 98)

    def crop(im, box, pad=4):
        a, b, c, d = box
        return im.crop(
            (
                max(0, a - pad),
                max(0, b - pad),
                min(im.width, c + pad),
                min(im.height, d + pad),
            )
        )

    with Image.new("RGBA", (170, 145), (110, 80, 180, 255)) as im:
        im.save(output / "dress.png")

    def compute(records):
        return calculation._compute_results_from_userdata_records(
            records, cfg, consts, duplicate_groups=[], default_ids={}
        )

    def forbidden_store(*a, **k):
        raise AssertionError("storage/Writer is not a parity dependency")

    def setup(prefix, path):
        pkg = module(prefix)
        pkg.__path__ = [str(path)]
        score = module(prefix + ".score_calculator")
        for source in [v1, dims]:
            for key in dir(source):
                if not key.startswith("__"):
                    setattr(score, key, getattr(source, key))
        score.PAIR_ID_GROUPS = []
        score.PAIR_ID_MAP = {}
        score.TREND_DIM_COLUMNS = [
            "大歌力",
            "体力",
            "高速处理",
            "精度力",
            "节奏处理",
            "复合处理",
        ]
        score.TREND_SHORT_LABELS = {
            "大歌力": "大歌",
            "体力": "体力",
            "高速处理": "高速",
            "精度力": "精度",
            "节奏处理": "节奏",
            "复合处理": "复合",
            "综合Rating": "综合",
        }
        score.TREND_COLORS = {k: "#4E79A7" for k in score.TREND_SHORT_LABELS}
        score.load_rating_config = lambda *a, **k: cfg
        score.compute_all_from_userdata = lambda *a, **k: compute(state["entries"])
        score._compute_results_from_userdata_records = lambda records, *a, **k: compute(
            records
        )

        def daily(*a, **k):
            state["old_io"].append(prefix + ":prepared-daily")
            return [
                (
                    datetime.datetime(2026, 10, 10),
                    {c: 1.5 for c in score.TREND_DIM_COLUMNS},
                    2.0,
                ),
                (
                    datetime.datetime(2026, 10, 12),
                    {c: 2.5 for c in score.TREND_DIM_COLUMNS},
                    3.0,
                ),
            ]

        score.build_daily_rating_points = daily
        score.getUtime = lambda *a: "2026-10-12T12:00:00"
        dress = module(prefix + ".draw_dress")
        dress.TITLE_FONT_PATH = assets / "fonts/DDFont.ttf"
        dress.draw_player_info = profile
        dress._crop_with_pad = crop
        dress._get_font = lambda size: ImageFont.truetype(
            str(assets / "fonts/FZPW_GBK.ttf"), size
        )
        dress._get_font_by_path = lambda path, size: ImageFont.truetype(str(path), size)
        dress._load_previous_song_map = lambda *a: state["previous"]
        dress.render_user_dress = lambda *a: output / "dress.png"
        duplicate = module(prefix + ".duplicate_versions")
        duplicate.group_ids_for_query = lambda **k: [278]
        duplicate.choose_best_record_in_group = lambda records, **k: (
            max(records, key=lambda r: r.get("high_score", 0)) if records else None
        )
        ds = module(prefix + ".taikob_v2_data")
        ds.V2DataSourceError = ValueError

        def load_v2():
            state["old_io"].append(prefix + ":prepared-v2")
            return types.SimpleNamespace(song_map=v2map)

        ds.load_v2_snapshot = load_v2
        tv = module(prefix + ".taikob_v2")
        tv._calculate_v2_from_chart = lambda chart, **kw: v2._calculate_v2_from_chart(
            chart, profile="v2-center-20261010", **kw
        )
        # Legacy cache helper is not an Application dependency. Renderer icon cache fixed <=7.
        if "taiko_runtime.memory" not in sys.modules:
            rt = module("taiko_runtime")
            rt.__path__ = []
            mem = module("taiko_runtime.memory")
            mem.BoundedLRU = lambda *a, **k: {}
            mem.budget = lambda key, default: default
            mem.image_bytes = lambda im: im.width * im.height * 4
            mem.register_cache = lambda cache: cache
        mods = {}
        for name in CLASSES:
            full = prefix + "." + name
            spec = importlib.util.spec_from_file_location(full, path / (name + ".py"))
            m = importlib.util.module_from_spec(spec)
            sys.modules[full] = m
            original = Path.read_text

            def redirect(p, *a, **kw):
                if str(p) == "/home/sigaer/taiko/songs/song_data.json":
                    return json.dumps([song])
                return original(p, *a, **kw)

            with patch.object(Path, "read_text", redirect):
                spec.loader.exec_module(m)
            mods[name] = m
        return mods

    contexts = {}
    image_counter = [0]

    def encode(value):
        if isinstance(value, Path):
            return {"__path__": str(value.resolve())}
        if isinstance(value, Image.Image):
            image_counter[0] += 1
            path = output / f"context-layer-{image_counter[0]}.png"
            value.save(path)
            return {"__image__": str(path)}
        if is_dataclass(value):
            return {
                "__object__": {
                    f.name: encode(getattr(value, f.name)) for f in fields(value)
                }
            }
        if isinstance(value, dict):
            return {"__dict__": [[encode(k), encode(v)] for k, v in value.items()]}
        if isinstance(value, tuple):
            return {"__tuple__": [encode(v) for v in value]}
        if isinstance(value, set):
            return {"__set__": [encode(v) for v in sorted(value)]}
        if isinstance(value, list):
            return [encode(v) for v in value]
        return value

    old = setup("old_score", args.reference)
    new = setup("new_score", args.adapter)

    def configure(mods, base):
        for name, m in mods.items():
            m.ROOT_DIR = output
            m.BASE = output
            m.USERDATA_DIR = str(output / "userdata")
            m.ASSETS_DIR = base
            m.B30_DIM_ICON_DIR = base / "icons/b30_dims"
            m.RATING_DB_PATH = str(output / "songs/rating_structured_with_ids.json")
            m.RATING_JSON_DEFAULT = output / "songs/rating_structured_with_ids.json"
            m.FONT_TITLE_PATH = base / "fonts/FZPW_GBK.ttf"
            m.FONT_SCORE_PATH = m.FONT_TITLE_PATH
            m.FONT_STATS_PATH = m.FONT_TITLE_PATH
            m.FONT_DD_PATH = base / "fonts/DDFont.ttf"
            m.FONT_TITLE_FALLBACK_PATHS = [m.FONT_TITLE_PATH]
            m.DEFAULT_PROGRESS_FONT_PATH = str(m.FONT_DD_PATH)
            m.PROGRESS_BG_PATH = base / "templates/progress_bg.png"
            m.NEW_ICON_PATH = base / "icons/other/new.png"
            for f in list(vars(m).values()):
                if not isinstance(f, types.FunctionType) or f.__module__ != m.__name__:
                    continue

                def fix(v):
                    if isinstance(v, (str, Path)):
                        text = str(v)
                        if text.endswith("rating_structured_with_ids.json"):
                            return (
                                str(output / "songs/rating_structured_with_ids.json")
                                if isinstance(v, str)
                                else output / "songs/rating_structured_with_ids.json"
                            )
                        if text.endswith("b30_single.png"):
                            return base / "templates/b30_single.png"
                    return v

                if f.__defaults__:
                    f.__defaults__ = tuple(fix(v) for v in f.__defaults__)
                if f.__kwdefaults__:
                    f.__kwdefaults__ = {k: fix(v) for k, v in f.__kwdefaults__.items()}
            if hasattr(m, "_RATING_INDEX_CACHE"):
                m._RATING_INDEX_CACHE = {"mtime": None, "index": {}, "const_table": []}
            if hasattr(m, "_ICON_CACHE"):
                m._ICON_CACHE.clear()
        # lru_cached loaders capture default global values only on invocation.

    base_entry = {
        "song_no": 278,
        "level": 5,
        "high_score": 910000,
        "good_cnt": 500,
        "ok_cnt": 35,
        "ng_cnt": 6,
        "pound_cnt": 80,
        "combo_cnt": 300,
        "clear_cnt": 1,
        "full_combo_cnt": 0,
        "dondaful_combo_cnt": 0,
        "best_score_rank": 4,
        "option_flg": [1.0, 1, 1, "10"],
    }
    cases = [
        "ordinary",
        "FC",
        "DF",
        "high-rating",
        "no-scores",
        "missing-resources",
        "thirty-card-grid",
    ]
    results = []
    import shutil

    missing = output / "missing"
    missing.mkdir(exist_ok=True)
    # Missing optional cover/icons/category templates/background triggers genuine fallback.
    for rel in [
        "templates/b30_template.png",
        "templates/b30_single.png",
        "templates/info-bg-final-fix.png",
        "fonts/FZPW_GBK.ttf",
        "fonts/DDFont.ttf",
    ]:
        target = missing / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(assets / rel, target)
    for case in cases:
        entry = copy.deepcopy(base_entry)
        if case == "FC":
            entry.update(
                full_combo_cnt=1, ng_cnt=0, good_cnt=510, ok_cnt=31, combo_cnt=541
            )
        if case in {"DF", "high-rating"}:
            entry.update(
                dondaful_combo_cnt=1,
                full_combo_cnt=1,
                ng_cnt=0,
                good_cnt=541,
                ok_cnt=0,
                combo_cnt=541,
                high_score=1200000,
                best_score_rank=8,
            )
        if case == "no-scores":
            entry = {"song_no": 278, "level": 5}
        state["entries"] = [] if case == "no-scores" else [entry]
        if case == "thirty-card-grid":
            cfg = copy.deepcopy(FIXTURE["rating_config"])
            state["entries"] = copy.deepcopy(FIXTURE["userdata"]["songs"])
            (output / "songs/song_data.json").write_text(
                json.dumps(FIXTURE["song_catalog"])
            )
            (output / "songs/rating_structured_with_ids.json").write_text(
                json.dumps(cfg)
            )
        previous = copy.deepcopy(state["entries"])
        for record in previous:
            record["good_cnt"] = max(1, int(record.get("good_cnt", 0)) - 20)
            record["high_score"] = max(1, int(record.get("high_score", 0)) - 50000)
            record["dondaful_combo_cnt"] = 0
        state["previous"] = {(r["song_no"], r["level"]): r for r in previous}
        user = {"songs": state["entries"], "profile": {"name": "Synthetic Player"}}
        (output / "userdata/1data.json").write_text(json.dumps(user))
        base = missing if case == "missing-resources" else assets
        configure(old, base)
        configure(new, base)
        recs = (
            []
            if case == "no-scores"
            else [
                {
                    "song_id": 278,
                    "level": 5,
                    "title": "花漾",
                    "song_indicator": 999.88 if case == "high-rating" else 34.0,
                    "reference_indicator": 30.0,
                    "indicator_deviation_percent": 0.1,
                    "accuracy": entry.get("good_cnt", 0) / 541,
                    "recommend_score": 1.5,
                    "is_unplayed": False,
                }
            ]
        )
        for name, cls in CLASSES.items():
            if case == "thirty-card-grid" and name != "b30_render":
                continue

            def invoke(mod):
                if name == "b30_single":
                    return mod.render_b30_single_card(
                        entry,
                        song,
                        template_path=base / "templates/b30_single.png",
                        assets_base=base,
                        rating_json_path=output
                        / "songs/rating_structured_with_ids.json",
                        rating_value_override=999.88 if case == "high-rating" else None,
                        show_new=case == "FC",
                        rating_delta=0.25 if case == "DF" else None,
                    )
                if name == "b30_render":
                    return mod.render_b30_image(
                        1,
                        template_path=base / "templates/b30_template.png",
                        assets_base=base,
                        song_db_path=output / "songs/song_data.json",
                        rating_json_path=output
                        / "songs/rating_structured_with_ids.json",
                        card_rating_resolver=(
                            (lambda e: 999.88) if case == "high-rating" else None
                        ),
                    )
                if name == "drawinfo":
                    return mod.generate_score_image(
                        278,
                        1,
                        template_path=str(base / "templates/info-bg-final-fix.png"),
                        assets_base=str(base),
                        db_path=str(output / "songs/song_data.json"),
                    )
                return mod.render_recommend_image_bytes(
                    recs,
                    userdata=user,
                    assets_base=base,
                    font_path=str(base / "fonts/DDFont.ttf"),
                    subtitle="fixture",
                )

            legacy = invoke(old[name])
            expected = summary(legacy)
            captured = []

            class Capture:
                def __init__(self, context):
                    self.context = context

                def render(self, *a, **kw):
                    captured.append(self.context)
                    if case == "ordinary":
                        contexts[name] = {
                            f.name: encode(getattr(self.context, f.name))
                            for f in fields(self.context)
                        }
                    state["application"] = True
                    try:
                        rendered = cls(self.context).render(*a, **kw)
                        # Render the supplied context twice; input images remain caller-owned.
                        repeated = cls(self.context).render(*a, **kw)
                        require(
                            summary(rendered) == summary(repeated),
                            "context repeat/mutation",
                        )
                        return rendered
                    finally:
                        state["application"] = False

                def __getattr__(self, key):
                    return getattr(cls(self.context), key)

            with patch.object(new[name], cls.__name__, Capture):
                actual = invoke(new[name])
            got = summary(actual)
            require(got == expected, f"{case}/{name} PNG mismatch: {expected} != {got}")
            require(len(captured) == 1, "adapter must call application once")
            if case == "thirty-card-grid":
                require(
                    len(captured[0].top_entries) == 30, "must render all thirty cards"
                )
            (output / (case + "-" + name + ".png")).write_bytes(
                actual.getvalue() if isinstance(actual, io.BytesIO) else actual
            )
            results.append({"case": case, "renderer": name, "status": "PASS", **got})
            print(case, name, "PASS", got["dimensions"], got["mode"], flush=True)
    (output / "contexts.json").write_text(json.dumps(contexts, ensure_ascii=False))
    # Required templates absent: same error type, no invented substitute image.
    failures = []
    empty = output / "empty-assets"
    empty.mkdir(exist_ok=True)
    for name in ["b30_single", "b30_render", "drawinfo"]:
        configure(old, empty)
        configure(new, empty)
        types_seen = []
        for mods in [old, new]:
            call_count = len(state["old_io"])
            try:
                if name == "b30_single":
                    mods[name].render_b30_single_card(
                        base_entry,
                        song,
                        assets_base=empty,
                        template_path=empty / "missing.png",
                    )
                elif name == "b30_render":
                    mods[name].render_b30_image(
                        1, assets_base=empty, template_path=empty / "missing.png"
                    )
                else:
                    mods[name].generate_score_image(
                        278,
                        1,
                        assets_base=str(empty),
                        template_path=str(empty / "missing.png"),
                        db_path=str(output / "songs/song_data.json"),
                    )
            except FileNotFoundError:
                types_seen.append("FileNotFoundError")
            require(
                len(state["old_io"]) == call_count,
                "required resource failure must precede daily/v2 acquisition",
            )
        require(
            types_seen == ["FileNotFoundError"] * 2, "missing required template parity"
        )
        failures.append(
            {"renderer": name, "result": "FileNotFoundError", "status": "PASS"}
        )
    cg = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    cgpath = Path("/sys/fs/cgroup") / cg.lstrip("/")
    report = {
        "status": "PASS",
        "cases": results,
        "required_resource_errors": failures,
        "core": version("sakura-taiko-core"),
        "contract": version("sakura-taiko-contract"),
        "pillow": version("Pillow"),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cgroup": cg,
        "memory_events": (cgpath / "memory.events").read_text(),
        "acquisition_calls": state["old_io"],
    }
    (output / "parity.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print("PHASE_2B_PARITY_PASS", flush=True)


if __name__ == "__main__":
    main()
