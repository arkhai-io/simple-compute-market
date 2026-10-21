## 1. Share explicit payments configuration across payment scenarios (PR #270)

- [x] 1.1 Add `e2e-tests/tests/e2e/roles/helpers/payments.py`: read the `PAYMENTS` settings into an `ArkhaiPaymentsConfig`, gate on the target's `/health`, and serialize one named payments table with explicit `livemode` and authentication (D6).
- [x] 1.2 Have the credits payment scenario use it, pin both registries in the buyer configuration, and document the settings in `e2e-tests/README.md` and `docs/development/TESTING.md`.

Landed in `6bdc14b6e`. E2E unit suite passed; the credits payment scenario collected its three tests and, without a payments target, skipped each with the named blocked prerequisite.

## 2. Repair the credits payment scenario invocation and option persistence (PR #271)

- [x] 2.1 Invoke `market credits buy` with the typed `--resource service_name=…` query.
- [x] 2.2 Store each typed payment option as its JSON value when the credits storefront writes a listing (D5).

Landed in `dd0952454` and `a58541900`. `tests/integration/test_publish_reconcile.py`: 4 passed.

## 3. Negotiate credits payments from the selected option (PR #272)

- [x] 3.1 Resolve a hook's `SettlementSelection` to the advertised `SettlementOption` in shared buyer orchestration (D1).
- [x] 3.2 Select each match's settlement proposal before pricing in `market credits buy`, and price from the selected artifact (D2).
- [x] 3.3 Leave the buyer principal to the shared settlement transport (D3).
- [x] 3.4 Compare recovered publisher subjects in their retained text form (D4).

Landed in `57e90106d`, `facaf68b7`, `080d0838a`, and `78cbae2ea`. The credits payment scenario's three stages passed against a payments service: purchase and API consumption, same-settlement re-drive, and seller refund. Core buyer, shared policy, and API-credit buyer suites passed. No permanent tests were added.

## 4. Merge the development branch

- [x] 4.1 Merge `dev`, which carries the payments kit refresh as its own squash commit.

Landed in `7764aad7f`. Conflicts were confined to dependency pins and lockfiles, resolved to `dev`'s. Outside the change's nine files the merged tree equals `dev`, and each of those files carries exactly this change's edits on `dev`'s. `check-packaging`, `check-architecture`, and comment hygiene passed; the core, API-credit, and e2e-unit suites passed. The end-to-end pipeline has not run.
