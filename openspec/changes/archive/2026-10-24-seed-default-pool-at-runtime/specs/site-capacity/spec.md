## MODIFIED Requirements

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

Every declaration MUST name its Resource Pool. A registration request that omits the
pool MUST be rejected at request validation rather than recorded against a default,
because registration replaces the whole declaration and a silently defaulted pool is
a reassignment nobody requested. A declaration naming a pool the site does not have
MUST be refused, whether it arrives as a registration or a document entry. A stored
declaration with no recorded pool MUST NOT be read as belonging to any pool.

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

#### Scenario: Registration names a pool that does not exist

- **WHEN** a capacity registration names a Resource Pool the site does not have
- **THEN** it is refused as invalid and no declaration is written or changed

#### Scenario: Registration omits the pool

- **WHEN** a capacity registration request carries no pool identifier
- **THEN** it is rejected at request validation and no declaration is written or changed

#### Scenario: Declaration omits a dimension

- **WHEN** a capacity declaration carries only some dimensions
- **THEN** the authority accepts it and treats the omitted dimensions as undeclared
  rather than rejecting the declaration or substituting a value from another record

#### Scenario: A stored declaration has no pool

- **WHEN** a stored declaration carries no pool identifier
- **THEN** it is not projected, admitted against, or moved as a member of any pool, including one named `default`
