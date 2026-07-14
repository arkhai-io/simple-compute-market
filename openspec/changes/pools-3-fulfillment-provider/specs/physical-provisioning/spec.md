## ADDED Requirements

### Requirement: Provider-owned fulfillment execution

The provisioning service MUST expose a `FulfillmentProvider` contract that
performs create/status/teardown operations against an already-selected
`SettlementResource`, and a provider MUST NOT independently select or
substitute a different resource without returning to the scheduler
boundary.

#### Scenario: Provider executes against a selected resource

- **WHEN** a `FulfillmentProvider` receives a `SettlementResource` selected by the scheduler
- **THEN** it performs its operation against that resource without requesting or substituting another one

#### Scenario: Create is retried after partial delivery

- **WHEN** `create(...)` is called twice for the same `allocation_id`
- **THEN** the provider detects the existing resource rather than double-provisioning

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
a credentials reference, and lifecycle state.

#### Scenario: Fulfillment completes

- **WHEN** a `FulfillmentProvider`'s `create(...)` succeeds
- **THEN** the persisted settlement record carries the provider metadata and a credentials reference rather than inline sensitive material
