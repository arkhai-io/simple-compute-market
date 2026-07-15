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
`FulfillmentService` boundary.

#### Scenario: Equivalent create request is retried

- **WHEN** create is requested again for the same allocation with the same agreement, selected resource, provider, and fulfillment identity
- **THEN** the existing fulfillment is returned and no second provider operation is dispatched

#### Scenario: Allocation is reused inconsistently

- **WHEN** create is requested for an existing allocation with conflicting agreement, resource, provider, or fulfillment identity
- **THEN** the request fails with a fulfillment-conflict error before another provider operation is dispatched

#### Scenario: Teardown request is retried

- **WHEN** teardown is requested more than once for the same fulfillment
- **THEN** the provider/lifecycle boundary detects the existing teardown or completed absence and does not dispatch uncontrolled duplicate work

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

`AnsiblePoolConfig` MUST NOT include `inventory_group`. The Ansible provider
MUST execute against the concrete Settlement Resource selected by the scheduler
and MUST NOT use an inventory group as an alternate placement mechanism.

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
