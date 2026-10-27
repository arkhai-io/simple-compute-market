# Implementation review — unbacked-bare-metal-listings

## Summary

This round is Sections 3–10 of `tasks.md`, design groups B and D: the Alkahest settlement inputs, and the provisioning service's refusal of unserved providers and its signed failures. It has now been through two review-and-triage cycles:

1. **`85-implementation` at `da1929a`**, triaged with `88-validation`, the owner's notes `82` and `91`, and orchestrator observations `73`, `77`, and `83`. The fixes are in `e15a5b2`.
2. **`122-implementation` at `e15a5b2`**, triaged in `122-implementation.triage.md`. The fixes are in `9aa024e`, which is `HEAD`. That triage recorded "Advance".

`131-validation.md` validated `e15a5b2` from the owner's evidence: local, Helm, and all three pipeline lanes passed.

**Base.** I measured against the merge base with `origin/dev`, `968a4a9`. The local `dev` ref is stale, so `git diff dev...HEAD` would include dev's own work. I read:

- the full diff of `9aa024e`;
- the second triage record and `131-validation.md`;
- the current `design.md`, `tasks.md`, the delta specs, and `interventions.jsonl`;
- the code the fixes touch.

I re-checked the earlier rounds' resolutions where `9aa024e` could affect them.

**Checks.** `make check-comment-hygiene` passed. `make check-architecture` was again refused in this session, so it is unrun here. The task notes record `make check-packaging` passing at `9aa024e`.

## Assessment

The second triage closed what remained, and every fix does what its record says.

- **Chain probe (122 F1).** It now keeps at most one client construction in flight per chain, on a daemon thread of its own, and adopts a late result rather than discarding it. That closes both the executor-starvation hazard and the earlier wedge. The new behaviour is covered by two unit cases that fail on the old code, including one that shrinks the default executor to a single worker and shows it still answering.
- **Trusted-oracle scenario (122 F3).** It now proves the kit's oracle-gated release condition against the deployed arbiter, not only the SDK.
- **Documentation fixes (122 F5, F6).** Both are made: D17's resume bullet, and the `negotiation-protocol` delta's attribution of the accepted-entry refusal.
- **Deferred to Section 11, on the owner's word (122 F2, F4).** Both are now precise tasks: 11.9, the shared derivation, and 11.5, VM's started-application probe test. They are not left as notes.

I found no new defect in the revised code.

What remains is about evidence, not code:

- `HEAD` differs from the validated `e15a5b2` in executable code: the probe's construction handling and the trusted-oracle scenario. The scenario's new derivation has never run against a chain.
- `131-validation.md` raised two observations about the validation tooling that no triage has disposed of. One of them contradicts a reason this change records for keeping the trusted-oracle scenario off the Helm step (F1).

## Questions

### direction — If you were implementing this change, what would you have done differently?

For the second-triage changes, nothing material.

- **Construction on a daemon thread.** Choosing a daemon thread per construction over a dedicated executor is sound: the thread count is bounded per chain, and a stuck thread cannot hold up process exit as a pool's worker would.
- **`asyncio.wait` over `asyncio.wait_for`.** This is the right primitive, because the pending construction must survive the probe's timeout (`kit/alkahest/src/market_alkahest/chain_probe.py:295-297`).
- **Adopting late clients only at a probe.** A late client is adopted at the next probe rather than by a done-callback writing the map directly. While a scenario holds the loops, a client finished late therefore waits for the next step. That is consistent with readiness, which reads the probe's result and so keeps the chain unreachable until the same step, so I would not change it.

Deferring 122 F2's shared derivation to Section 11 (task 11.9) is the owner's decision. I agree with the task as written, including retiring `publication_release_conditions` and correcting D19's sentence, which until then still names three callers that do not exist.

### testing — Is the validation strategy sound?

**The 122 F1 fix** is proven at unit level in `kit/alkahest/tests/unit/test_chain_probe.py`:

- five probes over a blocked constructor start exactly one construction, while the loop's default executor, reduced to one worker, still answers (`:360-385`);
- a construction finishing after its probe's wait is adopted by the next probe, which reads the chain reachable (`:388-414`);
- the earlier test, a hung constructor beside a healthy chain, still holds (`:324-357`).

