## ADDED Requirements

### Requirement: Explicit SQLite migration and runtime guard

Each stateful SQLite-backed seller or provisioning role MUST provide an idempotent packaged migration command and MUST run it before application startup. Ordinary runtime startup MUST verify schema compatibility without applying DDL and MUST fail actionably when schema is absent, behind, or incompatible.

#### Scenario: Fresh deployment starts

- **WHEN** a role is deployed with an empty database
- **THEN** its migration phase creates the current schema before the application process passes its startup guard

#### Scenario: Existing database is behind

- **WHEN** application startup observes an older supported schema because migration preparation did not complete
- **THEN** it exits without mutating schema and identifies the required migration command and observed/expected version

#### Scenario: Migration command is retried

- **WHEN** the packaged migration command runs more than once at the same version
- **THEN** it succeeds idempotently without losing current data or duplicating deterministic system rows

### Requirement: Composition-owned migration ordering

A concrete storefront composition MUST run shared core storefront migrations and its domain-specific migrations in a deterministic declared order and MUST expose one compatibility result to runtime startup.

#### Scenario: Domain migration fails

- **WHEN** shared migrations succeed but a composition-specific migration fails
- **THEN** application startup does not begin and the failure identifies the unsuccessful revision without claiming a compatible head
