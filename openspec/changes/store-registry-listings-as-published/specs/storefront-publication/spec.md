## ADDED Requirements

### Requirement: Resolved rate structures are published at listing level

A VM storefront MUST publish its resolved family rate structure as top-level
`rate_structure`, when present, on creation, refresh and reopen. The published
structure MUST match the durable rates the storefront serves and uses to derive
shape prices. It MUST NOT be placed inside `listing_resource` or interpreted by
the registry engine. Flat-priced listings MUST state no resolved structure.
The existing asking rate remains independent in `listing_resource`.

#### Scenario: A shape-priced listing is published

- **WHEN** a storefront derives a listing with resolved family rates
- **THEN** the registry publication carries those rates as top-level rate_structure
- **AND** buyers can verify them against retained seller publication evidence

#### Scenario: Family rates change or are withdrawn

- **WHEN** reconciliation refreshes a listing with changed or absent resolved rates
- **THEN** the complete republication replaces the previous rate_structure accordingly

#### Scenario: A listing reopens

- **WHEN** the storefront reopens a previously closed listing
- **THEN** it republishes its current durable rate structure before reopening discovery
