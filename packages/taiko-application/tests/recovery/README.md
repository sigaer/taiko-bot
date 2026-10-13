# Phase 2E-R recovery validation

This suite validates the existing six command integrations. It adds no application
usecase. Application remains 0.5.0; center Core is 0.1.1, client Core is 0.1.2,
and Python Contract is 0.1.0. The client host candidate is 0.2.9.

## Fresh environments and center source layout

Use separate new Python 3.11 virtual environments, without system site packages,
`PYTHONPATH`, or an existing maintainer environment. Resolve/install all entries
in `locks/center.txt` or `locks/client.txt` with normal pip dependency resolution
and run `pip check`. The Application and Core wheels come from the pinned
Phase 2E sources/wheelhouse; no `--no-deps` acceptance is allowed.

Create the center source runtime with:

```sh
git archive c8ed8c11088152ed2190bc422337a293f02fd9f0:taiko | tar -x -C "$CENTER_SOURCE"
git archive c8ed8c11088152ed2190bc422337a293f02fd9f0 runtime_memory qq_official_runtime | tar -x -C "$SUPPORT"
```

`center-source-provenance.json` pins the 284 Python source files and 15 support
Python files. `runtime_memory` is from this archive, not production `/opt`.
The test adds only these explicit source-layout directories. Application, Core,
Contract and framework dependencies must come from the fresh installed environment.
The center is a source-layout product: `CENTER_SOURCE_RUNTIME_PASS` and
`CENTER_WHEEL_NOT_REQUIRED` are different from a center wheel installation claim.

## Test entrypoints

Run each entrypoint through the existing Viewer `scripts/memory/run_qa.sh`.
Use disk-backed `/var/tmp` sandboxes, serial processes, and an outer 240-second
limit for the complete suite. Both scripts accept `--host center|client`,
`--sandbox`, `--installed` (the fresh venv), `--images` (prior public score fixture
PNG directory) and `--output`. Center additionally uses `--source` and `--support`.

`dispatch.py` loads the actual plugin and preserves its six matcher/rule/handler
objects, dispatches synthetic OneBot events through `handle_event`, and intercepts
only the message transport. Unrelated matchers are excluded. Provider results and
PNG input are fixtures in this dispatch-only test. It asserts captured framework
execution errors are absent, denied requests do not read/render/send private
results, and each allowed command reaches the installed Application usecase.
Center: 23 cases. Client: 39 cases, including 16 send-time denials across the four
private commands. This script alone is not real renderer integration evidence.

`chain.py` additionally requires `--fixture ../fixture.py` and `--resources`.
`provenance.json` pins the synthetic/public fixture, 42 external public assets and
old command references. No image or personal data files are committed here.
It runs real B30 and tinfo Provider preparation, Core computation, rendering,
JPEG conversion and OneBot payload delivery. Center B30 explicitly selects v1;
client retains its existing v1 profile. The v2 chart catalog is injected as input,
not a computed rating/image. Empty historical input is used; no daily Writer is
replaced by or moved into Application. The full draw_dress implementation runs.

Center's legacy filesystem inputs are explicitly redirected to the isolated
fixture layout. Client uses its actual `TAIKO_BOT_ROOT` configuration: no module
resource-global/default-argument patches are applied to client rendering.
The public resource addition is `dress/common/line/line_290.png`; its source and
SHA256 are recorded in provenance. Private Developer API responses use HTTPX
MockTransport, retaining the actual client authorization, provider and cache code.
Audit hooks reject real socket/SQL connections and production file opens, and
record rejected attempts so swallowed errors cannot silently pass.

With `--reference PATH`, the script executes the frozen complete B30/tinfo handler
bodies (removing only registration decorators), installing them on the same real
matcher/rule objects. Calculations and renderers remain real. Compare its
`renderer_png` and `messages` fields with the candidate: encoded hash, decoded
pixel hash, dimensions, mode, text and delivery all must match. Center's renderer
extraction already has Phase 2B parity; this test compares command behavior using
that real renderer, not a second legacy renderer implementation.

With `--revoke`, revoke authority after real rendering and before sending. Run
`--failure bind403|score403|timeout|identity|invalid-identity`. Every case must send
only the safe denial text, never the computed image. `score403` additionally
checks the rejected current cache entry was discarded. The original candidate
failed this test by sending B30 after revocation; the host delivery guard fixes it.
No claim of an atomic authorization lease extending across platform network
transport is made.

## Candidate changes and installation order

The only host behavior changes are the private send-time recheck and four renderer
resource roots honoring existing settings. No renderer functions/formulas are
rewritten. Four private handlers use `taiko_runtime.application_delivery`; public
song/constant commands retain their original delivery path. The six active
usecases still exist only in `taiko_application.commands`.

For a future integration (not performed here), make Application 0.5.0 available
first, then the center source adapter at c8ed8c1 with Core 0.1.1, and the client
0.2.9 wheel with Core 0.1.2. Contract stays 0.1.0. The dependency locks are host
specific; do not install the client root into the center environment. No main
merge, production installation, service restart or deployment is part of this suite.
