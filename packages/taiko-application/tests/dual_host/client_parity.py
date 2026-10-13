"""Execute complete old/new client handlers with injected authorized providers.

Images are the fixed public/synthetic Phase 2B resources. This test covers command
orchestration/encoding, not private transport or the unextracted client renderers.
Actual plugin dispatch and private transport are tested separately.
"""

import argparse, ast, asyncio, importlib.util, json, types, re, hashlib, sys
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "command_reference_test", Path(__file__).parents[1] / "commands/run_parity.py"
)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
r.HELPERS.add("_extract_official_what_song_query")


class ClientFixture(r.Fixture):
    def __init__(self, tree, images):
        super().__init__(tree, images)
        ns = self.ns
        ns.update(
            UserdataProviderError=r.BindError,
            SimpleNamespace=types.SimpleNamespace,
            ASSETS_DIR="fixture-assets",
            _SETTINGS="fixture-settings",
            is_qq_official_event=lambda e: False,
        )
        ns["logger"] = types.SimpleNamespace(
            exception=lambda *a: self.trace.append(["log", *a])
        )

        async def assets(*a):
            self.trace.append(["assets", list(a[2:])])
            return not self.options.get("asset_failure", False)

        ns["_ensure_asset_resources_ready"] = assets

        def read(user_id, **kwargs):
            self.trace.append(["current", user_id, kwargs])
            error = self.options.get("current_error")
            if error:
                raise RuntimeError(error)
            return {"songs": [{"song_no": 1, "level": 4, "high_score": 900000}]}

        def view(user_id, **kwargs):
            self.trace.append(["view", user_id, kwargs])
            return {
                "userdata": {
                    "songs": [{"song_no": 1, "level": 4, "high_score": 910000}]
                },
                "snapshots": [],
            }

        def compute(rows):
            self.trace.append(["compute_records", rows])
            if self.options.get("compute_error"):
                raise TypeError("bad data")
            return self.options.get(
                "compute_all_from_userdata", [{"fixture_rating": 10}]
            )

        ns.update(
            ensure_userdata_available=read,
            ensure_userdata_view_available=view,
            compute_all_from_userdata_records=compute,
        )

    async def run(self, *args):
        try:
            return await super().run(*args)
        except Exception as error:
            return {
                "outputs": r.copy.deepcopy(self.outputs),
                "calls": r.copy.deepcopy(self.trace),
                "exception": [type(error).__name__, str(error)],
            }


def cases():
    for key, label, text, opts in r.cases():
        if key == "b30":
            # Same fixture values, but the client's documented grammar requires N.
            text = text.replace("taikob v1", "taikob30").replace(
                "taikob v2", "taikob20 v2"
            )
        yield key, label, text, opts
    for text in [
        "taikob30",
        "taikob20 v2",
        "taikob20 v2 体力",
        "taikob20 v2 -r",
        "taikob20 v2 unknown",
        "taikob30 -r",
        "taikob30 体力",
    ]:
        yield "b30", "client/" + text, text, {}
    for error in ["missing", "file", "type", "v2"]:
        yield "b30", "v2-error/" + error, "taikob20 v2", {
            "fail": {"render_b20_v2_image": error}
        }
    for key, text in [
        ("b30", "taikob30"),
        ("score", "tinfo Neon"),
        ("constant", ""),
        ("progress", "6星进度"),
        ("recommendation", "taikorec"),
    ]:
        yield key, "assets-failed", text, {"asset_failure": True}
    for key, text in [
        ("b30", "taikob30"),
        ("progress", "6星进度"),
        ("recommendation", "推荐歌曲 紫雅"),
    ]:
        for error in ["revoked", "timeout", "invalid identity"]:
            yield key, "current/" + error, text, {"current_error": error}


async def main():
    p = argparse.ArgumentParser()
    for name in ["reference", "adapter", "images", "output"]:
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args()
    prov = json.loads(
        (Path(__file__).parents[1] / "commands/provenance.json").read_text()
    )
    images = {k: (a.images / v["path"]).read_bytes() for k, v in prov["images"].items()}
    for k, v in prov["images"].items():
        assert r.digest(images[k]) == v["sha256"]
    provenance = json.loads(Path(__file__).with_name("provenance.json").read_text())
    assert r.digest(a.reference.read_bytes()) == provenance["client_reference_sha256"]
    old = ClientFixture(ast.parse(a.reference.read_text()), images)
    new = ClientFixture(ast.parse(a.adapter.read_text()), images)
    results = []
    visited = set()
    r.Image.init()
    active = True

    def guard(event, args):
        if active and (
            event == "open"
            or event.startswith(
                ("socket.", "subprocess.", "os.mkdir", "os.rename", "os.remove")
            )
        ):
            raise AssertionError("Unexpected command IO " + event)

    sys.addaudithook(guard)
    for key, label, text, opts in cases():
        left = await old.run(key, text, opts)
        right = await new.run(key, text, opts)
        if left != right:
            raise AssertionError(
                json.dumps(
                    {"command": key, "case": label, "old": left, "new": right},
                    ensure_ascii=False,
                    default=str,
                )
            )
        if "exception" in left:
            allowed = (
                key == "b30"
                and (
                    label
                    in (
                        "render_b20_v2_image/type",
                        "render_b20_v2_image/v2",
                        "v2-error/type",
                        "v2-error/v2",
                    )
                    or label.startswith("current/")
                )
            ) or (key == "progress" and label.startswith("current/"))
            assert allowed, (key, label, left["exception"])
            assert left["exception"][0] in ("TypeError", "V2Error", "RuntimeError")
        if label.startswith("permission/"):
            assert new.app_calls == 0 and right["calls"] == [["permission"]], (
                key,
                label,
                right,
            )
        if new.app_calls:
            visited.add(key)
        results.append(
            {
                "command": key,
                "case": label,
                "result": left,
                "app_calls": new.app_calls,
                "status": "PASS",
            }
        )
    active = False
    assert visited == set(r.REG)
    a.output.write_text(
        json.dumps(
            {
                "status": "PASS",
                "count": len(results),
                "reference_sha256": r.digest(a.reference.read_bytes()),
                "cases": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("CLIENT_COMMAND_PARITY_PASS", len(results))


if __name__ == "__main__":
    asyncio.run(main())
