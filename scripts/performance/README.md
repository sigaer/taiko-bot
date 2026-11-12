# B30 0.21.2 evidence

All workloads use `/home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh`.
`run_cohorts.py` is a lightweight supervisor that invokes this wrapper itself;
do not nest it inside the wrapper (the shared QA lock is intentionally serial).
No command contacts a Bot account. Input/current/history is entirely synthetic.

The immutable corpus for this release remains at
`/var/tmp/taiko-b30-performance/fixture`; verify it with:

```bash
bash /home/sigaer/taiko/taiko-forum/scripts/memory/run_qa.sh \
  /opt/taiko-bot/releases/0.21.2/bin/python -I \
  scripts/performance/fixtures.py verify \
  --root /var/tmp/taiko-b30-performance/fixture
```

On a separate work directory, `fixtures.py prepare --root NEW --public PUBLIC`
then `finalize` freezes the required public resources, and `extras` adds the
three low-difficulty/accuracy boundary cases. All three must run under the QA
wrapper. The public source may have changed since this release: use the frozen
manifest/catalog/assets to reproduce the published hashes. Never use private
production userdata as input.

Run each release with its own installed interpreter and a fresh output prefix:

```bash
/opt/taiko-bot/releases/0.21.1/bin/python scripts/performance/run_cohorts.py \
  --source /opt/taiko-bot/releases/0.21.1/lib/python3.11/site-packages \
  --fixture /var/tmp/taiko-b30-performance/fixture \
  --output /var/tmp/taiko-b30-performance/results --prefix replay-before \
  --cohorts warm-query warm-compute warm-draw cold matrix-center matrix-client edges-center edges-client
```

Repeat with 0.21.2 and a different prefix. Client profile uses the separately
pinned Core 0.1.2 overlay at `fixture.parent/core-client`; Pillow remains 11.3.0.
For each version, run `stress.py --mode memory` and `--mode concurrency` under
the wrapper, passing the same `--source`, `--fixture` and a new `--output JSON`.
Run `host_events.py --profile center --fixture FIXTURE --work NEW_DIRECTORY
--benchmark-output NEW_JSONL` for actual Matcher pipeline timing; omit the last
option for center/client authorization revocation tests. Client host replay
requires the Core overlay in `sys.path`, as documented in the report.

The first baseline cohorts are retained separately. The final published baseline
uses `before-confirmed` for query/compute/draw/cold, rerun with the exact final
harness and installed old interpreter after restoring the real cached V2 getter.
The original baseline bypassed this getter using the identical frozen snapshot;
its times are retained as preliminary evidence, not mixed into final statistics.
Matrix/edge rows are single correctness repetitions; their `--verify` hash
instrumentation may render an additional default PNG and is not timing evidence.

`report.py --work WORK --output DEST --code-commit SHA --deployment JSON` collects
all raw records into the three deliverables and asserts output/algorithm/PNG/RGB
parity. It also writes supporting correctness and per-step evidence. Phase 2B,
installed package replays and external QA logs remain in their original evidence
directories. `verify_dependencies.py` checks versions and installed dependency
payloads, excluding only the two changed distributions.

`build_candidate.sh` builds in QA scratch and installs an unactivated release;
it refuses to reinstall an active release. Runtime activation stays owned by the
standard `scripts/deploy_taiko.sh`, with `TAIKO_DEPLOY_BOT_ONLY=1` for this task.
