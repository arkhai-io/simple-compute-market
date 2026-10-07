## MODIFIED Requirements

### Requirement: Listing-shape hint validation

A Resource Pool management surface that accepts `listing_shapes` MUST require a mapping from
offering mode to a non-empty list of structurally well-formed stated listing shapes. A
well-formed stated listing shape is a non-empty mapping of family name to a non-empty
mapping of field name to either a scalar value or a structurally valid constraint mapping.
The check MUST be the shared structural split the shape admissibility kit provides, which
applies the capability shape utility's structural check to the base shape, and MUST NOT
depend on any domain's family or field names. Which families and fields are meaningful,
which are required, and which may carry constraints MUST be validated by the domain that
reads the hint. A pool's stated shapes MUST NOT be judged against any storefront's
configured constraints at write. Every surface capable of persisting a Resource Pool's
`policy_tags` MUST apply the same check: the bulk pool-document import path and the
individual pool admin API (`create`/`replace`/`update`).

#### Scenario: Operator supplies a malformed shape list

- **WHEN** an operator submits `listing_shapes` whose VM list is empty, or whose shape
  holds a family that is not a mapping, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy
  metadata

#### Scenario: Operator names a field no domain defines

- **WHEN** an operator submits a structurally well-formed shape naming a field the VM domain
  does not define
- **THEN** Resource Pool validation accepts it, and the VM storefront reports the pool's
  shapes as unreadable when it derives listings

#### Scenario: Operator supplies a malformed constraint

- **WHEN** an operator submits a stated shape whose constraint mapping states a `min`
  above its `max`, a non-positive value, an `offer` outside its own range, no key, or an
  unknown key, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy
  metadata

#### Scenario: Operator constrains an attribute

- **WHEN** an operator submits a structurally valid constraint mapping on a field the VM
  domain defines as an attribute
- **THEN** Resource Pool validation accepts it, and the VM storefront reports that
  listing's constraints as unusable when it derives listings
