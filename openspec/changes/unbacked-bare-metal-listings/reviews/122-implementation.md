# Implementation review — unbacked-bare-metal-listings

## Summary

This is round 1 of implementation: Sections 3–10 of `tasks.md`, design groups B and D. Between them they cover:

- readiness blockers with a kind, and the `kit/alkahest` chain probe;
- release conditions only for ready clauses, and the API-credit `listing-seed` step with its retryable 503;
- settlement verified against the committed plan, and refusal of an escrow proposal with no contract;
- buyers funding only what they derive;
- the provisioning service refusing pools whose provider no handler serves, and signing failures that happen after authentication.

My earlier review, `85-implementation.md`, read this round at `da1929a`. Since then it has been triaged together with:

- `88-validation.md`, which failed on V1;
- the owner's notes `82` and `91` (O1);
- the orchestrator observations `73`, `77`, and `83`.

The accepted fixes are committed as `e15a5b2` ("round 1 triage fixes"), which is `HEAD`. I read every triage record, the fix commit's whole diff, and the current `design.md`, `tasks.md`, delta specs, and code at `HEAD`.

On the base: the local `dev` ref (`44abb4a`) is behind the `origin/dev` this branch merged, so `git diff dev...HEAD` would also show dev's own work (`repair-helm-render-tests` and others). I therefore measured the change from the merge base `968a4a9`, which `HEAD` shares with `origin/dev`. That range is `968a4a9..e15a5b2`, plus the pre-merge section commits from `d349c8c` on, reviewed in round 85.

I ran `make check-comment-hygiene`, which passed. `make check-architecture` was refused in this session again, so it is unrun here; the task notes record `make check-packaging` passing at `e15a5b2`.

No validation record exists for `e15a5b2`; the only one, `88-validation.md`, validated `da1929a`.

## Assessment

The triage was thorough, and the fix commit does what its records say.

**Earlier findings.**

