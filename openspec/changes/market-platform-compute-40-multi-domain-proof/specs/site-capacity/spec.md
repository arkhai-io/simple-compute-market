## ADDED Requirements

### Requirement: Many-to-many selected-site ownership proof

Separately composed VM and bare-metal storefronts MUST each bind to more than one provisioning authority through operator-trusted site configuration. Every Capacity Reservation MUST retain the selected authority so scheduling, fulfillment, result observation, teardown, and release use that authority without post-reservation fallback.

#### Scenario: Both storefronts use both sites

- **WHEN** deterministic VM and bare-metal agreements are placed across two configured provisioning authorities
- **THEN** all four storefront-to-site relationships complete while each lifecycle remains bound to the authority that admitted its Capacity Reservation

#### Scenario: Storefront restarts after reservation

- **WHEN** a storefront loses process-local routing caches after one site admitted a reservation
- **THEN** it reloads the durable selected-site binding and routes the next state-changing call only to that authority

#### Scenario: Selected site is unavailable

- **WHEN** the authority owning an existing reservation is unavailable during fulfillment or teardown
- **THEN** the storefront reports or retries against that authority and does not submit the operation to another configured site

### Requirement: Cross-mode execution exclusion proof

Within one provisioning authority, shareable VM allocations and exclusive bare-metal allocations referring to one Physical Resource MUST conflict before executor work is submitted, regardless of pool, provider, or access aliases.

#### Scenario: VM allocation already holds the host

- **WHEN** a bare-metal agreement requests exclusive use of a Physical Resource with held VM capacity
- **THEN** reservation fails and no bare-metal executor job is created

#### Scenario: Bare-metal allocation already holds the host

- **WHEN** a VM agreement requests shareable capacity on a Physical Resource held exclusively for bare metal
- **THEN** reservation fails and no VM executor job is created

#### Scenario: Conflicting allocation is released

- **WHEN** executor teardown succeeds and authoritative allocation release commits
- **THEN** capacity version advances and a later eligible reservation may proceed
