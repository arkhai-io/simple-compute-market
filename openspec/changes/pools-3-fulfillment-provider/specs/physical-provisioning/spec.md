## ADDED Requirements

### Requirement: Provider-owned fulfillment execution

The provisioning service MUST expose a `FulfillmentProvider` contract that
performs create/status/teardown operations against an already-selected
`SettlementResource`, and a provider MUST NOT independently select or
substitute a different resource without returning to the scheduler
boundary. `create(...)` MUST be dispatch-only: it submits underlying
provider work and returns once dispatched, without blocking until that
work reaches a terminal state; `get_status(...)` MUST be the mechanism by
which completion, in-progress, and failure states are subsequently
observed.

#### Scenario: Provider executes against a selected resource

- **WHEN** a `FulfillmentProvider` receives a `SettlementResource` selected by the scheduler
- **THEN** it performs its operation against that resource without requesting or substituting another one

#### Scenario: Create is retried after partial delivery

- **WHEN** `create(...)` is called twice for the same `allocation_id`
- **THEN** the provider detects the existing dispatch rather than double-provisioning

#### Scenario: Create returns before completion

- **WHEN** `create(...)` is called for an allocation
- **THEN** it returns a `FulfillmentResult` carrying a pending indicator and enough provider metadata to resume tracking, without waiting for the underlying provider job to finish

### Requirement: Registry-resolved provider selection

The provisioning service MUST resolve a `FulfillmentProvider` by provider
string through a `ProviderRegistry`, and lifecycle code MUST NOT branch on
concrete provider identity.

#### Scenario: Unregistered provider is requested

- **WHEN** a settlement record names a provider with no registered `FulfillmentProvider`
- **THEN** resolution fails with an actionable provider-not-found error before any execution is attempted

### Requirement: Durable settlement record

The provisioning service MUST persist a `SettlementRecord` extending the
scheduler's `allocation_id`-keyed binding with provider metadata,
a credentials reference, and lifecycle state (`pending` / `active` /
`failed`). `SettlementRecord` MUST NOT reference the storefront's
`settlement_claims`/`mechanism_state` (`ClaimsEngine`) — physical
settlement and financial claim collection are independent tracking
systems.

#### Scenario: Fulfillment is dispatched

- **WHEN** a `FulfillmentProvider`'s `create(...)` is called
- **THEN** the persisted settlement record is created in `pending` state with enough provider metadata to resume status tracking

#### Scenario: Fulfillment completes

- **WHEN** `get_status(...)` reports the dispatched work has finished successfully
- **THEN** the persisted settlement record moves to `active` and carries a credentials reference rather than inline sensitive material

## Out of Scope for This Delta

- Wiring `LeaseLifecycleService`/`ExecutorReleaseDispatcher`/
  `VmReleaseExecutor` to resolve providers through `ProviderRegistry` for
  teardown — no `SettlementRecord` has a production caller yet, so there is
  nothing live to release through it. Deferred to
  `pools-7-storefront-fulfillment-cutover`.
- Any change to `PhysicalSettlementScheduler`'s in-memory assignment
  storage — remains non-durable, as `pools-2` left it. Also deferred to
  `pools-7-storefront-fulfillment-cutover`.
- Any caller invoking `select_resource` + `create` together.
