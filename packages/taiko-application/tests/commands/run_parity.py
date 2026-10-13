"""Execute frozen complete command bodies and candidate adapters on injected fixtures.

NoneBot registration, private acquisition and final transport are isolated. Command
parsing/branching/error mapping and JPEG conversion execute unchanged.
"""

from __future__ import annotations
import argparse, ast, asyncio, copy, dataclasses, hashlib, importlib.abc, io, json, os, re, resource, sys, time, types
from pathlib import Path
from typing import *
from importlib.metadata import version
from PIL import Image
from sakura_taiko_core.recommendation.center import (
    parse_target_recommendation_request,
    target_recommendation_displays,
)
from taiko_application.dani import DaniProgressService, DaniInputs

parse_dani_progress_request = DaniProgressService(
    DaniInputs(
        {"2026": {"grades": []}, "2025": {"grades": [{"grade": "六段"}]}}, [], [], {}
    )
).parse_dani_progress_request
from taiko_application import commands as app

REG = {
    "b30": "taikob",
    "score": "music_info",
    "song": "what_song",
    "constant": "const_query",
    "progress": "matcher",
    "recommendation": "taikorec",
}
HELPERS = {
    "_extract_rating_version",
    "_parse_taikob_dim_arg",
    "_resolve_taikob_dim_arg",
    "_extract_what_song_query",
    "_parse_star_progress_value",
    "_is_fuzzy_query_result",
    "_is_accepted_fuzzy_query_result",
    "_is_rejected_fuzzy_query_result",
    "_build_fuzzy_query_hint",
    "_to_jpeg_bytes",
    "_resolve_read_bind_target_safe",
}
CONSTANTS = {
    "DIM_MAP",
    "DIM_ALIASES",
    "TAIKOB_V2_DIM_USAGE",
    "_TAIKOB_DIM_WRAPPER_CHARS",
    "WHAT_SONG_REGEX",
    "WHAT_SONG_OFFICIAL_PATTERNS",
    "STAR_PROGRESS_VALUE_MAP",
    "STAR_PROGRESS_REGEX",
    "TAIKOB_COMMAND_RE",
    "MUSIC_INFO_COMMAND_RE",
    "PROGRESS_WITH_PAGE_REGEX",
    "TAIKOREC_COMMAND_EXTRACT_RE",
}


class Finish(BaseException):
    pass


class V2Error(Exception):
    pass


