## ADDED Requirements

### Requirement: Preserving PostgreSQL registry rollout

An independently operated production registry MUST be deployable on PostgreSQL using Alembic as the schema authority. A blank database and every supported existing registry schema MUST migrate to the complete expected head before application rollout, and runtime startup MUST reject incompatible schema without applying DDL.

#### Scenario: Blank PostgreSQL database is prepared

- **WHEN** the packaged migration command upgrades an empty supported PostgreSQL database to head
- **THEN** every current registry table, column, index, constraint, and deterministic invariant exists without ORM `create_all`

#### Scenario: Existing registry is cut over

- **WHEN** an operator migrates a supported SQLite registry to PostgreSQL
- **THEN** publishers, listings and demands, API-key hashes/scopes, stable public identifiers, and sequence continuation are preserved and verified before traffic switches

#### Scenario: Migration preparation fails

- **WHEN** the pre-rollout migration Job or verification fails
- **THEN** registry application rollout does not begin and the prior authoritative database remains available for the rehearsed rollback procedure

### Requirement: PostgreSQL deployment state

PostgreSQL registry mode MUST use Secret-backed connection configuration and MUST NOT depend on an application-local SQLite PVC, `Recreate` rollout, or in-process schema bootstrap.

#### Scenario: PostgreSQL mode renders

- **WHEN** the registry is configured for external PostgreSQL
- **THEN** deployment resources reference the connection Secret and migration phase without rendering the SQLite persistence/rollout assumptions
