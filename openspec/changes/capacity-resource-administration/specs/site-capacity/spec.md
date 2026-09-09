## ADDED Requirements

### Requirement: Operator-administered capacity declarations

A site authority MUST accept operator-administered capacity resources as the
authoritative declaration of sellable capacity for one Physical Resource identity,
across every capacity dimension the declaration carries. A declaration is
authoritative for shape and quantity — what is declared sellable and how much of
it there is. Whether that declaration may be admitted against is a separate
property resolved outside the declaration, and a capacity resource MUST remain a
complete and authoritative declaration of its own shape regardless of that
property. A capacity declaration MUST be able to
express more than one dimension, and the authority MUST NOT require any particular
dimension to be present. Where an operator has declared capacity for a Physical
Resource, no other inventory record SHALL supply or override that resource's
projected capacity.

#### Scenario: Shape authority is not admission authority

- **WHEN** a consumer reads a declared capacity resource
- **THEN** the declared shape and quantity are authoritative
- **AND** whether the declaration may be admitted against is resolved outside the declaration itself

#### Scenario: Operator declares multidimensional capacity

- **WHEN** an operator registers a capacity resource declaring several dimensions for
  a Physical Resource
- **THEN** the site authority records every declared dimension and admission,
  matching, and projection all read the declared values

#### Scenario: Declared capacity supersedes any other inventory record

- **WHEN** a Physical Resource has both an operator-declared capacity resource and an
  inventory record elsewhere describing the same resource
- **THEN** the declared capacity resource is authoritative and the other record does
  not contribute capacity

#### Scenario: Declaration omits a dimension

- **WHEN** a capacity declaration carries only some dimensions
- **THEN** the authority accepts it and treats the omitted dimensions as undeclared
  rather than rejecting the declaration or substituting a value from another record

### Requirement: Projected inventory is internally consistent

Projected physical inventory MUST NOT report attribute values that contradict the
same resource's projected capacity. A projected resource's capacity and its
descriptive attributes MUST derive from one authoritative record for that resource.

#### Scenario: Declared capacity disagrees with a legacy inventory value

- **WHEN** an operator-declared capacity resource reports a different quantity for a
  dimension than a legacy inventory record holds for the same resource
- **THEN** the projection reports the declared value in both capacity and any
  corresponding attribute, and never reports the two disagreeing in one projected row

#### Scenario: Categorical hardware identity is projected

- **WHEN** a capacity declaration carries a categorical hardware attribute matched by
  equality rather than by sufficiency
- **THEN** the projection reports it as an attribute rather than as a capacity
  dimension, sourced from the same authoritative record as the capacity

### Requirement: A capacity declaration names no mandatory dimension

A capacity authority MUST accept a declaration expressing any set of dimensions and
MUST NOT write a dimension the caller did not declare. Where a legacy scalar unit
mirror is maintained, the dimension it mirrors MUST be supplied by the composition
root, the way domain-specific claim aliases already are, rather than fixed in the
shared capacity module.

Where a caller declares capacity explicitly, the authority MUST NOT add a mirror
dimension to that declaration. A declaration naming only dimensions a domain owns —
for example a credit balance with no compute dimension — MUST be stored as declared.

#### Scenario: A declaration names no compute dimension

- **WHEN** an operator declares capacity consisting only of a domain's own unit dimension
- **THEN** the stored declaration contains exactly that dimension
- **AND** no GPU or other compute dimension is manufactured

#### Scenario: A composition supplies its mirror dimension

- **WHEN** a composition root configures which dimension the legacy scalar mirror tracks
- **THEN** that dimension is used for the mirror in that composition
- **AND** no other composition's dimension name appears in it

### Requirement: A capacity resource does not move pools under live obligations

A capacity resource MUST NOT be reassigned from one Resource Pool to another while
it has a live capacity obligation — a hold, a reservation, an assignment, or a
workload — whose authority is resolved through its pool. A reassignment request in
that state MUST be refused, and the resource MUST remain in its current pool.

A reservation's pool is resolved through the resource's current pool rather than
recorded on the reservation, so reassignment would otherwise rewrite the authority
underneath an existing obligation without that obligation changing. This applies to
every reassignment, including moving a resource to a pool declaring a different
provider or different capacity backing.

#### Scenario: A resource with a live reservation is reassigned

- **WHEN** a reassignment is requested for a capacity resource holding a live reservation
- **THEN** the request is refused and the resource remains in its current pool

#### Scenario: A drained resource is reassigned

- **WHEN** a reassignment is requested for a capacity resource with no live capacity obligation
- **THEN** the reassignment succeeds

#### Scenario: An unbacked resource is reassigned

- **GIVEN** a capacity resource in a pool declaring no capacity backing, which therefore holds no reservations
- **WHEN** it is reassigned to a pool declaring capacity backing
- **THEN** the reassignment succeeds
