## ADDED Requirements

### Requirement: Shape-bounds hint validation

Resource Pool policy metadata SHALL support a domain-neutral `shape_bounds` key mapping
each offering mode to a shape bounds declaration. Every surface capable of persisting a
Resource Pool's `policy_tags` — the bulk pool-document import path and the individual
pool admin API (`create`/`replace`/`update`) — SHALL refuse a `shape_bounds` value that
fails the admissibility kit's structural check, without changing the stored policy
metadata. Which families and fields are quantities SHALL NOT be validated here. A pool's
`listing_shapes` SHALL NOT be compared with its `shape_bounds` at write, because a
storefront's own tiers may widen a pool's bound.

#### Scenario: Operator submits a malformed declaration

- **WHEN** an operator submits `shape_bounds` whose `bounds` field states a `min` above
  its `max`, a non-positive value, or an unknown key, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored
  policy metadata

#### Scenario: Operator bounds a field no domain defines

- **WHEN** an operator submits a structurally well-formed declaration bounding a field the
  VM domain does not define
- **THEN** Resource Pool validation accepts it, and the VM storefront reports the pool's
  bounds as unusable when it derives listings

#### Scenario: A pool's listing shapes fall outside its own bounds

- **WHEN** an operator submits a pool whose `listing_shapes` include a shape outside its
  `shape_bounds`
- **THEN** Resource Pool validation accepts it
