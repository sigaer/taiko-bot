# Center publication infrastructure

This package is not Taiko Core. It owns filesystem publication only; callers
retain score/profile interpretation, upstream credentials, authorization,
source metadata, timestamps and daily measurement rules.

**Activation: not yet wired to production.** Phase 6.2 delivers the isolated
protocol. Real writer coverage, reader adoption, full-size costs and release
are subsequent gates. Importing this package alone does not fix legacy writers.

`PublicationStore(root, identity).exclusive()` fences the entire read-modify-write
operation. `commit({"current": bytes, "history/data_….json": bytes})` stages
immutable content, writes/fsyncs a recovery intent, installs compatible C/H
projections and atomically/fsyncs the committed manifest last. One commit may
replace all history while preserving daily archives. Unique history names and
source provenance remain the caller's responsibility. Reusing a history key is
an explicit replacement, never an automatically generated observation.

`shared()` recovers a dead writer's intent before exposing a view. Readers use
that view's immutable references and retain the lease through consumption.
Concurrent readers share the lease; writer/recovery/collection requires exclusive
ownership. No stale-lock TTL, lockfile deletion or unlocked fallback exists.

Before the manifest linearization point, recovery restores the prior generation;
after it, recovery completes the new projection. The tests kill real child
processes at five checkpoints and inject disk failures. They do not claim to
have simulated physical power loss or production restoration.

Legacy adoption streams exact C/H bytes into private objects under the same
kernel lock. Invalid JSON is retained as evidence, not silently repaired. An
unadopted source has no committed view; read-model callers must not declare it
verified merely because files exist. All legacy writers must be converted
before activation: in-place modification of a compatibility hardlink would
corrupt its content object and is rejected by hash validation.

Optional schema-1 `fileMtimes`/`fileCtimes` capture filesystem seconds by file
key. Adoption retains original values, including equal-content history files
with distinct mtimes; new content records its staged object's values. Unchanged
references retain their captured times. These preserve the old malformed-name
sorting fallback and ctime caption through projection loss and portable restore.
They are neither play/observation timestamps nor readiness evidence. Older
manifests remain readable with object filesystem metadata, which cannot recover
lost original legacy times. Restore binds explicit captured times to its nonce.
The 32 MiB manifest budget is checked before durable publication as well as reads.

Python history reconstruction holds one SH view through full/delta rebuilding;
managed missing/corrupt objects fail closed. Invalid historical JSON keeps its
old exclusion behavior. Current caption lookup verifies the referenced object;
tombstones cannot expose an old projection. Explicit reader/daily roots precede
`TAIKO_USERDATA_DIR`, followed by their legacy default. Daily namespace locks and
freeze rules remain separate; a configurable root alone is not Writer convergence.

The Python bearer endpoint captures one SQL connection, resolves its explicit
token grant, finishes that optimistic snapshot, then acquires Source EX before
pinning the exact token row id/hash/Source with SQL `FOR UPDATE`. Refresh, fresh
canonical current decoding, the final grant proof and usage COMMIT share that
lease. Managed corruption/missing objects fail closed; projection loss/tamper
does not change the DTO. A token is its existing explicit Source capability,
independent of a later current-binding selection, until rotation/revocation.

Synchronous acquisition callers pass their existing `publication_store` through
Wahlap/Hiroba to `save_userdata`; the latter requires a live EX for that exact
identity and never opens a child EX or upgrades SH. Without an explicit store,
`TAIKO_USERDATA_DIR` precedes the existing acquisition root. The optional
`TAIKO_WAHLAP_CONFIG_PATH` selects the existing cookie JSON; its default path and
format remain unchanged. Wahlap transport has 5 s connect / 30 s read timeouts.
The bearer HTTP body is capped at 16 KiB with a 15 s read timeout.

Source publication and the SQL last-used metric are separate commits. A late SQL
failure/death may leave already authorized new C/H committed; a fresh acquisition
retains the previous observation semantics. No distributed SQL/filesystem
transaction or new cross-request retry nonce is claimed. Bot/gateway token
issuance ownership and all other Writer/grant gates still precede activation.

Limits: 64 MiB per object, 50,000 H files / 2 GiB H bytes per generation, 32 MiB
metadata/bridge message, 30 s lock deadline. New private directories/files use
0700/0600. This is a single-host protocol on the shared filesystem, not a
distributed lock or an authorization boundary against the host administrator.

`collect()` is explicit maintenance under the exclusive fence, preserving current
and previous generations and live read leases. It only deletes protocol-owned
objects/manifests/stages for this identity. It never deletes daily archives,
other identities' stages, or unrelated cache data. Staging/failed batches may
leave orphans until collection. Capacity and admission must be measured before
production activation; limits are ceilings, not evidence of low runtime cost.

An explicit 32-hex transaction ID provides immediate retry idempotence for the
current committed request; different content is rejected. This foundation does
not promise indefinite receipt retention or reapplying an old request over a
newer current generation. Product nonces retain their own lifecycle semantics.

