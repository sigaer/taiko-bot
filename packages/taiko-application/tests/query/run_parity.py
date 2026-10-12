"""Execute frozen legacy query bodies, new host adapters and installed Application.

Only filesystem acquisition / upstream computed-result providers are replaced.
No query matching, sorting, projection, pagination or Core formula is mocked.
"""

from __future__ import annotations
import argparse, ast, copy, dataclasses, hashlib, importlib.util, io, json, os, resource, sys, time, types
from pathlib import Path
from typing import *
from unittest.mock import patch
from importlib.metadata import version
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity, progress_catalog as core_catalog
from sakura_taiko_core.score import progress as core_progress
from sakura_taiko_core.rating import v1
from fixture import SONGS, ALIASES, CHARTS, STATIC, BEST, RECOMMENDATIONS, TARGET
from taiko_application.query import *
from taiko_application.query import progress as app_progress
from taiko_application.query import recommendation as app_recommendation


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canon(value):
    if dataclasses.is_dataclass(value):
        return {
            f.name: canon(getattr(value, f.name)) for f in dataclasses.fields(value)
        }
    if isinstance(value, dict):
        return {str(k): canon(v) for k, v in value.items()}
    if isinstance(value, set):
        return sorted(canon(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [canon(v) for v in value]
    return value


def outcome(call):
    try:
        return {"result": canon(call())}
    except (
        ValueError,
        TypeError,
        AttributeError,
        ZeroDivisionError,
        OverflowError,
    ) as e:
        return {"error": type(e).__name__, "message": str(e)}


def package(name, path):
    m = types.ModuleType(name)
    m.__path__ = [str(path)]
    sys.modules[name] = m
    return m


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


def plugin_functions(path, ns, new):
    # Full original functions are executed, not mocked; omit NoneBot registration
    # and unrelated module startup/Writer imports. Pin the whole source hash first.
    names = {"_query_music_with_mode", "queryMusic", "find_aliases_by_song_id"}
    if new:
        names.add("_query_group_maps")
    body = [
        n for n in ast.parse(path.read_text()).body if getattr(n, "name", None) in names
    ]
    require(len(body) == len(names), "plugin entry inventory")
    tree = ast.Module(
        body=[ast.ImportFrom("__future__", [ast.alias("annotations")], 0)] + body,
        type_ignores=[],
    )
    ast.fix_missing_locations(tree)
    exec(compile(tree, str(path), "exec"), ns)
    return types.SimpleNamespace(**ns)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    a = parser.parse_args()
    a.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    sys.dont_write_bytecode = True
    import taiko_application

    require(
        Path(taiko_application.__file__).is_relative_to(a.installed.resolve()),
        "must test installed wheel",
    )
    require(version("taiko-application") == "0.4.0", "Application version")
    require(version("sakura-taiko-core") == "0.1.1", "Core unchanged")
    require(version("sakura-taiko-contract") == "0.1.0", "Contract unchanged")
    provenance = json.loads(Path(__file__).with_name("provenance.json").read_text())
    for file, expected in provenance["reference"].items():
        require(sha((a.reference / file).read_bytes()) == expected, "reference " + file)
    state = {
        "songs": copy.deepcopy(SONGS),
        "aliases": copy.deepcopy(ALIASES),
        "charts": copy.deepcopy(CHARTS),
        "static": copy.deepcopy(STATIC),
        "trace": [],
        "app": False,
        "rating_results": [],
    }

    def data(path):
        key = Path(path).name
        state["trace"].append(key)
        if key == "song_data.json":
            return state["songs"]
        if key == "song_alias.json":
            return state["aliases"]
        if key == "rating_structured_with_ids.json":
            return {"songs": state["charts"]}
        if key == "song_difficulty.json":
            return state["static"]
        raise AssertionError("unexpected fixture acquisition " + str(path))

    def readtext(path, *args, **kw):
        return json.dumps(data(path))

    def fakeopen(path, *args, **kw):
        return io.StringIO(readtext(path))

    def groups(*args):
        state["trace"].append("group-catalog")
        return identity.build_group_maps(state["songs"])

    def available(*args):
        return {
            (int(s["id"]), level)
            for s in state["songs"]
            for level in (4, 5)
            if s.get(f"level_{level}") not in (None, "", "-")
            and s.get("shelf_status") != 1
        }

    def setup(prefix, path, modern):
        package(prefix, path)
        ca = types.ModuleType(prefix + ".chart_availability")
        ca.load_cn_available_chart_keys = available
        sys.modules[ca.__name__] = ca
        score = types.ModuleType(prefix + ".score_calculator")
        score.aggregate_topN_value = v1.aggregate_topN_value
        score.compute_dim_topN_means = v1.compute_dim_topN_means
        score.compute_all_from_userdata = lambda *a, **k: state["rating_results"]
        score.compute_recommendations_for_user = lambda *a, **k: RECOMMENDATIONS[
            : k["limit"]
        ]
        sys.modules[score.__name__] = score
        target = types.ModuleType(prefix + ".target_recommend")
        target.TargetRecommendationResult = types.SimpleNamespace
        target.compute_target_recommendations_for_user = lambda **k: TARGET
        sys.modules[target.__name__] = target
        store = types.ModuleType("taiko_store")
        store.PublicationError = RuntimeError
        sys.modules["taiko_store"] = store
        mods = {
            n: load(prefix + "." + n, path / (n + ".py"))
            for n in [
                "duplicate_versions",
                "progress_catalog",
                "progress_star",
                "const_query",
                "recommendation_intelligence",
            ]
        }
        mods["duplicate_versions"]._group_cache = groups
        namespace = {
            "json": json,
            "fuzz": fuzz,
            "List": List,
            "Any": Any,
            "Dict": Dict,
            "Optional": Optional,
            "Tuple": Tuple,
            "collapse_query_results_by_group": mods[
                "duplicate_versions"
            ].collapse_query_results_by_group,
            "alias_entry_for_song_id": mods[
                "duplicate_versions"
            ].alias_entry_for_song_id,
            "application_query_music": query_music,
            "SongQueryContext": SongQueryContext,
            "_query_group_cache": groups,
        }
        mods["plugin"] = plugin_functions(
            a.adapter / "taiko.py" if modern else a.reference / "taiko.py",
            namespace,
            modern,
        )
        return mods

    old = setup("legacy_query", a.reference, False)
    new = setup("candidate_query", a.adapter / "utils", True)

    # Prevent accidentally touching production paths. Only synthetic provider values
    # flow into the old/new functions; Application calls forbid all file/network IO.
    def guard(event, values):
        if event.startswith(("socket.", "subprocess.")):
            raise AssertionError("network/process forbidden")
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            p = Path(os.fsdecode(values[0])).resolve()
            if state["app"]:
                raise AssertionError("Application filesystem IO")
            if p.is_relative_to("/home/sigaer/taiko") and not p.is_relative_to(
                "/home/sigaer/taiko/.venv"
            ):
                raise AssertionError("production read")
            flags = values[2] if len(values) > 2 else 0
            if flags & (
                os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC
            ) and not p.is_relative_to(a.output.resolve()):
                raise AssertionError("out of scope write")

    sys.addaudithook(guard)
    expected_errors = {
        "song/invalid-type",
        "constant/invalid/False",
        "constant/None/False",
        "pagination/1/0",
        "pagination/bad/25",
        "progress/query_progress_items_by_const/bad",
        "progress/query_progress_items_by_star/bad",
        "recommendation/ordinary/unsupported/4",
        "recommendation/ordinary/unsupported/0",
    }
    records = []

    def reset(mods):
        for m in mods.values():
            for f in vars(m).values():
                if hasattr(f, "cache_clear"):
                    f.cache_clear()

    def host(call, mods):
        reset(mods)
        state["trace"] = []
        # Patches are boundary providers only. All returned objects are fixture data.
        with patch("builtins.open", fakeopen), patch.object(
            Path, "read_text", readtext
        ):
            value = outcome(call)
        return value, list(state["trace"])

    def check(label, left, right, direct, trace=True):
        before = repr(
            (
                state["songs"],
                state["aliases"],
                state["charts"],
                BEST,
                RECOMMENDATIONS,
                TARGET,
            )
        )
        l, lt = host(left, old)
        r, rt = host(right, new)
        state["app"] = True
        try:
            d = outcome(direct)
        finally:
            state["app"] = False
        # JSON keeps list/dict order and nulls, normalizes equivalent dataclass types.
        serial = lambda x: json.dumps(
            x, ensure_ascii=False, allow_nan=True, separators=(",", ":")
        )
        require(serial(l) == serial(r) == serial(d), f"{label}: {l} != {r} != {d}")
        if trace:
            require(lt == rt, f"{label}: acquisition order changed {lt} != {rt}")
        require(
            before
            == repr(
                (
                    state["songs"],
                    state["aliases"],
                    state["charts"],
                    BEST,
                    RECOMMENDATIONS,
                    TARGET,
                )
            ),
            "input mutation",
        )
        require(
            ("error" in l) == (label in expected_errors),
            f"{label}: unexpected success/error",
        )
        records.append(
            {
                "case": label,
                "status": "PASS",
                "output": l,
                "output_sha256": sha(serial(l).encode()),
                "acquisition": lt,
            }
        )

    def songctx(**kw):
        _, byid, bytitle = identity.build_group_maps(state["songs"])
        return SongQueryContext(
            state["songs"], state["aliases"], byid, bytitle, fuzz.ratio, **kw
        )

    for label, value, partial, fuzzy in [
        ("name", "NEON", True, True),
        ("id", "id2", True, True),
        ("alias", "common", True, True),
        ("partial", "Trac", True, True),
        ("fuzzy", "Neno", True, True),
        ("empty", " ", True, True),
        ("none", None, True, True),
        ("not-found", "xxxx", False, False),
        ("invalid-type", 123, True, True),
        ("unknown-alias-id", "ghost", True, True),
    ]:
        kwargs = {"allow_partial": partial, "allow_fuzzy": fuzzy}
        ctx = songctx(query=value, **kwargs)
        check(
            "song/" + label,
            lambda: old["plugin"]._query_music_with_mode(value, **kwargs),
            lambda: new["plugin"]._query_music_with_mode(value, **kwargs),
            lambda: query_music(ctx),
        )
    for sid, explicit in [
        (1, False),
        (2, False),
        (2, True),
        (999, False),
        ("invalid", False),
        (None, False),
    ]:
        ctx = songctx(song_id=sid, explicit_alias_id=explicit)
        check(
            f"alias/{sid}/{explicit}",
            lambda: old["duplicate_versions"].alias_entry_for_song_id(
                sid, explicit=explicit
            ),
            lambda: new["duplicate_versions"].alias_entry_for_song_id(
                sid, explicit=explicit
            ),
            lambda: query_aliases(ctx),
        )
    for payload in [[], {}]:
        state["aliases"] = payload
        ctx = songctx(song_id=1)
        check(
            "alias/empty-" + type(payload).__name__,
            lambda: old["duplicate_versions"].alias_entry_for_song_id(1),
            lambda: new["duplicate_versions"].alias_entry_for_song_id(1),
            lambda: query_aliases(ctx),
        )
    state["aliases"] = copy.deepcopy(ALIASES)
    for value, include in [
        (6.6, False),
        (6.6, True),
        (9.3, False),
        (99.0, False),
        ("invalid", False),
        (None, False),
        (float("nan"), False),
    ]:
        ctx = ConstantQueryContext(
            {s["id"]: s for s in state["songs"]}, state["charts"], value, include
        )
        check(
            "constant/" + str(value) + "/" + str(include),
            lambda: old["const_query"].query_charts_by_const(
                value, include_shelf_status=include
            ),
            lambda: new["const_query"].query_charts_by_const(
                value, include_shelf_status=include
            ),
            lambda: query_charts_by_const(ctx),
        )
    # Real const rows, not placeholder paging integers.
    ctx = ConstantQueryContext({s["id"]: s for s in SONGS}, CHARTS, 6.6)
    oldrows, _ = host(lambda: old["const_query"].query_charts_by_const(6.6), old)
    rows = query_charts_by_const(ctx)
    for page, size in [
        (1, 25),
        (2, 25),
        (99, 25),
        (0, 25),
        (-2, 25),
        (1, 1),
        (1, 0),
        ("bad", 25),
    ]:
        c = PaginationContext(rows, page, size)
        check(
            f"pagination/{page}/{size}",
            lambda: old["const_query"].paginate_rows(rows, page=page, page_size=size),
            lambda: new["const_query"].paginate_rows(rows, page=page, page_size=size),
            lambda: paginate_rows(c),
        )
    check(
        "pagination/empty",
        lambda: old["const_query"].paginate_rows([], page=99),
        lambda: new["const_query"].paginate_rows([], page=99),
        lambda: paginate_rows(PaginationContext([], 99)),
    )

    def progressctx(value=None):
        index = {s["id"]: s for s in state["songs"]}
        return ProgressQueryContext(
            core_catalog.ProgressCatalogInputs(
                song_index=index,
                active_song_ids=core_catalog.active_song_ids_from_index(index),
                rating_entries=state["charts"],
                static_progress_map=state["static"],
                cn_available_chart_keys=available(),
            ),
            value=value,
        )

    for name, values in [
        ("available_pass_progress_keys", [None]),
        ("available_const_progress_keys", [None]),
        ("load_star_progress_chart_keys", [None]),
        ("available_star_progress_values", [None]),
        ("query_progress_items_by_pass_const", ["9.0", "missing", None]),
        ("query_progress_items_by_const", [6.6, 99.0, "bad"]),
        ("query_progress_items_by_star", [9, 8, 99, "bad"]),
    ]:
        for val in values:
            params = () if name.startswith(("available", "load")) else (val,)
            ctx = progressctx(val)
            check(
                "progress/" + name + "/" + str(val),
                lambda: getattr(old["progress_catalog"], name)(*params),
                lambda: getattr(new["progress_catalog"], name)(*params),
                lambda: getattr(app_progress, name)(ctx),
            )
    for items, best in [
        (
            [
                (1, 4, "Neon"),
                (1, 4, "duplicate"),
                (1, 5, "Neon Ura"),
                (3, 4, "Moon"),
                (2, 4, "off-shelf"),
            ],
            BEST,
        ),
        ([], {}),
        ([("invalid", None, "broken")], {}),
    ]:
        keys = app_progress.load_star_progress_chart_keys(progressctx())
        ctx = ProgressQueryContext(
            core_catalog.ProgressCatalogInputs(),
            items=items,
            best_map=best,
            available_chart_keys=keys,
        )
        check(
            "summary/" + str(len(items)),
            lambda: old["progress_star"].build_star_progress_summary(items, best),
            lambda: new["progress_star"].build_star_progress_summary(items, best),
            lambda: summarize_progress(ctx),
        )
    for basis in ["rating", "speed", "unsupported"]:
        for rows in [RECOMMENDATIONS, []]:
            c = RecommendationContext(rows=rows, basis=basis)
            check(
                "recommendation/ordinary/" + basis + "/" + str(len(rows)),
                lambda: old[
                    "recommendation_intelligence"
                ].project_ordinary_recommendations(rows, basis=basis),
                lambda: new[
                    "recommendation_intelligence"
                ].project_ordinary_recommendations(rows, basis=basis),
                lambda: project_ordinary_recommendations(c),
            )
    for target in [
        TARGET,
        types.SimpleNamespace(
            target_key="goku",
            candidate_count=0,
            required_count=20,
            is_enough=False,
            rows=[],
        ),
    ]:
        c = RecommendationContext(target_result=target)
        check(
            "recommendation/target/" + target.target_key,
            lambda: old["recommendation_intelligence"].project_target_recommendations(
                target
            ),
            lambda: new["recommendation_intelligence"].project_target_recommendations(
                target
            ),
            lambda: project_target_recommendations(c),
        )
    for rating in [
        [],
        [
            types.SimpleNamespace(
                AI_rating=10.0,
                big_song=9.0,
                stamina=8.0,
                speed=7.0,
                accuracy_power=6.0,
                rhythm=5.0,
                complex_proc=4.0,
            )
        ],
    ]:
        state["rating_results"] = rating
        c = RecommendationContext(rating_results=rating)
        check(
            "recommendation/rating/" + str(len(rating)),
            lambda: old["recommendation_intelligence"].build_player_rating_intelligence(
                1
            ),
            lambda: new["recommendation_intelligence"].build_player_rating_intelligence(
                1
            ),
            lambda: project_player_rating(c),
        )
    # Empty source catalog must remain empty even with fuzzy enabled.
    state["songs"] = []
    state["aliases"] = []
    ctx = songctx(query="Neon")
    check(
        "song/empty-catalog",
        lambda: old["plugin"]._query_music_with_mode("Neon"),
        lambda: new["plugin"]._query_music_with_mode("Neon"),
        lambda: query_music(ctx),
    )
    cgroup = Path("/proc/self/cgroup").read_text().strip().split("::", 1)[1]
    cg = Path("/sys/fs/cgroup") / cgroup.lstrip("/")
    report = {
        "status": "PASS",
        "cases": records,
        "count": len(records),
        "core": version("sakura-taiko-core"),
        "contract": version("sakura-taiko-contract"),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "cgroup": cgroup,
        "memory_events": (cg / "memory.events").read_text(),
    }
    (a.output / "parity.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    print("QUERY_PARITY_PASS", len(records))


if __name__ == "__main__":
    main()
