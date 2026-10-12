"""Replay query fixtures from installed wheel with no Sakura and no query-time IO."""

from __future__ import annotations
import argparse
import dataclasses
import hashlib
import importlib.abc
import json
import os
from pathlib import Path
import resource
import sys
import time
from types import SimpleNamespace
from fixture import SONGS, ALIASES, CHARTS, BEST, RECOMMENDATIONS, TARGET


class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split(".")[0] in {
            "plugins",
            "taiko_store",
            "nonebot",
            "taiko_runtime",
            "pymysql",
            "mysql",
            "sqlite3",
            "requests",
            "httpx",
        }:
            raise AssertionError("host/SQL/network import: " + fullname)


sys.meta_path.insert(0, NoHost())
from fuzzywuzzy import fuzz
from sakura_taiko_core.chart import identity, progress_catalog as core_catalog
from taiko_application.query import *
import taiko_application


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


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--installed", type=Path, required=True)
    p.add_argument("--evidence", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    assert Path(taiko_application.__file__).is_relative_to(a.installed.resolve())
    expected = {
        c["case"]: c["output_sha256"]
        for c in json.loads(a.evidence.read_text())["cases"]
    }
    _, byid, bytitle = identity.build_group_maps(SONGS)
    song = SongQueryContext(
        SONGS, ALIASES, byid, bytitle, fuzz.ratio, query="NEON", song_id=2
    )
    const = ConstantQueryContext({s["id"]: s for s in SONGS}, CHARTS, 6.6)
    keys = {
        (int(s["id"]), level)
        for s in SONGS
        for level in (4, 5)
        if s.get(f"level_{level}") not in (None, "", "-") and s.get("shelf_status") != 1
    }
    summary = ProgressQueryContext(
        core_catalog.ProgressCatalogInputs(),
        items=[
            (1, 4, "Neon"),
            (1, 4, "duplicate"),
            (1, 5, "Neon Ura"),
            (3, 4, "Moon"),
            (2, 4, "off-shelf"),
        ],
        best_map=BEST,
        available_chart_keys=keys,
    )
    calls = {
        "song/name": lambda: query_music(song),
        "alias/2/False": lambda: query_aliases(song),
        "constant/6.6/False": lambda: query_charts_by_const(const),
        "pagination/2/25": lambda: paginate_rows(
            PaginationContext(query_charts_by_const(const), 2)
        ),
        "summary/5": lambda: summarize_progress(summary),
        "recommendation/ordinary/rating/4": lambda: project_ordinary_recommendations(
            RecommendationContext(rows=RECOMMENDATIONS)
        ),
        "recommendation/target/"
        + TARGET.target_key: lambda: project_target_recommendations(
            RecommendationContext(target_result=TARGET)
        ),
        "recommendation/rating/1": lambda: project_player_rating(
            RecommendationContext(
                rating_results=[
                    SimpleNamespace(
                        AI_rating=10.0,
                        big_song=9.0,
                        stamina=8.0,
                        speed=7.0,
                        accuracy_power=6.0,
                        rhythm=5.0,
                        complex_proc=4.0,
                    )
                ]
            )
        ),
    }
    active = True

    def guard(event, args):
        if active and (
            event == "open"
            or event.startswith(
                ("socket.", "subprocess.", "os.mkdir", "os.remove", "os.rename")
            )
        ):
            raise AssertionError("query IO: " + event)

    sys.addaudithook(guard)
    started = time.monotonic()
    results = []
    for name, call in calls.items():
        result = {"result": canon(call())}
        digest = hashlib.sha256(
            json.dumps(
                result, ensure_ascii=False, allow_nan=True, separators=(",", ":")
            ).encode()
        ).hexdigest()
        assert digest == expected[name], name
        results.append({"case": name, "status": "PASS", "output_sha256": digest})
    active = False
    a.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "cases": results,
                "count": len(results),
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            indent=2,
        )
    )
    print("QUERY_STANDALONE_PASS", len(results))


if __name__ == "__main__":
    main()
