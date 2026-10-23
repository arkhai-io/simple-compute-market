# Implementation review — unbacked-bare-metal-listings

## Summary

This round covers implementation round 1: groups B and D of the design, in Sections 3–10 of `tasks.md`. It delivers:

- Readiness blockers that state their kind.
- Unusable Alkahest configuration reported as unready, not fatal.
- A `kit/alkahest` chain probe, registered by each storefront as the `alkahest-chain-probe` loop.
- Release conditions derived only from ready clauses.
- The API-credit `listing-seed` loop step, a 503 for a create refused only because a mechanism cannot be reached, and CLI listing commands that call the running storefront.
- Settlement verification against the committed plan.
- Refusal of an escrow proposal that names no contract, and removal of first-entry pricing.
- Removal of `accepted_escrow_terms`; buyers fund only what they derive, and the run-log records the listing's release conditions.
- A startup refusal for stored pools whose provider no handler serves, and signed 500s after authentication in both middlewares.

I read the change's own commits, `968a4a9..da1929a` (from `d349c8c` to `da1929a`, eight section commits plus a WIP commit and a dev merge). I did not use `git diff dev...HEAD`. The local `dev` ref (`44abb4a`) is behind the `origin/dev` this branch merged at `968a4a9`, so that range would also show `repair-helm-render-tests` and other dev work. I checked the code against `design.md` decisions 16–19 and 23, the delta specs, and the task notes.

I ran `make check-comment-hygiene` and it passed. `make check-architecture` was refused in this session, so it is unrun here; the task notes record `make check-packaging` passing. No `reviews/NN-validation.md` exists yet for this commit.

## Assessment

The work is careful, and its records are unusually honest about where tests stop. The architectural placement holds:

- The probe and the client map are in `kit/alkahest`.
- `kit/storefront` gains only a constructor.
- Core stays mechanism-neutral: it has a status `settlement` list and an opaque `listing_record`.
- `core/buyer` imports no Alkahest.
- Both `ARCHITECTURE.toml` exception rows were correctly retired.

The Section 9 funding paths all derive the escrow themselves and check it against the seller's plan before funding. The two Section 10 middlewares handle the failure after authentication correctly.

What most needs attention is the negotiation-pricing rework in Section 8. It made seller safety depend on which policy runs first, and one default policy still reads the latest counter rather than the pinned opening. A VM buyer can therefore get a priced option at an arbitrary amount (F1). This breaks the change's own new delta scenario, and is the one blocking finding.

Two related gaps remain around the claim that "settlement can't be moved after acceptance":

- Verification still resolves the escrow codec from the current address book (F5).
- The kit's materialization chokepoint still takes the buyer's literal fields, so with the shape guard omitted, bare metal can be escrowed in another token (F6).

The chain probe is sound in design but has two edges:

- Readiness can say "ready" for a chain with no client (F7).
- Client construction is unbounded and can wedge the probe loop, its pause, and the seed (F8).

The remaining should-level items:

- The VM operator create path still publishes caller-supplied `demands` (F9).
- The buyer-orchestration delta and design D17/D18 no longer describe what was built (F4).
- The end-to-end and wiring evidence for the probe and the seed is weaker than recorded (F2, F3).

## Questions

### direction — If you were implementing this change, what would you have done differently?

**Pricing (D18, Section 8).** The chosen shape is: price an unmatched proposal at zero in VM and API credits, then rely on the default guards running first. That makes correctness depend on policy order and on every policy reading the pinned opening rather than the latest round. F1 shows that one default policy does not.

- **Alternative:** every domain refuses an opening whose pinned proposal selects nothing, inside its reference-amount hook, before any policy. Bare metal already does this (`_priced_acceptance`). The continuation hook then prices only the pinned opening's matched entry and refuses when it no longer matches (F17).
- **Trade-off:** one more refusal path in VM's and API credits' hooks. In exchange, a decider can never see a zero reference.
- **Recommendation:** adopt bare metal's shape in all three domains, and fix F1 in `kit/policy` regardless.