These test the kit's own behaviour against a stub constructor and transport, which is the level `TESTING.md` assigns to it. No storefront test exercises a hung construction, and none is owed: the storefronts compose the same object.

**The 122 F3 fix** is a system test. `e2e-tests/tests/e2e/roles/scenarios/core/test_alkahest_trusted_oracle.py` now builds its condition through `release_conditions` and `encode_authorized_release_condition`, and requests arbitration with the condition's own inner data. I checked that the kit calls it makes match their signatures and exports:

- `market_alkahest` exports `AlkahestSettlementConfig` and `release_conditions`;
- `encode_authorized_release_condition` takes `selected` as optional.

The scenario is unrun at `HEAD`. `131-validation.md` shows the earlier SDK-only version passing at `e15a5b2` (`actions.log` line 13050), not this one. The Section 10 second-triage note says this fix "is proven by the fix commit's validation", but no validation of `9aa024e` exists.

**What `131-validation.md` shows:**

- local passed;
- Helm passed (`contracts` and `e2e_alkahest_escrow_codecs`, 13 tests);
- the pipeline passed in all three lanes (VM 135 passed, bare metal 51, API credits 1 passed and 3 skipped for want of a payments target).

That evidence confirms the fixes of the first round in the lanes:

- `multi_registry`, for 88 V1, passed 21 tests;
- `e2e_credits_deal` passed with its stepped seed (85 F2);
- `e2e_alkahest_trusted_oracle` passed in its first form.

The record's "About the validation" section raises two points that no triage has taken up (F1).

### documentation — Do the code and documentation comply with AGENTS.md, ARCHITECTURE.md, and openspec/README.md?

Yes.

- **Comment hygiene** passes, and the comments `9aa024e` adds describe the current mechanism and why: why `wait` is used, why a daemon thread, why a `BaseException` is turned into an error. None narrates history.
- **D17's resume bullet** now matches the delta and the decision's settled paragraph (`openspec/changes/unbacked-bare-metal-listings/design.md:574-577`).
- **D19's timeout bullet** records the one-construction rule and its rationale.
- **The `settlement-configuration` delta** states the rule with a new scenario, "A client's construction never returns".
- **The `negotiation-protocol` delta** now attributes the accepted-entry refusal to the seller's acceptance (`specs/negotiation-protocol/spec.md:39-44`).
- **The low-level materializer's docstring** says the escrow is not held to an accepted entry there and that a seller authorizes first (`kit/alkahest/src/market_alkahest/alkahest.py:936-941`).

One small point: the delta's long amended sentence in `specs/settlement-configuration/spec.md:88-93` is wrapped unevenly. That is cosmetic, and closeout's archive will carry it as written.

### architecture — Is the code organized by ARCHITECTURE.md's layers?

Yes.

- **The probe change stays inside `kit/alkahest`'s `AlkahestChainProbe`.** No storefront's composition changed. Each still hands the probe its constructor and transport through the seams added in the first triage: `VmCompositionSeams`, `ApiCreditCompositionSeams`, and bare metal's `chain_json_rpc`.
- **Threads.** The kit starts a thread only for the per-chain construction it already owned. The probe's JSON-RPC work stays on the loop's executor, and is bounded per call.
- **The trusted-oracle scenario** imports only `kit/alkahest`'s public surface, as an end-to-end test may.

Nothing else moved between layers in `9aa024e`.

### consistency — Does the implementation do what the design and delta specs say, and only that?

Yes. By earlier finding:

**From `85-implementation`** (resolved in `e15a5b2`, checked in `122-implementation`):

- **F1, F2, F5, F6, F7, F9, F10, F11, F12, F13, F14, F15, F17:** resolved. Nothing in `9aa024e` regresses them.
  - F1's acceptors still judge the pinned opening (`kit/policy/src/market_policy/scalar_policies.py:945-1054`).
  - F7's no-client rule still holds (`kit/alkahest/src/market_alkahest/chain_probe.py:265-274`).
- **F3:** resolved for API credits and bare metal. VM's started-application test is task 11.5, as amended by 122 F4.
- **F4:** resolved, D17 included, by 122 F5.
- **F8:** superseded by 122 F1 and now resolved.
- **F16:** withdrawn on a false premise (`kit/alkahest/src/market_alkahest/settlement_config.py:57`).

**Triaged beside `85-implementation`:**

