# Python ownership candidate — 2026-10-15

Status: runtime migration candidate, **overall acceptance incomplete**. No deployment,
restart, production SQL/private-data access or main integration. Original dirty/P0
worktrees are untouched. Bases: Taiko 248713e, Viewer 777546c, Sakura 86b8334.

## Runtime and identity contracts

Viewer 0.81.13 selects an absolute `TAIKO_PYTHON_EXECUTABLE`, runs installed modules
with `-I`, and requires the candidate Taiko 0.14.1 wheel. No Sakura source fallback.
Install the non-editable wheel and dependencies into an independent environment;
set the same interpreter for the Viewer process and annual workers. Runtime data
roots remain separately configured. The sync service file is a template only.
No live service configuration was modified. Default /usr/bin/python3 must itself
have the wheel installed; an absent wheel is an explicit failure.

Annual systemd admission, memory/concurrency/time limits, protected paths and
teardown remain in place. Children reexecute sys.executable. Viewer owns its
accounts, SQL, Web, Goal and history orchestration. This Viewer baseline has no
merged-read worker; the installed merged-read CLI protocol was separately tested.

Annual and Rating fingerprints explicitly switch to v2 content identities of the
installed algorithm closure plus actual input content. Same-size/same-mtime edits
invalidate. A relocation alone does not change installed identity. Existing saved
annual reports are not relabelled; old cache keys require regeneration on a new
calculation. Algorithm changes invalidate cached inputs.

Growth retains the exact complete legacy digest for the verified equivalent wheel
and actual three catalog files, using a SHA-256 prefix checkpoint, not legacy
algorithm code. Sakura 86b8334 already lacks snapshot_history.py: the last complete
legacy closure is 6cc94e4. Compatibility is bound to the exact installed artifact;
changed algorithm contents switch to a domain-separated v2 revision. Historical
rows are never rewritten. Native checkpoint continuation requires OpenSSL 3
libcrypto; absence fails explicitly. Installation relocation and content mutation
were tested. Future intentional algorithm releases must not blindly regenerate
the compatibility identity without parity evidence.

## Validation evidence

All QA was admitted through scripts/memory/run_qa.sh, build through run_build.sh;
no deploy script was invoked. Synthetic data only; no mutating SQL integration.
Local bounded logs are under /var/tmp/taiko-final-ownership-20261015.

- Independent non-editable wheel: six CLI full-JSON comparisons including managed
  projection absence/tampering, corrupt canonical error/exit 75, missing root error.
- Twelve exact PNG comparisons: B30/dim/radar, five progress variants, MyDon/cloud,
  trend and recommendation. Frozen old source is an explicit QA oracle only.
- Merged current/history full protocol, source vector, duplicate-source error and
  lease release passed (merged.log).
- Installed fingerprint legacy equivalence, relocation, algorithm and same-mtime
  catalog mutation passed. Node tests cover persisted/memo cache reuse and no
  persisted report rewrite. Annual cgroup worker used the configured wheel Python
  and left no child cgroup. Nine admission/fingerprint/worker tests passed.
- Viewer annual contract and 54 Growth/history tests passed; production build
  succeeded (viewer-build.log). No production API/online smoke was attempted.
- Migrated legacy host tests: 57 passed. Storage tests: 57 passed, 25 subtests.
  Viewer adapters/fingerprint unit tests: 9 passed.
- Existing command ownership suite: 18 passed; representative center and client
  lifecycle suites: 46 each. Client used the existing 0.14.0 installed baseline;
  center used the candidate wheel. This is not a fresh client 0.14.1 install test.
- Offline full suite with --runxfail: **271 passed, 7 skipped, 1 failed**. The seven
  historical production-fixture cases were not accessed. Source-switch annual
  failure reproduces against frozen 790c2c7 (frozen-failure.log) and candidate
  (offline-final.log/final.log). It remains a failure, never xfail-as-PASS.

## Remaining ownership and integration blocks

The machine-readable final-ownership inventory records every baseline tracked path,
all deletion hashes, test destinations, remaining files and per-file reasons.
Sakura removal: 108 files = 96 source/tests (22,212 Python lines; 65 implementation
files) plus 12 unreviewed resources quarantined outside Git. No resources were
redistributed into public Taiko. The private quarantine is local /var/tmp storage,
not a durable off-host backup; prior Git history has not been purged.

Old Taiko Python runtime implementations remaining: zero. Remaining dedicated
implementation count under the inventory's extension rule: 197 = 195 files in the
independent Java/MyBatis + Vue stack and two actively consumed upload integrations.
The legacy web stack has 226 total files: no equivalent wheel service or verified
retirement/deployment record, and config/media redistribution is not cleared.
Upload consumers are server.py, sgmodule and their existing tests. Fifteen shared
host Python files retain concrete QQ/OneBot, feature-handler, HDU service or
cross-project storage-maintenance consumers; details are in the inventory.

Twenty-seven historical test/helper/fixture files still require owner adaptation,
SQL isolation or privacy/provenance review. They remain in Sakura with original
assertions; they are not claimed runnable after removal of their legacy imports.
The original Source-switch failure and these pending migrations prevent an overall
PASS. No authenticated end-to-end API/SQL acceptance was performed. External main
branch deployment hooks have not been ruled out, so all three repositories remain
isolated candidate branches, without PR or main push. Candidate commits do not
constitute a published wheel release or an online cutover.
