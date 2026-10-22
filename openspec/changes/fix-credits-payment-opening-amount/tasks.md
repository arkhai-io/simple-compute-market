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

## 5. Bound, harden, and prove the selected-option opening

Accepted in the design review's triage (`reviews/01-design-external.triage.md`); planning shapes this section.

- [ ] 5.1 Unit-test `_negotiate_matches` with a payment selection on a listing advertising a payment option and an escrow option at different rates: the negotiation policy receives the payment option, and the opening amount derives from its rate (D1; 01 F1).
- [ ] 5.2 Integration-test the API-credit storefront in-process through `StorefrontClient` over `ASGITransport`, with differently priced payment and escrow options and no supplied initial amount: the storefront records the payment option's mechanism and option ID and an opening at its rate (D1, D2; 01 F1).
- [ ] 5.3 In `market credits buy`, stop selection once `--max-matches` usable matches are found, state the option's meaning in its help, and test mixed listings for which are evaluated and which negotiate (D7; 01 F2).
- [ ] 5.4 Exit `unadvertised_settlement_selection` from `_negotiate_matches` when a selection resolves to no advertised option, before revalidation and without contacting the seller; unit-test the outcome and that no negotiation is attempted (D8; 01 F4).
- [ ] 5.5 In `configured_payments()`, skip only for a blank `SERVICE_URL` or an unready target; with `SERVICE_URL` set, fail naming any other missing required setting; parse `LIVEMODE` and `DEVELOPMENT_AUTH` as strict booleans; cover blank, misconfigured, and unready targets in the e2e unit tests (D6; 01 F3).
- [ ] 5.6 Update `docs/development/TESTING.md` and `e2e-tests/README.md` to the helper's skip and fail rule, and to say the API-credit payment scenario uses the shared helper and others may reuse it, the bare-metal table being one the serializer supports (D6; 01 F3, 01 F5).
