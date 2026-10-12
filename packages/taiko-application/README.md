# taiko-application 0.2.0 — Phase 2B

Independent Python distribution for Dani and score presentation. Install this subproject,
not the taiko-bot root distribution (which has a different Core pin).

```sh
python -m pip install ./packages/taiko-application
```

Python 3.11+, Core **0.1.1**, Contract **0.1.0**; no new formulas or storage format.
For exact PNG reproduction use Pillow **11.3.0** and the same font/image inputs.
Public API: `taiko_application.dani`.

- `DaniInputs`: prepared grade/catalog/roll/rating inputs, no account lookup.
- `DaniProgressService.prepare`: score and normalized dojo payload → display model.
- `DaniProgressRenderer.render`: model + `DaniAssets` paths → PNG bytes.
- `dani.rating.build_rating_context`: existing Core calls with supplied identity data.

The caller owns authorization, current/history acquisition, catalog refresh and
resource availability. Missing userdata is `None`; an account without scores is
`{"songs": [], "dojo": {}}`. Those states produce different, preserved outputs.
Instantiate the service per request: player caches are request scoped; no account
state, SQL, sync, Writer, network or Sakura import exists in this distribution.
Renderer reads only specified templates/fonts/icons and closes its icon cache.
No fonts, userdata or production assets are shipped with the package.

Sakura integration is a separate feature-branch adapter at
`taiko/plugins/utils/dani_progress.py`. Its existing command signature is retained.
Install this package before loading that adapter in an isolated candidate. This
is not a deployment instruction; Phase 2A makes no production service changes.

## Reproduce Phase 2A acceptance

The checked-in `tests/fixture.py` contains public chart vectors and 30 synthetic
score rows, plus a three-song normalized dojo result. It contains no player
snapshot. `tests/provenance.py` pins the SHA256 of eight unmodified P0 reference
source files and 32 externally supplied presentation assets. The legacy
`dani_progress.py` is identical to Sakura `cc66b220`'s file; the score calculator
reference is the accepted P0 file (`8f3e9a7d…`). Tests reject a different reference
or asset set before importing the legacy code.

Build/install the wheel in a private target or disposable environment without
changing the existing Core/Contract packages. From the Viewer repo use its
`bash scripts/memory/run_qa.sh` wrapper for each command. Example test arguments:

```sh
python tests/run_parity.py \
  --legacy-root /path/to/frozen/reference \
  --adapter /path/to/candidate/Sakura_bot/taiko/plugins/utils/dani_progress.py \
  --asset-root /path/to/pinned/assets \
  --output /var/tmp/dani-parity
python tests/standalone.py \
  --asset-root /path/to/pinned/assets \
  --installed-root /path/to/private/installed-package
```

The frozen reference directory contains the eight modules named in provenance;
its parent contains a test-only `taiko_runtime/memory.py` from the original
runtime, which uses the existing `/opt/python-memory-runtime/1.1.0` helper. This
is a legacy harness prerequisite, **not an Application dependency**. Tests load
full reference modules under an isolated namespace. Only catalog and account
input boundaries are redirected to the same fixture; allocation, Core calls,
drawing, PNG encoding and the candidate adapter execute normally.

Acceptance compares the complete derived targets and section models, PNG bytes,
decoded pixels, dimensions and mode, across old/Application/adapter outputs:
2025 六段 with dynamic-rate, the same grade with only three scores, empty scores,
and absent userdata. The 2025 六段 test rejects any scoreline refresh. Existing
`dani_overview` is also imported against the adapter compatibility surface.

The standalone check loads the installed wheel, blocks host/network/SQL imports
and all filesystem writes, and reproduces the pinned dynamic PNG. Original
production-data-reading/batch tests are not invoked. No full Bot session or
production rollout is claimed. This completes Phase 2A only.


## Phase 2B: score presentation

`taiko_application.score` exposes `ScorePresentationContext` and four renderers:
`B30Renderer`, `B30SingleRenderer`, `ScoreInfoRenderer`, `RecommendationRenderer`.
Construct a renderer with a prepared context, then call `render()`.
B30/score detail return PNG bytes; recommendation preserves the legacy `BytesIO`
result. Single cards also support `render(as_png_bytes=False)` returning a
caller-owned Pillow image. Core 0.1.1 and Contract 0.1.0 pins are unchanged.

```python
from pathlib import Path
from taiko_application.score import ScorePresentationContext, B30SingleRenderer

context = ScorePresentationContext(
    assets_base=Path("/isolated/public-assets"),
    entry=prepared_entry,
    song_info=prepared_song,
    rating=prepared_rating,
)
png = B30SingleRenderer(context).render()
```

The context contains prepared entries, rating text values, v1/v2 display metrics,
B30 ordering/means/deltas, trend rows, update text and external profile layers.
The caller owns its mappings and supplied images; keep them stable for a render.
The renderer does not mutate these inputs or close caller-owned images. Its own
Pillow images and icon cache are released after each call, including failures.
Use one renderer instance per request; do not share an instance concurrently.
`layout_assets_base` preserves the legacy distinction between global layout/font
resources and a per-request cover/icon root. Explicit font candidates preserve
caller-selected fallback order. Only supplied presentation resources are read.

Sakura retains commands, authorization, score/catalog/v2 acquisition, Core calls,
previous-score comparison, daily/history behavior, draw_dress generation and
message sending. Its four original entry points prepare the context and delegate.
No database, Writer, daily/history or sync implementation moved to Application.
The draw_dress profile layers remain outside this extraction; they are inputs,
not a second implementation of any of these four renderers. Install this isolated
subproject before using the adapter branch; no production installation is part
of Phase 2B.

### Score parity reproduction

Run `tests/score/run_parity.py` through the existing memory QA wrapper:

```sh
python tests/score/run_parity.py \
  --reference /path/to/frozen-four-original-modules \
  --adapter /path/to/candidate/taiko/plugins/utils \
  --assets /path/to/pinned-public-assets \
  --output /var/tmp/score-parity
python tests/score/standalone.py \
  --evidence /var/tmp/score-parity \
  --installed /path/to/isolated-installed-wheel
```

Set `PYTHONPATH` to the isolated wheel target. Use Core 0.1.1, Contract 0.1.0 and
Pillow 11.3.0 for byte parity. `tests/score/provenance.json` pins the four complete,
unmodified original modules and public presentation assets. Reference source
matches the accepted P0 runtime byte for byte. Sources/assets remain external;
no user snapshot or production asset bundle is committed.

The test matrix executes all four original renderer bodies and all four adapter
entry points on ordinary/FC/DF/high-rating/no-score/missing-optional-resource
fixtures. It compares PNG bytes by SHA256, decoded pixel SHA256, dimensions and
mode; it also checks a genuine 30-card B30 grid and update-delta display.
Missing mandatory templates must raise the same error before v2/daily acquisition.

The harness replaces only excluded boundaries: prepared daily/prior data,
profile/dress layers, catalog/identity input and v2 acquisition. Rating operations
use pinned Core functions. No renderer, layout, text, crown, template selection,
PNG encoding or pixel comparison is mocked. The profile layer is a synthetic
image, so this is not a draw_dress integration claim. Daily/Writer is never run.
The standalone test replays captured contexts from the installed wheel without
Sakura imports, any writes, network or data-file reads. This acceptance covers
score presentation, not full Bot events or production deployment.
