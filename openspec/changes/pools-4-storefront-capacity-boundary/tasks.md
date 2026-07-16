# POOLS-4 tasks

## Validation guards

- [x] `domains/vms/listings/models.py`: attach storefront-specific compute
      listing identity validation to `Listing` with a Pydantic after-validator.
      Normalize surrounding whitespace; reject missing, blank, or malformed
      identifiers; require at least one of `pool_id` / `resource_id`; allow both.
- [x] `listing_service.py`: remove the duplicate service-layer identity guard
      and rely on construction of the validated `Listing` before persistence.
- [x] `domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`:
      in `compute_capacity_claim_from_order`, reject a missing or empty order and
      raise if the built claim has neither `pool_id` nor `resource_id` after extraction. Backstop for any
      listing that reaches claim-building despite the guard above.
- [x] Same function: when both `pool_id` and `resource_id` are present,
      drop `pool_id` from the built claim so the listing is matched as
      specific-resource (`resource_id` wins) rather than requiring both to
      match. See `design.md` Decision 2 "Both present."
- [x] Test: a claim built from an offer with both `pool_id` and
      `resource_id` set contains `resource_id` and not `pool_id`.
- [x] `domains/vms/storefront/tests/integration/test_listings_api.py`
      (`TestCreateListing`): add a case asserting `POST /listings/create` is
      rejected when the offer has neither `pool_id` nor `resource_id`, and a
      case confirming a `resource_id`-only offer (no `pool_id`) still
      succeeds. (`_OFFER` itself had neither key — updated to carry
      `resource_id` so the four existing `_OFFER`-based tests keep passing
      under the new guard.)
- [x] `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`: add a
      case asserting `compute_capacity_claim_from_order` raises on an
      `offer_resource` with neither key; confirm the existing
      `test_claim_survives_listing_model_validation` still passes unchanged
      (it has `resource_id` set, so the new guard doesn't affect it).

- [x] `vm_fulfillment_planner.py`: reject missing, empty, or malformed
      settlement orders instead of producing an empty plan.
- [x] Verify missing orders fail before `capacity.probe` or reserve is called.

## Rename

- [x] `domains/vms/storefront/src/market_storefront/utils/migrations.py`:
      keep the fresh-database schema constructor on the new table name and add a
      new migration entry for already-recorded databases that runs
      `ALTER TABLE compute_inventory_pools RENAME TO compute_capacity_pools`,
      is a no-op when only the new table or neither table exists, renames when
      only the old table exists, and fails when both table names exist. Leave
      `compute_pool_members` unrenamed.
- [x] Verify (via a migration test, not assumption) that
      `compute_pool_members`'s `FOREIGN KEY(pool_id) REFERENCES
      compute_inventory_pools(pool_id)` correctly resolves to
      `compute_capacity_pools` after the rename. Confirmed: SQLite's
      `RENAME TO` rewrites the FK clause in the referencing table's schema
      text automatically — verified directly and via
      `tests/unit/test_migrations.py` (asserts the rewritten `sql`,
      the row survives, the join resolves, and `PRAGMA foreign_key_check`
      reports no violations).
- [x] `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`:
      update the `INSERT INTO compute_inventory_pools` / `ON CONFLICT`
      references to `compute_capacity_pools`.
- [x] `domains/vms/listings/reconciler.py`: update the two raw-SQL
      references (`sqlite_master` existence check and the `FROM
      compute_inventory_pools p JOIN compute_pool_members m` query) to
      `compute_capacity_pools`.
- [x] Update `_migrate_compute_inventory_pools`'s own `CREATE TABLE IF NOT
      EXISTS` statement to create `compute_capacity_pools` directly for
      brand-new databases, so a fresh install doesn't create the old name
      and immediately rename it. (The function itself keeps its old name —
      migrations aren't renamed retroactively — only the table it creates
      changes.)
- [x] Grep the full repo after the change for any remaining
      `compute_inventory_pools` string to confirm no reference was missed
      (tests, docs, fixtures). Confirmed clean — remaining hits are the
      historical migration id/function name and the new rename migration's
      own before/after logic, all intentional.

## Docs

- [x] Correct `design.md`'s Decision 1 (`fill_first`/`most_available` never
      decided host placement — this file originally implied it) and
      Decision 2 (what actually forced host-specificity, and the resolved
      validation-guard approach). Done during design review.
- [x] Correct the `site-capacity` spec delta's scenario wording to describe
      the structural (pool-membership-based) specific-resource mechanism
      instead of an "opt-in" flag that doesn't exist, including the
      both-present priority rule. Done during design review.
- [x] Document the operator listing-mode-hint open question
      (`ResourcePool.policy_tags`, non-binding on provisioning, the
      `ResourcePoolService`↔`SiteResource` sync gap) in `pools-7`'s
      `proposal.md` Non-Goals and `design.md` "Remaining open questions."
      Done during design review — see those files' 2026-07-16 entries.
- [x] Re-checked `docs/development/ARCHITECTURE.md`'s capability map and
      official-vocabulary section — already states "`pool_id` and
      `resource_id` remain boundary-sensitive," which matches this change
      without needing an update.
- [x] Confirmed `openspec/specs/resource-pool-management/spec.md` and
      `openspec/specs/site-capacity/spec.md` need no further correction —
      this change's spec delta extends the baseline without contradicting
      it; the delta merges into the baseline at archive time, not now.

## Verification

- [x] Ran the storefront's unit + integration suites in this session's
      sandbox (not the canonical dev environment — no `make dist`/`make
      reinit` wheel chain available here, so this used an ad hoc
      `PYTHONPATH` against the package sources plus `pip install` for
      third-party deps). Results: `test_migrations.py` 3/3,
      `test_two_phase_reserve.py` 9/9, `test_listings_api.py` (integration)
      31/31, reconciler-touching suites (`test_compute_allocations.py`,
      `test_fulfillment_service.py`, `test_admin_api.py`) 44/44, full
      `tests/unit/` 540 passed / 27 failed. All 27 failures verified
      unrelated to this change — missing `web3` (a third-party dependency
      this sandbox never had reason to install) and a plugin entry-point
      lookup that only resolves through a real `pip install`/wheel
      installation, not a raw `PYTHONPATH` — **please still run `make
      test-storefront` in the canonical environment before merging**, this
      sandbox run is corroborating evidence, not a replacement.
- [x] Confirmed the "convoluted admin sequence" this session identified —
      `POST /listings/create` called directly with an offer missing both
      `pool_id` and `resource_id` — now fails with 400 instead of silently
      publishing (`test_rejects_offer_with_neither_pool_id_nor_resource_id`).

## Resolved follow-up

- [x] **`fulfill_vm_obligation`'s exception handling
  (`vm_fulfillment_service.py`)**: `build_vm_fulfillment_plan(...)` is now
  called *inside* that function's `try:` block instead of before it, so a
  plan-building failure (missing/malformed order, or the claim-build
  backstop's missing-identity guard) now goes through the same
  graceful-failure path as every other reservation failure —
  `apply_failure_policy`, the `"provision"/"failed"` stage event, and a
  `{"status": "error", ...}` response — instead of raising past it.
  `order_id` is pre-initialized alongside the other reserved-state
  variables so the `except` block's references to it stay safe when the
  plan itself never builds. Regression test:
  `tests/unit/test_fulfill_vm_obligation_error_handling.py` — verified it
  fails against the pre-fix code (a missing order silently reserved
  arbitrary mocked capacity and returned `"fulfilled"`, which is the exact
  unscoped-claim risk `design.md`'s Decision 4 describes) and passes
  against the fix.

