## Why

The 2026-08-06 Goal 1 sweep recorded in
`pools-9-retire-local-physical-authority`'s `design.md` found five physical
surfaces in the VM storefront whose callers are gone:

- `compute_allocations`, an execution ledger `kit/site`'s `CapacityReservation`
  supersedes by its own account. No production code inserts into it; its only
  writer is a release-`UPDATE` inside `apply_resource_transition`, and its
  readers (`held_gpu_counts`, `held_gpu_counts_by_resource`) are exported from
  `domains/vms/listings` with no caller.
- `reserved_vm_host` in `vm_fulfillment_service.py`, provably always `None`
  because `kit/site` strips `vm_host` at the opaque-reservation boundary, yet
  threaded through `register_lease`, `schedule_shutdown`, `provision_vm`,
  `_do_provision`, and `_register_vm_lease_with_settings`. The in-code comment
  records that it was retained only to avoid a signature change.
- `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}` and
  `storefront_client`'s `get_resource`/`patch_resource`. `PATCH`'s documented
  caller, the provisioning service's `LeaseWatchdog`, no longer makes that call;
  the provisioning service's only reverse call is the `capacity_released` event.
- The legacy local-row normalization loop in `release_reservations`, whose
  authoritative half (`_release_site_ledger_holds`) is already correct.
- `SQLiteClient.delete_resource` and `ensure_default_resources` (no reference
  anywhere, tests included), `host_capacity_remaining` (referenced only by its
  own tests), and the storefront's `list_hosts`.
- `resource_count` on the health surface, which counts a table being retired.

All were re-confirmed present on 2026-09-25. None depends on the projection
cutover, and the cutover's start trigger is undefined by design, so leaving them
in that change meant waiting on a decision nobody has to make. They were split
out on 2026-09-25 as Sections 2 and 3 of that plan, with their task numbers.

## What Changes

- Retire `compute_allocations`: remove its readers and their exports, the
  release-`UPDATE` in `apply_resource_transition` with the
  `$.allocation_id`/`$.compute_allocation_id` attribute-path special case that
  feeds it, and freeze the table (stop creating it, its trigger, its four
  indexes, and its migration-added columns). No `DROP`.
- Remove the always-`None` `reserved_vm_host` threading in the storefront's
  fulfillment service. `vm_host` inside the provisioning adapter is the real
  execution target and is untouched.
- Remove the orphaned resource admin routes, their request/response models,
  and both client variants' `get_resource`/`patch_resource`.
- Remove the legacy local-row half of `release_reservations` and rewrite its
  docstring.
- Delete the four zero-caller `SQLiteClient` methods and the tests that exist
  only to exercise `host_capacity_remaining`.
- Remove `resource_count` from `SystemService.get_health` and from both
  `core_storefront`'s and `storefront_client`'s `HealthResponse`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The contract these removals serve — the storefront holds no
physical-resource, host, or physical-allocation authority — is
`pools-9-retire-local-physical-authority`'s "Storefront holds no
physical-resource authority" requirement, which describes the terminal state
both changes reach together. This change removes code nothing calls; it adds
no behavior and changes none an implementation could exhibit, so it carries no
delta of its own (`skip_specs`).

## Non-Goals

- Do not retire the local-table listing path, the flag, CSV import, the
  legacy override tier, or the deployment contract. Those remain
  `pools-9-retire-local-physical-authority`'s.
- Do not `DROP` `compute_allocations`; freeze only, matching the campaign's
  additive-only schema posture until a deployment cycle confirms the freeze.
- Do not touch `vm_host` in the provisioning adapter.

## Impact

- **BREAKING (wire):** `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`
  are removed and `HealthResponse.resource_count` disappears from
  `/api/v1/system/status`. Both clients lose the corresponding methods. No
  consumer in this repository is affected; pre-1.0 APIs may break in this way.
- Affected code: `domains/vms/listings/reconciler.py` and `__init__.py`,
  `domains/vms/storefront/src/market_storefront/` (`controllers/admin_controller.py`,
  `services/{system_service,vm_fulfillment_service}.py`,
  `utils/{sqlite_client,migrations}.py`), `core/storefront`'s
  `system_models.py`, `core/storefront-client`'s `client.py` and `models.py`,
  and the storefront unit tests `test_compute_allocations.py`,
  `test_cli_publish_helpers.py` (its test-only `INSERT`), and `test_hosts.py`.
- Not affected: provisioning, `kit/site`, bare metal.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification — the terminal requirement is
      `pools-9-retire-local-physical-authority`'s; one Evidence entry in
      `openspec/specs/storefront-publication/spec.md` cites resource-count
      diagnosis and is corrected here.
- [ ] New subsystem specification
- [x] No permanent documentation change beyond that Evidence entry.

### Knowledge to promote

- None new. The evidence that each surface was dead stays in
  `pools-9-retire-local-physical-authority`'s `design.md`, which this change
  cites rather than copies.

## Dependencies and Related Changes

- Split out of `pools-9-retire-local-physical-authority` on 2026-09-25. May
  land before or after it; the freeze migration in that change's task 6.1
  covers `compute_allocations` if this one has not landed first.
- Edits adjacent lines in `vm_fulfillment_service.py` to
  `fix-vm-fulfillment-capacity-boundary`, which is complete and awaiting
  archival, so no coordination is needed.
