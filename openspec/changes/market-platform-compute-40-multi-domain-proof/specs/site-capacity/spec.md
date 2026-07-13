## ADDED Requirements

### Requirement: Multi-domain compute authority proof

One site authority MUST serve VM and bare-metal storefront ownership contexts while routing deal-scoped events by each allocation's recorded owner and publishing domain-neutral capacity versions.

#### Scenario: Two storefronts hold allocations

- **WHEN** VM and bare-metal deals reserve capacity through one authority
- **THEN** each allocation retains its own deal/storefront reference and subsequent lifecycle events reach only that owner

#### Scenario: Process-global storefront setting differs

- **WHEN** an allocation's recorded owner differs from any service default callback setting
- **THEN** event routing follows the allocation record rather than the process-global default

### Requirement: Cross-mode execution exclusion

Shareable VM allocations and exclusive bare-metal allocations referring to one Physical Resource MUST conflict before executor work is submitted.

#### Scenario: VM allocation already holds the host

- **WHEN** a bare-metal deal requests exclusive use of that Physical Resource
- **THEN** reservation fails and no bare-metal executor job is created

#### Scenario: Conflicting allocation is released

- **WHEN** executor release succeeds and the authoritative allocation release commits
- **THEN** capacity version advances and a later eligible reservation may proceed
