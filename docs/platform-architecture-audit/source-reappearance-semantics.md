# Source reappearance fact correction

This source candidate fixes Annual's known false play inference at the event projection boundary. It does not replace the locked `taiko-bot 0.14.1` wheel or change an installed environment. Base: `15722e86bbd554ce8d89f2df031ab0f29bb7437d`; branch: `fix/source-reappearance-g1-20261016`.

## Corrected semantics

`annual_summary.events.build_observation_events` formerly treated an absent previous chart as a never-seen chart. A full deletion followed by reappearance could therefore emit `play_delta=1`, including the original Wahlap → Hiroba → empty Wahlap → Wahlap sequence. The old failure and frozen oracle remain retained; this is an intentional fact correction, not byte-for-byte equivalence for that sequence.

Replay now retains a set of previously observed chart keys across source, source-account and merged-topology boundaries. `select_window` carries keys from evidence before its selected baseline, so an empty baseline does not erase an older sighting. On reappearance, the chart's counter epochs restart without a play event. The next comparable observation can emit its ordinary measured delta. An omitted delta row leaves the chart in reconstructed state; an explicit removal or full absence removes it. A genuinely new chart retains the existing bounded first-observation proxy policy. That proxy is not proof of a physical visit or an exact play timestamp.

The set is request-local metadata. No snapshot, userdata, measurement, Goal completion or published report is rewritten. The code does not connect to SQL. The added replay test checks original snapshot hashes and repeated fact IDs; actual persisted SQL/report preservation is still an integration gate, not proved by that test.

## Revision and artifact boundary

The event algorithm declaration advances from `annual-observation-v4.5.3` to `annual-observation-v4.5.4`. Package version remains unchanged because no replacement artifact is built or installed. New algorithm identity selects a new normalized-cache namespace; old saved output retains its original provenance.

A future approved new wheel must have a distinct artifact identity and an approved version. Viewer `annual-summary/constants.ts` must be coordinated with it. The existing package-wide installed fingerprint will also depart from `growth-compatibility.dat` and choose its v2 Growth revision; this candidate does not regenerate the compatibility checkpoint to hide that change. Old measurement revisions must remain untouched. Source QA is not an installed-runtime PASS.

## Product impact

The following dependency audit describes the pre-companion Viewer behavior. The coordinator subsequently added a separate Viewer candidate with ever-seen tracking, blocked timestamps, identity-boundary state reset and explicit fact-policy provenance. That candidate is outside this commit and requires its own product evidence.

| Consumer | Actual dependency and implication |
| --- | --- |
| Annual | `annual_summary/service.py` and `shadow.py` call the corrected event builder. New calculations omit false reappearance plays; already saved reports are outside this patch. |
| Viewer Growth and History | Separate TS replay: `utils/dailyProgress.ts` creates chart attendance before checking `before`, then fills empty facts with `played`. `growth-history/evidence.ts` consumes `songs_removed` internally but drops it from emitted snapshots. This candidate alone does **not** fix that path. |
| Recent, Weekly, Passport | Consume Viewer score-history projection. `utils/growthHistory.ts::projectScoreFacts` currently promotes every returned daily fact without L0 filtering. Require the separate Viewer fix and product tests. |
| Goal | Completion facts use independent SQL Goal lifecycle/evaluation. No Goal writes occur here; existing completions must not be recalculated from the changed Annual event list. |
| Viewer current fallback | `dailyProgress.ts` unconditionally visits current rows with no previous row, so a naive reappearance guard can be bypassed. The companion Viewer change must prevent that fallback from recreating suppressed attendance. |

The Viewer coordinator owns that companion implementation; no Viewer worktree was modified by this change.

## Validation

The machine-readable evidence records every run, including the first full-suite run with its missing frozen-oracle configuration and the old semantic FAIL. The original failing test assertion is unchanged; only its historical xfail marker is removed from the fixed candidate. The seven privacy-blocked fixtures remain skipped and unaccessed. New tests cover full absence, delta omission, explicit removal, source/account/topology changes, merged/manual/import sources, pre-window tombstones, true first observations, later comparable changes, same-day history, duplicate/creation ordering and deterministic replay.

All execution uses the Viewer memory QA wrapper and synthetic roots. Tests deliberately select candidate source via the repository's test bootstrap and use an existing separate environment for dependencies; this is explicit source-candidate QA, never a silent runtime fallback.

## Partial delta source boundaries

A second boundary occurs when a delta from identity B contains chart 1 but inherits chart 2 from identity A. Assigning B's epoch to every rebuilt row would make B's first actual chart 2 observation a false comparison against A. Rebuilt snapshots now retain internal `observed_keys`; source/account/topology switches establish epochs only for actual rows. An equal-valued row that first confirms a new chart identity is retained as evidence instead of being discarded as a duplicate. Window selection carries per-chart baseline identities, so cropping cannot accidentally promote inherited rows. Score state bytes and raw snapshots are unchanged; observation retention and fact eligibility are intentionally revised.

The cross-identity Golden varies source, account and topology, first equal/different values, and a window beginning after the partial delta. Its expected result is only the final +2 comparable change, never the earlier cross-identity difference.

## Retained oracle outcome

The complete original offline suite plus 28 new fact cases, with the external frozen baseline enabled and xfail disabled, yields **299 PASS / 7 privacy SKIP / 1 FAIL**. The historical source-switch false-play assertion now passes without modification. The retained failure is the old exact successful Annual JSON equality assertion: the new declared algorithm deliberately changes the input fingerprint and report identity. This result is not presented as full equivalence or an all-green suite. See [run evidence](evidence/source-reappearance-20261016.json).

An additional, separate revision test restricts permitted differences to four exact paths and checks both cold/hot candidate results. It also hashes synthetic old reports, snapshots and normalized-cache objects before the candidate runs, and checks that new cache objects use the new namespace. It does not alter the frozen implementation or the original strict-equality test, and does not prove SQL Goal preservation.

The separate revision/preservation test passed (1 PASS). It confirmed exactly those four differences and no others, preserved all old synthetic JSON hashes, and generated distinct normalized-cache objects. The retained whole-suite result remains 299/7/1; the additional test is recorded separately.
