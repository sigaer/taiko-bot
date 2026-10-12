"""Six direct usecase replays from an installed wheel; no Sakura source dependency."""

import argparse, dataclasses, hashlib, importlib.abc, io, json, re, resource, sys, time
from pathlib import Path
from PIL import Image


class NoHost(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, *args):
        if fullname.split(".")[0] in {
            "plugins",
            "taiko_store",
            "taiko_runtime",
            "nonebot",
            "qq_official_runtime",
            "pymysql",
            "mysql",
            "sqlite3",
            "requests",
            "httpx",
        }:
            raise AssertionError("host import " + fullname)


sys.meta_path.insert(0, NoHost())
from taiko_application import commands as app


def sha(v):
    return hashlib.sha256(v).hexdigest()


def image_result(data, prefix=""):
    if isinstance(data, io.BytesIO):
        data = data.getvalue()
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        payload = {
            "bytes_sha256": sha(data),
            "pixels_sha256": sha(im.tobytes()),
            "dimensions": list(im.size),
            "mode": im.mode,
            "format": im.format,
        }
    return {"kind": "image", "payload": payload, "prefix": prefix}


def jpeg(data, quality=85):
    with Image.open(io.BytesIO(data)) as src:
        im = Image.new("RGB", src.size, (255, 255, 255))
        if src.mode in ("RGBA", "LA"):
            alpha = src.getchannel("A")
            try:
                im.paste(src, mask=alpha)
            finally:
                alpha.close()
        else:
            im.paste(src.convert("RGB"))
        try:
            out = io.BytesIO()
            im.save(out, format="JPEG", quality=quality, optimize=True)
            return out.getvalue()
        finally:
            im.close()


def unexpected(*a, **k):
    raise AssertionError("unexpected provider")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--images", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    a = parser.parse_args()
    assert Path(app.__file__).is_relative_to(a.installed.resolve())
    evidence = json.loads(a.evidence.read_text())
    expected = {
        (x["command"], x["case"]): x["result"]["outputs"] for x in evidence["cases"]
    }
    provenance = json.loads(Path(__file__).with_name("provenance.json").read_text())
    images = {}
    for key, entry in provenance["images"].items():
        data = (a.images / entry["path"]).read_bytes()
        assert sha(data) == entry["sha256"]
        images[key] = data
    common = {
        "_to_jpeg_bytes": jpeg,
        "TAIKOB_FONT_PATH": "fixture-font",
        "FONT_PATH": "fixture-font",
        "DEFAULT_PAGE_SIZE": 25,
    }
    values = {
        "b30": dict(
            compute_all_from_userdata=lambda *a, **k: [{"fixture_rating": 10}],
            render_b30_image=lambda *a, **k: images["b30"],
        ),
        "score": dict(
            queryMusic=lambda *a, **k: [[1, "Neon"]],
            _is_rejected_fuzzy_query_result=lambda x: False,
            generate_score_image=lambda *a, **k: images["score"],
        ),
        "song": dict(
            _extract_what_song_query=lambda x: "Neon",
            _resolve_what_song_query=lambda *a: [[1, "Neon"]],
            _is_rejected_fuzzy_query_result=lambda x: False,
        ),
        "constant": dict(
            query_charts_by_const=lambda *a, **k: list(range(30)),
            paginate_rows=lambda rows, page=1: (rows[:25], 1, 2),
            render_const_query_image=lambda *a, **k: images["constant"],
        ),
        "progress": dict(
            parse_dani_progress_request=lambda x: None,
            _load_decimal_progress_set=lambda: {"6.6"},
            _load_pass_progress_set=lambda: {"6.6"},
            render_pass_progress_image_bytes=lambda **k: images["progress"],
        ),
        "recommendation": dict(
            TAIKOREC_COMMAND_EXTRACT_RE=re.compile(r"^taikorec\s*(.*)$"),
            DIM_MAP={"rating": "rating"},
            compute_recommendations_for_user=lambda **k: [{"song_id": 1, "level": 4}],
            generate_recommend_image=lambda *a, **k: io.BytesIO(
                images["recommendation"]
            ),
        ),
    }
    contexts = {
        "b30": app.CommandContext(user_id="42"),
        "score": app.CommandContext(
            user_id="42", match=re.match(r"tinfo (.*)", "tinfo Neon")
        ),
        "song": app.CommandContext(text="Neon是什么歌"),
        "constant": app.CommandContext(match=re.match(r"(6.6)(.*)", "6.6")),
        "progress": app.CommandContext(user_id="42", assets_base="fixture-assets"),
        "recommendation": app.CommandContext(
            user_id="42", text="taikorec", rating_path="fixture-rating"
        ),
    }
    Image.init()
    active = True

    def guard(event, args):
        if active and (
            event == "open"
            or event.startswith(
                ("socket.", "subprocess.", "os.mkdir", "os.rename", "os.remove")
            )
        ):
            raise AssertionError("usecase IO " + event)

    sys.addaudithook(guard)
    started = time.monotonic()
    results = []
    labels = {
        "b30": "taikob 30 v1",
        "progress": "6.6进度",
        "recommendation": "taikorec",
    }
    for key, overrides in values.items():
        cls = getattr(app, key.title() + "Ports")
        fields = {
            f.name: common.get(f.name, unexpected) for f in dataclasses.fields(cls)
        }
        fields.update(overrides)
        args = [contexts[key], cls(**fields)]
        if key == "b30":
            args.append((30, [], False, False, None))
        if key == "progress":
            args.append(("6.6进度", 1))
        result = getattr(app, "execute_" + key)(*args)
        if key == "song":
            assert result.kind == "fumen" and result.payload == ("Oni", "1")
            actual = [image_result(images["song"])]
        else:
            assert result.kind == "image"
            actual = [image_result(result.payload, result.prefix_text)]
        assert actual == expected[(key, labels.get(key, "normal"))], key
        results.append({"command": key, "status": "PASS", "output": actual})
    active = False
    a.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "cases": results,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            },
            indent=2,
        )
    )
    print("COMMAND_STANDALONE_PASS", len(results))


if __name__ == "__main__":
    main()
