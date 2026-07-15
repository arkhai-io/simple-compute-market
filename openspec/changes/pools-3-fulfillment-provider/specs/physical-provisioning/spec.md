## ADDED Requirements

### Requirement: Fulfillment service owns physical dispatch consistency

The provisioning service MUST expose a `FulfillmentService` that validates and
coordinates fulfillment against a scheduler-selected `SettlementResource`.
The storefront MAY own the surrounding business workflow, but it MUST NOT be
the authority for duplicate physical dispatch or directly select a replacement
resource.

#### Scenario: Storefront begins physical fulfillment

- **WHEN** the storefront requests fulfillment for a Capacity Reservation
- **THEN** the provisioning `FulfillmentService` validates the request, resolves the provider, and dispatches against the already-selected Settlement Resource

### Requirement: Providers execute without placement

A `FulfillmentProvider` MUST perform create, status, and teardown operations
against the supplied `SettlementResource` and MUST NOT independently select or
substitute a different physical resource.

#### Scenario: Provider cannot use the selected resource

- **WHEN** a provider determines that the supplied Settlement Resource cannot be used
- **THEN** it returns an actionable failure instead of silently executing against another resource

### Requirement: Asynchronous provider operations

Provider create and teardown operations MUST be dispatch-only. Each operation
MUST return a `FulfillmentResult` containing enough provider metadata to resume
tracking without waiting for the underlying work to complete.

#### Scenario: Create returns before completion

- **WHEN** create is accepted for an allocation
- **THEN** it returns provider tracking metadata while the normalized provider state remains `pending`

#### Scenario: Teardown returns before completion

- **WHEN** teardown is accepted for an allocation
- **THEN** it returns provider tracking metadata without holding the caller until physical teardown completes

### Requirement: Normalized provider operation state

`ProviderStatus` MUST report one of `pending`, `succeeded`, `failed`, or
`unknown`. Provider-specific job states MUST be translated to these values
before returning across the provider boundary.

#### Scenario: Ansible job completes successfully

- **WHEN** the underlying Ansible job reaches its successful terminal state
- **THEN** the provider reports `succeeded`

#### Scenario: Provider status cannot be determined

- **WHEN** the provider cannot read or identify the underlying operation
- **THEN** it reports `unknown` and the fulfillment layer does not infer success

### Requirement: Idempotent fulfillment identity

Fulfillment MUST be idempotent on `allocation_id` at the
`FulfillmentService` boundary. Equivalence for a retried `create` is scoped
to `agreement_id`, `market`, `terms` (from the request) and the entire
selected `SettlementResource` — not the request's optional `resource_id`,
which is a selection constraint rather than part of fulfillment identity.
Once `create` has registered a fulfillment for an `allocation_id`,
`FulfillmentService` MUST resolve the resource, provider, and provider
metadata for that allocation from its own stored state for `teardown` and
`get_status` — callers do not supply them.

#### Scenario: Equivalent create request is retried

- **WHEN** create is requested again for the same allocation with matching agreement, market, terms, and selected resource
- **THEN** the existing fulfillment is returned and no second provider operation is dispatched

#### Scenario: Allocation is reused inconsistently

- **WHEN** create is requested for an existing allocation where agreement, market, terms, or the selected resource differs from the stored fulfillment
- **THEN** the request fails with a fulfillment-conflict error before another provider operation is dispatched

#### Scenario: Teardown request is retried

- **WHEN** teardown is requested more than once for the same `allocation_id`
- **THEN** `FulfillmentService` returns the stored teardown result rather than dispatching a second provider operation

### Requirement: Registry-resolved provider selection

The provisioning service MUST resolve providers by provider string through a
`ProviderRegistry`. Fulfillment and lifecycle code MUST NOT branch on concrete
provider identity.

#### Scenario: Unregistered provider is requested

- **WHEN** fulfillment names a provider with no registered implementation
- **THEN** resolution fails with an actionable provider-not-found error before execution

### Requirement: Pool provider configuration is snapshotted at dispatch

The Ansible provider MUST resolve the selected resource pool's generic provider
configuration, validate it, translate it to executor inputs, and persist a
snapshot with the submitted operation.

#### Scenario: Pool configuration changes after dispatch

- **WHEN** an operator edits the pool after a fulfillment operation has been accepted
- **THEN** the already-accepted operation continues using the configuration snapshot captured at dispatch

### Requirement: Ansible placement remains scheduler-owned

The Ansible provider's typed pool configuration MUST NOT include
`inventory_group`, and the provider MUST execute against the concrete
Settlement Resource selected by the scheduler rather than using an inventory
group as an alternate placement mechanism. This applies to the provider's
own configuration type only — it does not require changing the persisted
pool-configuration schema or its validation.

#### Scenario: Ansible job is constructed

- **WHEN** the Ansible provider dispatches work
- **THEN** the selected settlement resource determines the execution target

### Requirement: Fulfillment metadata supports later teardown

The fulfillment representation MUST retain the selected resource, provider, and
opaque provider metadata needed to resume status observation and later dispatch
teardown after process restart. POOLS-3 MUST NOT introduce a new credential
publication or secret-distribution system.

#### Scenario: Create completes and teardown occurs later

- **WHEN** a lease later reaches its teardown path
- **THEN** the persisted fulfillment metadata is sufficient to resolve the provider and target the original settlement resource

## Out of Scope for This Delta

- Storefront call-path cutover.
- Durable ORM design and migration.
- Database uniqueness and transaction mechanics; these are required in POOLS-7
  and MUST replace process-local locking as the correctness mechanism.
- Final teardown state transitions, retention, and capacity notification.
- Changes to `PhysicalSettlementScheduler` assignment persistence.
