# Runtime ownership acceptance

Use the existing bounded `scripts/memory/run_qa.sh` runner. All data is synthetic;
network/SQL connections and production file opens are rejected. `events.py`
uses installed candidate wheels, actual NoneBot OneBot/QQ event dispatch,
complete frozen old handlers and real score-card renderers. Only external
SQL/HTTP replies, public resources and platform sends are supplied by fixtures.
Center uses the real relocated materializer/PublicationStore; client uses its
real private-read cache/provider with an offline HTTP-response boundary.

Arguments: `--host center|client --baseline PATH --work EMPTY_OWNED_DIRECTORY
--assets PUBLIC_FIXTURE_ASSETS --application TAIKO_CHECKOUT`.
Baselines are Sakura `86a308c` (`taiko/`) and Taiko `1e7d0f9` respectively.
The center old handler is the already frozen D0.6 reference; D1 renderers are
loaded from the baseline path. The old handler's outer binding lookup is
supplied by the same real provider, isolating matcher/handler/render parity;
this does not independently prove SQL/remote authorization policy parity.
The unchanged native binding-read functions and D1 provider checks are audited
separately. No legacy renderer or frozen handler is part of the candidate runtime.

Each host: 108 parity cases (six scenarios × two transports × nine branches),
four revocation checkpoints, three stale target checks. Successful image cases
must contain an image hash; expected exceptions must occur on both sides.
Center first-u0 image events use independent unmaterialized directories.
Client u0 scenarios describe remote fixture responses, not a local Writer.
`tinfo` intentionally does not fetch history, so missing history is acceptable.
`--guard-smoke` exercises 15 cases with the same Application capability guard.

`public_dispatch.py` preserves the existing 78/80 public command assertions
while loading the new public/player entries alongside the full legacy host.
`storage.py SAKURA_TAIKO_ROOT` executes the existing 60 storage tests plus five
subtests against the installed relocated store. Its guard permits owned
filesystem/process tests, including real lock competition and recovery.
`scope.py APPLICATION SAKURA` checks unchanged storage implementation and the
non-target command ASTs. Historical public-command scripts require their
existing synthetic/public fixtures and frozen references; see the phase report
for exact retained paths. No test starts a live Bot connection or production DB.

`load_order.py center|client reverse|forward|all` validates dependency ownership
and idempotent require in a new process (nine public + one player matcher).

Pre-merge delivery checks: `delivery_smoke.py --host center|client --work EMPTY_DIR
--assets PUBLIC_FIXTURE_ASSETS` sends one representative event for each of the
nine public entries on OneBot and QQ through the installed modules. It uses
`tests/archive/public-song-plugin/tests/{fixtures,catalog-fixtures}` and does
not need the retired distribution path. This smoke is not frozen-output parity;
retain the original parity evidence and use `events.py --guard-smoke` for the
limited tinfo image/text comparison and revocation checks.
