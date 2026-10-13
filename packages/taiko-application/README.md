# taiko-application 0.5.0 — Phase 2E candidate

Independent Python distribution for Dani, score presentation, queries and command usecases. Install this subproject,
not the taiko-bot root distribution when installing the center host.
Center keeps Core **0.1.1**; the distributed host keeps Core **0.1.2**.
The distributed root now depends on this same Application distribution.

```sh
python -m pip install ./packages/taiko-application
```

Python 3.11+, Core **>=0.1.1, <=0.1.2**, Contract **0.1.0**; no new formulas or storage format.
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

## Phase 2C: queries

`taiko_application.query` accepts explicit request contexts and returns the legacy
query result types. No file, SQL, userdata, history, sync or Writer implementation
is included. Context mappings belong to the caller: keep them stable during a
request. Exceptions for malformed inputs, list ordering, duplicates, nulls and
numeric precision retain the legacy behavior; this is extraction, not validation
policy redesign.

| Context | Application function | Result |
| --- | --- | --- |
| `SongQueryContext` | `query_music` | rows plus matching mode |
| `SongQueryContext` | `query_aliases` | title, aliases, display ID |
| `ConstantQueryContext` | `query_charts_by_const` | `ConstChartRow` list |
| `PaginationContext` | `paginate_rows` | page rows, current page, total pages |
| `ProgressQueryContext` | progress catalog functions / `summarize_progress` | chart list / Core summary |
| `RecommendationContext` | `project_*` functions | existing recommendation/rating DTO |

Song contexts inject catalogs, Core identity group maps and `SimilarityProvider`.
Sakura supplies its existing `fuzzywuzzy.fuzz.ratio`; Application does not choose
or install another fuzzy matcher. Optional `group_provider` preserves lazy host
catalog acquisition for name/alias matches. Explicit ID and fuzzy queries do not
invoke it. Alias listing uses prepared maps. All provider implementations remain
caller-owned; callers are responsible for their authorization and side effects.

Constant contexts carry prepared song indexes and rating entries. Pagination
preserves page clamping and the original errors for invalid page sizes/types.
Progress contexts carry the existing Core `ProgressCatalogInputs`, prepared
chart/score summaries and availability keys. Recommendation contexts carry
already computed rating objects, ordinary rows or a structural target result.
No entire score calculator or recommendation algorithm was copied. Core 0.1.1
continues to implement identity, aggregation and progress rules.

Sakura retains command parsing/registration, authorization, current/history and
catalog reads, caches, upstream computations, renderers and message sending.
The six modified query modules delegate through contexts; compatibility exports
refer to the same Application model/helper implementations.

### Query parity reproduction

Build/install this subproject's wheel into a disposable target, keeping Core
0.1.1 and Contract 0.1.0. Set `PYTHONPATH` to that target and run from a non-Sakura
working directory through `scripts/memory/run_qa.sh`:

```sh
python tests/query/run_parity.py \
  --reference /path/to/frozen-six-query-modules \
  --adapter /path/to/candidate/taiko/plugins \
  --installed /path/to/isolated-wheel-target \
  --output /var/tmp/query-parity
python tests/query/standalone.py \
  --installed /path/to/isolated-wheel-target \
  --evidence /var/tmp/query-parity/parity.json \
  --output /var/tmp/query-standalone.json
```

`tests/query/provenance.json` pins six complete Phase 2B source files; references
remain external to Git. The small legacy modules execute in full. For the giant
NoneBot plugin, the harness compiles and executes complete unchanged query
function bodies selected by AST, avoiding unrelated startup/Writer imports.
This is execution parity, not an AST-only behavior test or full Bot session.
Only acquisition and upstream result providers are substituted with the same
synthetic fixture; matching, filtering, grouping, Core formulas and projections
execute unchanged. Tests compare old, adapter and direct Application output,
including field/list ordering and exception type/message, acquisition order and
input immutability. Normal cases must succeed, not merely share an exception.

Coverage includes normal/empty/invalid queries, duplicate titles and explicit
IDs, aliases, multi-page constants, page bounds, progress summaries and ordinary/
target/rating explanations. An independent installed-wheel process replays eight
successful results with Sakura/SQL/network imports blocked and all query-time IO
forbidden. No production userdata, database or full Bot event is accessed.

## Phase 2D: command usecases

`taiko_application.commands` provides `execute_b30`, `execute_score`,
`execute_song`, `execute_constant`, `execute_progress`, and
`execute_recommendation`. Each accepts a `CommandContext` and its explicit frozen
`*Ports` dataclass. The caller supplies existing query, calculation, rendering,
parser and resource providers. This package contains no framework event,
authorization decision, data loader implementation or message sender.