- **88 V1:** resolved; `multi_registry` passed at `e15a5b2` (`131-validation.md:102`).
- **91 O1:** resolved as decided; the scenario passed at `e15a5b2`.
- **73 R1, R2; 77 R1; 83 R1:** done as disposed.

**From `122-implementation`:**

- **F1 — resolved.**
  - At most one construction per chain (`chain_probe.py:291-294`).
  - It runs on a daemon thread (`:316-354`).
  - A pending construction survives a probe's timeout and is adopted later (`:297-313`).
  - A `BaseException` is delivered as an error, so the chain cannot read "still being constructed" forever (`:343-345`).
  - This matches the amended delta and its new scenario.
- **F2 — deferred by the owner to Section 11, task 11.9.** Not resolved in this round, by decision. Until then D19's sentence on `publication_release_conditions` is inaccurate, as recorded.
- **F3 — resolved in code; unrun at `HEAD`** (see testing).
- **F4 — planned in 11.5,** which now names the seams and the stub switched to answering before the stepped probe.
- **F5 — resolved.**
- **F6 — resolved, by wording.** It matches the code: a buyer's derivation deliberately carries no accepted entries, and every seller acceptance goes through `authorize_escrow_proposal`.

**From `131-validation`:** passed; its two observations are F1 below.

## Findings

### F1 — `131-validation`'s observations on the Helm scenario list are untriaged, and one contradicts this change's recorded reason for leaving the trusted-oracle scenario off Helm

- **Lens:** testing
- **Basis:** evidence
- **Severity:** minor
- **Evidence:**
  - `openspec/changes/unbacked-bare-metal-listings/reviews/131-validation.md:132-135`;
  - `scripts/validate_slice.py:63` (`PIPELINE_MARKER_VARIABLES` omits `E2E_APICREDITS_MODULE`) and `:70` (`HELM_SCENARIOS`);
  - `openspec/changes/unbacked-bare-metal-listings/tasks.md:336-337` and `reviews/91-implementation-owner.triage.md:30` ("Not added to the Helm `e2e` step's selection, whose release may not fund the seller").

`131-validation.md` records two points that `122-implementation.triage.md` does not dispose of, and no `131-validation.triage.md` exists.

1. The validation tooling's `not_run` map omits the API-credit scenarios, so a Helm record can silently under-report what did not run.
2. The `e2e_alkahest_trusted_oracle` exclusion from Helm is a blanket reason. The scenario "needs only the chain and funded development wallets".

The second contradicts the reason this change records for leaving the scenario off the Helm step: that the release "may not fund the seller". Either the Helm release funds the seller's development wallet, in which case the scenario could run there, or it does not, in which case the validation record's premise is wrong. Neither is settled.

These are validation-tooling and evidence questions rather than defects in the change's code. But the change's own task notes rest on one of them, and an untriaged validation observation is a gap the workflow means to close.

**Suggested action:** Triage `131-validation.md`'s two points alongside this review:

- Confirm whether the default Helm release funds the seller wallet the scenario uses. Either add `e2e_alkahest_trusted_oracle` to `HELM_SCENARIOS`, or correct the Section 3 note and the 91 O1 record to the real reason.
- Record the `PIPELINE_MARKER_VARIABLES` omission against the validation tooling, or fix it there.

## Readiness

The round's code is ready to advance to round 2. No finding blocks it, and every finding of `85-implementation` and `122-implementation` is resolved, or, for 122 F2 and F4, planned as owner-approved Section 11 tasks.

`HEAD` (`9aa024e`) has no validation of its own. It differs from the validated `e15a5b2` in executable code: the chain probe's construction handling, covered by unit tests, and the trusted-oracle scenario, whose kit-derived condition has never run against a chain. Before advancing, either:

- validate `9aa024e`, at least the VM lane for `e2e_alkahest_trusted_oracle` and the local suites; or
- record that round 2's validation is the first evidence for these two fixes.

`131-validation.md`'s observations (F1) can be triaged with either.

<!-- reviewer-session: claude:c66b9641-ebc7-4b54-8f87-d5f36fe524fd -->
<!-- reviewer: claude claude-opus-5-5 high -->
<!-- reviewer-unavailable: codex gpt-6-sol: codex is not installed -->
<!-- reviewed-commit: 9aa024e2448b2758f71c23ee65a6021c8562369b -->
