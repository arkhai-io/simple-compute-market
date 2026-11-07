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

- [ ] 2.1 Re-verify `design.md`'s Context against the tree: the hook
      names in `NegotiationDomainHooks`, that continue/advance carry a typed
      `proposal`, that `hold_ttl_seconds` still defaults to 0, and that
      `build_vm_accepted_artifacts` still derives the order from the listing record.
- [ ] 2.1a **Decision gate.** Decide where a buyer reads a listing's rate structure,
      and with what authority, per `design.md`'s "Where a buyer reads the rate
      structure is a decision gate", taking `store-registry-listings-as-published`'s
      accepted carrier policy as an input, and record the decision and reasoning in
      `design.md`. If the decision needs the registry to keep a listing-level field,
      record the dependency on that change here and in the campaign index before
      any task relying on it starts.
- [ ] 2.2 Add the revised-shape field as a child of `proposal`, typed as the existing
      `ProvisionTerms` envelope, to the continue/advance request models. The
      envelope stays opaque to core; the VM codec decodes its payload as a
      family-grouped capability shape validated by `VM_CAPABILITY_SCHEMA`.
- [ ] 2.3 Widen `kit/negotiation-runtime`'s `validate_continuation` contract so a
      domain sees the decoded revised shape, and carry the shape on `RoundRequest`
      and `RoundEvaluation` so `evaluate_round` and `agreement_terms` receive what
      the round proposed and what was agreed.
- [ ] 2.4 Compose the VM `evaluate_round` in `design.md`'s order — admissibility,
      authoritative feasibility, commercial feasibility, pricing — with a distinct
      refusal reason for each, and a stated "not checked" for a check the domain
      does not compose. Implement the commercial feasibility guard here: a
      requested shape's categorical commitments (GPU model, region) checked by
      equality against the listing's, declining without a quote; the quantitative
      check is the envelope's predicate. Tests: a categorical mismatch declines
      without pricing; a shape outside the envelope declines before the guard runs.
      Promote "Seller feasibility precedes pricing" with this change's spec delta.
- [ ] 2.5 Retire `_validate_vm_opening`'s shape-mismatch refusal: a round-0 shape
      differing from the listing is evaluated by the same composition rather than
      rejected. Delete the Section 0 regression tests that assert the refusal.
- [ ] 2.6 Focused tests: a revised shape is decoded and validated; an unreadable
      shape is refused at the boundary; each refusal reason surfaces distinctly; a
      round without a revised shape is evaluated against the previously agreed
      shape.

### 2b. The multiplier

- [ ] 2.7 Reinterpret the negotiated reference quantity as a multiplier in basis
      points over the advertised minimum rate structure, through the
      `reference_amount`, `amount_from_proposal`, and `proposal_from_amount` hooks.
      Every intermediate value is an exact integer or `Decimal`; the quote rounds up;
      a quote exceeding the asset's amount type is refused.
- [ ] 2.8 Audit every consumer that assumed the negotiated scalar was an amount in
      an asset's base units — the escrow and hosted obligation construction paths
      first, since a missed consumer surfaces as a wrong on-chain amount. This is an
      audit, not a rename.
- [ ] 2.9 Express the seller's floor once as a multiplier bound (default 10,000)
      and confirm it applies to a shape never explicitly priced; a policy may lower
      it explicitly.
- [ ] 2.10 Confirm `bisection_middleware` converges unchanged on the reinterpreted
      quantity, and that a shape change between rounds does not re-anchor bounds.
- [ ] 2.11 Focused tests: concession comparability across a shape change; floor
      applied to an unanticipated shape; agreed terms yield one derivable price;
      a base-unit amount above 2^63 survives a full round trip through persistence
      and the hooks unchanged.

### 2c. The agreed shape reaches the claim

- [ ] 2.12 Write the agreed shape into the settlement order's `listing_resource`
      quantities in `build_vm_accepted_artifacts`, so
      `compute_capacity_claim_from_order` reserves what was agreed. Confirm
      `vm_fulfillment_planner` and `encode_compute_lease` need no change.