- The one blocking finding (85 F1, a counter buying a priced option at an unpriced option's amount) is fixed at its root in `kit/policy`. A typed-client VM test reproduced it against the old kit before the fix.
- The materialization chokepoint now holds an escrow to the listing's accepted entry, and bare metal can no longer drop its shape guard (F6).
- VM's operator create derives its own release conditions (F9). That also explains and fixes 88 V1.
- The chain probe now reads unreachable when a chain has no client (F7). Readiness is one rule across all three storefronts (F10), and each storefront has composition seams for the probe (F3).
- Two decisions narrowed the specs rather than the code:
  - F5: the codec lookup through the address book, owner disposition (b).
  - F16: withdrawn, since an Alkahest clause must name its chain (`kit/alkahest/src/market_alkahest/settlement_config.py:57`).
  - Both are sound and recorded.

**What most needs attention.** The fix for 85 F8 bounds how long the probe waits for a client's construction, but not the construction itself. A construction that never returns leaves its worker thread behind, and every later probe starts another. That trades the original single-loop wedge for gradual starvation of the process's default thread pool, which the storefront's database calls share (F1).

**Smaller points.**

- The VM fix re-implements the kit's readiness gate for release conditions instead of reusing it (F2).
- One D17 bullet still describes the superseded resume derivation (F5).
- The exported low-level materializers are not covered by the accepted-entry check the delta attributes to "plan materialization" (F6).
- Two test placements could prove more than they do (F3, F4).

**Validation.** None of the fixes has been validated: the end-to-end evidence for V1, F2, and the new trusted-oracle scenario all waits on the fix commit's pipeline run.

## Questions

### direction — If you were implementing this change, what would you have done differently?

Most of the round's late design calls I would make the same way:

- pricing from the pinned opening, with acceptors judging the opening (F1's fix);
- the listing, not a policy, deciding what can settle (D18's new principle);
- the codec limit recorded beside D19's rather than a new plan field;
- readiness with no publication input judging every configured chain;
- the once-per-change bump rule (`docs/development/RELEASING.md`).

I would have done two things differently.

**Bounding construction.** I would bound the construction, not only the wait, and keep at most one construction in flight per chain. See F1.

**Release-condition derivation.** The triage made the derivation domain-neutral ("derive for every published escrow under the readiness it was judged on"), but placed it in VM's `publication_terms`. Three domains now derive release conditions three ways:

- bare metal through `kit/alkahest`'s `publication_release_conditions`;
- VM through its own readiness check and `release_conditions`;
- API credits through its composition's `release_conditions` and `alkahest_ready`.

The concern is one, and the design is about to promote "one behaviour for one concern across domains" to `ARCHITECTURE.md`. A kit function over published escrows would serve all three (F2).

### testing — Is the validation strategy sound?

The test levels, by fix:

- **85 F1:** kit unit (`kit/policy/tests/unit/test_selection_scalar.py`). Application integration through `StorefrontClient` and `NegotiationRuntime` (`domains/vms/storefront/tests/integration/test_negotiate_controller.py:739`, `TestCounterNamingAnotherOption`), including the `pinned_option_withdrawn` continuation (`:818`). This closes the gap I noted about `TestRoundReference`.
- **85 F6:** kit unit (`test_release_authorization.py`), and bare-metal application integration through the typed client (`test_http_negotiation.py`) with only `listed_price` configured.
- **85 F9:** VM application integration through the typed client (`test_listings_api.py`, `TestCreateListingReleaseConditions`).
- **85 F7, F8, F10:**
  - kit unit (`test_chain_probe.py`, `test_settlement_config.py`);
  - API credits: application integration of the started application through `StorefrontClient`, over `ApiCreditCompositionSeams`, with the module patches gone;
  - bare metal: composition level, through the configured runtime's registered loop;
  - VM: unit at the composition boundary (`test_alkahest_chain_probe_composition.py`), not the started application (F4).
- **85 F12, F13:** core and kit unit, and API-credit application integration (a restarted seed finds its listing).
- **85 F2:** the credits scenario now steps `alkahest-chain-probe` and `listing-seed` through the storefront's administrator typed client before discovering (`e2e-tests/tests/e2e/roles/scenarios/apicredits/test_credits_deal_buyer_cli.py:150-163`). That is the explicit-step discipline in `TESTING.md`.
  - Its fixture's credential is the committed Anvil 3 development key, with the required public-fixture comment (`e2e-tests/config/config-docker.yml:74-82`).
  - Publication is synchronous inside the create (`domains/apicredits/storefront/src/apicredits_storefront/services/listing_service.py:373-381`), so a `done` seed is discoverable.
- **91 O1:** the two chain-spawning SDK tests moved to the system tier as `e2e_alkahest_trusted_oracle`. It tests no repository code (F3).

The hung-construction kit test runs one step only (`kit/alkahest/tests/unit/test_chain_probe.py:323-354`), so it cannot show what repeated steps do (F1).

What validation shows: the local and Helm parts passed at `da1929a`. The pipeline failed on 88 V1, which the fix commit addresses but no run has yet confirmed. Unrun so far: `multi_registry`, `e2e_credits_deal` with the new fixture, and `e2e_alkahest_trusted_oracle`. The Helm render probe edit is again unrun here.

Findings: F1 (test half), F3, F4.

### documentation — Does the code and documentation comply with AGENTS.md, ARCHITECTURE.md, and openspec/README.md?

**Comments and permanent docs.** Comment hygiene passes. I also scanned the fix commit's added lines for review numbers, "round", and history narration; the only hits describe current behaviour. The permanent documents the fix touches describe current state:

- `docs/development/RELEASING.md`;
- `docs/agents/change-workflow.md`;
- the probe and verification module docstrings.

**Delta specs.** These were amended to what was built:

- `buyer-orchestration` (the resume sentence and `seller_plan_missing`);
- `negotiation-protocol` (the guard runs in every domain, the token scenario, the unpriced counter, `pinned_option_withdrawn`);
- `settlement-configuration` (a client is needed, every configured chain);
- `settlement-servicing` (narrowed to the codec limit);
- `storefront-publication` (supplied escrows, refused `demands`).

Closeout tasks 23.5 and 23.9 name the new promotions: the Goal 4 unowned row, and the `ws`→`http` sentence.

**Design.** D17 still carries the superseded resume bullet beside the paragraph that replaced it (F5).

**Delta wording.** The `negotiation-protocol` delta attributes the accepted-entry refusal to "plan materialization" generally, while only the authorizing entry enforces it (F6).

### architecture — Is the code organized by ARCHITECTURE.md's layers?

Yes, for the fixes as for the round.

- **`kit/policy`.** The F1 fix keeps the acceptors domain-neutral: they read `pinned_proposal(history)`.
- **`kit/alkahest`.** `require_accepted_escrow` sits in `release_authorization.py` beside `require_pinned_escrow`, and `authorize_escrow_proposal` runs it (`kit/alkahest/src/market_alkahest/proposals.py:167`). So the policy-independent check lives in the mechanism kit, as D18 says.
- **`kit/storefront`.** Its client construction only gains an injectable `constructor=` (`kit/storefront/src/market_storefront_kit/alkahest_clients.py:99-113`); it acquires no probe behaviour.
- **Composition roots.** Each owns its seams: `VmCompositionSeams`, `ApiCreditCompositionSeams`, and bare metal's `chain_json_rpc`. That is the injection pattern `TESTING.md` asks for.
- **`core/buyer`.** It gains only a protocol refusal (`seller_plan_missing`) and still names no Alkahest concept.
- **Bare metal.** Its required guards are composition data (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation.py:39-61`).

F2 is the one placement point: a domain-neutral rule implemented in a domain.

### consistency — Does the implementation do what the design and delta specs say, and only that?

Mostly. For each earlier finding:

- **85 F1 — resolved.** `accept_unpriced_selection` judges and accepts the opening (`kit/policy/src/market_policy/scalar_policies.py:945-978`). `accept_exact_listing` settles the opening's option (`:1010-1054`). No other default decider takes its option from the counter.
- **85 F2 — resolved in code; end-to-end unrun.** Task 6.6 is corrected.
- **85 F3 — resolved for API credits and bare metal; partly for VM, as recorded.** The residue is F4.
- **85 F4 — mostly resolved.** The delta and D17's plan-check bullet are corrected and D18's rationale is rewritten, but D17's resume bullet is not (F5).
- **85 F5 — resolved by decision.** The `settlement-servicing` delta now promises only what verification can honour, D16 and D19 record the limit, and D18 records the cutover for deals accepted unpinned.
- **85 F6 — resolved at the seller's acceptance path.**
  - Every production acceptance goes through `accepted_escrow_artifacts_from_proposal` → `authorized_escrow_proposal_at_amount` → `authorize_escrow_proposal` (`kit/alkahest/src/market_alkahest/proposals.py:350`, `:398`). Bare metal's plan builder calls it directly (`domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/negotiation_runtime.py:317`).
  - Bare metal prepends `escrow_shape_guard`.
  - The residue is F6.
- **85 F7 — resolved.** A chain without a client reads unreachable (`kit/alkahest/src/market_alkahest/chain_probe.py:260-269`).
- **85 F8 — the wait is bounded; the thread is not.** See F1.
- **85 F9 — resolved.** A VM create refuses supplied `demands` and derives them for every published escrow (`domains/vms/storefront/src/market_storefront/services/listing_service.py:429-433`, `:576-584`).
- **85 F10 — resolved.** `_selected_chain_names` judges every configured chain with no publication input (`kit/alkahest/src/market_alkahest/settlement_config.py:301-328`), and each status asks that way, bare metal's with `clauses=()`. For a multi-chain buyer, readiness improves: it previously read `alkahest.chain_missing` with no default chain.
- **85 F11 — resolved.** `docs/development/RELEASING.md` now states the rule.
- **85 F12 — resolved** in both funding paths: `core/buyer/src/core_buyer/orchestration.py:910-924`, and `kit/alkahest/src/market_alkahest/proposals.py:132-136`.
- **85 F13 — resolved** (paging, and the restart test).
- **85 F14 — resolved.** Neither removed function has a remaining reference outside a historical attachment.
- **85 F15 — resolved** (the Section 10 note is rewritten).
- **85 F16 — withdrawn correctly.** Its premise was false (`settlement_config.py:57`, a required `chain`).
- **85 F17 — resolved.** VM refuses `pinned_option_withdrawn` before any policy (`domains/vms/negotiation/src/arkhai_vms_negotiation/storefront_round.py:287-311`), and the unification is recorded for the roadmap.
- **88 V1 — addressed by F9's derivation; unverified** until the fix commit is validated.
- **91 O1 — resolved as decided (a).** The CI deselects are removed (`.github/workflows/tests.yml:69`). See F3 for what the new scenario proves.
- **73 R1, R2; 77 R1; 83 R1 — done as disposed.** These are workflow-tooling edits (`scripts/change_workflow/wrapper.py`, `scripts/round_view.py`, `docs/agents/change-workflow.md`), outside this change's design but placed in this commit on the owner's word. I read `round_view.py`'s `read-tree` fix; I did not review the others in depth.

New in the revision: F1, F2, and F6.

## Findings

### F1 — Bounded client construction leaks a worker thread at every probe and can starve the storefront's default thread pool

- **Lens:** consistency
- **Basis:** specification
- **Severity:** should
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/chain_probe.py:271-297` (`asyncio.wait_for(asyncio.to_thread(self._build_client, …), timeout=…)`, rerun at every step while the chain is missing from the map);
  - `kit/alkahest/src/market_alkahest/chain_probe.py:263` (the probe's own work also runs through `asyncio.to_thread`);
  - `core/storefront/src/core_storefront/sqlite_client.py`: 64 `asyncio.to_thread` call sites on the same default executor;
  - `kit/alkahest/tests/unit/test_chain_probe.py:323-354` (one step only);
  - delta `specs/settlement-configuration/spec.md:88-90` ("each construction bounded by the same timeout").

`wait_for` cancels the await, but a thread running the constructor cannot be stopped. A construction that never returns therefore keeps its thread, as the fix's own docstring acknowledges. That is the premise 85 F8 was accepted on: a websocket endpoint that accepts and never upgrades.

The chain is still absent from the map, so the next step, one probe interval later, starts another construction on another thread. The default executor holds `min(32, cpu_count + 4)` threads; in a two-CPU pod that is 6, used up in about three minutes at the default 30-second interval. Once it is full:

- the probe's own `to_thread(self._probe_sync)` queues behind the stuck threads, so the step and its loop's cycle lock hang again;
- every database call the storefront makes through `asyncio.to_thread` queues too.

The original defect wedged one loop. This one, after a few intervals, wedges the process.

**Suggested action:**

- Keep at most one construction in flight per chain. Hold the pending future and, while it is unfinished, skip building again and record `alkahest.chain_unreachable`. Adopt its result if it ever completes.
- Run constructions on a small dedicated executor rather than the loop's default one.
- Add a kit unit case that steps a probe with a never-returning constructor several times and asserts that a single construction is in flight and that other `to_thread` work still completes.

### F2 — Release conditions under readiness are derived three ways in three domains

- **Lens:** direction
- **Basis:** judgement
- **Severity:** minor
- **Evidence:**
  - `domains/vms/storefront/src/market_storefront/services/publication_terms.py:311-339` (VM's own readiness gate around `release_conditions`);
  - `domains/apicredits/storefront/src/apicredits_storefront/settlement_composition.py:165-196` and `:289-294`;
  - `domains/bare_metal/storefront/src/arkhai_bare_metal_storefront/settlement_composition.py:285` (the kit's `publication_release_conditions`);
  - `kit/alkahest/src/market_alkahest/release_conditions.py:133-164`;
  - `design.md` "Permanent documentation", the `ARCHITECTURE.md` promotion of "one behaviour for one concern across domains".

The triage made VM's rule domain-neutral: derive for every published escrow, whether compiled or supplied, under the readiness it was judged on. But the rule was written into VM, beside API credits' equivalent and bare metal's use of the kit's clause-based form. A fourth reader, such as a release model with chain-specific conditions, would have three places to change.

**Suggested action:** Add a `kit/alkahest` function deriving release conditions for published escrows under their readiness, have VM, API credits, and bare metal call it, and retire `publication_release_conditions` or define it in terms of the new function.

### F3 — The new trusted-oracle scenario tests only the SDK, not this repository's encoding of the condition

- **Lens:** testing
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `e2e-tests/tests/e2e/roles/scenarios/core/test_alkahest_trusted_oracle.py:64-91` (the demand is built with the SDK's `TrustedOracleArbiterDemandData` and the address book's arbiter);
  - `docs/development/TESTING.md`, "System Integration Tests (End-to-End)" (system tests "cover only the cross-service contract").

The scenario replaces tests the owner rightly moved out of the storefront's integration tier (91 O1). But as written it exercises no repository code: escrow creation, arbitration, and collection all go through `alkahest_py` directly. What the repository owns, and what a real arbiter would catch if it were wrong, is how `kit/alkahest` encodes the oracle-gated condition that a listing advertises and a plan carries.

**Suggested action:** Build the scenario's arbiter and demand through `kit/alkahest`'s release-condition derivation and encoding for an oracle-gated section, so the system tier proves the repository's encoding against the deployed arbiter. Otherwise, record in the scenario's docstring that it pins SDK behaviour the kit depends on.

### F4 — VM's chain-probe wiring is still proven only at the composition boundary

- **Lens:** testing
- **Basis:** guidance
- **Severity:** minor
- **Evidence:**
  - `domains/vms/storefront/tests/unit/test_alkahest_chain_probe_composition.py`;
  - `tasks.md` Section 4's round-1 note ("VM has no harness starting its whole application with seams");
  - `domains/vms/storefront/tests/integration/test_publishable_startup.py:161-191` (the started VM app stops at the provisioning and site steps);
  - `docs/development/TESTING.md`, "Integration Tests".

The triage recorded the shortfall and its reason. That reason goes away in round 2: Section 11 removes the VM storefront's provisioning preflight, after which the real application can start with its dependencies unreachable.

**Suggested action:** In Section 11, add the VM application-integration case the triage agreed: the started app over `VmCompositionSeams` with a stub JSON-RPC, stepped through `StorefrontClient`, with status read back. Name it in Section 11's tasks so it isn't lost.

### F5 — D17 still says a resumed run derives from the Agreement's selected option

- **Lens:** documentation
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `openspec/changes/unbacked-bare-metal-listings/design.md:574-577`, contradicted by `design.md:602-607` and the amended delta `specs/buyer-orchestration/spec.md:11-16`.

85 F4's fix rewrote D17's plan-check bullet and the delta, but left the next bullet, which still prescribes the superseded derivation. Closeout promotes the `buyer-orchestration` companion from this decision (23.9), so it could carry over.

**Suggested action:** Rewrite the bullet: a resumed run derives the escrow from its recorded accepted proposal and recorded conditions, at the Agreement's exact amount, and holds it to the recorded seller plan.

### F6 — The exported low-level materializers don't hold an escrow to the listing's accepted entry, though the delta credits "plan materialization" with it

- **Lens:** consistency
- **Basis:** specification
- **Severity:** minor
- **Evidence:**
  - `kit/alkahest/src/market_alkahest/alkahest.py:908-996` (`materialize_escrow_terms_from_proposal`: pinning and the release condition only);
  - `kit/alkahest/src/market_alkahest/plans.py:250` and `:423`;
  - `kit/alkahest/src/market_alkahest/alkahest.py:999`;
  - `kit/alkahest/src/market_alkahest/proposals.py:148-167` (`authorize_escrow_proposal` is the only caller of `require_accepted_escrow`);
  - delta `specs/negotiation-protocol/spec.md:39-43`.

Every production acceptance runs through `authorize_escrow_proposal`, so no deal is exposed today. But the package still exports four materializers that build a plan without that check:

- `materialize_escrow_terms_from_proposal`;
- `materialize_escrow_terms_payload_from_proposal`;
- `materialize_settlement_plan_from_proposal`;
- `settlement_plan_payload_from_proposal`.

The delta says the refusal is made "independently of any seller policy, by plan materialization". Pinning and the release condition are enforced in every materializer; accepted-entry membership is enforced only at the authorizing entry. The buyer's resume derivation deliberately uses the low-level form with a listing record carrying only release conditions.

**Suggested action:** Either word the delta and D18 to name `authorize_escrow_proposal` as the seller's chokepoint, or mark the low-level materializers as buyer- and kit-internal: drop them from the package's exports and document that a seller acceptance goes through the authorizing entry.

## Readiness

The revision resolves every finding of the earlier review except 85 F8. There the fix bounds the wait but leaves a resource leak that can exhaust the process's thread pool (F1). It should be fixed in this round, since round 2's degraded start (decision 20) relies on the probe recovering from a dead chain without harm.

The other findings are minor and can be taken now or at closeout. F4 belongs in Section 11's tasks.

The fix commit `e15a5b2` has no validation record. Before this round advances, it needs a validation run that includes:

- the VM lane, with `multi_registry` for 88 V1 and the new `e2e_alkahest_trusted_oracle`;
- the credits lane with the stepped seed (85 F2);
- the Helm render, for the twice-unrun render-probe edit.

Once F1 is fixed and that validation passes, the round is ready to advance to round 2.

<!-- reviewer-session: claude:c66b9641-ebc7-4b54-8f87-d5f36fe524fd -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: e15a5b23e1db0889947ff6740e051aa5df8a59e6 -->
