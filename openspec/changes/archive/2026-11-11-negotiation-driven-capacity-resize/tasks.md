## 0. Round-0 resource-shape mismatch guard (implemented, 2026-07-29)

Direct consequence of the Section 2 resolution on item 1 (round-0 shape
negotiation deferred, but silent mismatch is worse than loud rejection).

- [x] 0.1 Add `_reject_unsupported_resource_shape_request` to `sync_negotiation.py`: compares `provision_terms.compute_resource` against the listing's own shape across `arkhai_vms.DIMENSION_KEYS`; raises `OfferUnfulfillableError` on any disagreement.
- [x] 0.2 Wire the guard into `start_sync_negotiation`, after listing load/status check, before any seller policy runs.
- [x] 0.3 Update `start_sync_negotiation`'s docstring (was stale: "eventually compute spec") and `_place_capacity_hold`'s docstring (documents the intentional block per repository-owner direction on item 5/7) to describe current, real behavior.
- [x] 0.4 Add regression tests: mismatched shape rejected before seller policy runs; matching shape proceeds normally.
- [x] 0.5 Run the full test file plus three adjacent negotiation unit-test files; confirm no regressions (74 tests total).

## 1. Guard against silent shape-change loss on negotiation continuation -- REVERTED

**Reverted in full, repository-owner direction, 2026-07-29.** Preserved
here per `AGENTS.md`'s "preserve completed tasks; amend rather than
replace implementation history," not because any of it remains active.

- [x] 1.1 Confirm, by inspection, that `NegotiateContinueRequest`/`AdvanceRequest` use Pydantic's default (silent-drop) `extra` handling.
- [x] 1.2 ~~Set `model_config = {"extra": "forbid"}` on both models~~ -- reverted.
- [x] 1.3 ~~Add regression tests~~ -- reverted; test file deleted (tombstone: `core/storefront/tests/unit/test_negotiation_models_extra_fields.py`).
- [x] 1.4 Confirm no production or test call site constructs either model with fields beyond its declared set (still true; not itself reverted, just no longer load-bearing for anything).
- [x] 1.5 ~~Run `core/storefront/tests/unit/test_negotiation_sync.py` alongside the new tests~~ -- moot, reverted.
- [x] 1.6 Correction (repository-owner review, 2026-07-29): fixed the overclaiming docstrings/design record -- the guard protects top-level fields only, not content nested inside `proposal`; a future revised-terms field is a child of `proposal`, typed as the existing `ProvisionTerms` opaque envelope, never new core-level vocabulary. **This correction's substance (placement + core-vocabulary reasoning) remains valid and is retained in `design.md` for Section 2 planning even though the code it corrected is gone.**
- [x] 1.7 Full revert (repository-owner direction, 2026-07-29): `model_config = {"extra": "forbid"}` removed from both models; both restored to their pre-Section-1 form; regression test file deleted. `core_storefront` is unchanged from before this change opened.

## 2. Negotiate the capacity shape

Depends on `capacity-shape-pricing` and, for task 2.4's quantitative check,
`capacity-shape-envelope`. Section 2b is the
deployment boundary.

### 2a. The revised-terms field

- [x] 2.1 Re-verify `design.md`'s Context against the tree: the hook
      names in `NegotiationDomainHooks`, that continue/advance carry a typed
      `proposal`, that `hold_ttl_seconds` still defaults to 0, and that
      `build_vm_accepted_artifacts` still derives the order from the listing record.
- [x] 2.1a **Decision gate resolved: D-a through D-d, webapp owner 2026-11-06, pending maintainer review.** Registry listing-level `rate_structure`, verified by the retained seller proof; depends on `store-registry-listings-as-published`.
      Original gate: Decide where a buyer reads a listing's rate structure,
      and with what authority, per `design.md`'s "Where a buyer reads the rate
      structure is a decision gate", taking `store-registry-listings-as-published`'s
      accepted carrier policy as an input, and record the decision and reasoning in
      `design.md`. If the decision needs the registry to keep a listing-level field,
      record the dependency on that change here and in the campaign index before
      any task relying on it starts.
- [x] 2.2 Add the revised-shape field as a child of `proposal`, typed as the existing
      `ProvisionTerms` envelope, to the continue/advance request models. The
      envelope stays opaque to core; the VM codec decodes its payload as a
      family-grouped capability shape validated by `VM_CAPABILITY_SCHEMA`.
- [x] 2.3 Widen `kit/negotiation-runtime`'s `validate_continuation` contract so a
      domain sees the decoded revised shape, and carry the shape on `RoundRequest`
      and `RoundEvaluation` so `evaluate_round` and `agreement_terms` receive what
      the round proposed and what was agreed.
