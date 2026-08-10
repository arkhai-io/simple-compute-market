## ADDED Requirements

### Requirement: Pushed events are applied idempotently with durable deduplication

A storefront MUST apply delivered events idempotently and MUST persist the identity of
events it has already applied, so a duplicate delivered after a restart is not applied
twice. Pull reconciliation MUST remain available and authoritative for every state a
delivered event reports. Delivered invalidation of a cached projection MUST cause the
storefront to re-read that projection through its existing atomic-replace path rather
than applying a projection body carried in the event.

#### Scenario: The same event is delivered twice

- **WHEN** an event is delivered more than once, including across a storefront restart
- **THEN** its effect is applied once

#### Scenario: An event is never delivered

- **WHEN** an event is lost or never delivered
- **THEN** the storefront still reaches the same state through pull reconciliation or its
  local recovery sweep

#### Scenario: A cached projection is invalidated

- **WHEN** a storefront receives notice that a projection generation changed
- **THEN** it re-reads and atomically replaces that generation, rather than applying a
  projection body from the notification

#### Scenario: An unattributable event arrives

- **WHEN** a delivered event cannot be attributed to a registered site identity
- **THEN** it is rejected and not applied
