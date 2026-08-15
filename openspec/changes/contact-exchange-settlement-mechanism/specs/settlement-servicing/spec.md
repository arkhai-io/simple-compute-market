## ADDED Requirements

### Requirement: Non-financial obligations are serviceable

An obligation with no amount, no asset, and no funding requirement MUST be a valid
obligation when its mechanism declares a non-financial deliverable. Servicing MUST
materialize it to ready on the mechanism's availability signal, report it satisfied,
and produce a receipt referencing the accepted `service_terms`, without requiring
funding state, a chain client, or an expiration-driven reclaim path.

#### Scenario: Servicing an introduction obligation

- **WHEN** a `contact_exchange.v1` obligation is registered and its mechanism reports
  the introduction available
- **THEN** the runtime records it ready, completes collection with a receipt, and no
  funding or reclaim machinery is invoked