- [x] 2.4 Compose the VM `evaluate_round` in `design.md`'s order — admissibility,
      authoritative feasibility, commercial feasibility, pricing — with a distinct
      refusal reason for each, and a stated "not checked" for a check the domain
      does not compose. Implement the commercial feasibility guard here: a
      requested shape's categorical commitments (GPU model, region) checked by
      equality against the listing's, declining without a quote; the quantitative
      check is the envelope's predicate. Tests: a categorical mismatch declines
      without pricing; a shape outside the envelope declines before the guard runs.
      Promote "Seller feasibility precedes pricing" with this change's spec delta.
- [x] 2.5 Retire `_validate_vm_opening`'s shape-mismatch refusal: a round-0 shape
      differing from the listing is evaluated by the same composition rather than
      rejected. Delete the Section 0 regression tests that assert the refusal.
- [x] 2.6 Focused tests (existing suites plus the replayable fixture encounter;
      no new permanent acceptance tests): a revised shape is decoded and validated; an unreadable
      shape is refused at the boundary; each refusal reason surfaces distinctly; a
      round without a revised shape is evaluated against the previously agreed
      shape.

- [x] 2.6a Pin the seller-authenticated rate-structure digest at opening; refuse a
      later round or acceptance as `rate_structure_changed_reopen` on change
      (D-e). Focused test: shifted family rates preserve the listing total but
      change a revised shape's price; continuation and acceptance are refused.

### 2b. The multiplier

- [x] 2.7 Reinterpret the negotiated reference quantity as a multiplier in basis
      points over the advertised minimum rate structure, through the
      `reference_amount`, `amount_from_proposal`, and `proposal_from_amount` hooks.
      Every intermediate value is an exact integer or `Decimal`; the quote rounds up;
      a quote exceeding the asset's amount type is refused.
- [x] 2.8 Audit every consumer that assumed the negotiated scalar was an amount in
      an asset's base units — the escrow and hosted obligation construction paths
      first, since a missed consumer surfaces as a wrong on-chain amount. This is an
      audit, not a rename.
- [x] 2.9 Express the seller's floor once as a multiplier bound (default 10,000)
      and confirm it applies to a shape never explicitly priced; a policy may lower
      it explicitly.
- [x] 2.10 Confirm `bisection_middleware` converges unchanged on the reinterpreted
      quantity, and that a shape change between rounds does not re-anchor bounds.
- [x] 2.11 Focused tests: concession comparability across a shape change; floor
      applied to an unanticipated shape; agreed terms yield one derivable price;
      a base-unit amount above 2^63 survives a full round trip through persistence
      and the hooks unchanged.

### 2c. The agreed shape reaches the claim

- [x] 2.12 Write the agreed shape into the settlement order's `listing_resource`
      quantities in `build_vm_accepted_artifacts`, so
      `compute_capacity_claim_from_order` reserves what was agreed. Confirm
      `vm_fulfillment_planner` and `encode_compute_lease` need no change.
- [x] 2.13 Rewrite `_place_capacity_hold`'s claim to come from the acceptance's
      agreed order rather than `listing_record`, so a non-zero `hold_ttl_seconds`
      deployment holds the agreed shape. No resize is placed here; record that
      `negotiation-time-capacity-hold` owns `resize_reservation`'s first call.
- [x] 2.14 Focused tests: a negotiation agreeing a shape smaller than the listing's
      reserves the smaller shape; the committed reservation's dimensions match the
      agreed shape; the fulfillment request derives from the reservation.
- [x] 2.15 **Amended by the round-1 triage (owner record R13):** no buyer command
      could request a shape, so the run below could not have been made as written.
      Add a round-0 shape option to the VM buyer's `buy` and `negotiate` commands,
      filling `compute_resource` within the advertised cap (D10), and a stage in
      `e2e-tests/tests/e2e/roles/scenarios/vms/test_listing_shapes.py` after 07a that
      buys a smaller shape and asserts the reservation's dimensions and create-job
      sizing equal it, reusing 05a/05b's helpers. Validation's pipeline (the CI
      runner with Docker) and Helm parts observe it; the local Podman Compose
      include-path failure below stays out of scope.
      **Unobservable after a genuine VM-lane attempt; owner-authorized disposition.**
      One e2e run with a shape agreed below the listing's, asserting the VM
      built has the agreed shape. Fresh rebased images built with Podman 5.7.0 and
      the explicit native Compose 1.6.0 provider, but startup failed before readiness
      because included registry environment-file paths resolved against the wrong
      directory. No deployed assertion ran. Exact command, failure and cleanup:
      `docs/attachments/resize-shape-pricing/final-validation.md`.
      Treat this as the deployment boundary: incompatible in-flight negotiations
      must drain before upgrading or rolling back.
      **Observed:** validation 21's pipeline run 43090303156 at `77cee0783` passed
      stages 07a2–07a4 in the VM lane: `market buy --shape` reached ready, and the
      site's reservation and the create job held exactly the agreed smaller shape.
      Observed again, with stage 08b, by validation 33's run 43106684835 at
      `a414cdd98`.
