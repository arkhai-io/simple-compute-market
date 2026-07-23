# Site capacity delta

## ADDED Requirements

### Requirement: Reservation exposes settlement-validation data

A Capacity Reservation SHALL expose sufficient identity, state, expiry, requested units or shape, resource kind, and deal relationship data for settlement validation.

#### Scenario: Unknown reservation

- **WHEN** scheduling references an allocation identifier that does not exist
- **THEN** scheduling fails with an entity-not-found error.

#### Scenario: Expired reservation

- **GIVEN** a reservation whose hold expiry has passed
- **WHEN** scheduling is requested
- **THEN** scheduling fails with a reservation-expired error.

#### Scenario: Agreement or represented terms mismatch

- **GIVEN** a reservation whose recorded agreement, market, or terms differ from the request
- **WHEN** scheduling is requested
- **THEN** scheduling fails with a request-mismatch error.

### Requirement: Concrete capacity claim and assignment are atomic

The durable architecture SHALL claim concrete-resource capacity and persist the Capacity Settlement Assignment atomically with assignment idempotency and cursor advancement.

#### Scenario: Concurrent assignments compete for one resource

- **GIVEN** two concurrent reservations and capacity sufficient for only one
- **WHEN** both assignments are attempted
- **THEN** at most one transaction claims the capacity
- **AND** the other request receives no eligible resource or retries against updated state.

### Requirement: Intermediate reservation constraint is documented

Until the durable assignment transaction is implemented, the concrete site-ledger reservation and process-local assignment/cursor storage SHALL remain documented as intermediate constraints rather than distributed-idempotency guarantees.

#### Scenario: Process restart loses in-memory assignment state

- **GIVEN** a Capacity Settlement Assignment recorded only in process-local memory
- **WHEN** the provisioning service process restarts
- **THEN** the assignment and policy cursor state are lost
- **AND** a retry of the same reservation is scheduled as if for the first time, rather than idempotently returning the prior assignment.

#### Scenario: Multiple service instances do not share assignment state

- **GIVEN** two running instances of the provisioning service, each with independent process-local assignment storage
- **WHEN** the same reservation is scheduled against both instances
- **THEN** each instance may independently record its own assignment
- **AND** idempotency is guaranteed only within one process, not across the deployment, until the durable assignment transaction replaces process-local storage.
