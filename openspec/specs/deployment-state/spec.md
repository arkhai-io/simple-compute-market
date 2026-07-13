# Deployment and State Specification

## Purpose

Define service topology, persistence ownership, migration execution, packaging, and rollout compatibility.

## Requirements

### Requirement: Role-separated deployment
Production topology MUST support independently operated registries, seller storefront/provisioning stacks, and ephemeral or long-running buyers; the local Anvil environment MUST remain a development-only fixture.

#### Scenario: Provider joins an existing market
- **WHEN** a provider deploys its node
- **THEN** it can point at an externally operated registry instead of requiring a private registry instance

### Requirement: Explicit persistence ownership
Each service MUST own its database and migration history; cross-service identifiers MUST cross APIs/events rather than relational foreign keys between service databases.

#### Scenario: A deal crosses a service boundary
- **WHEN** storefront settlement invokes provisioning
- **THEN** correlation identifiers cross the API while provisioning retains ownership of its allocation records

### Requirement: Service-owned migration history
Each stateful service MUST run and record its own ordered migration chain against its owned database.

#### Scenario: Database initialization is repeated
- **WHEN** a service initializes a database whose migrations are already applied
- **THEN** initialization leaves the schema at the same current version without duplicate schema changes

### Requirement: Installable package boundaries
Published wheels MUST resolve internal runtime dependencies by distribution version or a supplied wheel directory and MUST NOT encode parent-directory monorepo paths in customer-facing lock metadata.

#### Scenario: Wheel is installed outside the monorepo
- **WHEN** its dependencies are available from PyPI or `--find-links`
- **THEN** installation succeeds without the repository's relative directory layout

## Evidence

- Configurable registry endpoints and independently composed role stacks: core buyer registry configuration plus domain Compose and Helm manifests.
- Service-owned persistence and migration runners: registry Alembic tests and `domains/vms/provisioning/service/src/tests/unit/test_database.py`.
- Wheel-directory dependency resolution without parent-path UV sources: package `pyproject.toml` files and package Makefiles using `--find-links`.

Strict startup schema-drift rejection and compatibility-preserving non-additive registry rollout are proposed in `add-database-migration-commands` and `migrate-registry-to-postgres`; they are not current baseline behavior.
