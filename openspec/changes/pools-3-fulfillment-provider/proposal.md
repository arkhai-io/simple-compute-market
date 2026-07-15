## Why

`pools-2-physical-settlement-scheduler` selects a concrete
`SettlementResource`, but the provisioning service still needs a formal layer
that executes create, status, and teardown operations against that selected
resource without allowing executor mechanisms to perform placement.

The storefront will eventually own the end-to-end business workflow: obtain a
Capacity Reservation, negotiate a Market Agreement, begin physical fulfillment,
observe completion, and let the lease lifecycle request teardown. The
provisioning service must nevertheless remain authoritative for physical
fulfillment consistency, duplicate detection, provider resolution, and
execution against the selected resource.

## What Changes

- Add a provisioning-side `FulfillmentService` above provider execution. It is
  the future storefront-facing physical-fulfillment boundary and owns request
  validation, allocation-to-fulfillment identity, equivalent-retry behavior,
  conflict detection, provider resolution, and provider-state normalization.
- Define `FulfillmentProvider`, `FulfillmentResult`, and `ProviderStatus`.
  Providers execute against an already-selected `SettlementResource` and MUST
  NOT select or substitute another resource.
- Make both create and teardown dispatch-only. They return after asynchronous
  work is accepted; callers observe progress through `get_status(...)`.
- Define normalized provider operation states: `pending`, `succeeded`,
  `failed`, and `unknown`.
- Guarantee idempotency at the `FulfillmentService` boundary: an equivalent
  retry for the same `allocation_id` returns the existing fulfillment; a
  conflicting reuse fails before another provider operation is submitted.
  Backed by a simple in-memory dict this round (mirrors
  `PhysicalSettlementScheduler`'s own in-memory assignment map) — enough to
  make this change's spec scenarios true and testable, but not a concurrency
  guarantee and not durable across restarts. See "Explicitly Deferred This
  Round."
- `FulfillmentService` takes an already-selected `SettlementResource` as
  input and never calls `PhysicalSettlementScheduler` itself — placement and
  execution stay separate services, called in sequence by whatever
  orchestrates the workflow (the storefront, from `pools-7`).
- Add `ProviderRegistry.require(provider)` and register the initial Ansible
  implementation in the provisioning composition root.
- Wire the resource pool's generic provider-configuration metadata into
  `AnsibleFulfillmentProvider`. Configuration is resolved and snapshotted into
  executor inputs at dispatch time. This requires real changes below
  `AnsibleFulfillmentProvider`, not just the provider itself: `AnsibleJobParams`
  has no `playbook_path`/pool-extra-vars fields today, `_build_params` (job
  service) explicitly reconstructs every persisted field by name rather than
  splatting the stored dict, `_playbook_path_for_params` always selects a
  globally configured playbook, and `_build_vm_vars` (ansible service) has no
  generic extra-vars merge path — it hand-enumerates known fields. All four
  need updating for a snapshotted per-pool playbook/extra-vars to actually
  reach the dispatched job. No migration: `AnsibleJob.params` is already a
  JSON column, so new `AnsibleJobParams` fields persist through the existing
  `dataclasses.asdict(params)` write path. Built-in job identity fields
  (`vm_host`, `vm_action`, executor contract fields) are authoritative;
  collisions from pool extra-vars are rejected, not silently overridden.
- Remove `inventory_group` from the **public** pool provider-configuration
  contract: drop it from `AnsiblePoolConfigHandler._FIELDS`/validation, stop
  returning it from `read_config`/pool API responses, and update the pool
  API/import tests that currently assert it round-trips
  (`tests/integration/test_pools_api.py`). It is not operationally used —
  verified: no code path reads `pool_config["inventory_group"]` for job
  dispatch, inventory is always rendered per-host from the `hosts` table
  (`AnsibleService.write_inventory`) — and leaving it required on the public
  API would preserve exactly the confusion this decision exists to remove.
  No migration: `replace_config` writes a fixed internal compatibility value
  into the still-`NOT NULL` `db/models.py` column instead of a user-supplied
  one; the column itself and `db/migrations.py` are untouched. See `design.md`
  Decision 6.
- Keep existing credential behavior. POOLS-3 introduces no new
  secret-distribution or credential-publication system.
- Preserve enough fulfillment metadata for later status checks and asynchronous
  teardown. The durable ORM and final teardown lifecycle are completed in
  `pools-7-storefront-fulfillment-cutover`.

## Explicitly Deferred This Round

- Storefront workflow cutover and API/client wiring.
- Database-backed settlement persistence, uniqueness, and transaction handling.
  POOLS-7 MUST use the database as the correctness boundary; process-local locks
  are insufficient.
- Rewiring `LeaseLifecycleService` / `ExecutorReleaseDispatcher` / release
  executors to dispatch teardown through `ProviderRegistry`.
- Final teardown states, record retention, and storefront capacity-change
  notification.
- Changes to `PhysicalSettlementScheduler`'s current in-memory assignments.

## Non-Goals

- Kubernetes, cloud, storage, power, or bandwidth providers.
- Recreating the removed generic `provisioning_client` package.
- Extracting the contracts to a shared package before the package-boundary work
  requires it.
- Correlating physical fulfillment with storefront financial claim collection.

## Settlement Record / Claims Boundary

Physical fulfillment is keyed by `allocation_id` and records the selected
resource, provider, provider operation metadata, lifecycle state, and existing
credential reference. The storefront's `settlement_claims` /
`mechanism_state` and `ClaimsEngine` remain an independent financial-claim
system keyed by `claim_ref`.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: adds the `FulfillmentService`, provider contract,
  registry, normalized asynchronous operation model, Ansible pool-metadata
  execution path, and idempotency guarantees.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler`.
- Precedes `pools-7-storefront-fulfillment-cutover`, which supplies the
  production caller, durable persistence, database-backed idempotency, and
  teardown wiring.
- Independent of `pools-4-storefront-capacity-boundary`, though POOLS-7 depends
  on both paths being ready.

## Impact

- **Packages:** VM provisioning service fulfillment/provider layer and DI
  composition.
- **Database:** no schema or migration changes. `AnsibleJob.params`'s
  existing JSON column absorbs the new snapshotted `playbook_path`/
  `provider_extra_vars` fields on `AnsibleJobParams` without any migration.
  `AnsiblePoolConfigHandler`'s validation behavior changes (`inventory_group`
  no longer required/returned on the public pool-config contract) but no
  column is added, dropped, or altered — the durable `SettlementRecord`
  table itself is still implemented in POOLS-7.
- **API:** none new required by POOLS-3 alone, but the existing pool
  create/import API's accepted/returned shape changes (`inventory_group` no
  longer required or returned) — a compatibility-relevant behavior change
  for any existing caller currently sending it, not just an internal detail.
- **Compatibility:** existing Ansible job and credential behavior remains in
  place; the provider wraps and extends that machinery rather than replacing
  it.
