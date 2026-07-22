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
Each stateful service MUST run and record its own ordered migration chain against its owned database; a deployed provisioning service MUST apply pending migrations before application startup and MUST reject schema drift from its normal startup path instead of applying migrations in-process.

#### Scenario: Database initialization is repeated
- **WHEN** a service initializes a database whose migrations are already applied
- **THEN** initialization leaves the schema at the same current version without duplicate schema changes

#### Scenario: Provisioning deployment has pending migrations
- **WHEN** a provisioning pod is created with an older owned database
- **THEN** its migration init container applies the ordered migration chain before the application container starts

#### Scenario: Provisioning application sees schema drift
- **WHEN** the application process starts against a database missing the latest known migration
- **THEN** startup fails with an actionable schema-drift error and does not mutate the schema

### Requirement: Installable package boundaries
Published wheels MUST resolve internal runtime dependencies by distribution version or a supplied wheel directory and MUST NOT encode parent-directory monorepo paths in customer-facing lock metadata.

#### Scenario: Wheel is installed outside the monorepo
- **WHEN** its dependencies are available from PyPI or `--find-links`
- **THEN** installation succeeds without the repository's relative directory layout

### Requirement: Installable compute provisioner

The extracted compute-provisioning distribution MUST install outside the repository layout with all declared runtime dependencies and MUST expose supported commands for its API and worker roles.

#### Scenario: Wheel is installed from built artifacts

- **WHEN** an operator installs the compute provisioner and selected adapter extras from built wheels without editable parent-directory sources
- **THEN** API and worker commands resolve their dependencies and start using the supplied configuration

### Requirement: Extracted service image

The repository MUST provide one destination compute-provisioning image whose startup, routes, background lifecycle, persistence, and shutdown behavior match the migrated service.

#### Scenario: Destination image starts

- **WHEN** the image starts with VM and bare-metal adapters and an existing compatible database
- **THEN** migrations initialize once, readiness becomes healthy, configured background tasks run, and graceful shutdown cancels them without corrupting job or lease state

### Requirement: Coordinated deployment cutover

Deployment manifests and operator configuration MUST reference the destination package, commands, and image, and MUST NOT retain the old VM-owned generic service after cutover.

#### Scenario: Repository deployment references are checked

- **WHEN** package, image, command, and manifest references are scanned after migration
- **THEN** all active deployments use the compute-owned service and no runtime path depends on the repository's parent-directory layout

## Evidence

- Configurable registry endpoints and independently composed role stacks: core buyer registry configuration plus domain Compose and Helm manifests.
- Service-owned persistence, provisioning migration init, and schema-drift rejection: registry Alembic tests, `provisioning/compute/service/tests/unit/test_database.py`, and `helm/charts/provisioning/templates/deployment.yaml`.
- Wheel-directory dependency resolution without parent-path UV sources: package `pyproject.toml` files and package Makefiles using `--find-links`.
- Extracted compute API/worker packaging and image lifecycle: `provisioning/compute/service/pyproject.toml`, `provisioning/compute/service/Dockerfile`, and its composition, worker, and image smoke tests.

Repository-wide migration entrypoints and compatibility-preserving non-additive registry rollout remain proposed in `add-database-migration-commands` and `migrate-registry-to-postgres`.

## Internal wheel development contract

Internal Python distributions MUST be built into the repository `.dist` directory and consumed with `--find-links`. A project MUST NOT add editable relative sibling sources as its normal local-development dependency mechanism.

A touched project's `init` or `reinit` target MUST explicitly upgrade and reinstall changed internal distributions from `.dist`. Docker stages that resolve internal packages MUST copy `.dist` from the build context so wheel changes invalidate the relevant layer.

The aggregate kit test target MUST build prerequisite kit wheels and invoke every kit subproject's default test suite. Standalone targets MAY remain for focused development, but aggregate coverage MUST not silently omit a kit.
