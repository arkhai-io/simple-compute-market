## ADDED Requirements

### Requirement: The compute schema names its family, not one domain

The compute-family filter specification MUST declare a schema identity naming the
family rather than a single domain within it, since the schema carries bare-metal,
virtual-machine, and container listings alike. Buyer commands declare compatibility
with a schema identity, so changing it is backwards-incompatible and MUST bump the
specification version and the schema version together.

#### Scenario: A buyer declares schema compatibility

- **WHEN** a buyer command declares the compute-family schema identity it understands
- **THEN** it queries only registries declaring that identity
- **AND** a registry serving the retired identity is not queried

### Requirement: The published listing shape is named for the seller's listing

A registry's published listing shape MUST be named `listing_resource`, and the
offering-mode field within it MUST be named `offering_mode`. A registry MUST NOT
accept a second spelling of either, and `offer` MUST NOT name a published shape —
including as a client-side attribute or request field holding that shape, since a
second spelling in a client is the same collision as a second spelling on the wire.
A registry's own responses MUST NOT report a derived tag named for the retired shape
key.

Renaming a required field of the listing shape and its filter is
backwards-incompatible and MUST bump the specification version.

#### Scenario: A listing is published under the retired shape key

- **WHEN** a publisher submits a listing carrying its shape under `offer_resource` or `offer`
- **THEN** the submission is rejected rather than accepted under a second spelling

#### Scenario: A validation response reports the shape it checked

- **WHEN** a publisher dry-runs a listing against the registry's listing shape
- **THEN** the response reports validity and the listing identity without a resource-type tag naming the retired shape key

#### Scenario: A buyer filters on the offering mode

- **WHEN** a buyer filters listings by offering mode
- **THEN** the filter reads `listing_resource.offering_mode`
- **AND** a listing publishing no offering mode is excluded rather than matching
