## ADDED Requirements

### Requirement: Optional durable Settlement Result push

After durable pull-readable fulfillment results exist, a provisioning service MAY notify an owning storefront through a transactional outbox. Push delivery MUST be at least once, MUST retain stable event/result identity across retries and restart, and MUST NOT replace pull reconciliation as the correctness authority.

#### Scenario: Result transition commits

- **WHEN** fulfillment commits a new reportable result generation
- **THEN** the same transaction records a non-secret outbox event for the trusted owner binding

#### Scenario: Delivery is lost or duplicated

- **WHEN** a receiver acknowledgment is lost or the worker retries after restart
- **THEN** the same stable event/result generation is redelivered and converges idempotently with pull-visible state

#### Scenario: Storefront misses every push

- **WHEN** a storefront restores local state after notifications expired or were unavailable
- **THEN** it reconstructs the authoritative result through pull status/result APIs
