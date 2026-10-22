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

## 5. Resolve or refuse the selected option in shared buyer orchestration

Replanned against the reviewed design: the design triage's tasks 5.1–5.6 are split by layer into sections 5–7. Delivers D1's proof, D8, and D4's proof in `core/buyer`, implementing the `buyer-orchestration` delta's "Negotiation opens from the selected advertised option". Touches `core/buyer/src/core_buyer/orchestration.py` and `core/buyer/tests/unit/`.

- [x] 5.1 Unit-test `_negotiate_matches`, through `make_negotiate_hook` as `domains/vms/buyer/tests/test_buy_orchestrator.py` drives it, with a hook returning a payment `SettlementSelection` on a listing advertising a payment option and an escrow option at different rates: revalidation and the negotiation policy receive the payment option, and the opening amount derives from its rate, not the escrow's (D1; delta scenario "A listing advertises differently priced options"; 01 F1).
- [x] 5.2 In `_negotiate_matches`, when a selection resolves to no advertised option, record the attempt and return an `exited` outcome with reason `unadvertised_settlement_selection`, before revalidation and before contacting the seller, as the neighbouring `no_compatible_settlement_option` exit does (D8; 01 F4).
- [x] 5.3 Unit-test 5.2: the outcome and attempt carry `unadvertised_settlement_selection`, and neither revalidation nor the seller's negotiation call runs (D8; delta scenario "A selection names nothing the listing advertises").
- [x] 5.4 Unit-test `make_publisher_trust_resolver` with a publisher subject retained as text and refreshed from the registry as an integer: the refresh accepts it, keeping the listing identity and trust pin, and still refuses a changed publisher or storefront (D4; the review's additional-tests table — no committed test covers the mixed forms).

Verification: `core/buyer` unit suite (unit level, hooks and seller calls injected), with 5.1's test failing if `orchestration.py` stops resolving the selection; `make test`. No dependency changes. End-to-end: `e2e_credits_payment_deal` drives this path once deployed, but skips without a payments target, so the pipeline is not evidence for it.

Done. `_negotiate_matches` exits `unadvertised_settlement_selection` when a selection resolves to no advertised option, recording the attempt, before revalidation and before the publisher-trust refresh or any seller call (5.2). Tests:
- `tests/unit/test_selected_option_negotiation.py` (unit; the hook driven through `make_negotiate_hook`, the registry refresh and seller call patched at module level as the VM buyer's tests do — the hook offers no injection seam for them): a payment selection on a listing advertising a payment and an escrow option at different rates reaches revalidation and the negotiation policy as the payment option (5.1); with that option in context the opening proposal carries an amount, and without it none (5.1); a selection naming an unadvertised option ID or mechanism records `unadvertised_settlement_selection` and contacts neither registry nor seller (5.3).
- `tests/unit/test_orchestrator.py` (unit): a publisher ID retained as text is accepted against the registry's integer, a changed publisher or storefront is refused, and the retained listing is not rewritten (5.4).

What these prove, and do not: core proves that the selected option reaches negotiation and makes the opening bargain an amount. The amount's value is the domain's derived opening price, not core's, so "the opening derives from the option's rate, not the escrow's" is proved for the credits buyer in 6.3. 5.3 asserts the attempt's error; the exited outcome's reason is not exposed by the hook's result when no candidate agrees.

Evidence: `core/buyer` unit suite passed, 141. Mutations: restoring the pre-resolution lookup (`_selected_settlement.option`) fails the payment-option test; comparing publisher IDs without `str()` fails the mixed-form case. `make -k test` passed except the two known environmental gaps (the VM storefront's Alkahest chain tests; the Helm render step without `helm`).

End-to-end: as planned — `e2e_credits_payment_deal` drives this path once deployed and skips without a payments target.

## 6. Bound the credits buyer's selection and prove its opening

Delivers D7, the in-process proof of D1 and D2 for `market credits buy`, and D5's proof, implementing the `buyer-orchestration` delta's "The match cap counts candidates the buyer can settle with". Touches `domains/apicredits/buyer/src/arkhai_apicredits_buyer/buy_cli.py`, `domains/apicredits/buyer/tests/`, and `domains/apicredits/storefront/tests/integration/`.

- [x] 6.1 In `market credits buy`, stop the selection loop once `--max-matches` usable matches are found, and state in `--max-matches`'s help that it counts sellers with a usable settlement option (D7; 01 F2).
- [x] 6.2 Test 6.1 with mixed listings — some with no option the buyer can use, more usable ones than the limit — asserting which listings selection evaluates and which reach negotiation, in discovery order (D7; delta scenario "Some discovered listings cannot be settled with").
- [x] 6.3 Application-integration test: `market credits buy` against the API-credit storefront running in-process, its storefront calls made by the production typed `StorefrontClient` over `httpx.ASGITransport` (as `tests/integration/test_exact_selection_api.py` builds it), with a listing advertising a payment option and an escrow option at different rates and no initial amount supplied. Assert the storefront records the payment option's mechanism and option ID and an opening amount at its rate. `tests/integration/test_credits_negotiate_cli.py` shows the buyer CLI driven in-process (D1, D2; 01 F1).
- [x] 6.4 Library-integration test of the credits storefront's listing publication with real SQLite and an actual typed `SettlementOption`: the stored listing's `settlement_options` read back as the option's JSON value, and discovery's codec reads the option again (D5; the review's additional-tests table — `tests/integration/test_publish_reconcile.py`'s cases publish escrows only).

Verification: API-credit buyer suite (unit, for 6.2) and API-credit storefront integration suite (application integration through the typed client, for 6.3; library integration with real SQLite, for 6.4); `make test`. End-to-end: `e2e_credits_payment_deal` exercises `market credits buy` once deployed, but skips without a payments target.

Done. The selection loop is `select_settlement_for_matches` in `buy_cli.py`, lifted out of the command so it can be tested without driving the command through its configuration; it stops once `--max-matches` usable matches are found, and the option's help says it counts sellers with a usable settlement option (6.1). Tests:
- `domains/apicredits/buyer/tests/test_buy_selection.py` (unit): of five discovered listings with a limit of two — one with no option, one usable, one whose selection its listing does not advertise, two more usable — selection evaluates the first four in order and keeps the two usable ones, each carrying only its selected option, and leaves the listing it was given unchanged (6.2).
- `domains/apicredits/storefront/tests/integration/test_credits_buy_selection.py` (application integration: the real `market credits buy` command against the real negotiation routes, response-authentication middleware, API-credit negotiation runtime and SQLite, served on loopback; registry discovery, the buyer's identity and configuration, the quota hold, and post-agreement payment settlement are controlled at their seams): a listing advertising a legacy escrow at 100 per token beside a payment option at 70 per credit, with no prices supplied, negotiates three credits at 210 — the buyer's opening and the agreed price — and the storefront's stored Agreement names the payment option's mechanism and option ID (6.3).
- `tests/integration/test_publish_reconcile.py`'s `test_a_published_payment_option_is_stored_as_its_json_value` (service integration: `ListingService.publish_from_quota` against real SQLite, below the HTTP application, as its neighbours in that file): a published typed payment option is stored as its JSON value and reads back as the same `SettlementOption` (6.4).

Plan divergence: 6.3 named the typed `StorefrontClient` over `httpx.ASGITransport`, but `market credits buy` negotiates through `core_buyer.negotiation_client`'s signed `urllib` client, which takes no transport, so an ASGITransport test could not run the command or prove D2. The test serves the real routes on loopback through `tests/loopback.py`, as `test_credits_negotiate_cli.py` does; moving buyers onto the typed client is `buyers-use-the-storefront-client`'s. The fixtures both tests share — the payments service key, the dispute account, the quota-hold double, and `payment_option(rate)` — now live in `tests/integration/credit_negotiation.py`. The storefront's `arkhai-apicredits-buyer` dev dependency now names both commands it is kept for.

Evidence: API-credit buyer suite passed, 27; API-credit storefront suite passed, 184, against wheels rebuilt from this tree and reinstalled with `reinit`. Mutations: removing the early stop fails 6.2; removing the narrowing to the selected artifact makes 6.3's opening 300 instead of 210; storing the typed options unserialized fails 6.4 with no options stored.

Handoff: never edit an installed package file for a mutation check. `uv` hard-links installed files to its cache, so the edit alters the cached copy every later reinstall reuses; after one such edit here, `uv cache clean arkhai-apicredits-buyer` and a reinstall from the rebuilt wheel restored it. Mutate source, rebuild the wheel, and reinstall instead. Follow-ups outside this change: `TESTING.md` does not describe the loopback-serving seam for clients that take no transport, which now has two consumers; and the storefront's tests import `core_buyer` without declaring it.

End-to-end: as planned — `e2e_credits_payment_deal` exercises `market credits buy` once deployed and skips without a payments target.

## 7. Block payment scenarios only on an absent or unready target

Delivers D6's refined rule, implementing the `test-compatibility` delta's "A configured payments run lacks a buyer credential", and corrects the helper's documentation. Touches `e2e-tests/tests/e2e/roles/helpers/payments.py`, `e2e-tests/tests/unit/`, `e2e-tests/README.md`, and `docs/development/TESTING.md`.

- [x] 7.1 In `configured_payments()`, skip as blocked only when `SERVICE_URL` is blank or the target's `/health` is not ready; with `SERVICE_URL` set, fail naming each other missing required setting before checking readiness; parse `LIVEMODE` and `DEVELOPMENT_AUTH` as strict booleans, failing on a value that is neither (D6; 01 F3).
- [x] 7.2 E2E unit tests of 7.1, with readiness injected rather than reached over the network: blank target skips, configured target missing a buyer credential fails naming it, unready target skips, and `"false"` and `"true"` strings parse as booleans (D6).
- [x] 7.3 Update `docs/development/TESTING.md#private-service-dependencies` and `e2e-tests/README.md`'s "Shared payment-scenario configuration" to 7.1's rule, and to say the API-credit payment scenario uses the shared helper and others may reuse it, the bare-metal table being one the serializer supports (D6; 01 F3, 01 F5).
- [x] 7.4 **Comment hygiene and import placement, before the pre-closeout review.** Run `make check-comment-hygiene`, read the comments this change added for any that narrate the review or migration that introduced them, and move each import it added to module level unless a verified circular import or a recorded lazy-load reason keeps it local. That includes the function-local `from .escrow_selection import select_escrow_entry` PR #272 moved within `buy_cli.py` (`openspec/README.md#plan-closeout-requirements` parts 1 and 2; closeout only confirms both).

Verification: e2e unit suite (`make -C e2e-tests test-unit`; unit level); `make test`; `make check-change`. End-to-end: the pipeline's API-credit lane exercises 7.1's blank-target skip, since it configures no payments target; a configured target is exercised only off the pipeline.

Done. `configured_payments()` skips as blocked only for a blank `SERVICE_URL` or a target whose `/health` is not ready; with `SERVICE_URL` set it fails naming each other missing required setting before asking the target; `LIVEMODE` and `DEVELOPMENT_AUTH` read through `payment_flag`, which accepts a boolean or the text `true`/`false` and fails on anything else; readiness is `target_ready`, injected as `ready=` (7.1). `TESTING.md#private-service-dependencies` and the e2e README's "Shared payment-scenario configuration" describe that rule and say the API-credit scenario uses the helper and others may reuse it (7.3). `select_escrow_entry` is imported at module level in `buy_cli.py` — `escrow_selection` imports nothing back — and the change adds no other function-local import; `make check-comment-hygiene` passes (7.4).

Tests: `e2e-tests/tests/unit/test_payments_helper.py` (unit; settings replaced by a stand-in, readiness injected): a blank target skips without readiness being asked; a configured target missing the buyer credential fails naming it; an unready target skips; a ready one yields its policy; `"false"`/`"true"` text parses for both flags; `DEVELOPMENT_AUTH = "false"` without an API key still fails for the missing key; a non-boolean flag fails (7.2). Skips and failures are caught as values, so a helper that wrongly skips fails the test rather than being reported as a skipped test.

Evidence: e2e unit suite passed, 53. Mutations: skipping on a missing setting fails the misconfigured-target test; reading either flag with `bool()` fails its parsing tests (four for `DEVELOPMENT_AUTH`). `make check-packaging` and `make check-change` passed.

Fresh-context compliance check of sections 5–7 (one pass over the three sections' diff): no violation of layering, comments, import placement, or documentation placement in production code. Fixed: task claims the tests did not support (5.1's amount value, 5.3's outcome reason, 5.4's listing identity, 6.3's storefront-side assertions, 6.4's codec), the strict-boolean tests covering `LIVEMODE` only, unmarked development keys, the helper's docstring, the storefront dev dependency's stated reason, fixtures copied between the buy and negotiate tests, private `_pytest` imports, and spacing and import grouping. Added to closeout: `openspec/specs/test-compatibility/architecture.md#payment-evidence-ownership` contradicts D6 (8.9 and the proposal). Declined: module-level patching in the core unit tests, which the plan prescribes and the hook gives no seam to avoid. Recorded as follow-ups: section 6's notes.

End-to-end: as planned — the pipeline's API-credit lane, configuring no target, exercises the blank-target skip.

## 8. Closeout

The closeout task of `openspec/README.md#plan-closeout-requirements`, in its order. It edits documentation only; a part needing code returns the change to implementation.

- [ ] 8.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene` and read every comment and docstring in the change's diff from its merge base with `dev` (`git diff $(git merge-base origin/dev HEAD) HEAD`) for any that narrate the review or migration that introduced them. Do not edit code here.
- [ ] 8.2 **Import placement — confirm.** Check the imports the change added for any still local without a recorded reason. One that should move returns the change to implementation.
- [ ] 8.3 **Documentation compliance.** Re-check D1–D8 against `openspec/README.md`'s placement rules and the permanent documents against the code: `TESTING.md` and the e2e README describe the helper as 7.1 left it, and `market credits buy --help` states D7's meaning.
- [ ] 8.4 **Narrative compression.** Compress completed-task notes in sections 1–7 to final behaviour, material evidence, deferrals, and destinations, moving durable rationale into `design.md` first.
- [ ] 8.5 **Roadmap currency.** This change closes no gap row of `docs/development/ROADMAP.md`'s Goal 6, and its payment qualification boundaries stay true; confirm and record the disposition explicitly.
- [ ] 8.6 **Campaign index currency.** Update this change's row under "Roadmap goal — Make the settlement mechanism a composed choice" in `openspec/changes/README.md` to `in closeout` with notes describing the archived state, then point it at the archive (8.11). Record in the notes that PRs #270 and #271 are included in #272. Leave the unowned kit-selection item as it is, and other rows' `Depends on` alone.
- [ ] 8.7 **Packaging.** Run `make check-packaging`, then `make check-architecture-change CHANGE=fix-credits-payment-opening-amount`. The change touched no `.agents/`, `.claude/`, or `.codex/` file, so `make check-agent-skills` is not owed.
- [ ] 8.8 **End-to-end pipeline.** Record the run the latest passing validation names and its result, as regression evidence that the three lanes deploy and run: no lane has a payments target, so `e2e_credits_payment_deal` skips and no scenario exercises the selected-option opening. Record the payment scenario's outcome — run, or skipped for want of a target — rather than counting a skip as a pass. The opening's evidence is sections 5 and 6, and #272's live run of the credits payment scenario against a payments service (section 3).
- [ ] 8.9 **Promotion.** The `buyer-orchestration` and `test-compatibility` `spec.md` changes are written by the archive in 8.11 from this change's deltas; `TESTING.md` and the e2e README are written in 7.3. `openspec/specs/test-compatibility/architecture.md#payment-evidence-ownership` says missing credentials are reported as an unmet prerequisite; rewrite that sentence to D6's rule — blocked only with no target or an unready one, failing on a configured run's missing setting — since the archive does not touch companions (named in section 7's compliance check). Complete a design-promotion record in `design.md` naming, for D1–D8, the delta requirement, permanent document, or code-only disposition of each.
- [ ] 8.10 **Documentation citations.** Run `make check-doc-citations CHANGE=fix-credits-payment-opening-amount` and resolve every match, then `make check-change CHANGE=fix-credits-payment-opening-amount`, which runs the pinned `@fission-ai/openspec@1.14.0` strict validation.
- [ ] 8.11 **Archival.** `bunx @fission-ai/openspec@1.14.0 archive fix-credits-payment-opening-amount -y`, merging the `buyer-orchestration` and `test-compatibility` deltas into `openspec/specs/`, then point the index row at the archive directory.
