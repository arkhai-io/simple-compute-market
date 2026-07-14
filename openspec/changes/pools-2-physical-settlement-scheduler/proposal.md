## Why

The current path conflates capacity reservation, physical host placement, and
provider execution into one step. That creates race conditions and leaves
`resource_id` ambiguous — sometimes a physical scheduling decision, sometimes
a market-level capacity commitment. POOLS-1 gave operators durable pool
identity and administrative host membership but explicitly deferred
settlement selection: `site-capacity`'s executor-neutral site authority
requirement states administrative pool membership "MUST NOT alter settlement
selection until integrated through the site-authority boundary," and
`physical-provisioning` records `PhysicalSettlementScheduler` as not yet an
implemented baseline contract.

This change adds that missing boundary: a scheduler that binds an already
-reserved capacity allocation to one durable, idempotent settlement resource,
before any provider executes against it.

## What Changes

- Add `PhysicalSettlementScheduler.select_resource(request)`, keyed durably
  and idempotently by `allocation_id`: repeated calls for the same
  allocation return the existing binding rather than selecting another
  resource.
- Add the `PhysicalSettlementRequest` and `SettlementResource` shapes.
  A request carries either fungible pool/capacity attributes or an explicit
  `resource_id` for the specific-resource opt-in path; the scheduler honors
  whichever is supplied.
- Implement bottleneck-normalized least-loaded pool selection for the
  fungible path: the eligible pool with the lowest maximum per-dimension
  utilization (CPU/RAM/GPU/disk) is selected. This is a lightweight,
  schema-free slice of Dominant Resource Fairness; full DRF (weighting by
  each request's own resource shape) is deliberately deferred.
- Extend capacity reservations to carry lease-shaped `start`/`end` windows
  (mirroring executor leases) and add a periodic reservation-expiry
  watchdog, generalized from the existing `LeaseWatchdog` thin-timer
  pattern, so uncommitted holds expire without depending on storefront-side
  polling. The storefront continues to hold only a cached capacity
  projection; the site authority remains the sole source of truth per site.
- Add a guardrail to `ResourcePoolService.disable_pool`: a pool with an
  active settlement-resource binding cannot be disabled. (Previously a
  documented no-op — "the check will be added once the scheduler creates
  something to check.")
- **Correct POOLS-1 behavior:** remove `_ensure_default_pool_enabled`'s
  blanket rejection of disabling the `default` pool (create/replace/patch/
  import all currently reject `enabled=false` for `default`). `default`
  MUST still always exist under its configured ID and remain the fallback
  for hosts/create-requests that omit a pool ID, but disabling it is
  otherwise ordinary — it only excludes `default` from new scheduler
  selection, and is subject to the same active-binding guardrail as any
  other pool.

## Non-Goals

- **Settlement-resource persistence.** No new table or durable row lands in
  this change; idempotency is exercised at the scheduler's own boundary
  within this change's test scope. Durable `SettlementRecord` storage
  (`provider_metadata`, `credentials_ref`, `state`) is `pools-3` work, which
  is expected to extend the same binding identity rather than introduce a
  second one.
- **`FulfillmentProvider` execution.** No provider ABC, `ProviderRegistry`,
  or Ansible implementation change lands here. Nothing calls
  `select_resource` from a real provisioning path yet.
- **Specific-resource listing/opt-in configuration.** Whether opt-in lives at
  resource, pool, provisioning-service, or storefront level is unresolved by
  design; this change only ensures an explicit `resource_id`, if supplied, is
  honored without substitution.
- **Full Dominant Resource Fairness.** Weighting selection by each request's
  own resource shape (not just each pool's current load) is deferred past
  this change.
- **Storefront-side reservation cleanup.** Removing the `vm_host` requirement
  from `CapacityLedgerService`'s ordinary reservation path and renaming
  `SiteLedger`/`SiteResourcesService` toward capacity language is `pools-4`
  work; this change only supplies the lease-window/watchdog expiry model
  that `pools-4` will apply to the storefront-facing path.

## Capabilities

### New Capabilities

None. `physical-provisioning`'s purpose already scopes scheduling and
fulfillment; it has simply not implemented the scheduler half yet.

### Modified Capabilities

- `physical-provisioning`: adds the `PhysicalSettlementScheduler` contract,
  idempotent allocation-keyed resource binding, and bottleneck-normalized
  pool selection.
- `site-capacity`: capacity reservations gain lease-shaped windows and a
  watchdog-driven expiry path alongside the existing lazy TTL check.
- `resource-pool-management`: `disable_pool` rejects disabling a pool with an
  active settlement-resource binding.

## Dependencies and Related Changes

- Requires `pools-1-resource-pool-foundation` (archived): pool identity,
  provider configuration, and host membership.
- Precedes not-yet-drafted `pools-3` (`FulfillmentProvider` ABC + Ansible
  implementation + `SettlementRecord` persistence) and `pools-4` (storefront
  capacity boundary cleanup, which applies this change's reservation-expiry
  model to the storefront-facing path).

## Impact

- **Packages:** `provisioning/compute` (scheduler, selection algorithm,
  request/response shapes), `kit/site` (lease-shaped reservation windows),
  and the VM provisioning composition root (reservation-expiry watchdog,
  `disable_pool` guardrail wiring).
- **Database:** none. No migration in this change.
- **API:** none new. The scheduler is not yet wired to a caller-facing route;
  wiring it into a real settlement path is `pools-3` work.
- **Compatibility:** no wire or persistence break. Existing pool and
  reservation behavior is unchanged for callers that do not use the
  scheduler, with one deliberate exception: `PoolReplace`/`PoolUpdate`/
  import calls that set `default`'s `enabled=false` currently fail with
  `default_pool_disabled` and will start succeeding. Any caller or test
  relying on that rejection needs updating.
