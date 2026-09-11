## ADDED Requirements

### Requirement: The capacity resource is the unit of projection

The resource-pool projection SHALL enumerate declared capacity resources and
correlate executor host inventory into each projected entry. Executor
correlation SHALL be optional per-entry metadata rather than a precondition for
projecting a declared resource. A declared capacity resource with no correlated
host SHALL project with its declared capacity, attributes, and Physical Resource
identity.

Several capacity resources mapping to one executor identity SHALL remain an
error rather than resolving to one of them.

#### Scenario: A declared resource has no executor host

- **GIVEN** a capacity resource is declared with no host inventory record
  correlating to it
- **WHEN** the resource-pool projection is produced
- **THEN** the resource appears in the projection with its declared capacity and
  attributes
- **AND** no entry is omitted merely because executor inventory is absent

#### Scenario: Every declared resource has an executor host

- **GIVEN** a deployment in which every declared capacity resource correlates to
  a host inventory record
- **WHEN** the resource-pool projection is produced
- **THEN** the projection is unchanged from one produced by enumerating host
  inventory

#### Scenario: Two declarations claim one executor identity

- **WHEN** more than one declared capacity resource correlates to the same
  executor identity
- **THEN** projection fails rather than selecting one of them

### Requirement: An uncorrelated entry omits executor fields

A projected entry with no correlated executor host SHALL omit its
executor-correlated fields rather than emitting empty values for them, so a
consumer can distinguish an absent correlation from a correlated host whose
identifier failed to populate.

#### Scenario: A consumer reads an uncorrelated entry

- **GIVEN** a projected entry for a declared resource with no correlated host
- **WHEN** a storefront ingests that entry
- **THEN** the executor-correlated fields are absent rather than empty
- **AND** the storefront's reconciler continues to treat absence as distinct
  from zero

### Requirement: Execution paths require executor correlation

Placement, provider dispatch, and rendered executor inventory SHALL require
executor correlation and SHALL fail closed for a capacity resource that has
none. Projecting a declared resource without executor correlation SHALL NOT make
it schedulable or dispatchable.

#### Scenario: An uncorrelated resource reaches placement

- **WHEN** placement is attempted for a capacity resource with no correlated
  executor host
- **THEN** placement is refused
- **AND** no provider dispatch occurs

#### Scenario: Executor inventory is rendered

- **GIVEN** declared capacity resources of which some have no correlated host
- **WHEN** executor inventory is rendered
- **THEN** uncorrelated resources are excluded entirely rather than rendered with
  an absent address
