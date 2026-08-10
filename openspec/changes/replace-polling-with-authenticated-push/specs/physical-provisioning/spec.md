## ADDED Requirements

### Requirement: Authority-originated events are delivered, not polled for

A provisioning authority MUST deliver lifecycle, capacity, and projection events to the
storefront that owns them over its authenticated outbound channel, rather than requiring
the storefront to poll for them. Each event MUST be recorded in a durable outbox written
in the same transaction as the state change it reports, MUST carry stable event
identity, and MUST be delivered at least once with capped retry and observable delivery
state. Delivery MUST NOT be the correctness path: every pull endpoint it accelerates MUST
remain available and authoritative.

#### Scenario: A reportable transition occurs

- **WHEN** an authority commits a state change the storefront needs to observe
- **THEN** the event is recorded in the outbox within the same transaction, and delivered
  over the authenticated channel

#### Scenario: The transaction rolls back

- **WHEN** a reported transition rolls back
- **THEN** no event for it is delivered, because the outbox write rolled back with it

#### Scenario: Delivery fails repeatedly

- **WHEN** delivery fails beyond the retry cap
- **THEN** the failure is observable and replayable, and the storefront can still reach
  the same state through the pull endpoint

#### Scenario: Delivery is disabled entirely

- **WHEN** event delivery is disabled
- **THEN** the system remains correct through pull reconciliation and local recovery,
  and is only slower

#### Scenario: An event stream already has ordering semantics

- **WHEN** the underlying data is a versioned feed with its own cursor and gap recovery
- **THEN** delivery notifies that the feed advanced rather than replacing the feed's own
  ordering and recovery behavior
