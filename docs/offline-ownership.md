# Offline ownership migration — 0.14.0

Baselines: Taiko f11febd (0.13.0), Sakura 790c2c7 (9.82.16).
This release changes source ownership. It does not deploy services, relocate runtime data,
change Viewer, Core/Contract, SQL schema, Writer or PublicationStore protocols.

## Owned implementations

`taiko_bot.offline` contains annual schema v4 / annual-observation-v4.5.3,
Growth, Recommendation Intelligence, my-don, rating/score aggregation, forecast,
progress and dani rendering, the song updater, TJA analysis, roll/balloon audit,
ESE audio synchronization, song-index/catalog merges, grade extraction and image producers.
Shared dress/title/dojo/V2 adapters are completed in `runtime/player/center`, not forked.
The merged-binding adapter delegates to the existing Application and taiko_store writer.

New CLI modules:

- `python -m taiko_bot.offline.annual_summary` (`taiko-annual`)
- `python -m taiko_bot.offline.growth_compute` (`taiko-growth`)
- `python -m taiko_bot.offline.recommendation_intelligence` (`taiko-recommendation`)
- `python -m taiko_bot.offline.my_don_cli` (`taiko-my-don`)
- `python -m taiko_bot.offline.song_update_task` (`taiko-song-update`)
- `python -m taiko_bot.cli.taiko_admin_backup` (`taiko-admin-backup`)
- `python -m taiko_bot.cli.backfill_daily_ability`
- `python -m taiko_bot.cli.merged_read_cli`
- `python -m taiko_bot.cli.migrate_multi_bind_to_db`
- `python -m taiko_bot.cli.resources` (`taiko-resources`)

Run these using an installed wheel or Taiko checkout. No Sakura import namespace or
sys.path injection is required. Keep the existing runtime working directory for relative
catalog arguments. `TAIKO_OFFLINE_ROOT`, then `TAIKO_CENTER_ROOT`, override the historical
`/home/sigaer/taiko` default. Existing explicit data/output arguments retain precedence.
Growth/recommendation console launchers retain publication-unavailable exit 75.
The old binding migration is preserved exactly, including its DDL even in dry-run;
it was tested only with a recording fake database and must not be run as a production smoke.

The center startup plugin is now `taiko_bot.runtime.center_startup`: feature-switch
migration, Hiroba initialization failure fallback, memory telemetry and media cleanup
retain their ordering. The client startup plugin remains separate.

## Resource ownership

See [deployment manifest](../resources/deployment-manifest.json) and
[resource procedure](../resources/README.md). 142 resources / 42,692,283 bytes have
matching SHA256 hashes in a separate private object store. Rights-unverified artwork,
fonts and catalog files are not copied into this public repository. The source-authored
annual schema and reference model JSON are included in the wheel.

The object store is currently a local private artifact at
`/home/sigaer/taiko-private-resources` (directory 0700, objects 0600), not a remote backup.
No production resource files were moved. Ten `songs/archive_unused` samples were not
opened. The historical workbook and generated grade output remain pending provenance
review. Restoring resources is an explicit future provisioning operation, not part of
this migration. Existing Viewer relative resource names are preserved by the manifest.

## Retirement and remaining consumers

Sakura removes 176 tracked files: net 11,621 Python lines including tests, or 9,973
implementation lines excluding tests. The exact deleted and remaining paths are in
[ownership inventory](../resources/ownership-inventory.json). Six original test modules
move intact to `tests/offline`; remaining historical test imports follow the new owners.
Two comment-only obsolete scripts are retired without republishing their contents.

The following dependencies prevent final Sakura de-Taikoization without a Viewer change:

- `server/services/account/python-compute.ts`: old `plugins.utils.recommendation_intelligence`
  and `growth_compute` module names.
- `server/utils/account/my-don.ts:128,282`: old `plugins.utils.my_don_cli`.
- `server/services/account/annual-summary/runtime.ts:341,551`: direct
  `plugins/utils/annual_summary/standalone.py`; its fingerprint code also hashes that
  source directory, chart-roll metadata, schema and dataset inputs.
- `server/services/growth-history/model-revision.ts`: source-file labels and bytes for
  Growth and old utility modules, plus catalog files. Merely hashing relocated files
  is not equivalent. Existing retained source bytes are unchanged.
- `server/infrastructure/account/merged-read-worker.ts:11`: `scripts.merged_read_cli`.
- Viewer chart/progress inline Python imports the old score/dani/progress utilities.
  Their transitive rendering, authorization lookup and memory/environment dependencies
  therefore remain. The annual audit CLI still selects arbitrary legacy source roots.

There is no forwarding shell in Sakura for deleted implementations. The independent
Taiko alternatives work, but Viewer still needs a separately authorized call-path and
fingerprint transition before its old source closure can be retired. This release does
not claim the entire Sakura repository is free of Taiko code.

Generic `feature_handler`, `onebot_runtime`, bootstrap and gateway code stays with its
hosts: actual consumers include Miku, maimaiDX, miku-self and the generic root bots.
The center fallback feature handler remains because its launcher still consumes it;
center QQ platform/media implementations now live in Taiko and their tests follow that owner. `runtime_memory` remains the separately installed
shared artifact, also used by Miku/maimaiDX; this wheel does not copy it.
HDU upload and cross-project storage maintenance, including Miku/PJSK cleanup and their
systemd configuration, are unchanged.

## Validation and limits

- Offline suite: **262 passed, 7 skipped, 1 expected baseline failure**.
- Frozen 790c2c7 success comparisons: annual JSON and input fingerprint, TJA parsing,
  catalog merge, scoreline cold/hot output bytes, four PNG render/generator SHA256
  comparisons, full updater network/OSS/write-order success and failure branches.
- Seven historical tests require production player/chart fixtures; they remain present
  but are skipped before opening those paths. No production files were read by tests.
- The annual source-switch/deleted-readded-chart test fails on frozen 790c2c7 as well.
  It is retained as strict xfail and blocks annual retirement; it is not a success parity
  result. Two stale test interfaces were fixed to patch Application aggregation and use
  the actual scoreline resolver, preserving their original assertions.
- Changed Sakura consumers: **18 passed**, plus the startup AST no-binding-migration check.
- Center and client: **18 public + 46 representative lifecycle checks each**, all passed.
- Installed wheel outside both repositories: imports, CLI help, real annual envelope,
  guarded startup, publication exit handling and resource roundtrip/idempotence.
- Backup and binding maintenance use synthetic files and recording SQL. No native MySQL
  or production publishing acceptance is claimed. No complete Core/Application/Storage
  matrix was repeated.

QA uses the existing bounded memory wrapper (2 GiB high / 3 GiB maximum, serialized).
`tests/offline/conftest.py` blocks production filesystem access, SQL, DNS/network and
unmocked child commands. The frozen-source preparer reads only selected tracked utility
sources from commit 790c2c7; no player fixtures or credential files are used.

To reproduce frozen comparisons, prepare an external directory with
`python tests/offline/prepare_frozen.py SAKURA_GIT /var/tmp/taiko-frozen`, then set
`TAIKO_FROZEN_BASELINE_ROOT` inside the bounded QA command and run `pytest tests/offline`.
Install the wheel into a separate center/client environment for package delivery checks.
Do not run these tests against an existing runtime working directory.