`CommandContext` carries plain text/regex captures, the host-authorized subject,
resource settings and a lazy missing-data hint provider. It is not an authorization
token: the host must establish access before calling an execution usecase and
retain all existing before-send checks. Contexts/providers are per request and
must not be shared as mutable account state. Providers can perform existing host
IO; their storage, lock, transaction and Writer implementation remains outside
Application, unchanged. No new database or sync interface is introduced.

`CommandResult` distinguishes text, image, silent finish, fumen selection and fuzzy
fumen selection. Image payloads retain bytes/BytesIO behavior. `delivery` and
`prefix_text` preserve the legacy choice of reply helper versus direct text
finish. Fumen results carry the selected difficulty/song; host delivery retains
file lookup, missing-resource fallback and QQ/OneBot transport behavior.
A `None` result preserves a command's no-op path rather than sending a message.

B30 and progress use `prepare_b30` / `prepare_progress` before the host's existing
permission check. They return parsed values, a terminal result, or (progress
only) `None`. Only successfully prepared requests proceed to authorization and
execution. This preserves invalid-argument versus permission-error precedence.
Score and recommendation retain authorization before input interpretation.
Public song and constant command registration/rules remain unchanged in Sakura.

Sakura's six handler decorators and signatures stay in `plugins/taiko.py`.
Handlers perform platform extraction and authorization, construct providers, then
hand the returned result to `_deliver_application_command`. Original commands
outside these six registrations, data acquisition, renderers, Writer, SQL, sync,
Core and Contract are not moved. Score here means `tinfo`; score mutation,
estimation, scoreline commands and unrelated handlers remain outside Phase 2D.
Song query here means `xx是什么歌`; alias mutation is not part of this extraction.

### Command parity reproduction

Use the existing memory QA wrapper and an independently installed wheel target,
with Python 3.11, Core 0.1.1, Contract 0.1.0 and Pillow 11.3.0:

```sh
python tests/commands/run_parity.py \
  --reference /path/to/frozen-phase2c/taiko.py \
  --adapter /path/to/candidate/taiko/plugins/taiko.py \
  --images /path/to/pinned-phase2c-score-fixture-images \
  --installed /path/to/isolated-wheel-target \
  --output /var/tmp/command-parity
python tests/commands/standalone.py \
  --installed /path/to/isolated-wheel-target \
  --images /path/to/pinned-phase2c-score-fixture-images \
  --evidence /var/tmp/command-parity/parity.json \
  --output /var/tmp/command-standalone.json
```

The complete old command function bodies execute, selected by their decorators
from a SHA256-pinned reference. The candidate handler bodies and Application
usecases execute on the same synthetic event/input providers. AST selection only
avoids NoneBot startup and unrelated infrastructure; it does not replace command
branches, error mapping, text composition or JPEG conversion. Permission-failure
cases exercise the actual retained handler checks and safe binding wrapper with
an injected authority result, asserting no execution-usecase/data-provider call.
The group-level rule/framework scheduler is not started.

Rendering/calculation/data and final message transport are explicit fixture
boundaries. Images are fixed PNG outputs from earlier score-renderer fixtures;
constant/progress/fumen providers use image payload fixtures, not a fresh claim
of rendering those types. Command acceptance checks provider identity, arguments,
call order, exact text, prefixes, empty/silent behavior, PNG/JPEG bytes hash,
pixel hash, dimensions and mode. Thus it tests business dispatch and output
preservation, not full Bot/network delivery or private-data access. Existing
renderer parity remains separate evidence.

An independent process directly invokes all six usecases from the installed
wheel without reading Sakura source. It blocks host/SQL/network imports and all
query-time IO after Pillow plugin initialization. Phase 2D is a candidate feature
branch only; no production install or restart is part of this delivery.

## Phase 2E dual host candidate — BLOCKED

The distributed six-command adapter now delegates to the same `commands` module.
`CommandContext.profile` is explicitly `client` there and defaults to `center` for
the existing Sakura adapter. It preserves B30 grammar/defaults/error handling,
constant empty-result lookup policy and target-recommendation text. Renderer and
query providers preserve each host's fuzzy behavior and argument conventions.
The client Core profiles `progress-client-20261010` and
`recommend-client-20261010` remain at the original providers. No formulas,
permissions, cached-read semantics or private data source are shared across hosts.

Clean installed client plugin registration/OneBot dispatch and both Core versions'
Application fixture replay pass. **The entire Phase 2E is not accepted**: the
center host cannot currently be built by its declared packaging metadata; clean
center plugin dispatch and full fresh cross-host renderer integration are not
proven. See [dual-host validation](tests/dual_host/README.md) for exact boundaries,
installation order, retained implementations and reproduction. No main merge or
production rollout is authorized by these candidate artifacts.
