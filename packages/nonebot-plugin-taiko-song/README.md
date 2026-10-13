# nonebot-plugin-taiko-song 0.2.0

Taiko owns seven public command entries: `what_song`, `alias_query`, `song_where`,
`song_position_phrase`, `song_pos_by_id`, `diff_by_id`, and `note_count`. Both hosts
load this single distribution through their existing NoneBot plugin configuration.
Application 0.5.0 remains platform independent and unchanged.

## Installation and ownership

Build Application 0.5.0 and this plugin's wheels before installing either host.
The center retains its source runtime layout and exact Core 0.1.1 / Contract 0.1.0
pins. The client package 0.2.11 pins Core 0.1.2 / Contract 0.1.0 and this plugin
0.2.0. Install with the full dependency resolver; no `--no-deps` installation.
The exact verified environment locks are under `tests/acceptance/`.

Register `nonebot_plugin_taiko_song` once in `tool.nonebot.plugins`. The generic
host `feature_handler` plugin must be available; its switches and whitelist remain
host responsibilities. Center config uses `taiko_song_profile="center"` and an
explicit `taiko_song_public_root` (default cwd). Client uses profile `client` and
its existing settings/public resource manager. No Sakura utility import or
absolute checkout path is required by this package.

Install the new wheel before using the matching center source revision or client
wheel. Do not combine the expanded plugin with a host that still registers these
six entries. Review/integrate the Taiko dependency artifacts first, then the Sakura
removal revision. This branch has not been merged or deployed.

## Modules and retained semantics

- `__init__.py`: existing Application `execute_song` entry plus one registration
  import. The new handlers live in `public_commands.py`.
- `provider.py`: public catalog, aliases, note counts and Core position profile;
  no userdata, SQL, credentials, Writer or private authorization.
- `public_queries.py`: note ordering/text helpers and position presentation.
- `alias_renderer.py`: original alias layout/PNG encoding with an explicit font.
- Existing `delivery.py`, `center_messages.py`, `client_messages.py`: unchanged
  and reused, with no second platform sending framework.

Center retains duplicate-group aliases, fuzzy threshold, center position ranking
and down-shelf notices. Client retains its own alias selection, fuzzy notices,
visibility filtering, `position-client-20261010`, resource readiness and missing
chart messages. Difficulty-ID commands reuse the existing fumen delivery path.
`note_count` keeps its original priority/block defaults, ordering, first-20 limit
and text; the other five entries retain priority 10 and block true. Only alias
and difficulty-ID additionally require `tsearch`. Existing mention behavior is
preserved, including regex rejection before handlers run.

The two hosts no longer define the six matchers or handlers. Orphan alias drawing,
lookup, note and position implementations were removed, as were five newly unused
client resolution/fumen helpers. Generic font/wrapping/fuzzy-hint helpers still
needed by unrelated host commands remain; this small presentation-helper overlap
is explicit, not a second active command implementation. Shared query, tset Writer,
private commands and unrelated renderers remain host-owned. No new duplicate
matcher, Application usecase, Core formula or platform sender was introduced.

## Finite acceptance

`tests/public_dispatch.py` replaces the Phase 2F-A test entry. It loads the actual
installed external plugin before loading the complete host plugin, verifies seven
external registrations and zero corresponding host registrations, then runs real
NoneBot rules/handlers with synthetic OneBot and QQ events. It compares each new
entry with the frozen, unchanged old entry and removed helper bodies. Only outer
feature storage, resource readiness and sends are substituted; catalog reading,
Core profiles, matching, alias drawing and fumen selection run normally.

Center: 156 cases. Client: 160 cases (four extra resource-admission refusals).
Both compare full message payloads, sending options, PNG bytes hash, pixel hash,
dimensions and mode. Cases cover normal/ID/alias/fuzzy/duplicate, difficulty
selection and missing fumen, empty/malformed catalogs, invalid input, note sorting
and truncation, switches, mentions, real down-shelf/hidden/double-chart inputs,
and the former position sort/tie/off-shelf vectors. Two deliberately malformed
note-provider cases per host compare captured exceptions; they are not counted
as successful business responses. Every ordinary first case must actually send.
The original `what_song` executes Application once in representative events on
both platforms; unchanged Phase 2F-A parity evidence remains in Git history.

`tests/scope_audit.py --workspace <task-root>` verifies the unchanged remaining
functions/classes, remaining matcher declarations (center 67, client 63), unchanged
62 Application files, unchanged send-authority helper and all 35 private guard
calls. None of the private handlers changed. The old Sakura-only position tests
moved into this installed-plugin acceptance; unrelated tests remain intact.

References: Taiko `c5ef227`, Sakura `241a237`. `tests/acceptance/summary.json`
records source/resource/fixture hashes, precise versions and installed-source
comparison. `center-dispatch.json` and `client-dispatch.json` contain every output.
No private userdata or live network/SQL/QQ is involved. The center is explicitly
`CENTER_SOURCE_RUNTIME_PASS` / `CENTER_WHEEL_NOT_REQUIRED`.

Full frozen references, public resources, isolated environments, installation logs,
preparation/build/finalization scripts and QA artifacts are retained under
`/var/tmp/taiko-phase2fb-20261013`. Reproduce via the existing bounded QA wrapper:

```sh
bash scripts/memory/run_qa.sh /bin/bash /var/tmp/taiko-phase2fb-20261013/test.sh
bash scripts/memory/run_qa.sh /bin/bash /var/tmp/taiko-phase2fb-20261013/final-check.sh
```

For another workspace, supply the explicit paths from
`tests/public_dispatch.py --help`; materialize frozen references with `git show`
from the revisions above and verify their manifest hashes. Public font/image
resources remain external. Generic runtime support provenance is recorded in the
prior Phase 2E-R evidence. Never point these tests at a production runtime root.

Status: **PHASE_2F_B_COMPLETE**. No main merge, deployment or production restart.

## Phase 2F-C candidate update (0.3.0)

The current candidate adds `const_query` and `patterns` to this existing package,
for nine external matchers. The preceding sections describe the retained 0.2.0
baseline; its evidence remains historical. Application stays 0.5.0; the client
candidate is 0.2.12, with the same precise host Core/Contract versions.

`score_cmd` is explicitly **blocked**: its public configuration loader can rebuild
and write the scoreline dataset. It remains entirely host-owned. This candidate
is **PHASE_2F_C_BLOCKED**, not three-command completion.

Current installation, ownership/removal list, exact locks, real dispatch/PNG
parity and remaining command names are documented in
[the Phase 2F-C report](../../../docs/phase2fc-catalog-cutover.md) and
`tests/catalog-acceptance/`. Reproduction uses `tests/catalog_dispatch.py` with
`PYTHONHASHSEED=0`; sampling resets to seed 73013 for every old/new comparison.
Run only via the existing bounded QA wrapper. The original seven commands retain
their source and have representative real-dispatch regression coverage here.
