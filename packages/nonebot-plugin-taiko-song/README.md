# Taiko song plugin (Phase 2F-A candidate)

`nonebot-plugin-taiko-song==0.1.0` owns only `xx是什么歌`. Its matcher uses priority 10,
block true, and `taiko_application.commands.execute_song` from unchanged Application
0.5.0. Application remains independent of NoneBot.

## Installation and host configuration

Build Application and this distribution in the Taiko repository, alongside the
existing Core/Contract wheels. Install using the complete dependency resolver:

```sh
python -m pip wheel ./packages/taiko-application ./packages/nonebot-plugin-taiko-song -w /path/to/wheels
# Center source runtime (do not install taiko-bot root):
python -m pip install --find-links /path/to/wheels 'sakura-taiko-core[hiroba]==0.1.1' 'sakura-taiko-contract==0.1.0' 'nonebot-plugin-taiko-song==0.1.0'
# Client: its root distribution pins Core 0.1.2 and Contract 0.1.0.
python -m pip install --find-links /path/to/wheels .
```

Core/Contract wheels retain their existing provenance; they are not published or
upgraded by this change. Do not assume Application/plugin wheels are on PyPI.
The two host changes must be coordinated: make wheels available, install them,
then adopt the corresponding source candidate. Do not remove the old matcher
without installing and enabling the replacement. This task does not perform a
production installation, merge or restart.

The existing generic NoneBot TOML loader loads `nonebot_plugin_taiko_song` via
`tool.nonebot.plugins`; it is **not** a builtin plugin. `feature_handler` remains
the host's generic feature-switch API, loaded with `nonebot.require`. Its existing
`feature_on('taiko')` and `feature_on('tsearch')` rules remain authoritative. The
plugin does not own or replace feature storage, SQL, whitelist or permissions.

Center defaults to profile `center`; `TAIKO_SONG_PUBLIC_ROOT` optionally sets the
public catalog/assets root (default runtime cwd). Its source runtime is retained;
no Sakura wheel is required. Client `bot.py` explicitly selects profile `client`,
using existing `taiko_bot.settings` and resource-readiness manager. Neither profile
imports `plugins.taiko`, Sakura utilities, private score Providers or an absolute
Sakura checkout. The generic host feature plugin is a required runtime capability,
not bundled into this distribution.

## Preserved host differences

- Center: duplicate song grouping through fixed Core, fuzzy acceptance threshold,
  song/category/BPM brief, missing-chart hint, existing QQ keyboard and passive-send
  fallback. Public catalog location is explicit rather than a Sakura source path.
- Client: original visibility filtering and query matching, fuzzy hint behavior,
  resource readiness, existing missing-chart text and QQ keyboard.
- Official QQ input restrictions, OneBot external Bot mention exclusion, difficulty
  prefixes, exact-alias precedence, and chart selection retain each host's behavior.
- The public query does not perform private authorization checks. Client private
  commands retain the main security patch unchanged (35 existing guarded exits).

Shared helpers still used by other commands remain in the hosts. The old
`what_song` matcher, handler, command-only extractor/rule and two regex constants
are removed from both hosts. No second active song-command usecase is retained.
Other command handlers are not integrated from Phase 2E-R in this limited cutover.

## Verification

`tests/dispatch.py` loads the installed external plugin **before** the host plugin,
checks one external matcher and no host matcher, and dispatches real OneBot/QQ
synthetic events through real NoneBot rules/handlers. Only feature storage,
resource-admission input and outer message transport are replaced. Matching,
Core grouping, Application execution, chart lookup, image bytes and message
construction run normally. Framework exceptions are captured and fail the test.

The old entry is executed from frozen source in a separate reference namespace;
its unchanged shared functions come from the loaded host. A scope audit compares
all remaining host functions/classes to the frozen baseline. References:
Sakura `c8ed8c1`, client main `5f8465f`, Application `44aaf656`.

34 cases per host cover query, ID, alias, duplicate, fuzzy, difficulty, invalid,
missing/empty, Provider errors, both platforms, feature denial and external mention.
Messages compare full structured payloads; chart PNG compares bytes, pixel hash,
size and mode. Public Phase 2E-R catalog vectors are supplemented with an explicitly
synthetic duplicate and aliases. A fixed tracked `1007.png` chart is mapped to the
fixture ID for path-selection tests; this is not a new real-world chart mapping.
No production data or network is used.

Evidence/locks and the scope audit are in `tests/acceptance/`. Full execution
artifacts and frozen references are retained at
`/var/tmp/taiko-phase2fa-20261013`. Run using the repository's bounded QA wrapper;
`tests/dispatch.py --help` describes runtime/source/support paths. The center uses
isolated source layout and explicitly sourced generic `runtime_memory`/
`qq_official_runtime` support from the preceding recovery fixture. No existing
private virtual environment is used as installation evidence.
