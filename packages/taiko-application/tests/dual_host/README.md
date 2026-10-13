# Phase 2E validation — blocked candidate

Application 0.5.0 and client 0.2.8, feature branch only. The center keeps Core
0.1.1, the client keeps Core 0.1.2, and both keep Python Contract 0.1.0.
Application accepts only `>=0.1.1,<=0.1.2`; both hosts must retain their exact pins.
Pillow's existing lower bound remains unchanged; reproduction pins 11.3.0.

## Actual coverage

- Clean system-Python venvs, ordinary PEP 517 wheels and full pip dependency
  resolution. Neither `--no-deps`, editable installs, source `PYTHONPATH`, a
  maintainer venv nor a running Sakura checkout is part of the installation proof.
- Both Core versions: installed Application Dani dynamic-rate PNG, four score
  contexts, eight query contexts and six center-profile command contexts replayed.
- Center: 86 original frozen handler versus Phase 2D adapter cases, including
  output, JPEG/PNG bytes and pixels, dimensions/mode, provider order and denials.
- Client: 111 full old/new handler cases in `client_parity.py`. Reference digest
  is required by `provenance.json`. Ten intentionally propagating failures are
  checked explicitly; unexpected exceptions cannot count as successful parity.
- `plugin_dispatch.py`: actual installed plugin registration and NoneBot
  `handle_event`, actual OneBot event, real matching/dependency injection and
  host send helpers, mocked API transport. Six handlers; 22 scenarios including
  image, text, empty, invalid and denial. Run postprocessor rejects swallowed
  handler exceptions. Other product matchers are excluded from event execution;
  the real six rule/handler objects are retained. No startup connections run.
- `private_transport.py`: actual installed Developer API reader/cache with
  in-memory HTTP transport; 401/403/404/429/500/503, timeout, absent token and
  invalid identity fail closed after a successful cached read.

The command matrix injects renderer outputs from the public/synthetic Phase 2B
fixtures. It proves orchestration/encoding, **not a fresh execution of all client
renderers against live or synthetic private-provider pipelines**. No production
userdata is copied. The private transport tests do not claim to prove revocation
between the last authorized read and a later send; existing host behavior is
unchanged, and that full race acceptance remains unverified.

## Reproduction

Run QA through the existing Viewer `scripts/memory/run_qa.sh`, with a disk-backed
`/var/tmp` work area and serial bounded processes. Build Core/Contract from the
immutable commits in `provenance.json`. Supply external assets/references matching
existing `tests/{commands,score}/provenance.json`; never use private player data.

Build the client wheels with a full resolver (paths below are your isolated source
archives, not existing installed packages):

```sh
python -m pip wheel --wheel-dir "$WHEELS" "$CLIENT_SOURCE" \
  "$CLIENT_SOURCE/packages/taiko-application" "$CORE_012_SOURCE" \
  "$CONTRACT_SOURCE" 'Pillow==11.3.0'
python -m pip wheel --wheel-dir "$WHEELS" "$CORE_011_SOURCE" "$CONTRACT_SOURCE"
python3.11 -m venv "$CENTER_ENV"
python3.11 -m venv "$CLIENT_ENV"
"$CENTER_ENV/bin/python" -m pip install --no-index --find-links "$WHEELS" \
  'taiko-application==0.5.0' 'sakura-taiko-core==0.1.1' 'sakura-taiko-contract==0.1.0' 'Pillow==11.3.0'
"$CLIENT_ENV/bin/python" -m pip install --no-index --find-links "$WHEELS" \
  'taiko-bot==0.2.8' 'sakura-taiko-core==0.1.2' 'sakura-taiko-contract==0.1.0' 'Pillow==11.3.0'
"$CENTER_ENV/bin/python" -m pip check
"$CLIENT_ENV/bin/python" -m pip check
```

Archive `pip --report`, `pip freeze --all`, venv config, wheel hashes and interpreter
version. Retain all wheels for exact offline reproduction. The center installation
above installs Application and dependencies only; it does **not** install the
center Bot successfully.

```sh
git show 1be8d67d911861bbd6a6a83f70c4ad973476eeea:plugins/taiko.py > "$REFERENCE"
"$CLIENT_ENV/bin/python" tests/dual_host/client_parity.py \
  --reference "$REFERENCE" --adapter "$CLIENT_SOURCE/plugins/taiko.py" \
  --images "$SCORE_FIXTURES" --output "$RESULTS/client-parity.json"
"$CLIENT_ENV/bin/python" tests/dual_host/plugin_dispatch.py \
  --sandbox "$RESULTS/plugin-sandbox" --installed "$CLIENT_ENV" \
  --images "$SCORE_FIXTURES" --output "$RESULTS/plugin-dispatch.json"
"$CLIENT_ENV/bin/python" tests/dual_host/private_transport.py \
  --sandbox "$RESULTS/transport-sandbox" --output "$RESULTS/private-transport.json"
```

## Remaining blockers and order

1. Application compatibility has been demonstrated for the pinned fixture suite,
   not all potential Core inputs. Center Core must not be upgraded, nor client
   Core downgraded to resolve dependencies.
2. Center host `pip install <Sakura>/taiko` fails during wheel requirements with
   `Multiple top-level packages discovered in a flat-layout`. Its runtime also
   references the external `/opt/python-memory-runtime/1.1.0` boundary. No source
   path injection or private runtime installation was substituted for a clean
   center plugin installation. Center actual plugin dispatch remains unverified.
3. Full fresh dual-host renderer/provider integration and read-to-send revocation
   timing remain unproven. Do not equate frozen provider PNG replay with that gate.
4. Keep both feature branches unmerged. First resolve and validate the center
   host installation boundary and remaining integration checks. Then review the
   shared Application artifact, publish/retain its exact wheel, and install it
   before either host adapter. A future integration must merge/publish the B repo
   artifact before the A dependency pin; never merge A first into an environment
   lacking Application 0.5.0. Deployment is a separate, unrequested task.

## Dedupe and deliberately retained code

All six client handler business bodies now delegate to the same active
`taiko_application.commands.execute_*` implementations used by Sakura. The old
client body is an external immutable Git reference, not an active fallback.
There is no `execute_client_*` copy. 399 non-command top-level AST nodes in the
client plugin are unchanged.

Existing client `plugins/utils/{b30_render,b30_single,drawinfo,recommend_image,
dani_progress,const_query,progress_catalog,progress_star,score_calculator,
target_recommend}.py` remain active providers, not a second command usecase.
They still overlap with earlier Application presentation/query modules. Removing
or redirecting them requires their own client profile/resource/private-provider
parity and is not silently included in this six-command integration. No remaining
active old implementation of these six handler business bodies needs removal;
other commands, storage, Writer, SQL, sync and daily/history stay untouched.
