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

### Requirement: Pool membership follows the executor

Where a capacity declaration is correlated to an executor inventory record, that
executor's pool membership MUST be authoritative for the declaration, and every consumer
— physical-inventory projection, grouped-capacity projection, and reservation admission —
MUST resolve the declaration to that one pool. A declaration naming a pool other than its
executor's MUST be refused when it is written, rather than accepted and reconciled
differently by different readers. A declaration correlated to no executor MUST retain the
pool it declares, so a site may hold logical capacity that belongs to no physical
grouping. Pool membership MUST NOT be expressible as a descriptive attribute of a
declaration; a declaration carrying pool membership as an attribute MUST be refused,
naming the field that carries it.

#### Scenario: Declaration inherits its executor's pool

- **WHEN** an operator declares capacity for an executor that belongs to a pool
- **THEN** the declaration resolves to that pool for projection and for admission alike,
  without the operator restating it

#### Scenario: Declaration contradicts its executor's pool

- **WHEN** a capacity declaration names a pool other than the pool its executor belongs to
- **THEN** the site authority refuses the declaration and identifies both pools, rather
  than silently preferring either

#### Scenario: Logical capacity with no executor

- **WHEN** a declaration is correlated to no executor inventory record
- **THEN** the site authority accepts the pool the declaration names, and a site serving
  non-physical capacity is unaffected

#### Scenario: Pool membership offered as an attribute

- **WHEN** a declaration carries pool membership among its descriptive attributes
- **THEN** the site authority refuses it and names the field that carries pool membership,
  rather than accepting a second spelling no consumer reads

### Requirement: One capacity declaration per executor

A site authority MUST accept at most one capacity declaration per executor inventory
record, and MUST refuse a second declaration correlated to an executor another declaration
already claims. The refusal MUST occur when the declaration is written. Producing physical
inventory MUST NOT fail wholesale on an ambiguous correlation that predates this rule: the
ambiguous correlation is omitted and reported, and every unaffected pool at that site
continues to project, because a consumer cannot distinguish a failed projection from an
unreachable site.

#### Scenario: Second declaration claims a claimed executor

- **WHEN** an operator declares capacity for an executor another declaration already claims
- **THEN** the site authority refuses the new declaration and names the existing one

#### Scenario: Ambiguous correlation predating the rule

- **WHEN** physical inventory is produced for a site where two stored declarations
  correlate to one executor
- **THEN** the projection omits the ambiguous correlation, reports it, and continues to
  serve every other pool at that site rather than failing the whole projection