**Codec resolution (D16).** I would record the escrow kind (codec slot) in the plan obligation at acceptance, and verify from it rather than from the current address book. This closes F5. For the unpinned deals accepted before this release (Section 7's handoff, left for triage), I would record a disposable-state cutover in D18. All known such deals are lane deals, and the buyer can reclaim at expiry.

**Settled positions for the items left to triage.** I agree with:

- running the plan check at funding (D17's Section 9 paragraph);
- bare metal continuing every round against the opening's record;
- the new status `settlement` list.

I would remove the listing form of verification (`verify_escrow_for_settlement`). It has no production caller, and keeping two verification paths invites drift.

**Re-bumping unreleased packages.** Re-bumping the same unreleased package in each section is churn. I would bump each package once per change, against its last release (F11).

### testing — Is the validation strategy sound?

The test levels, against `TESTING.md`'s definitions:

- **Kit suites are unit tests over stub boundaries.** This covers `test_chain_probe.py`, `test_settlement_config.py`, `test_plans.py`, `test_release_authorization.py`, and the `kit/policy` and settlement-runtime suites. They are the strongest evidence for the per-rule claims.
  - `test_chain_probe.py` proves the timeout only by checking that it is passed through.
  - No test exercises a websocket chain, a hung construction, or a multi-chain seller (F7, F8, F10).
- **Status and probe tests are application integration through `StorefrontClient`, but over doubles.** This covers VM `test_lifecycle_status.py`, bare metal `test_http_system.py`, and API credits `test_lifecycle_status.py`. VM and API credits replace both the container's probe and its settlement composition (`test_lifecycle_status.py:226-238`). So the production hand-off of `chain_probe` and the shared client map is proven only by bare metal's identity test at composition level (F3).
- **API credits' 503 and seed tests are application integration through `ApiCreditListingClient` and the administrator's typed client.** These are in `test_alkahest_release_conditions.py`, which patches `server._build_alkahest_chain_probe`. The seed's production find path and site resolution are never exercised (F13).
- **VM settle-controller dry-run tests are application integration through the typed client.** VM has no typed-client test of settle itself after a listing change; that is recorded.
- **The heartbeat test builds raw signed requests.** `test_deals_controller.py` does so because the route has no client method. Under `TESTING.md`'s "no raw calls" rule that is a deferred-debt marker; adding the method would close it.
- **Bare-metal negotiation and settlement tests are application integration with a replaced plan builder and verifier.** These are `test_http_negotiation.py` and `test_http_settlement.py`.
- **Section 8's round-reference tests are unit tests over hand-built rounds.** `TestRoundReference` asserts only `action != "accept"`. No test runs a counter through `accept_unpriced_selection` or through `NegotiationRuntime`, which is how F1 went unseen.
- **Core buyer tests are unit tests.** No test drives `_settle_one` with `settlement_plan=None` (F12).
- **The provisioning and `kit/site` signed-500 tests are application integration through the typed clients.** These are `test_pools_api.py`, `test_signed_authority.py`, and `kit/site`'s integration test.

The validation report does not exist yet. Every end-to-end claim in Sections 4–10 is "unrun", by reading. Section 6's claims about the credits lane are partly wrong (F2). The bare-metal lane settles only with Sections 7 and 8 together, which HEAD has. The VM chart's render-probe edit (`helm/charts/storefront/tests/test_render.py:946-960`) is unrun here, and the pipeline must show it.

Findings: F2, F3, F13, and the testing half of F1.

### documentation — Do the code and documentation comply with AGENTS.md, ARCHITECTURE.md, and openspec/README.md?

- **Comment hygiene passes mechanically.** I also scanned the added lines for history narration ("no longer", "previously", "moved") and found none.
- **Promotion is correctly deferred to closeout.** The design's promotion list was extended for what implementation settled: the `buyer-orchestration` companion, `DEPLOYMENT_AND_CONFIG.md`'s RPC timeout and status `settlement`, and the `storefront-publication` companion's opening-record continuation.
- **Docs edited in this round describe current state.** `docs/configuration.md`'s guard rows, `RELEASING.md`, and the manifest order all do.
- **But the change's own documents have drifted from the code.** The buyer-orchestration delta still prescribes deriving from the Agreement's selected option. D17's bullets still describe widening `AdvertisedPlanValidatorFn`. D18's rationale still states a premise the implementation showed false (F4).
- **Two code-adjacent texts describe paths that no longer hold.**
  - `release_conditions.py`'s module docstring still offers a startup refusal, which the delta forbids (F14).
  - Section 10's handoff note misstates how a failure mid-stream behaves (F15).

### architecture — Is the code organized by ARCHITECTURE.md's layers?

Yes.

- **`kit/alkahest`** owns the probe, its schedule constants, the plan-form verifier, the unpinned refusal, the release-conditions record and its reader, and `require_escrow_terms_fund_plan`. It declares `arkhai-kit-config` for `PositiveSeconds`, which correctly retires the `undeclared_import` row.
- **`kit/storefront`** gains only `alkahest_client_constructor`, on its already-excepted edge (`ARCHITECTURE.md:192`), with no probe or schedule. This extends an excepted edge by one function rather than adding a new edge; acceptable, but `move-escrow-into-alkahest` should carry it when the factory moves.
- **`kit/settlement-runtime`** owns `ReadinessBlockerKind` and the disabled-section readiness, staying mechanism-neutral.
- **Core** gains an uninterpreted status `settlement` list and an opaque `listing_record`. The vocabulary row's removal is justified: the coercions are gone.
- **The domains compose rather than encode.** Each registers the kit's probe as its loop. API credits' seed is domain composition, as it should be.
- **`kit/policy`'s `escrow_contract_unpinned` and `kit/alkahest`'s `require_pinned_escrow`** are deliberately duplicated, because the scope rule forbids `kit/policy` from importing a mechanism kit. They agree on every input I checked.

No layer finding. The ownership questions I raise (F6's chokepoint, F7's readiness) are recorded as consistency findings.

### consistency — Does the implementation do what the design and delta specs say, and only that?

Mostly. These hold:

- Every production `ReadinessBlocker` sets a kind.
- A chain not yet probed reads as reachability, and disabled sections drop reachability blockers.
- No probe consumer copies the client map: VM, API credits, and bare metal share it, and the `dict(...)` and `or {}` copies are gone.
- Every settle, recover, and dry-run path verifies against `thread["settlement_plan"]`.
- The heartbeat and interrupt read the plan.
- All five materializers call `require_pinned_escrow`.
- No production reader of `accepted_escrow_terms` remains.
- Every funding path checks the derivation against the plan whenever one was sent.
- `release_conditions_unrecorded` is raised only before funding.
- Both middlewares catch only after authentication and do not swallow `BaseException`.
- `stored_provider_problems` counts disabled pools.

Divergences: F1, F5, F6, F7, F8, F9, F16, F17.

## Findings

### F1 — A VM counter selecting an unpriced option is accepted at the counter's amount against the opening's priced option

- **Lens:** consistency
- **Basis:** specification
- **Severity:** blocking
- **Evidence:**
  - `kit/policy/src/market_policy/scalar_policies.py:945-974` (`accept_unpriced_selection` reads `_peer_proposal`, the latest round, at `:959` and `:824-825`).
  - `kit/policy/src/market_policy/scalar_policies.py:790-808` (`buyer_counter_guard` treats the round as scalar from the opening and passes a counter carrying an amount).
  - `kit/policy/src/market_policy/scalar_policies.py:848-850` (`escrow_shape_guard` passes a selection-only round).
  - `domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py:125-133` (`accept_unpriced_selection` is a default guard in every VM chain).
  - `domains/vms/storefront/src/market_storefront/controllers/negotiate_controller.py:201-219` (a counter may carry `settlement_selection`).
  - `kit/negotiation-runtime/src/market_negotiation_runtime/runtime.py:950-972` (`agreed_amount` comes from the decision's proposal; the acceptance carries `pinned_proposal`).
  - Delta `specs/negotiation-protocol/spec.md:100-101` ("MUST price the pinned proposal in every round, whatever a later counter names") and `:130-134`.

The path, traced by reading and not reproduced:

1. A buyer opens on priced option A of a VM listing that also offers an unpriced option B.
2. It counters with `settlement_selection` = B and an amount of 1.
3. `buyer_counter_guard` reads the round as scalar from the opening and accepts the counter's amount.
4. The shape guard passes a selection-only round.
5. `accept_unpriced_selection` sees an exact selection of an unpriced option and accepts the counter as proposed.
6. The runtime commits `agreed_amount = 1` against the pinned opening, option A. VM builds the plan from `acceptance.pinned_proposal`.

The seller is committed to deliver option A for 1 base unit. Section 8 set out to make "a counter naming another option" change nothing; the reference amount now follows the opening, but this acceptor still follows the counter. No test drives `accept_unpriced_selection` on a counter (`TestRoundReference` asserts only `action != "accept"`).

**Suggested action:**

- Have `accept_unpriced_selection` judge `pinned_proposal(history)`, accepting only when the opening is an exact selection of an unpriced option.
- Have `buyer_counter_guard` refuse a counter whose `settlement_selection` or escrow differs from the opening's.
- Add a VM application-integration case in `tests/integration/test_negotiate_controller.py` that runs this counter through `StorefrontClient`.
- Check API credits' chain for the same acceptor.

### F2 — The credits lane's end-to-end evidence for the seed is a race, and one cited scenario cannot be evidence

- **Lens:** testing
- **Basis:** guidance
- **Severity:** should
- **Evidence:**
  - `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py:154-170` (a single `credits buy` discovers once).
  - `domains/apicredits/buyer/src/arkhai_apicredits_buyer/buy_cli.py:455-461` ("No listings matched" exits).
  - `e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_payment_deal.py:63-65` (skips without `PAYMENTS.*`).
  - `tasks.md:906-907` and `:924-928`.
  - `docs/development/TESTING.md`, "Async test discipline — no sleeps" (`:136-145`) and "Pause the loop, then advance it explicitly" (`:159-171`).

The seed now publishes after the probe's first cycle, plus up to 2 s, after the loops start. No scenario steps or waits on `listing-seed` before discovery, so `e2e_credits_deal` passes only if the seed wins a timing race. That is the kind of timer dependence `TESTING.md` asks to replace with an explicit step.

Section 6.6 also cites `e2e_credits_payment_deal` as proof that the step publishes. That scenario skips unless `PAYMENTS.*` is configured, and the seed offers only Alkahest anyway.

The recorded handling — wait and see whether the pipeline loses — treats a flaky pass as evidence.

**Suggested action:**

- Before discovery, have the credits scenario step `listing-seed` through the administrator's typed client, or wait on its `done` state.
- Correct 6.6 so it names only `e2e_credits_deal`.

### F3 — The production wiring of the chain probe is untested in VM and API credits, and the seam the tests need is missing

- **Lens:** testing
- **Basis:** guidance
- **Severity:** should
- **Evidence:**
  - `tasks.md:460-472` (production hand-off untested in all three storefronts) and `:759-762` (a server-level seam declined).
  - `domains/vms/storefront/tests/integration/test_lifecycle_status.py:226-238` (probe and composition both monkeypatched onto the container).
  - `docs/development/TESTING.md:36-42` ("Do not patch module-level imports") and `:141-145` ("If no such seam exists yet where a test needs one, adding it is the correct fix").

The behaviour this change most needs proven is the hand-off itself: that the composition hands readiness the same probe whose loop is registered, and that every client consumer holds the probe's map. In VM and API credits it is untested, because the tests replace both ends. API credits reaches the probe only by patching `server._build_alkahest_chain_probe`.

A wiring regression would pass every suite: for example, a copy of the client map reappearing, or the composition receiving a different probe from the one the loop steps.

**Suggested action:**

- Give each storefront's composition root an injectable JSON-RPC transport for the probe, through the same container override pattern the other boundaries use.
- Add one application-integration test per storefront that runs the real settlement composition and the registered loop: step the probe, and observe readiness change through status.

### F4 — The buyer-orchestration delta and design D17/D18 describe what was planned, not what was built

- **Lens:** documentation
- **Basis:** evidence
- **Severity:** should
- **Evidence:**
  - `openspec/changes/unbacked-bare-metal-listings/specs/buyer-orchestration/spec.md:11-13` ("a resumed run MUST derive the escrow from the Agreement's selected option").
  - `kit/alkahest/src/market_alkahest/proposals.py:100-136` (derives from the recorded accepted proposal).
  - `design.md:548-552` (D17 bullet: `AdvertisedPlanValidatorFn` "runs on every branch … and on resume … API credits supplies it as VM does"), contradicted by `design.md:566-573`.
  - `design.md:617-619` (D18: "no buyer in this repository sends an unpinned proposal"), contradicted by `tasks.md:1454-1457`.

Task 9.3 records the derivation from the accepted proposal as "Differed", but the delta was not amended. At archive, the permanent `buyer-orchestration` spec would state a requirement the code does not meet.

D17 now holds both the original bullet and a "Settled in implementation" paragraph that contradicts it. D18's stated rationale rests on a premise Section 8 showed false; its outcome is unaffected.

**Suggested action:**

- Amend the delta requirement and its "A run is resumed with only an accepted proposal" scenario to the recorded accepted proposal, the recorded conditions, and the exact Agreement amount.
- Rewrite D17's plan-check bullet to the funding-time port.
- Correct D18's rationale: the client used to fill in the zero address, and the wire must refuse such a proposal whatever the client.

### F5 — Plan-form verification still depends on the current address book to find the escrow codec

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/escrow_verification.py:474-477` and `:309-321`.
  - `kit/alkahest/src/market_alkahest/alkahest.py:2213-2223`.
  - Delta `specs/settlement-servicing/spec.md:11-13` ("A seller's change to its release policy, wallet, or chain address book after acceptance MUST NOT change how an accepted deal is verified").
  - `tasks.md:1005-1013` (the Section 7.1 tests move only the arbiter).
  - `tasks.md:1199-1207` (unpinned pre-release deals).

`verify_escrow_against_plan` resolves the codec by looking the plan's `escrow_contract` up in the address book as configured now. If a seller moves or renames the escrow contract after acceptance, a correctly funded escrow fails with "Cannot resolve escrow codec" and waits for reclaim. That is exactly the outcome D16 exists to prevent.

The same lookup is why deals accepted unpinned before this release cannot verify. On bare metal, deals already verified but not yet delivered also stall at `revalidate_alkahest` (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_stages.py:611-628`), a case the handoff does not mention.

**Suggested action:**

- Record the escrow kind in each Alkahest plan obligation at acceptance, and verify through it, falling back to the address book only for plans that lack it.
- Add a unit case that moves the escrow contract.
- Record in D18 the decision on deals accepted unpinned before the release. I recommend an explicit disposable-state cutover, naming the bare-metal recovery stall.

### F6 — The materialization chokepoint does not hold an escrow to the listing's accepted entry

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/alkahest.py:936-952` (pinning and release condition checked; `literal_fields`, the token included, taken from the buyer's proposal).
  - `kit/policy/src/market_policy/scalar_policies.py:866-902` (accepted-set membership and the literal-field check exist only in the guard).
  - Delta `specs/negotiation-protocol/spec.md:36-42` (an escrow naming a contract the listing does not accept "MUST be refused before any seller decision accepts it", with no "where the policy runs" qualifier).
  - `design.md:601-605` (D18's motive: "a deal priced in one token could be escrowed in another").

Bare metal supports a chain without the shape guard; 8.6 tests `["listed_price"]` alone. Its pricing matches the entry by chain and address only. The kit then materializes the plan with the buyer's `token` literal, so a buyer can pay the listing's rate in a different token. A custom VM seller hook bypasses the accepted-set check the same way.

The negotiation-protocol requirement already makes plan materialization the policy-independent chokepoint for the release condition and for pinning. Accepted-set membership and the entry's literal fields are the same kind of check.

**Suggested action:**

- Have `authorize_escrow_proposal` and `materialize_escrow_terms_from_proposal` require the proposal's (chain, contract) to be one of the listing's `accepted_escrows`, and its literal fields to equal that entry's, raising through the `ReleaseConditionError` family.
- Alternatively, qualify the delta and record the guard-omitted exposure as unowned.

### F7 — Alkahest can read as ready on a chain that has no client

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/chain_probe.py:82-90` (a websocket `rpc_url` is probed over HTTP) and `:255-268` (a construction failure is logged; the probe result ignores it).
  - `kit/alkahest/src/market_alkahest/settlement_config.py:459-476` (with an `rpc_url` or a `get_client`, a missing client raises nothing).
  - `domains/vms/storefront/src/market_storefront/settlement_composition.py:868` and `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py:344` (`get_client` always supplied).
  - Delta `specs/settlement-configuration/spec.md:88-91`.

The probe reports `reachable` from the HTTP JSON-RPC calls, whatever happened to client construction. A chain whose HTTP side answers while its websocket construction fails therefore reads as ready. Alkahest options publish, and servicing finds no client.

Conversely, a provider whose websocket path differs from its HTTP path reads as unreachable forever, even though the SDK client works.

The spec requires the storefront to "recover without a restart". Readiness that ignores whether the map holds a client cannot tell recovered from not recovered.

**Suggested action:**

- When the probe holds a constructor, report a chain whose client could not be constructed as `alkahest.chain_unreachable`, a reachability result, even if the HTTP calls answer.
- Document, or make configurable, how a websocket URL maps to its HTTP probe endpoint.

### F8 — Client construction inside the probe has no time limit and can wedge the loop, its pause, and the seed

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/chain_probe.py:257-262` (`asyncio.to_thread(self._build_client, …)` with no timeout).
  - `kit/storefront/src/market_storefront_kit/alkahest_clients.py:61-70` (a websocket client connects at construction).
  - `kit/storefront/src/market_storefront_kit/lifecycle.py:792-803` (a step holds the loop's cycle lock).
  - Delta `specs/settlement-configuration/spec.md:79-85` ("every call bounded by a timeout").
  - `design.md:765-766`.

A websocket endpoint that accepts TCP but never completes the upgrade blocks construction indefinitely, and `step()` gathers every chain. The cycle lock is then held for good:

- timer cycles stop;
- an operator's `run-cycle` hangs;
- a pause never reaches the gate (the loop reports `pausing`), which Section 13's module holds will depend on;
- API credits' `listing-seed` waits forever on a probe that never produces a result.

The only construction test covers a refused port, which fails fast.

**Suggested action:**

- Bound construction with the RPC timeout (`asyncio.wait_for` around the thread) and record `alkahest.chain_unreachable` when it times out.
- Probe each chain independently, so one stuck chain does not hold the others' results.

### F9 — A VM create with supplied escrows and no clauses still publishes the caller's `demands` unchecked

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `domains/vms/storefront/src/market_storefront/services/listing_service.py:428-438` (`demands` taken from the request).
  - `domains/vms/storefront/src/market_storefront/services/listing_service.py:577-585` (derived only when clauses exist).
  - Delta `specs/storefront-publication/spec.md:418-427` (conditions "derived by the Alkahest mechanism … only for Alkahest clauses whose mechanism is ready").
  - `tasks.md:291-298` (recorded for triage).

An operator create on this path advertises whatever release condition it sends. When Alkahest is ready, D19's rules (no oracle, oracle equal to the wallet) are never applied. When Alkahest is unready, `publication_artifacts` drops the escrows but the `demands` still publish.

API credits gates and derives the same path (`release_conditions(..., readiness=)`), so the two domains now differ on one concern without reason.

**Suggested action:**

- Refuse request-supplied `demands`, as `settlement_options` already are (`listing_service.py:373-376`).
- Derive the conditions for supplied escrows under the readiness they were judged on, as API credits does.

### F10 — Status readiness and publication disagree on multi-chain sellers, and one unreachable chain withdraws Alkahest on all of them

- **Lens:** direction
- **Basis:** judgement
- **Severity:** minor
- **Evidence:**
  - `domains/vms/storefront/src/market_storefront/settlement_stages.py:136-148` (all of a candidate's clause chains go into one readiness input).
  - `kit/alkahest/src/market_alkahest/settlement_config.py:301-320` and `:476`.
  - `domains/vms/storefront/src/market_storefront/services/system_service.py:82-92` (status readiness has no clauses, so only the default chain is judged).
  - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/runtime.py:744` (bare metal passes clauses).

Status can say `ready: true` while publication suppresses Alkahest because a clause chain is down. A two-chain seller also loses its options on the healthy chain whenever the other is unreachable. The per-chain `chain_probe` detail satisfies the letter of the spec, but anything reading `ready` or `blockers` is misled. VM and bare metal also judge status differently.

**Suggested action:** Either evaluate status over the publication clauses in every storefront, or document that status `ready` reflects the default chain. Decide whether Alkahest readiness should be per chain.

### F11 — Re-bumping already-bumped, unreleased packages in each section is churn with no policy

- **Lens:** direction
- **Basis:** judgement
- **Severity:** minor
- **Evidence:** `tasks.md:692-698`, `:1157-1161`, `:1408-1410`, and `:1683-1685` (each leaves the policy to triage).

The storefronts were bumped in every section while the kits were not, which is two policies inside one change.

**Suggested action:** Settle one rule — bump once per change, relative to the last release — and record it in `RELEASING.md` or the implement skill.

### F12 — A buyer funds its derivation unchecked when the seller sends no plan

- **Lens:** direction
- **Basis:** judgement
- **Severity:** minor
- **Evidence:**
  - `core/buyer/src/core_buyer/orchestration.py:968` and `kit/alkahest/src/market_alkahest/proposals.py:134` (the check is skipped without a plan).
  - `openspec/specs/negotiation-protocol/spec.md:284` (a seller "MUST NOT accept an Alkahest deal" without its materialized plan).

A conforming seller always sends a plan, so its absence is itself a protocol violation, and the check that catches buyer–seller derivation skew disappears exactly then. No test covers `_settle_one` with no plan.

**Suggested action:** Have the escrow settle hook refuse an Alkahest acceptance that carries no plan (`seller_plan_missing`), and add the unit case.

### F13 — The seed's production "found" path and site resolution are untested

- **Lens:** testing
- **Basis:** judgement
- **Severity:** minor
- **Evidence:**
  - `domains/apicredits/storefront/src/apicredits_storefront/listing_seed.py:160-171` (`_listing_for`) and `:93-104` (`capacity_authority_site`).
  - `domains/apicredits/storefront/tests/unit/test_startup_seed_quota.py` injects `find` and `register` stubs, and the integration test replaces `register_quota`.

`_listing_for` is what stops a restart from creating a duplicate seeded listing, and no test reads a real listing row through it.

**Suggested action:** Add a library- or application-integration case that seeds, restarts the step against the same database, and asserts a single listing and no second registration.

### F14 — `require_deliverable_release_model` is still exported and documented as a startup check the delta now forbids

- **Lens:** documentation
- **Basis:** specification
- **Severity:** minor
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/release_conditions.py:19-26` and `:54-62`.
  - `kit/alkahest/src/market_alkahest/__init__.py:31` and `:62`.
  - Delta `specs/storefront-publication/spec.md:425-427`.

Task 3.4 said the "at startup" wording would hold "until Section 5"; Section 5 landed and the wording stayed. Only tests call the helper.

**Suggested action:** Remove the helper and its export, or at least the module docstring's startup alternative.

### F15 — Section 10's handoff note misstates how a failure mid-stream is handled

- **Lens:** documentation
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `tasks.md:1836-1839`.
  - `provisioning/compute/service/.venv/lib/python3.13/site-packages/starlette/middleware/base.py:139-146` and `:173-198`.
  - `provisioning/compute/service/src/compute_provisioning_service/middleware/auth.py:378-397`.

After `http.response.start`, Starlette stores the route's exception and ends the body stream rather than raising into `call_next`'s caller. The middleware would sign, and the provisioning service would record, a truncated body under the original status; Starlette then re-raises after sending. No streaming route exists today, so there is no current impact.

**Suggested action:** Correct the note. If a streaming route is ever added, check `app_exc` explicitly or refuse streaming responses in these middlewares.

### F16 — The 503 omits Alkahest's chain when a clause relies on the default chain

- **Lens:** consistency
- **Basis:** specification
- **Severity:** minor
- **Evidence:**
  - `domains/apicredits/storefront/src/apicredits_storefront/services/listing_service.py:82-89` (`_clause_chain` returns `None` without `mechanism_input.chain`).
  - `domains/apicredits/storefront/src/apicredits_storefront/services/listing_service.py:261-290` and `:64-69`.
  - Delta `specs/storefront-publication/spec.md:479-484` ("names Alkahest's unreached chain").

**Suggested action:** Resolve a clause's chain through the composition's default chain before naming it, and add the case to `test_alkahest_release_conditions.py`.

### F17 — A VM continuation after an option is repriced is decided against a zero reference

- **Lens:** consistency
- **Basis:** specification
- **Severity:** minor
- **Evidence:**
  - `domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py:242-244` (`selected is None` returns 0).
  - `kit/alkahest/src/market_alkahest/settlement_config.py:668-682` (`option_id` hashes the option's rates).
  - Delta `specs/negotiation-protocol/spec.md:100-101` ("refused before any seller decision accepts it").

VM resolves each continuation against the current listing. A publication cycle that reprices an option in place changes its `option_id`, so the pinned selection matches nothing. The reference becomes 0, and `bisection` can decide "accept"; acceptance then fails `settlement_selection_not_exact` with a 409 instead of a named refusal.

Bare metal avoids this by continuing against the opening's record.

**Suggested action:** Refuse in VM's continuation reference hook when the pinned proposal no longer selects anything, naming the reason. This is part of the direction answer's recommendation.

## Readiness

Round 1 should not advance to round 2 until F1 is fixed. It is a money-losing path on every VM seller's default chain, and it contradicts a requirement this change adds. I traced it by reading; a typed-client test should reproduce it before the fix.

F5–F9 should be resolved in this round's triage, since they bear on claims round 1 makes: settlement fixed at acceptance, policy-independent refusal, and readiness the hold rule can trust. Rounds 2 and 3 build on those claims: decision 20 relies on the probe, and decision 7 on blocker kinds.

F4 must be done before closeout, or the archive will write a wrong requirement into `buyer-orchestration`.

Validation of `da1929a` has not been recorded. Every end-to-end claim in Sections 4–10 is unrun, the VM chart's render-probe edit is unrun, and F2 means the credits lane's pass can't yet be relied on as evidence for the seed. Triage should read this review together with that validation record once it lands.

<!-- reviewer-session: claude:c66b9641-ebc7-4b54-8f87-d5f36fe524fd -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: da1929a6e5acbb5b976cabedd3c8267b4da3aad3 -->
