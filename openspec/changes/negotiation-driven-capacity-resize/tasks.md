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

## 2. Section 2+ (not yet planned)

Resolutions recorded in `design.md`'s "Section 2 resolutions" section
(2026-07-29). Placement (child of `proposal`) and core vocabulary (reuse
`ProvisionTerms`) are settled; the field itself is not added until seller
negotiation policy exists to evaluate it -- policy design is out of scope
for this change. No tasks are written here because there is nothing
concrete to plan yet; opening this section's task list is itself the next
discuss-phase trigger, once policy design is ready to start.