`python3 -m taiko_store.bridge --root … --identity … --mode read|write` gives a
bounded local JSON pipe to other runtimes. Bodies use stdin, never command-line
arguments. EOF/process exit/deadline releases the lease. `put` stages one object
at a time, `publish` commits the batch, and `finish` closes it. It has no listener
or DB/framework dependency and returns sanitized failure codes.

Native Bot token management now takes the adapter-authenticated sender's
`identity_key`; a mentioned user or a visible binding is not an owner grant.
`bot_binding_authority` captures the current real binding and proves its row,
principal, Source, slot, current and visibility after Source EX. SQL locks take
all caller bind rows before `taiko_bind_identity_state`. Missing legacy state
is materialized as neutral real-account selection within the transaction,
without resetting an existing u0; this pins a concurrent virtual selection even
at READ COMMITTED, independent of absent-row gap locking. Virtual u0 and manual Sources cannot manage these tokens.
Issuance, status and revocation use one owner/current/token SQL transaction;
no C/H observation or manifest commit is emitted. An uncertain COMMIT is
acknowledged only after a fresh transaction proves the exact token outcome and
unchanged current owner while the same Source EX remains held. Failed rollback
closes the connection; user replies contain fixed errors, not driver details.

The internal `/score-token` dispatcher route returns 410. Its old userid-only
body cannot identify a resource owner. Viewer uses its authenticated direct SQL
service; only frozen rollback/boundary fixtures retain the old gateway adapter.
The native Python function names remain, but ownerless calls and the old
`require_bot_binding=False` bypass are rejected. Existing public bearer tokens
continue to be explicit Source read/refresh capabilities until rotation/revoke;
changing a later current selection does not silently revoke that capability.
This is Source preparation only, pending the Phase 6 coordinated runtime rollout.

Native u0 now captures all member SH leases in sorted Source order before its
derived EX lease. Members must already have canonical publications; a read
request cannot adopt legacy members or overwrite an unadopted existing u0.
Activation must therefore stop the old writers and explicitly adopt existing
member **and u0** publications first. New u0 current/history publish together;
incremental refresh preserves existing history bytes, and a history-only member
commit records the new dependency without adding a score observation. Native
manual members/profile selection remain supported. This does not change the
external-only client profile.

An optional opaque `dependencyHash` in the publication manifest covers the exact
principal, ordered member commits, profile member and active merge-rule revision.
It is included in the publication request hash; a later publisher must supply
its own proof rather than inheriting it. No timestamp or projection stat is a
cache-validity proof. Current observation clocks retain the frozen initial and
incremental behavior. Two admitted materializations per process, 30 s admission
and lock waits, and 32 MiB aggregate input/derived output limits are explicit
ceilings; full-size acceptance remains part of the final Phase 6 gate.

Startup no longer mutates the bind table or legacy multi-bind JSON. SQL binding
authority uses the explicit verified migration transaction; pure old JSON
normalization helpers remain for compatibility tests. Feature-switch migration,
credential table initialization, telemetry and QQ cleanup remain startup tasks.
Do not restore the removed automatic binding writers as a rollout fallback.

Owned QA: 319 guarded Source regressions plus 40 publication/backup tests and
25 fault subtests passed; four additional boundary checks passed separately.
Frozen 539f6e5 initial/incremental current and history bytes match. Actual child
death before/after the commit and member/output fence contention are covered.
No production data/SQL, complete NoneBot boot, real upstream, million-record
cost, runtime synchronization or online acceptance is claimed here.

Daily measurement IO now has one infrastructure implementation in `daily.py`.
All namespace reads/writes retain Source SH; acquisition reuses its existing
Source EX for both v1/v2 families. Source deletion, backup and collection take
EX before the same namespace lock. The lock has a 30 s deadline and rejects
symlinks/non-files; archive bodies remain capped at 8 MiB. Mutation requires an
active canonical current/history generation, so a tombstone or legacy Source
cannot create a new measurement. Read-only frozen values remain available.

Trend holds its Source SH through history capture, computation and persistence.
Backfill streams canonical history under the same lease, keeps the existing
10,000-file / 32 MiB-per-file bounds, and bounds plain-file seed input to 8 MiB
/ 10,000 records. Explicit root precedes the environment/default. Stored past
days, observation time, origin, namespaces and daily envelopes retain the old
rules. Daily bytes remain independent of C/H commits; this is not a transaction
across v1/v2 or a new score observation. Source-tagged atomic stages are cleaned
only by the existing Source EX collector after a writer exits.

QA passed 349 guarded Source tests, 40 publication/backup tests and three
retained daily adapter checks, plus 25 fault subtests. Frozen d4a9d22 v1/v2
envelopes match both stubbed rules and actual computations from tracked public
catalogs with synthetic scores. Actual child deaths before/after daily replace,
namespace contention, Source EX exclusion, dead-stage collection, canonical
projection loss, tombstone/caps/symlinks and existing-EX reuse are covered.
Host storage maintenance protects userdata; admin backup manages catalog,
cover assets and admin-log tables, not score/history. These remain outside the
Source Writer surface. Runtime rollout and the full Phase 6 gate remain pending.
