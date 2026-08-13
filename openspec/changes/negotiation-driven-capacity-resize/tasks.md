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

## 2. Section 2+ (unblocked 2026-08-06; not yet planned)

> **Archival audit, 2026-08-13: this change is not complete and must not be archived on a
> checkbox count.** Every `- [ ]` in this file is checked, which makes it look finished to
> any scan that counts them. It is not: Section 0 shipped, Section 1 was reverted in full,
> and Section 2 — the actual subject of the change, a negotiated resize — is prose with no
> tasks written yet. A section that has not been planned has nothing to check, so the
> absence of unchecked boxes here means the opposite of what it means elsewhere. Planning
> Section 2 is the next step; archiving is not.

Resolutions recorded in `design.md`'s "Section 2 resolutions" section
(2026-07-29). Placement (child of `proposal`) and core vocabulary (reuse
`ProvisionTerms`) are settled; the field itself was not to be added until seller
negotiation policy existed to evaluate it -- policy design was out of scope for this
change. No tasks were written here because there was nothing concrete to plan yet;
opening this section's task list was itself named as the next discuss-phase trigger,
once policy design was ready to start.

**That trigger has fired.** Seller policy design was completed 2026-08-06 and is owned
by `capacity-shape-pricing`, which establishes: per-dimension rates carried inside the
family-grouped capability shape; a replaceable aggregation interface; and -- the
resolution most consequential for this section -- the negotiated quantity becoming a
**rate multiplier** over the listing's advertised minimum rate structure rather than an
absolute amount. That is what keeps a round's concession comparable to the previous
round's when the requested shape changes between them, which is precisely the problem
that made a shape-change field unplannable here.

Two further changes were opened at the same time and bear directly on this section:
`capacity-shape-envelope` (whether a counter-offered shape is one the seller will
consider, and the admissible range for one dimension given the rest of a shape -- the
range query exists so a seller can counter usefully rather than only reject), and
`negotiation-capacity-feasibility-probe` (whether the site can currently serve it,
verified non-consumingly before terms are agreed).

Planning this section is now unblocked but deliberately not done here, because its
shape depends on decisions those three changes make. When it is planned, it must
cover at minimum:

- The revised-terms field as a child of `proposal`, typed as the existing
  `ProvisionTerms` envelope -- placement and vocabulary already settled above.
- Wiring `resize_reservation`, respecting its documented ordering constraint: resize
  before `schedule_resource()` runs, never after, or an already-scheduled
  `SettlementResource.dimensions` keeps reflecting the old shape.
- The rate consequence of a resize. A shape change changes the burn rate, so whatever
  the storefront holds alongside the reservation must be updated in step with it;
  `resize_reservation` mints a new `capacity_reservation_id` rather than mutating,
  which the storefront-side record must follow.
- Removing `_reject_unsupported_resource_shape_request` (Section 0's guard), whose
  docstring records that it exists only because policy could not price an alternative
  shape.
- Settlement and fulfillment reading the negotiated shape rather than the listing's
  `offer_resource` -- `_resolve_compute_resource` and `vm_fulfillment_planner` both
  read the listing today.
