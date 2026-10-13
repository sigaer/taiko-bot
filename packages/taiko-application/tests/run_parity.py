"""Bounded real legacy/Application/Sakura-adapter PNG parity; public/synthetic inputs.

Run under the repository's memory QA wrapper. See README for required frozen
legacy sources and external asset manifest. No network or database is permitted.
"""

from __future__ import annotations
import argparse
import copy
import hashlib
import importlib
import importlib.util
from importlib.metadata import version
import io
import json
import os
from pathlib import Path
import resource
import sys
import time
import types

from fixture import FIXTURE
from provenance import PROVENANCE


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-root", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    cgroup = Path('/proc/self/cgroup').read_text().strip().split('::',1)[1]
    cgroup_dir = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
    for name, expected in PROVENANCE["reference"].items():
        with (args.legacy_root / (name + ".py")).open("rb") as source:
            require(
                hashlib.file_digest(source, "sha256").hexdigest() == expected,
                "Legacy reference changed: " + name,
            )
    for name, expected in PROVENANCE["assets"].items():
        with (args.asset_root / name).open("rb") as source:
            require(
                hashlib.file_digest(source, "sha256").hexdigest() == expected,
                "Presentation asset changed: " + name,
            )
    os.environ["TAIKO_COMPUTE_ONLY"] = "1"
    sys.dont_write_bytecode = True
    require(version("sakura-taiko-core") == "0.1.1", "Core pin changed")
    require(version("sakura-taiko-contract") == "0.1.0", "Contract pin changed")

    # A test-only namespace lets the unmodified legacy source import its real siblings
    # without importing Sakura's giant plugins.utils initializer and its Writers.
    sys.path.insert(0, str(args.legacy_root.parent))
    package("legacy_dani", args.legacy_root)
    duplicate = importlib.import_module("legacy_dani.duplicate_versions")
    from sakura_taiko_core.chart.identity import build_group_maps

    groups = build_group_maps(FIXTURE["song_catalog"])
    duplicate._group_cache = lambda *a, **kw: groups
    dojo = importlib.import_module("legacy_dani.dojo_score")
    dojo.GRADE_CONFIG_PATH = args.output / "grade.json"
    dojo.GRADE_CONFIG_PATH.write_text(json.dumps(FIXTURE["grade_payload"]))
    scoreline = types.ModuleType("legacy_dani.score_line")

    def unexpected_roll_refresh():
        raise AssertionError("2025 六段 must not trigger scoreline refresh")

    scoreline.load_scoreline_data = unexpected_roll_refresh
    sys.modules[scoreline.__name__] = scoreline
    legacy = importlib.import_module("legacy_dani.dani_progress")
    # These are the genuine P0 functions, including _get_song_indicator_value.
    score = importlib.import_module("legacy_dani.score_calculator")
    require(callable(score._get_song_indicator_value), "P0 dynamic-rate bridge missing")

    from taiko_application.dani import (
        DaniAssets,
        DaniInputs,
        DaniProgressService,
        DaniProgressRenderer,
    )
    from taiko_application.dani.rating import build_rating_context

    default_ids = {sid: group.default_id for sid, group in groups[1].items()}
    duplicate_groups = sorted(
        group.ids for group in groups[0].values() if len(group.ids) > 1
    )
    inputs = DaniInputs(
        {"2025": FIXTURE["grade_payload"], "2026": {"year": "2026", "grades": []}},
        FIXTURE["song_catalog"],
        FIXTURE["roll_catalog"],
        build_rating_context(
            FIXTURE["rating_config"],
            default_ids=default_ids,
            duplicate_groups=duplicate_groups,
        ),
    )
    assets = DaniAssets(
        args.asset_root / "templates/dani_up.png",
        args.asset_root / "templates/dani_down.png",
        args.asset_root / "icons/diff",
        args.asset_root / "icons/dani",
        args.asset_root / "fonts/FZPW_GBK.ttf",
        args.asset_root / "fonts/DDFont.ttf",
    )
    songs_dir = args.output / "songs"
    songs_dir.mkdir(exist_ok=True)
    (songs_dir / "song_data.json").write_text(json.dumps(FIXTURE["song_catalog"]))
    (songs_dir / "rating_structured_with_ids.json").write_text(
        json.dumps(FIXTURE["rating_config"])
    )
    (songs_dir / "grade_dojo_nijiiro_2025_simple.json").write_text(
        json.dumps(FIXTURE["grade_payload"])
    )
    (args.output / "grade2026.json").write_text('{"year":"2026","grades":[]}')
    for attr, value in {
        "BASE": args.output,
        "USERDATA_DIR": args.output / "userdata",
        "VERSION_CONFIG_PATHS": {
            "2025": dojo.GRADE_CONFIG_PATH,
            "2026": args.output / "grade2026.json",
        },
        "UP_TEMPLATE_PATH": assets.upper,
        "DOWN_TEMPLATE_PATH": assets.lower,
        "DIFF_DIR": assets.difficulty_icons,
        "DANI_DIR": assets.dani_icons,
        "FONT_PATH": assets.font,
        "DDFONT_PATH": assets.ddfont,
    }.items():
        setattr(legacy, attr, value)
    legacy.USERDATA_DIR.mkdir(exist_ok=True)

    package("candidate_dani", args.adapter.parent)
    sys.modules["candidate_dani.dojo_score"] = dojo
    sys.modules["candidate_dani.score_line"] = scoreline
    sys.modules["candidate_dani.duplicate_versions"] = duplicate
    authority = importlib.import_module("legacy_dani.taiko_domain_adapter")
    sys.modules["candidate_dani.taiko_domain_adapter"] = authority
    adapter = load_module("candidate_dani.dani_progress", args.adapter)
    importlib.import_module(
        "candidate_dani.dani_overview"
    )  # existing runtime consumer, actual import
    for attr in [
        "BASE",
        "USERDATA_DIR",
        "VERSION_CONFIG_PATHS",
        "UP_TEMPLATE_PATH",
        "DOWN_TEMPLATE_PATH",
        "DIFF_DIR",
        "DANI_DIR",
        "FONT_PATH",
        "DDFONT_PATH",
    ]:
        setattr(adapter, attr, getattr(legacy, attr))

    # Enforce that tests cannot accidentally read live userdata, credentials or write
    # outside their own artifacts. The application standalone probe is stricter.
    output_root = args.output.resolve()
    production_root = Path("/home/sigaer/taiko").resolve()

    def audit(event, values):
        if event in {"socket.connect", "socket.bind", "subprocess.Popen", "os.system"}:
            raise RuntimeError("External IO forbidden in Dani parity")
        if event == "open" and isinstance(values[0], (str, bytes, os.PathLike)):
            path = Path(os.fsdecode(values[0])).resolve()
            if path.is_relative_to(production_root) and not path.is_relative_to(
                production_root / ".venv"
            ):
                raise RuntimeError("Live runtime access forbidden in Dani parity")
            mode = values[1] or ""
            flags = values[2] or 0
            if (
                any(x in mode for x in "wax+")
                or flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT)
            ) and not path.is_relative_to(output_root):
                raise RuntimeError("Write outside QA artifacts forbidden")

    sys.addaudithook(audit)

    from PIL import Image

    commands = [
        "虹2025六段进度",
        "2025 6段进度",
        "虹25六段进度",
        "虹2025未知段位进度",
        "虹六段进度",
        "虹2025未知进度",
    ]
    for command in commands:
        expected = legacy.parse_dani_progress_request(command)
        require(
            expected
            == DaniProgressService(inputs).parse_dani_progress_request(command),
            "request parsing differs",
        )
        require(
            expected == adapter.parse_dani_progress_request(command),
            "Sakura parsing differs",
        )

    fixture_before = canonical(FIXTURE)
    results = []
    cases = [
        ("2025-six-dynamic", FIXTURE["userdata"]),
        (
            "2025-six-basic",
            {
                "songs": FIXTURE["userdata"]["songs"][:3],
                "dojo": FIXTURE["userdata"]["dojo"],
            },
        ),
        ("empty-scores", {"songs": [], "dojo": {}}),
        ("missing-userdata", None),
    ]
    for name, userdata in cases:
        target = legacy.USERDATA_DIR / "900001data.json"
        if userdata is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(json.dumps(userdata))
        captured = []
        draw = legacy._draw_progress_section

        def capture(canvas, top, title, grade, songs, footer, **kw):
            captured.append(
                {
                    "title": title,
                    "songs": copy.deepcopy(songs),
                    "footer": copy.deepcopy(footer),
                    "title_icon": kw.get("title_icon", 0),
                }
            )
            return draw(canvas, top, title, grade, songs, footer, **kw)

        legacy._draw_progress_section = capture
        try:
            old_png = legacy.render_dani_progress_image_bytes(
                900001, "六段", version="2025", explicit_version=True
            )
        finally:
            legacy._draw_progress_section = draw
        normalized_dojo = dojo.normalize_dojo_scores((userdata or {}).get("dojo", {}))
        service = DaniProgressService(inputs)
        model = service.prepare(
            900001,
            "六段",
            userdata=copy.deepcopy(userdata),
            dojo_payload=normalized_dojo,
            dan_id=FIXTURE["dan_id"],
            version="2025",
            explicit_version=True,
        )
        if userdata is not None:
            expected_derived = legacy._derive_song_targets(
                legacy._load_grade_index("2025")["六段"], userdata["songs"]
            )
            require(
                canonical(expected_derived) == canonical(model.derived),
                name + ": target allocation differs",
            )
            actual = [
                {
                    "title": s.title,
                    "songs": [
                        {k: v for k, v in song.items() if k != "star"}
                        for song in s.songs
                    ],
                    "footer": s.footer,
                    "title_icon": s.title_icon,
                }
                for s in model.sections
            ]
            require(
                canonical(captured) == canonical(actual),
                name + ": display model differs",
            )
        if name == "2025-six-dynamic":
            require(
                model.derived["dynamic_rate_enabled"] is True,
                "dynamic-rate silently disabled",
            )
            require(
                len(model.derived["dynamic_role_dims_per_song"]) == 3,
                "missing three-song role allocation",
            )
        if name == "2025-six-basic":
            require(
                model.derived["dynamic_rate_enabled"] is False,
                "too few songs should use fixed targets",
            )
        if name in {"2025-six-dynamic", "2025-six-basic"}:
            require(
                all(song["entry"] is not None for song in model.sections[0].songs),
                "missing regular scores",
            )
            require(
                all(song["entry"] is not None for song in model.sections[1].songs),
                "missing in-dojo scores",
            )
        if name == "empty-scores":
            require(
                model.derived["dynamic_rate_enabled"] is False,
                "empty scores unexpectedly dynamic",
            )
            require(
                all(song["entry"] is None for song in model.sections[0].songs),
                "empty scores fabricated entries",
            )
        new_png = DaniProgressRenderer(assets).render(model)
        adapter_png = adapter.render_dani_progress_image_bytes(
            900001, "六段", version="2025", explicit_version=True
        )
        old_hash = hashlib.sha256(old_png).hexdigest()
        require(
            hashlib.sha256(new_png).hexdigest() == old_hash, name + ": PNG bytes differ"
        )
        require(
            hashlib.sha256(adapter_png).hexdigest() == old_hash,
            name + ": adapter PNG bytes differ",
        )
        with Image.open(io.BytesIO(old_png)) as a, Image.open(io.BytesIO(new_png)) as b:
            require(
                a.size == b.size and a.mode == b.mode, name + ": image geometry differs"
            )
            pixels = hashlib.sha256(a.tobytes()).hexdigest()
            require(
                pixels == hashlib.sha256(b.tobytes()).hexdigest(),
                name + ": decoded pixels differ",
            )
            size = list(a.size)
        for suffix, png in [
            ("legacy", old_png),
            ("application", new_png),
            ("adapter", adapter_png),
        ]:
            (args.output / (name + "-" + suffix + ".png")).write_bytes(png)
        results.append(
            {
                "case": name,
                "status": "PASS",
                "size": size,
                "png_sha256": old_hash,
                "pixels_sha256": pixels,
                "dynamic_rate_enabled": model.derived.get("dynamic_rate_enabled"),
                "role_dimensions": model.derived.get("dynamic_role_dims_per_song"),
            }
        )
    require(canonical(FIXTURE) == fixture_before, "input fixture mutated")
    result = {
        "status": "PASS",
        "core": version("sakura-taiko-core"),
        "contract": version("sakura-taiko-contract"),
        "pillow": version("Pillow"),
        "cases": results,
        "request_cases": len(commands),
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "cgroup": cgroup,
        "memory_peak_bytes": int((cgroup_dir / 'memory.peak').read_text()) if (cgroup_dir / 'memory.peak').exists() else None,
        "memory_events": (cgroup_dir / 'memory.events').read_text().strip(),
        "memory_current_bytes": int((cgroup_dir / 'memory.current').read_text()),
        "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    (args.output / "parity.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