- [ ] 2.13 Rewrite `_place_capacity_hold`'s claim to come from the acceptance's
      agreed order rather than `listing_record`, so a non-zero `hold_ttl_seconds`
      deployment holds the agreed shape. No resize is placed here; record that
      `negotiation-time-capacity-hold` owns `resize_reservation`'s first call.
- [ ] 2.14 Focused tests: a negotiation agreeing a shape smaller than the listing's
      reserves the smaller shape; the committed reservation's dimensions match the
      agreed shape; the fulfillment request derives from the reservation.
- [ ] 2.15 One e2e run with a shape agreed below the listing's, asserting the VM
      built has the agreed shape. Treat this as the deployment boundary: in-flight
      negotiations carry a multiplier after it.
- [ ] 2.16 **Comment hygiene and import placement, before the pre-closeout review.** Run
      `make check-comment-hygiene` and read the comments this change added for any that
      narrate the review or migration that introduced them; move each import the change
      added to module level unless a verified circular import or a recorded lazy-load
      reason keeps it local. Closeout only confirms both.

## 3. Closeout

Per `openspec/README.md#plan-closeout-requirements`. This change's implementation predates the closeout task becoming a planning requirement. The parts are recorded here so each carries an explicit disposition rather than an assumed one; confirm and tick each rather than treating the change as closed.

- [ ] 3.1 **Comment hygiene — confirm.** Run `make check-comment-hygiene`, and read
      the comments this change added for any that narrate the review or migration that
      introduced them. Do not edit code here: anything to rewrite returns the change to
      implementation.
- [ ] 3.2 **Import placement — confirm.** Check the imports this change added for any
      still local without a recorded reason. One that should move returns the change to
      implementation.
- [ ] 3.3 **Documentation compliance.** Re-check this change's accepted decisions
      against `openspec/README.md`'s placement rules, and the permanent documents
      against the code they describe. Every material decision in `design.md` has a
      permanent destination or an explicit temporary, superseded, or rejected
      classification, and no production source references
      `openspec/changes/negotiation-driven-capacity-resize`.
- [ ] 3.4 **Narrative compression.** Compress completed-task notes to final behavior,
      material validation evidence, unresolved or deferred work, and
      permanent-documentation destinations, moving durable rationale into `design.md`
      first.
- [ ] 3.5 **Roadmap currency.** Update the affected goal's current state and gap
      mapping in `docs/development/ROADMAP.md`, or record that no goal is affected.
      Expected: the “Negotiate full compute capability, not GPU count alone” goal's
      current-state description and gap-to-change mapping change, and the
      design-promotion record names that update.
- [ ] 3.6 **Campaign index currency.** Update this change's row, and its campaign's
      dependency graph, in `openspec/changes/README.md`, or record that both are
      unchanged. Other rows' `Depends on` are left alone: archive cleanup releases
      dependents after the closeout gate.
- [ ] 3.7 **Packaging.** Run `make check-packaging` and resolve every failure it
      reports (a failure needing a code or lock change returns the change to
      implementation).
- [ ] 3.8 **End-to-end pipeline.** Record the passing run the latest validation names,
      its result, and the scenarios that exercise this change (the run with a shape
      agreed below the listing's, 2.15), or an explicit blocker naming its cause and
      the change that owns it, with the validations it gates treated as unrun.
- [ ] 3.9 **Promotion.** Write the permanent documents this change owes —
      `docs/development/ARCHITECTURE.md`, "Discovery and negotiation" (what a round
      negotiates) — and complete the design-promotion record, mapping every accepted
      decision to its exact permanent heading. A `spec.md` the deltas cover
      (`negotiation-protocol`, `vm-storefront-fulfillment`) is written by the archive
      in 3.11, not by hand; the record names it all the same.
- [ ] 3.10 **Documentation citations.** After promotion, run
      `make check-doc-citations CHANGE=negotiation-driven-capacity-resize` and resolve
      every match, then `openspec validate negotiation-driven-capacity-resize --strict`.
- [ ] 3.11 **Archival.** Last, once every other part is checked: `openspec archive
      negotiation-driven-capacity-resize -y` merges the deltas into `openspec/specs/`
      and moves the change under `openspec/changes/archive/`; point the index row at the
      archived directory, and run `openspec validate --specs --strict`.
