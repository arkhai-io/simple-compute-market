## Why

The VM storefront carries physical surfaces with no production caller:

- `compute_allocations`, an execution ledger `kit/site`'s `CapacityReservation`
  supersedes. No production code inserts into it. Its one runtime write is a
  release-`UPDATE` inside `apply_resource_transition`. Its readers
  (`held_gpu_counts`, `held_gpu_counts_by_resource`, `allocation_table_exists`,
  and the `HELD_ALLOCATION_STATES` set they read) are exported from
  `domains/vms/listings` with no caller.
- `reserved_vm_host` in `vm_fulfillment_service.py`. It is always `None`:
  `kit/site` names a host `host_id` and strips it from every reservation, so no
  reservation carries a `vm_host` key. It is still passed to `provision_vm` and
  accepted by `_do_provision` as a compatibility parameter.
- `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}` and
  `storefront_client`'s `get_resource`/`patch_resource`. The provisioning
  service's only reverse call into the storefront is the `capacity_released`
  event; nothing patches a resource. Removing the routes also orphans
  `SQLiteClient.get_resource`, both clients' `_authenticated_patch`, and the
  `resource_released` stage event.
- `SQLiteClient.delete_resource` and `ensure_default_resources` (no reference
  anywhere, tests included), `host_capacity_remaining` (referenced only by
  tests), and the storefront's `list_hosts`.

The local-row half of `release_reservations` and the `resource_count` health
field remain useful while local inventory and CSV import remain supported.
Their retirement belongs to `pools-9-retire-local-physical-authority`, alongside
the local listing path and its operator and test consumers.

The surfaces retained in this change's scope do not depend on the projection
cutover `pools-9-retire-local-physical-authority` owns. That cutover's start
trigger is a repository-owner decision, so these removals land independently.

## What Changes

This is a cleanup change: it deletes each unused surface and whatever that
deletion leaves unused. It stops at code that still has a live caller.

- Retire `compute_allocations`:
  - Remove its readers, `HELD_ALLOCATION_STATES`, and their exports.
  - Remove the release-`UPDATE` in `apply_resource_transition` and the
    `$.allocation_id`/`$.compute_allocation_id` attribute-path special case
    that feeds it.
  - Freeze the table. Stop creating it, its trigger, and its four indexes.
    Drop the two migrations that only add its columns from the migration
    list, and stop migration 002 and the pool backfill from touching it. No
    `DROP`.
- Remove the always-`None` `reserved_vm_host`, the `provision_vm` keyword that
  carries it, and `_do_provision`'s `vm_host` parameter.
- Remove the dead VM expiry hook. `bare-metal-mock-provisioned-deal` delivered
  this as its task 5B.8.C.6; it is this change's task 3.8.
- Remove the orphaned resource admin routes, and with them:
  - their request/response models, administrator authentication contracts,
    and stage event;
  - both client variants' `get_resource`/`patch_resource` and
    `_authenticated_patch`;
  - `SQLiteClient.get_resource`.

  Narrow `apply_resource_transition` to the state transition
  `release_reservations` still performs, folding in its pass-through wrapper.
  Retire the route-specific tests; generic administrator signing and client
  parity coverage already runs through `authenticated_request`.
- Delete the four `SQLiteClient` methods with no production caller. Delete
  the tests that exist only to exercise `host_capacity_remaining` and
  `list_hosts`. Rewrite the capacity-check tests that used
  `host_capacity_remaining` to observe the check itself.
- Correct prose that describes the removed surfaces:
  - `release_reservations`' docstring;
  - both VM full-deal scenarios' stage `00h` docstrings, including their
    administrator-key troubleshooting text;
  - a stale `vm_host` comment in the reservation boundary test;
  - `kit/site`'s `CapacityReservation` docstring;
  - the provisioning chart's `storefront` values comment.

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
- Do not remove `resource_count`, the local-row half of `release_reservations`,
  or the resource-transition machinery that loop uses. These retire with
  local inventory in `pools-9-retire-local-physical-authority`.
- Do not change provisioning, adapter, or `kit/site` production behavior.

## Impact

- **BREAKING (wire):** `GET`/`PATCH /api/v1/admin/portfolio/resources/{resource_id}`
  are removed. Both clients lose the corresponding methods. No executable e2e
  scenario uses them; API and client tests do. Future physical-lifecycle
  scenarios use the authoritative site and provisioning controls. Pre-1.0
  APIs may break in this way.
- **Schema:** fresh storefront databases no longer contain
  `compute_allocations`. Existing databases keep the table and its rows
  unchanged, and the two removed migration IDs stay recorded but unused.
- **Production code:**
  - `domains/vms/listings/src/arkhai_vms_listings/`: `reconciler.py` and
    `__init__.py`.
  - `domains/vms/storefront/src/market_storefront/`:
    `controllers/admin_controller.py`, `middleware/admin_identity.py`,
    `models/capacity_admin_models.py`, `services/vm_fulfillment_service.py`,
    `services/fulfillment_service.py`, `utils/sqlite_client.py`, and
    `utils/migrations.py`.
  - `core/storefront-client/src/storefront_client/client.py`.
  - The `kit/site/src/market_site/db.py` docstring and the
    `helm/charts/provisioning/values.yaml` `storefront` comment, which are
    prose only.
- **Tests:**
  - Storefront unit tests: `test_compute_allocations.py`, `test_hosts.py`,
    `test_identity_dispatch.py`, and `test_fulfillment_provisioning.py`.
  - Storefront integration tests: `test_admin_api.py`,
    `test_settle_controller.py`, and `test_capacity_reservation_boundary.py`,
    plus new `test_compute_allocations_freeze.py` and
    `test_resource_transitions.py`.
  - `core/storefront-client/tests/test_admin_auth.py`.
  - Provisioning: `test_ledger_lease_lifecycle.py`, where only a test stub
    changes.
  - The two VM full-deal scenario docstrings.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [ ] Existing subsystem specification — the terminal requirement is
      `pools-9-retire-local-physical-authority`'s.
- [ ] New subsystem specification
- [ ] No permanent documentation change.
- [x] Other permanent documentation:
  - `docs/development/DEPLOYMENT_AND_CONFIG.md` "Migrations at startup"
    gains the migration-retirement rule.
  - `docs/development/ROADMAP.md` Goal 1 is brought current at closeout.

  The terminal authority requirement stays
  `pools-9-retire-local-physical-authority`'s.

### Knowledge to promote

- A migration whose only effect is on a frozen table leaves the chain. Its
  recorded ID stays inert and is never reused. Destination:
  `docs/development/DEPLOYMENT_AND_CONFIG.md`'s "Migrations at startup".
- Why each surface is dead is recorded in this change's `design.md` and needs
  no permanent home once the surfaces are gone.

## Dependencies and Related Changes

- Independent of `pools-9-retire-local-physical-authority`; either order. That
  change's freeze migration covers `compute_allocations` if this one has not
  landed first. Its local-row cleanup in `release_reservations` uses the
  narrowed transition this change leaves behind.
- `fix-vm-fulfillment-capacity-boundary` is complete; its committed-claim reads
  in `fulfill_vm_obligation` are adjacent to the `reserved_vm_host` removal and
  must survive it.
- `bare-metal-mock-provisioned-deal` delivered task 3.8 and rewrote the
  post-provision lease path the `reserved_vm_host` removal edits.
