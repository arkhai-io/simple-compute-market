## Why

The provisioning service has no formal abstraction separating physical
settlement *operations* from lifecycle and job-management machinery.
`pools-2-physical-settlement-scheduler` selects a `SettlementResource` but
nothing yet executes against it, and `pools-2` explicitly defers durable
storage of that binding. Without a provider boundary, future domain
provisioning services would have to duplicate VM-domain execution code or
depend on it directly.

## What Changes

- Define `FulfillmentProvider` (ABC), `FulfillmentResult`, and
  `ProviderStatus` in the VM provisioning service. A provider receives an
  already-selected `SettlementResource` and performs `create`/
  `get_status`/`teardown` against it; it MUST NOT independently select or
  substitute a different resource.
- Add durable `SettlementRecord` persistence, extending the same binding
  identity `pools-2` establishes (`allocation_id`) rather than creating a
  second, competing record — `pools-2` is deliberately non-durable and this
  is where that persistence lands.
- Implement `AnsibleFulfillmentProvider` around the existing
  `AnsibleJobService`/`AnsibleService`: resolve `AnsiblePoolConfig`, build
  Ansible variables, dispatch jobs, normalize results, and extract
  credentials for the selected resource. It owns execution, not placement.
- Keep `ProgrammableMockAnsibleService`'s `mockMode`-flag test seam inside
  the Ansible provider; do not promote it to the `FulfillmentProvider`
  level.
- Implement `ProviderRegistry.require(provider)`, constructed in the DI
  container at startup, mapping provider strings to `FulfillmentProvider`
  instances. Lifecycle code stays free of provider-specific branches.
- Rewire `LeaseLifecycleService`'s `release_delegate` to become a thin
  adapter around the selected provider's `teardown(...)`; the lifecycle
  state machine never learns which concrete mechanism executed.

## Non-Goals

- Kubernetes, cloud, storage, power, or bandwidth providers — Ansible only.
- Recreating the removed generic `provisioning_client` package.
- Any storefront-side change (`pools-4`).
- Extracting these contracts into a shared package (`pools-5` — conditional
  on a second domain actually needing them).

## Open Design-Review Topic (unresolved — not decided by this proposal)

The ownership boundary between `SettlementRecord` (provisioning-side,
physical-settlement state) and the storefront's `settlement_claims` /
`mechanism_state` in `ClaimsEngine` (market-side, on-chain claim
collection) is unresolved. These are parallel tracking systems for
different concerns — physical settlement vs. financial claim collection —
but the naming is close enough to invite confusion, and neither codebase
states the boundary explicitly today. Whether they reference each other
(and via what key), and whether `SettlementRecord` replaces any
storefront-side state, needs a design-review session before
implementation — this was true when originally written and remains true;
no design discussion has resolved it yet.

## Capabilities

### Modified Capabilities

- `physical-provisioning`: adds `FulfillmentProvider`, `ProviderRegistry`,
  and durable `SettlementRecord` persistence extending the `pools-2`
  binding.

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler` (not yet implemented):
  consumes its `SettlementResource` binding and extends its identity.
- Loosely precedes `pools-4-storefront-capacity-boundary`.
- `pools-5-shared-provisioning-package`'s residual scope (extracting these
  contracts to a shared package) is conditional on this change landing
  first.

## Impact

- **Packages:** `domains/vms/provisioning/service` (provider, registry,
  persistence); no change to `provisioning/compute` unless the plan step
  determines the scheduler itself should live there (see `pools-2`
  `design.md`, "carried-forward note").
- **Database:** new durable settlement-record storage, extending
  `pools-2`'s binding identity rather than adding a second table for the
  same key.
- **API:** none new required by this change alone; a caller-facing route
  wiring `select_resource` + `create` together is downstream work.
- **Compatibility:** existing `AnsibleJobService`/`AnsibleService` tests
  must pass unchanged — this change wraps, not replaces, that machinery.
