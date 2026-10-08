## Why

The VM storefront carries physical surfaces with no production caller:

- `compute_allocations`, an execution ledger `kit/site`'s `CapacityReservation`
  supersedes. No production code inserts into it; its runtime writer is a
  release-`UPDATE` inside `apply_resource_transition`, and its readers
  (`held_gpu_counts`, `held_gpu_counts_by_resource`) are exported from
  `domains/vms/listings` with no caller.
- `reserved_vm_host` in `vm_fulfillment_service.py`, always `None` because
  `kit/site` strips `vm_host` at the opaque-reservation boundary, yet threaded
  through `register_lease`, `schedule_shutdown`, `provision_vm`, `_do_provision`,
  and `_register_vm_lease_with_settings`.
- `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}` and
  `storefront_client`'s `get_resource`/`patch_resource`. The provisioning
  service's only reverse call into the storefront is the `capacity_released`
  event; nothing patches a resource.
- `SQLiteClient.delete_resource` and `ensure_default_resources` (no reference
  anywhere, tests included), `host_capacity_remaining` (referenced only by its
  own tests), and the storefront's `list_hosts`.

The local-row half of `release_reservations` and the `resource_count` health
field remain useful while local inventory and CSV import remain supported.
Their retirement belongs to `pools-9-retire-local-physical-authority`, alongside
the local listing path and its operator and test consumers.

The surfaces retained in this change's scope do not depend on the projection
cutover `pools-9-retire-local-physical-authority` owns. That cutover's start
trigger is a repository-owner decision, so these removals land independently.

## What Changes

- Retire `compute_allocations`: remove its readers and their exports, the
  release-`UPDATE` in `apply_resource_transition` with the
  `$.allocation_id`/`$.compute_allocation_id` attribute-path special case that
  feeds it, and freeze the table (stop creating it, its trigger, its four
  indexes, and its migration-added columns). No `DROP`.
- Remove the always-`None` `reserved_vm_host` threading in the storefront's
  fulfillment service.
- Remove the dead VM expiry hook (`schedule_shutdown`, wired to `_do_shutdown`,
  which always raises because no expiry-scheduling endpoint exists); the lease
  watchdog performs expiry. Routed here from `bare-metal-mock-provisioned-deal`, and
  delivered there (its task 5B.8.C.6; this change's task 3.8). `vm_host` inside the provisioning adapter is the real
  execution target and is untouched.
- Remove the orphaned resource admin routes, their request/response models,
  authentication contracts, and both client variants' `get_resource`/`patch_resource`.
  Retire their route-specific tests and preserve generic administrator signing
  coverage through a supported operation.
- Delete the four `SQLiteClient` methods with no production caller and the tests that exist
  only to exercise `host_capacity_remaining` and `list_hosts`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None by requirement text. The contract these removals serve — the storefront
holds no physical-resource, host, or physical-allocation authority — is
`pools-9-retire-local-physical-authority`'s "Storefront holds no
physical-resource authority", which describes the terminal state both changes
reach together. No permanent requirement prescribes the removed routes or
helpers. The existing operator-visible acceptance requirement and its
`resource_count` scenario remain in force, so this change carries no delta
(`skip_specs`).

## Non-Goals

- Do not retire the local-table listing path, the flag, CSV import, the legacy
  override tier, or the deployment contract — `pools-9-retire-local-physical-authority`.
- Do not `DROP` `compute_allocations`; freeze only, matching the campaign's
  additive-only schema posture.
- Do not touch `vm_host` in the provisioning adapter.
- Do not remove `resource_count` or the local-row half of `release_reservations`;
  both retire with local inventory in `pools-9-retire-local-physical-authority`.

## Impact

- **BREAKING (wire):** `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`
  are removed. Both clients lose the corresponding methods. No executable e2e
  scenario uses them; API and client tests do. Future physical-lifecycle
  scenarios use the authoritative site and provisioning controls. Pre-1.0
  APIs may break in this way.
- Code: `domains/vms/listings/src/arkhai_vms_listings/reconciler.py` and `__init__.py`;
  `domains/vms/storefront/src/market_storefront/` (`controllers/admin_controller.py`,
  `middleware/admin_identity.py`, `models/capacity_admin_models.py`,
  `services/vm_fulfillment_service.py`,
  `utils/{sqlite_client,migrations}.py`); `core/storefront-client`'s `client.py`;
  the storefront unit tests `test_compute_allocations.py`,
  `test_hosts.py`, and `test_identity_dispatch.py`; its integration
  `test_admin_api.py`; and `core/storefront-client/tests/test_admin_auth.py`.
  The two VM full-deal scenario docstrings incorrectly describe a PATCH
  callback and need correction. The previously named CLI publish test file
  is absent from the current tree.
- Not affected: provisioning, `kit/site`, bare metal.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification — the terminal requirement is
      `pools-9-retire-local-physical-authority`'s.
- [ ] New subsystem specification
- [x] No permanent documentation change.

### Knowledge to promote

- None. Why each surface is dead is recorded in this change's `design.md` and
  needs no permanent home once the surfaces are gone.

## Dependencies and Related Changes

- Lands before `pools-9-retire-local-physical-authority`, which depends on it:
  that change stops creating `resources` and `hosts` on fresh databases, and
  this change removes the remaining surfaces that read them. This change has
  no dependency on it.
- `fix-vm-fulfillment-capacity-boundary` is complete; its committed-claim reads
  in `fulfill_vm_obligation` are adjacent to the `reserved_vm_host` removal and
  must survive it.
