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
- Define provider-neutral fulfillment contracts in `kit/resource-pools`,
  including `PhysicalSettlementRequest`, `FulfillmentProvider`,
  `FulfillmentResult`, and `ProviderStatus`. The concrete
  `FulfillmentService` remains in the VM provisioning service. Providers
  execute against an already-selected `SettlementResource` and MUST NOT
  select or substitute another resource.
- Make both create and teardown dispatch-only. They return after asynchronous
  work is accepted; callers observe progress through `get_status(...)`.
- Define normalized provider operation states: `pending`, `succeeded`,
  `failed`, and `unknown`.
- Guarantee idempotency at the `FulfillmentService` boundary: an equivalent
  retry for the same `allocation_id` returns the existing fulfillment; a
  conflicting reuse fails before another provider operation is submitted.
- Add `ProviderRegistry.require(provider)` and register the initial Ansible
  implementation in the provisioning composition root.
- Wire the resource pool's generic provider-configuration metadata into
  `AnsibleFulfillmentProvider`. Configuration is validated before dispatch and
  resolved into executor inputs. Durable snapshots that remain stable across
  later pool edits are completed in POOLS-7.
- Remove `inventory_group` from `AnsiblePoolConfig`; it is not operationally
  used and concrete placement already belongs to `PhysicalSettlementScheduler`.
- Keep existing credential behavior. POOLS-3 introduces no new
  secret-distribution or credential-publication system.
- Rename the settlement request payload from ambiguous `terms` to concrete
  technical `requirements`. The storefront translates negotiated deal terms;
  provisioning validates and executes the supplied requirements without using
  the Capacity Reservation or pool configuration as their source.
- Require VM fulfillment requests to supply a deterministic `vm_target` and
  complete VM create parameters. Preserve `vm_host`, `vm_target`, and provider
  operation identifiers in provider metadata so teardown dispatches the exact
  workload created.
- Atomically rebind the allocation's existing capacity hold when scheduling
  selects a different physical resource. Fulfillment does not subtract
  capacity a second time.
- Add a side-effect-free validation path shared with create so a later API can
  dry-run allocation, pool, resource, provider, and request checks immediately
  before agreement execution.
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
- Durable settlement-assignment persistence beyond the atomic capacity-ledger
  rebind introduced here.

## Non-Goals

- Kubernetes, cloud, storage, power, or bandwidth providers.
- Recreating the removed generic `provisioning_client` package.
- Moving the concrete provisioning `FulfillmentService` into a shared package.
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

- **Packages:** provider-neutral fulfillment contracts in `kit/resource-pools`;
  VM provisioning service fulfillment/provider implementation and DI
  composition.
- **Database:** none in POOLS-3; the record contract is implemented durably in
  POOLS-7.
- **API:** none required by POOLS-3 alone.
- **Compatibility:** existing Ansible job and credential behavior remains in
  place; the provider wraps and extends that machinery rather than replacing
  it.