- [x] 2.16 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

### Section 2 outcome

Compressed at closeout from the slice plans, checkpoints, handoffs and fix-round
notes. Final behaviour is D1–D17 in `design.md`; what the implementation rounds found
that is worth keeping is in its "Findings during implementation"; each review's
findings and dispositions are in its triage record under `reviews/`.

Where it lives:

- **Revised terms.** `proposal.provision_terms` on `core_storefront`'s continue and
  advance models; `NegotiationDomainHooks.decode_revised_terms`,
  `RoundRequest.revised_terms` and `RoundEvaluation.agreed_terms` in
  `kit/negotiation-runtime`; each message's effective terms recorded by core migration
  `20261106_001_negotiation_message_terms`. Bare-metal and API-credit adapters take the
  wider hook and refuse a revision.
- **Multiplier.** `arkhai_vms_negotiation.amounts` (the ratio rule, the exact quote,
  `rate_structure_digest`) and `storefront_round`; `negotiation.multiplier_floor_bps`,
  refused above 10,000 at VM composition; `kit/policy` exports `amount_from_proposal`
  and `set_proposal_amount`; the core buyer's `NegotiationAmountCodec`, the VM buyer's
  in `arkhai_vms_buyer.negotiation_amounts`; `--shape` on `market buy` and
  `market negotiate` (`opening_shape.py`). Flat-priced and hidden-reserve paths, and
  `core/tests/unit/test_rate_helpers.py`'s truncation, are unchanged.
- **Evaluation.** `services/negotiation_shapes.py` and the VM `negotiation_runtime.py`:
  `shape_policy_unavailable`, `shape_inadmissible`, `shape_exceeds_advertised`,
  `shape_commercially_infeasible`, `shape_price_unavailable`, `shape_price_overflow`.
- **Pin.** `publications.published_payload_json` (core migration
  `20261111_001_publication_published_payload`), `load_published_payloads`, and the
  runtime's `_as_last_published`: `rate_structure_changed_reopen`,
  `rate_structure_unpublished`, `rate_structure_divergent`.
- **Rename.** `negotiation_threads.negotiated_scalar` (core migration
  `20261111_002_negotiation_negotiated_scalar`), through the storefront wire,
  `storefront_client.models`, the kit's `Acceptance` and every domain consumer.
- **Agreed shape.** `agreed_vm_order` and `settlement_vm_order` in
  `services/vm_job_spec_service.py`, read by the acceptance hold, escrow and hosted
  settlement, and the administrator's settlement preview; the planner and
  `encode_compute_lease` are unchanged.
- **Outside the plan, accepted by the owner.** The `dev-env` image installs nothing
  and its probes call `cast block-number` (06 O2); API-credit wheel installs pass
  `--refresh` (07 V1); the e2e scenarios' `_pool_actions` filter (21 V1).

Evidence (levels as `TESTING.md` defines them):

- Validation 33 at `a414cdd98`, passed: local (`make check-packaging`, `make test`),
  Helm, and pipeline run 43106684835 (see 3.8).
- Validation 21's run 43090303156 at `77cee0783`: the deployed smaller-shape purchase,
  stages 07a2–07a4.
- Last `scripts/change-workflow run pre-commit` before the closeout: passed at
  `58491f7c1` with the pre-closeout fix staged, VM storefront unit 1180 passed and 1
  skipped, integration 575 passed, every change check passed.
- Regressions: `domains/vms/storefront/tests/integration/test_vm_multiplier.py` (a
  smaller agreed shape reserved through real SQLite, the signed site API and the
  real ledger, held and fresh-reserve paths; a payment above 2^63 through
  persistence), `test_revised_shape_client.py` (the typed client against the served
  app), `tests/unit/test_sync_negotiation_seller_round_hook.py` (refusal order, the
  pin, divergence and the partial first refresh), `test_vm_multiplier.py`,
  `test_vm_revised_terms.py`, `test_admin_settle_service.py`; core storefront
  `test_published_payloads.py` and `test_negotiated_scalar.py`; VM buyer
  `test_negotiation_amounts.py`, `test_opening_shape.py`,
  `test_shape_negotiation_cli.py`; `kit/negotiation-runtime`'s `test_runtime.py`.
