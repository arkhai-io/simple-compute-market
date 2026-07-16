# POOLS-4 tasks

## Validation guards

- [ ] `domains/vms/storefront/src/market_storefront/services/listing_service.py`:
      in `_parse_offer_and_escrows` (or a small helper it calls), reject a
      compute (`ComputeResource`) offer that has neither `pool_id` nor
      `resource_id` set, with a clear `ValueError` message. Do not default
      `pool_id` to `resource_id` here — a `resource_id`-only offer is valid.
- [ ] `domains/vms/storefront/src/market_storefront/services/vm_job_spec_service.py`:
      in `compute_capacity_claim_from_order`, raise if the built claim has
      neither `pool_id` nor `resource_id` after extraction. Backstop for any
      listing that reaches claim-building despite the guard above.
- [ ] Same function: when both `pool_id` and `resource_id` are present,
      drop `pool_id` from the built claim so the listing is matched as
      specific-resource (`resource_id` wins) rather than requiring both to
      match. See `design.md` Decision 2 "Both present."
- [ ] Test: a claim built from an offer with both `pool_id` and
      `resource_id` set contains `resource_id` and not `pool_id`.
- [ ] `domains/vms/storefront/tests/integration/test_listings_api.py`
      (`TestCreateListing`): add a case asserting `POST /listings/create` is
      rejected when the offer has neither `pool_id` nor `resource_id`, and a
      case confirming a `resource_id`-only offer (no `pool_id`) still
      succeeds.
- [ ] `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`: add a
      case asserting `compute_capacity_claim_from_order` raises on an
      `offer_resource` with neither key; confirm the existing
      `test_claim_survives_listing_model_validation` still passes unchanged
      (it has `resource_id` set, so the new guard doesn't affect it).

## Rename

- [ ] `domains/vms/storefront/src/market_storefront/utils/migrations.py`:
      add a new migration entry (do not edit
      `_migrate_compute_inventory_pools` in place) that runs
      `ALTER TABLE compute_inventory_pools RENAME TO compute_capacity_pools`,
      guarded by existence checks so it's a no-op on a fresh database that
      already created the table under the new name and safe to run whenever
      the old table exists. Leave `compute_pool_members` unrenamed.
- [ ] Verify (via a migration test, not assumption) that
      `compute_pool_members`'s `FOREIGN KEY(pool_id) REFERENCES
      compute_inventory_pools(pool_id)` correctly resolves to
      `compute_capacity_pools` after the rename — SQLite's `RENAME TO`
      should rewrite this automatically, but this needs a test, not an
      assumption, before relying on it.
- [ ] `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`:
      update the `INSERT INTO compute_inventory_pools` / `ON CONFLICT`
      references to `compute_capacity_pools`.
- [ ] `domains/vms/listings/reconciler.py`: update the two raw-SQL
      references (`sqlite_master` existence check and the `FROM
      compute_inventory_pools p JOIN compute_pool_members m` query) to
      `compute_capacity_pools`.
- [ ] Update `_migrate_compute_inventory_pools`'s own `CREATE TABLE IF NOT
      EXISTS` statement to create `compute_capacity_pools` directly for
      brand-new databases, so a fresh install doesn't create the old name
      and immediately rename it. (The function itself keeps its old name —
      migrations aren't renamed retroactively — only the table it creates
      changes.)
- [ ] Grep the full repo after the change for any remaining
      `compute_inventory_pools` string to confirm no reference was missed
      (tests, docs, fixtures).

## Docs

- [x] Correct `design.md`'s Decision 1 (`fill_first`/`most_available` never
      decided host placement — this file originally implied it) and
      Decision 2 (what actually forced host-specificity, and the resolved
      validation-guard approach). Done during design review.
- [x] Correct the `site-capacity` spec delta's scenario wording to describe
      the structural (pool-membership-based) specific-resource mechanism
      instead of an "opt-in" flag that doesn't exist. Done during design
      review.
- [x] Document the operator listing-mode-hint open question
      (`ResourcePool.policy_tags`, non-binding on provisioning, the
      `ResourcePoolService`↔`SiteResource` sync gap) in `pools-7`'s
      `proposal.md` Non-Goals and `design.md` "Remaining open questions."
      Done during design review — see those files' 2026-07-16 entries.
- [ ] After implementation, re-check `docs/development/ARCHITECTURE.md`'s
      capability map and official-vocabulary section against what actually
      landed; update only if implementation revealed something current
      prose doesn't already cover (per this session's working agreement,
      ARCHITECTURE.md documents current state, not this change's history).
- [ ] Confirm `openspec/specs/resource-pool-management/spec.md` and
      `openspec/specs/site-capacity/spec.md` need no further correction
      beyond what's already captured in this change's spec delta.

## Verification

- [ ] Run the storefront's unit + integration suites
      (`domains/vms/storefront`, `core/storefront`) and the listings package
      tests (`domains/vms/listings`) in the canonical development
      environment.
- [ ] Manually confirm (or add a regression test for) the "convoluted admin
      sequence" this session identified — `POST /listings/create` called
      directly with an offer missing both `pool_id` and `resource_id` — now
      fails with a clear error instead of silently publishing.
