# taiko-application 0.1.0 — Phase 2A

Independent Python distribution for Dani display only. Install this subproject,
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
