## ADDED Requirements

### Requirement: A fulfillment attempt may be deferred to its domain's convergence

A fulfillment attempt MUST report one of three outcomes: fulfilled, failed, or deferred.
Deferred means work remains that the domain's own convergence will finish: the workload
exists, but a step after it did not complete. A deferred outcome MUST be persisted through
the domain, so the domain can leave its deal open; no fulfillment MAY be bound for it, and
servicing MUST NOT be woken for it.

#### Scenario: A domain defers a fulfillment

- **WHEN** a domain's fulfillment reports deferred
- **THEN** the outcome is persisted, no fulfillment reference is bound to the obligation,
  and servicing is not woken