class BindError(Exception):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canon(v):
    if isinstance(v, io.BytesIO):
        v = v.getvalue()
    if isinstance(v, bytes):
        with Image.open(io.BytesIO(v)) as im:
            im.load()
            return {
                "bytes_sha256": digest(v),
                "pixels_sha256": digest(im.tobytes()),
                "dimensions": list(im.size),
                "mode": im.mode,
                "format": im.format,
            }
    if dataclasses.is_dataclass(v):
        return {f.name: canon(getattr(v, f.name)) for f in dataclasses.fields(v)}
    if isinstance(v, dict):
        return {str(k): canon(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [canon(x) for x in v]
    if isinstance(v, types.SimpleNamespace):
        return canon(vars(v))
    return v


def handler(tree, reg):
    return next(
        n
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef)
        and any(
            isinstance(d, ast.Call)
            and isinstance(d.func, ast.Attribute)
            and isinstance(d.func.value, ast.Name)
            and d.func.value.id == reg
            for d in n.decorator_list
        )
    )


def load_functions(tree, ns):
    selected = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name in HELPERS:
            n = copy.deepcopy(n)
            n.decorator_list = []
            selected.append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id in CONSTANTS for t in targets):
                selected.append(copy.deepcopy(n))
    for key, reg in REG.items():
        n = copy.deepcopy(handler(tree, reg))
        n.name = "handle_" + key
        n.decorator_list = []
        selected.append(n)
    selected += [
        copy.deepcopy(n)
        for n in tree.body
        if isinstance(n, ast.AsyncFunctionDef)
        and n.name == "_deliver_application_command"
    ]
    module = ast.Module(
        body=[ast.ImportFrom("__future__", [ast.alias("annotations")], 0)] + selected,
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    exec(compile(module, "isolated-command-functions", "exec"), ns)


class Fixture:
    def __init__(self, tree, images):
        self.trace = []
        self.outputs = []
        self.options = {}
        self.app_calls = 0
        self.images = images
        ns = {
            "re": re,
            "Image": Image,
            "BytesIO": io.BytesIO,
            "RegexMatched": lambda: None,
            "MergedBindError": BindError,
            "MergedBindMissingUserdataError": BindError,
            "FONT_PATH": "fixture-font",
            "TAIKOB_FONT_PATH": "fixture-font",
            "DEFAULT_PAGE_SIZE": 25,
            "V2DataSourceError": V2Error,
            "V2_TAIKOB_DIM_ALIASES": {"体力": "stamina", "精度": "accuracy_power"},
            "FUZZY_ACCEPT_THRESHOLD": 0.7,
            "is_accepted_similarity": lambda ratio, threshold: float(ratio) / 100
            >= threshold,
            "parse_target_recommendation_request": parse_target_recommendation_request,
            "target_recommendation_displays": target_recommendation_displays,
            "parse_dani_progress_request": parse_dani_progress_request,
            "print": lambda *x: None,
            "extract_plain_text": lambda e: e.text,
            "_is_external_bot_mentioned": lambda e: e.external,
        }
        ns.update(
            {name: getattr(app, name) for name in dir(app) if not name.startswith("_")}
        )
        for key in REG:
            fn = getattr(app, "execute_" + key)

            def counted(*args, _fn=fn, **kw):
                self.app_calls += 1
                return _fn(*args, **kw)

            ns["execute_" + key] = counted

        class Matcher:
            async def finish(_, value=None):
                self.outputs.append(
                    {
                        "kind": "silent" if value is None else "text",
                        "delivery": "direct",
                        "payload": canon(value),
                    }
                )
                raise Finish()

        for name in set(REG.values()) | {"matcher"}:
            ns[name] = Matcher()

        async def text(m, e, value):
            self.outputs.append({"kind": "text", "delivery": "reply", "payload": value})
            raise Finish()

        async def image(m, e, value, **kw):
            self.outputs.append(
                {
                    "kind": "image",
                    "payload": canon(value),
                    "prefix": kw.get("prefix_text", ""),
                }
            )
            raise Finish()

        async def fumen(m, e, diff, sid):
            self.trace.append(["fumen", diff, sid])
            await image(m, e, images["song"])

        async def fuzzy(m, e, rows, difficulty="Oni"):
            self.trace.append(["fuzzy_fumen", canon(rows), difficulty])
            await image(
                m, e, images["song"], prefix_text=ns["_build_fuzzy_query_hint"](rows)
            )

        ns.update(
            _finish_text_reply=text,
            _finish_image_reply=image,
            _send_fumen_or_hint=fumen,
            _finish_fuzzy_query_with_fumen=fuzzy,
        )

        def bind(e):
            self.trace.append(["permission"])
            value = self.options.get(
                "permission", {"user_id": "42", "source": "synthetic"}
            )
            if value == "error":
                raise BindError("synthetic binding error")
            return value

        ns["_resolve_read_bind_target"] = bind
        ns["_taiko_bind_usage_message"] = lambda e: "fixture binding help"
        ns["_build_missing_userdata_upload_hint"] = lambda b: "fixture upload help"

        def provider(name, default):
            def call(*args, **kw):
                self.trace.append([name, canon(args), canon(kw)])
                failure = self.options.get("fail", {}).get(name)
                if failure:
                    raise {
                        "missing": FileNotFoundError("userdata not found"),
                        "file": FileNotFoundError("catalog missing"),
                        "type": TypeError("bad data"),
                        "v2": V2Error(),
                        "error": RuntimeError("fixture error"),
                    }[failure]
                if name in self.options:
                    return self.options[name]
                return default(*args, **kw) if callable(default) else default

            return call

        for name in [
            "render_b30_image",
            "render_b20_v2_image",
            "render_b20_v2_dim_image",
            "generate_dim_top_image",
            "generate_top_N_image",
        ]:
            ns[name] = provider(name, images["b30"])
        ns["generate_score_image"] = provider("generate_score_image", images["score"])
        ns["generate_recommend_image"] = provider(
            "generate_recommend_image",
            lambda *a, **k: io.BytesIO(images["recommendation"]),
        )
        ns["render_target_recommendation_image_bytes"] = provider(
            "render_target_recommendation_image_bytes", images["recommendation"]
        )
        for name in ["render_const_query_notice", "render_const_query_image"]:
            ns[name] = provider(name, images["constant"])
        for name in [
            "render_dani_progress_image_bytes",
            "render_pass_progress_image_bytes",
            "render_progress_image_bytes",
            "render_star_progress_image_bytes",
            "render_progress_image_bytes_by_list",
        ]:
            ns[name] = provider(name, images["progress"])
        defaults = {
            "compute_all_from_userdata": [{"fixture_rating": 10}],
            "_load_user_song_records": [],
            "queryMusic": [[1, "Neon"]],
            "_resolve_what_song_query": [[1, "Neon"]],
            "_load_decimal_progress_set": {"6.6"},
            "_load_pass_progress_set": {"6.6", "7.7"},
            "_load_star_progress_set": {6},
            "_load_progress_name_set": {"SS", "地力S", "個人差A"},
            "query_charts_by_const": lambda value, **kw: list(range(30)),
            "paginate_rows": lambda rows, page=1: (
                rows[(page - 1) * 25 : page * 25],
                page,
                (len(rows) + 24) // 25,
            ),
            "compute_recommendations_for_user": [{"song_id": 1, "level": 4}],
            "compute_target_recommendations_for_user": types.SimpleNamespace(
                is_enough=True,
                message="fixture insufficient",
                userdata={"songs": []},
                target_display="紫雅",
                rows=[{"song_id": 1, "level": 4}],
            ),
        }
        for name, val in defaults.items():
            ns[name] = provider(name, val)
        ns["_extract_taikob_command_match"] = lambda e: ns[
            "TAIKOB_COMMAND_RE"
        ].fullmatch(e.text)
        ns["_extract_music_info_command_match"] = lambda e: ns[
            "MUSIC_INFO_COMMAND_RE"
        ].fullmatch(e.text)
        ns["_extract_progress_command_match"] = lambda e: ns[
            "PROGRESS_WITH_PAGE_REGEX"
        ].fullmatch(e.text)
        load_functions(tree, ns)
        self.ns = ns

    async def run(self, key, text, options):
        self.trace = []
        self.outputs = []
        self.options = options
        self.app_calls = 0
        event = types.SimpleNamespace(
            text=text, external=options.get("external", False)
        )
        kw = {"event": event}
        if key == "song":
            kw["matcher"] = self.ns["matcher"]
        if key == "constant":
            kw["match"] = types.SimpleNamespace(
                group=lambda i: (
                    options.get("constant", "6.6")
                    if i == 1
                    else options.get("extra", "")
                )
            )
        try:
            await self.ns["handle_" + key](**kw)
        except Finish:
            pass
        return {
            "outputs": copy.deepcopy(self.outputs),
            "calls": copy.deepcopy(self.trace),
        }


def cases():
    result = []

    def add(key, label, text, **options):
        result.append((key, label, text, options))

    for text in [
        "taikob",
        "taikob 30 v1",
        "taikob 30 v1 体力",
        "taikob30 v1 -r",
        "taikob 30 v2 精度",
        "taikob30 v2 -r",
        "taikob30 v2 unknown",
        "taikob v1 v2",
        "bad",
    ]:
        add("b30", text, text)
    for label, records, oni in [
        ("empty", [], []),
        ("below-threshold", [], [{"level": 4}]),
    ]:
        add(
            "b30",
            label,
            "taikob30 v1",
            compute_all_from_userdata=records,
            _load_user_song_records=oni,
        )
    for name in ["compute_all_from_userdata", "render_b20_v2_image"]:
        for error in ["missing", "type"] + (
            ["file", "v2"] if name == "render_b20_v2_image" else []
        ):
            add(
                "b30",
                name + "/" + error,
                "taikob v2" if name.startswith("render") else "taikob v1",
                fail={name: error},
            )
    for label, rows in [
        ("normal", [[1, "Neon"]]),
        ("empty", []),
        ("duplicates", [[1, "Neon"], [2, "Neon"]]),
        ("fuzzy", [[1, "Neon", 20]]),
        ("accepted", [[1, "Neon", 99]]),
    ]:
        add("score", label, "tinfo Neon", queryMusic=rows)
    add("score", "invalid", "bad")
    for error in ["missing", "error"]:
        add("score", error, "tinfo Neon", fail={"generate_score_image": error})
    for label, text, rows in [
        ("normal", "Neon是什么歌", [[1, "Neon"]]),
        ("prefix", "里Neon是什么歌", [[1, "Neon"]]),
        ("empty", "Neon是什么歌", []),
        ("duplicates", "Neon是什么歌", [[1, "Neon"], [2, "Neon"]]),
        ("fuzzy", "Neon是什么歌", [[1, "Neon", 20]]),
        ("invalid", "bad", []),
        ("copy", "@菌菌 Neon是什么歌", []),
    ]:
        add("song", label, text, _resolve_what_song_query=rows)
    add("song", "external", "Neon是什么歌", external=True)
    add(
        "song",
        "query-error",
        "Neon是什么歌",
        fail={"_resolve_what_song_query": "error"},
    )
    for label, value, extra in [
        ("normal", "6.6", ""),
        ("page2", "6.6", "2"),
        ("overflow", "6.6", "3"),
        ("shelf", "6.6", "含下架"),
        ("invalid-value", "bad", ""),
        ("invalid-page", "6.6", "0"),
        ("invalid-token", "6.6", "abc"),
    ]:
        add("constant", label, "", constant=value, extra=extra)
    add("constant", "empty", "", query_charts_by_const=[])
    for text in [
        "6.6进度",
        "6.6综合进度 2",
        "7.7过关进度",
        "8.8过关进度",
        "8.8综合进度",
        "8.8进度",
        "6星进度",
        "9星进度",
        "SS进度",
        "unknown进度",
        "bad",
        "6星进度 0",
        "2025六段进度",
    ]:
        add("progress", text, text)
    for text in [
        "taikorec",
        "taikorec体力30",
        "推荐歌曲 50",
        "taikorec rating 0",
        "taikorec rating 99",
        "taikorec rating bad",
        "taikorec invalid",
        "推荐歌曲 紫雅",
        "推荐歌曲 紫雅 9星",
        "推荐歌曲 紫雅 nope",
        "推荐歌曲 紫雅 9星 extra",
    ]:
        add("recommendation", text, text)
    add("recommendation", "empty", "taikorec", compute_recommendations_for_user=[])
    add(
        "recommendation",
        "insufficient",
        "推荐歌曲 紫雅",
        compute_target_recommendations_for_user=types.SimpleNamespace(
            is_enough=False,
            message="fixture insufficient",
            userdata={},
            target_display="紫雅",
            rows=[],
        ),
    )
    for name, text in [
        ("compute_recommendations_for_user", "taikorec"),
        ("compute_target_recommendations_for_user", "推荐歌曲 紫雅"),
    ]:
        for error in ["missing", "error"]:
            add("recommendation", name + "/" + error, text, fail={name: error})
    for key, text in [
        ("b30", "taikob v1"),
        ("score", "tinfo Neon"),
        ("progress", "6星进度"),
        ("recommendation", "taikorec"),
    ]:
        for permission in [403, 404, "error"]:
            add(key, "permission/" + str(permission), text, permission=permission)
    add("b30", "invalid-before-permission", "taikob v1 v2", permission=403)
    add("progress", "invalid-before-permission", "6星进度 0", permission=403)
    return result


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--adapter", type=Path, required=True)
    p.add_argument("--images", type=Path, required=True)
    p.add_argument("--installed", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    assert Path(app.__file__).is_relative_to(a.installed.resolve())
    assert (
        version("sakura-taiko-core") == "0.1.1"
        and version("sakura-taiko-contract") == "0.1.0"
    )
    provenance = json.loads(Path(__file__).with_name("provenance.json").read_text())
    assert digest(a.reference.read_bytes()) == provenance["reference_sha256"]
    oldtree = ast.parse(a.reference.read_text())
    newtree = ast.parse(a.adapter.read_text())
    images = {}
    for key, name in provenance["images"].items():
        data = (a.images / name["path"]).read_bytes()
        assert digest(data) == name["sha256"]
        images[key] = data
    old = Fixture(oldtree, images)
    new = Fixture(newtree, images)
    a.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = []
    # Imports/fixture reads are complete. Command execution must do no file/network IO.
    Image.init()
    active = True

    def guard(event, args):
        if active and (
            event == "open"
            or event.startswith(
                ("socket.", "subprocess.", "os.mkdir", "os.rename", "os.remove")
            )
        ):
            raise AssertionError("command IO " + event)

    sys.addaudithook(guard)
    for key, label, text, options in cases():
        before = repr(options)
        left = await old.run(key, text, options)
        right = await new.run(key, text, options)
        assert json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True), (
            key,
            label,
            "output/call-order mismatch",
            left,
            right,
        )
        assert repr(options) == before, (key, label, "fixture mutated")
        if label.startswith("permission/"):
            assert new.app_calls == 0 and right["calls"] == [["permission"]], (
                key,
                label,
                "permission failure invoked Application/data",
            )
        report.append(
            {
                "command": key,
                "case": label,
                "status": "PASS",
                "result": left,
                "sha256": digest(
                    json.dumps(left, ensure_ascii=False, sort_keys=True).encode()
                ),
            }
        )
    active = False
    cg = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    result = {
        "status": "PASS",
        "count": len(report),
        "cases": report,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "memory_events": (
            Path("/sys/fs/cgroup") / cg.lstrip("/") / "memory.events"
        ).read_text(),
        "cgroup": cg,
    }
    (a.output / "parity.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print("COMMAND_PARITY_PASS", len(report))


if __name__ == "__main__":
    asyncio.run(main())
