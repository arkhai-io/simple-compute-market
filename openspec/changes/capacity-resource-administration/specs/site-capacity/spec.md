## ADDED Requirements

### Requirement: Operator-administered capacity declarations

A site authority MUST accept operator-administered capacity resources as the
authoritative declaration of a Physical Resource's sellable capacity, across every
capacity dimension the declaration carries. A capacity declaration MUST be able to
express more than one dimension, and the authority MUST NOT require any particular
dimension to be present. Where an operator has declared capacity for a Physical
Resource, no other inventory record SHALL supply or override that resource's
projected capacity.

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