- Reproducible first use: `docs/attachments/resize-shape-pricing/index.md` and
  `first_use.py`; `final-validation.md` records the local compose attempt.
- Not claimed: a typing gate (the VM storefront's `mypy src` matched `dev`'s error
  count at the rebase, `docs/attachments/goal8-stack/resize.md`); `first_use.py` was
  not rerun after its last update (running it was refused in the triage sessions).

Deferred, each with its owner:

- `resize_reservation`'s first call — `negotiation-time-capacity-hold`.
- Negotiating a shape larger than the advertised one — `negotiation-capacity-feasibility-probe`.
- Round 0 adopting the family-grouped form — `settle-capacity-claim-vocabulary`.
- The buyer's verifier of the seller's retained publication proof —
  `negotiate-open-ended-compute-terms`.
- Unowned, in `openspec/changes/README.md` ("Unowned work found by
  `negotiation-driven-capacity-resize`"): the settlement-option repricing lag; a
  buyer-named publication digest; process guidance on when a misleading name is fixed.

## 3. Closeout

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement. The parts are recorded here so each carries an explicit disposition rather than an assumed one; confirm and tick each rather than treating the change as closed.

- [x] 3.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
      *Closeout:* `make check-comment-hygiene` passed (no change-ID, task-number or
      change-name references). Every comment and docstring line the change added to
      source, TOML and YAML (`git diff origin/dev...HEAD`) was read: each states a
      current invariant (the scalar is not money, the advertised-shape cap standing in
      for the probe, exit never refused, a revision not echoed on acceptance); none
      names a review or migration.
- [x] 3.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
      *Closeout:* the change's Python diff adds no indented import; every added import
      is at module level.
- [x] 3.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. Every material decision in `design.md` has a
      permanent destination or an explicit temporary, superseded, or rejected
      classification, and no production source references
      `openspec/changes/negotiation-driven-capacity-resize`.
      *Closeout:* the promotion record left D2's rationale and D17 in `design.md` and
      D12 there alone; durable rationale belongs in the capability companion, so D2–D4,
      D9's trade-off, D10's order, D17 and the current limits go to
      `negotiation-protocol/architecture.md` and D12 to `ARCHITECTURE.md`'s "Capacity
      reservation". Stale permanent prose found against the code and corrected:
      `ARCHITECTURE.md` (a revised shape "priced from" the listing record;
      `resize_reservation` described as unimplemented intent), `ROADMAP.md` Goal 2
      (round-zero rejection, no shape in a round), and `storefront-publication`'s
      companion (pricing from the listing record). No production source references the
      change; only `docs/attachments` evidence, which the hygiene rule exempts, names it.
- [x] 3.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
      *Closeout:* the slice plans, checkpoints, handoffs and four fix-round notes in
      Section 2 are replaced by "Section 2 outcome". Moved first to `design.md`'s new
      "Findings during implementation": the scalar consumers found by driving the
      buyer, the registry record mistaken for a storefront listing, the stale wheel
      cache, the release guard keeping delivered reservations, the partial first
      refresh, and the local compose failure. Dropped as duplication: command
      transcripts, corrected test invocations, per-checkpoint counts superseded by
      later runs. Task texts and their amendments are unchanged.
- [x] 3.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: the “Negotiate full compute capability, not GPU count alone” goal's
      current-state description and gap-to-change mapping change, and the
      design-promotion record names that update.
      *Closeout:* Goal 2's current state describes shape negotiation, the multiplier,
      the evaluation order, the published-rate pin and the agreed shape reaching the
      reservation; this change's gap row is removed; the feasibility probe's row now
      names the larger-shape limit; the two unowned gaps (option repricing lag,
      buyer-named digest) are added. Goal 5 is unchanged: its hold gaps stand. Named in
      the promotion record.
- [x] 3.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
      *Closeout:* the row is `in closeout` with its Notes rewritten for the landed
      state, and after the archive links the archived directory. Both campaign graphs
      (Goal 2's and Goal 5's) are unchanged: their edges still hold until archive
      cleanup. Other rows untouched; `scripts/change-workflow check index` passed.
- [x] 3.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
      *Closeout:* `scripts/change-workflow run pre-archive` passed at `a414cdd98`:
      `make check-packaging` (wheelhouse, locks, Python selection, editable installs,
      layers, scope, dependencies and kinds) and `make check-architecture-change`
      ("owns no architecture row"). The change touched no `.agents/`, `.claude/` or
      `.codex/` file.
- [x] 3.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change (the run with a shape
      agreed below the listing's, 2.15), or an explicit blocker naming its cause and
      the change that owns it, with the validations it gates treated as unrun.
      *Note (27 F2, owner's disposition):* GitHub Actions ends every e2e.yml dispatch
      of this branch in `startup_failure` before any job starts (validation 22), and
      the owner waived validation's pipeline part for the rest of the change (log
      seq 48). That waiver does not discharge this part. At closeout's HEAD, run the
      pipeline's lanes locally against their compose stacks — `make -C e2e-tests
      test-e2e-vm`, `test-e2e-bare-metal` and `test-e2e-apicredits`, the targets
      e2e.yml runs — and record each lane's result and the scenarios exercising
      this change (`e2e_listing_shapes`, stage 08b included; `e2e_non_erc20_settlement`;
      the `compute_deal_stages` helper's deals) as the evidence, naming the Actions
      startup failure as why the pipeline itself did not run. If the local lanes
      cannot run, the owner waives the evidence: record the blocker — Actions
      `startup_failure`, cause not visible, owned by no change in this repository —
      with the pipeline-gated scenarios unrun, and proceed to archival.
      *Closeout:* the note's premise no longer holds. Validation 33 dispatched e2e.yml
      at `a414cdd98`, the pre-closeout commit this closeout sits on and the code it
      carries unchanged, and run 43106684835 succeeded: e2e-vm 293 passed, e2e-bare-metal
      98 passed, e2e-apicredits 4 passed, native-ansible-gate passed. The scenarios
      exercising this change ran in the VM lane, selected by marker: `e2e_listing_shapes`
      with stages 07a2–07a4 (a shape agreed below the listing's, the reservation and
      create job holding it) and 08b, `e2e_non_erc20_settlement`, and the
      `compute_deal_stages` helper's deals; the collected log gives the lane's pass
      count, not a line per scenario. So the pipeline itself is the evidence: the local
      lanes, the waiver and the blocker were not needed. No section owes a CI
      observation (`Owed by validation:` appears nowhere), and with no failure there is
      no `dev` baseline to compare.
- [x] 3.9 **Promotion.** Write the permanent documents this change owes —
      `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" (what a round
      negotiates) — and complete the design-promotion record, mapping every accepted
      decision to its exact permanent heading. A `spec.md` the deltas cover
      (`negotiation-protocol`, `vm-storefront-fulfillment`) is written by the archive
      in 3.11, not by hand; the record names it all the same.
      *Closeout:* written — `ARCHITECTURE.md` "Discovery and negotiation" (what a round
      negotiates, the multiplier, the buyer's amount codec, the evaluation order, the
      pin, the agreed shape) and "Capacity reservation" (why `resize_reservation` has
      no caller); `negotiation-protocol/architecture.md` "Negotiating a shape" with its
      four subsections; `storefront-publication/architecture.md`'s shape-resolvable
      rates paragraph (the last successful publication); `ROADMAP.md` (3.5). The
      operator handbook's drain steps (D15) were written during implementation and
      were checked against the code. `storefront-publication`'s delta is covered by
      the archive as well. None of the three capabilities has an `index.md`. The
      design-promotion record maps every decision to its heading.
- [x] 3.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=negotiation-driven-capacity-resize` and resolve
      every match, then `openspec validate negotiation-driven-capacity-resize --strict`.
      *Closeout:* `scripts/change-workflow run pre-commit` passed after promotion: its
      `make check-repository` ran documentation citations, the specification index,
      decision destinations, history wording and the rest with no match, and
      `scripts/openspec validate negotiation-driven-capacity-resize --strict` reported
      the change valid. The change has spec deltas for three capabilities.
- [x] 3.11 **Archival.** Last, once every other part is checked: `openspec archive
      negotiation-driven-capacity-resize -y` merges the deltas into `openspec/specs/`
      and moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
      *Closeout:* no permanent `spec.md` already carried the deltas, so they were
      merged (no `--skip-specs`): `scripts/change-workflow openspec archive
      negotiation-driven-capacity-resize -y` added three requirements to
      `negotiation-protocol`, one to `storefront-publication` and one to
      `vm-storefront-fulfillment`, and moved the change to
      `openspec/changes/archive/2026-11-11-negotiation-driven-capacity-resize/`. Each
      spec diff holds those requirements once, as the deltas stated them, and changes
      nothing else. The index row links the archive; `scripts/change-workflow run
      pre-commit` validated every specification strictly. This tick was made in the
      archived copy, after the archive.
