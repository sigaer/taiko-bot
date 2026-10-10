# Phase 4 — Taiko Domain Client alignment

Client release `0.2.0`. Core `0.1.2` / commit `0b7319d94b041daafb0a0d32e3ccc95e50da8810` / tag `v0.1.2`.
Contract `0.1.0` / schema `1.0`, sourced from Viewer commit `23f89b4f70e5a64ae76c33ac04c6c2d242808df1`.
Baseline client: `46c8646847f8d642b53043b6123d8763e26c0a16`.

## Step archive

1. Audit existing client algorithm/parser/model differences. Preserve `web.conf` and `v1_test_report.md` user changes. Confirm no active client business process.
2. Freeze old outputs with synthetic inputs. Core adds explicit client policies for Hiroba shapes, public visibility, pair identity, CSV, progress, position and scoreline; v1/v2/dimensions/roll/recommendation arithmetic stays shared.
3. Delegate 188 symbols and policy tables across 14 modules. The [manifest](phase4-adapter-manifest.json) records original revision/hash per symbol. Keep commands, permission rules, message/image rendering, transport, file IO, local read caches and clocks in this client.
4. Validate installed Core package and client host adapters. All original 43 regressions and five host-boundary regressions pass (48/48). Core installed-wheel tests pass (29/29), including all previous center Goldens and 86 added client cases.
5. Build/install client wheel in an isolated target; import all 14 delegated modules and the real NoneBot command module from installed files. Version checks and code-byte comparisons pass. No live client process is present to restart. Production Sakura keeps its pinned Core 0.1.1.

`plugins/taiko.py` remains byte-identical to the baseline (`25014419bda9da3a47754b114d556590f11d6a5bc0e21f2be739c7bfba6645b1` SHA-256).
Userdata provider and public-data transport are unchanged. No public data names, manifest format, proxy paths or assets contract changed, so no Viewer runtime release is needed for this phase.

Tests use the Viewer memory runner, an isolated `/var/tmp` root, production personal-data/write guards and blocked HTTP. Temporary QA roots are removed in `finally`.
Tests do not read personal production records, use production DB mutations, connect adapters or perform central write operations.

## Dependency installation and access

Python 3.11+ matches the extracted SDK and current tested runtime. Install [requirements-domain.txt](../../requirements-domain.txt) before `pip install -e .`.
Both domain dependencies are privately hosted: authorized SSH read access or maintainer-supplied wheels is required. There is no anonymous package-index release in this phase. The private repository setting is preserved.
Versions are checked at import; a mismatched Core/contract fails clearly instead of silently selecting another source checkout.

Known numerical splits are retained: client `v2-client-20261010`, center `v2-center-20261010`; client SongStats has 13 legacy fields. v1 pair grouping and v2/target title grouping remain distinct.
Parser capture times are supplied per record by the host, keeping the old clock boundary. Cache lifetimes and files remain local infrastructure; they are not authoritative central userdata.

## Rollback

Restore baseline client revision and its prior environment. For `0.2.0`, restore the pinned Core/contract wheels recorded in validation evidence.
No migration, DB write or production consumer switch occurred. Do not downgrade the deployed center's package environment when rolling back this isolated client.
Only this task's source/docs/tests are committed; user files and generated build/cache directories stay outside the release.
