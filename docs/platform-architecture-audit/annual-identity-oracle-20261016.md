# Annual identity oracle disposition

**PASS_VERSION_AWARE_FULL_DTO_PARITY**, 3 targeted tests passed against the installed local Taiko 0.14.2 center role, using its absolute Python with `-I`. The role still has 94 distributions; independent runtime-memory 1.1.0 and center core 0.1.1 are unchanged. No product code, wheel, Growth compatibility checkpoint, published report or saved measurement was modified.

The old strict comparison expected the frozen algorithm `annual-observation-v4.5.3` identity from Sakura `790c2c7`; the approved 0.14.2 candidate intentionally uses `annual-observation-v4.5.4`. The original failing result remains `/var/tmp/taiko082-combined-offline.log`. The previous test version remains in Git at `99df52f`, SHA-256 `1e7bd496a9242ef2e2c4104d64a4286a2b8c1fe48c235bf6dbdea54e06cf6bf6`.

The external oracle remains `/var/tmp/taiko-offline-20261015/repro-frozen/frozen_source`, with its original source digest manifest and adapted module hashes recorded. It was not regenerated or rewritten.

The revised expectation independently derives both fingerprints and summary IDs using only Python standard-library canonical JSON/SHA-256 over the two fixed snapshot byte hashes, catalog/rating hashes and explicitly asserted reporting window. It asserts the exact snapshot names, 12 charts, source, stage counts and observation dates; both approved algorithm strings are explicit. The old derivation must first match the frozen old oracle. Only these four expected fields then change:

- `summary.summaryId`
- `summary.poster.summaryId`
- `summary.provenance.algorithmVersion`
- `summary.provenance.inputFingerprint`

Both candidate runs still compare the entire serialized DTO, all sections, metrics, events and array order against the frozen expectation. No candidate helper/output is used to manufacture expected identity. A targeted sensitivity test demonstrates that changes to any snapshot/catalog/rating input bytes alter the identity and an unapproved algorithm domain is rejected. The existing preservation test still proves exactly four changed identity fields, unchanged old report/cache bytes and creation of separate current-version normalized cache objects.

The runner appends external pytest tooling without installing anything into the role and disables automatic plugins. `--confcutdir` excludes the parent test hook that normally injects the source checkout. It asserts every imported Taiko/core/contract/runtime-memory module originates in the selected center `site-packages`, and records the original Growth checkpoint hash unchanged. This closes the strict Annual identity oracle residual; it does not close operational O1, production admission or owner release signoff.

Evidence: [annual-identity-oracle-20261016.json](evidence/annual-identity-oracle-20261016.json). Only the three affected cases ran, not the offline suite.
