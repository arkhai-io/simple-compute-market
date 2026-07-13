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

#### Scenario: Storefront records a provisioning allocation
- **WHEN** physical settlement is scheduled
- **THEN** the storefront stores the market correlation while provisioning/site authority owns physical resource and allocation state

### Requirement: Forward-safe schema changes
Database migrations MUST be ordered, durable, and compatible with the deployed application version; non-additive changes MUST use a rollout strategy that prevents incompatible versions from sharing the schema.

#### Scenario: Startup sees unexpected schema version
- **WHEN** the applied migration version differs from the service expectation after the schema-guard change lands
- **THEN** startup fails with an actionable migration command instead of serving against drifted state

### Requirement: Installable package boundaries
Published wheels MUST resolve internal runtime dependencies by distribution version or a supplied wheel directory and MUST NOT encode parent-directory monorepo paths in customer-facing lock metadata.

#### Scenario: Wheel is installed outside the monorepo
- **WHEN** its dependencies are available from PyPI or `--find-links`
- **THEN** installation succeeds without the repository's relative directory layout

<!-- Provenance: ARCHITECTURE.md deployment, build, artifact publishing, and state migration sections; evidence: Helm/compose manifests, service migration modules, package Makefiles -->
