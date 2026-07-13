## MODIFIED Requirements

### Requirement: Postgres-backed registry rollout
The registry can use Cloud SQL/Postgres and run Alembic before deployment rollout. The implementation MUST preserve the ownership and compatibility constraints in the `deployment-state` baseline specification.

#### Scenario: Change acceptance
- **WHEN** the implementation is complete and its focused verification runs
- **THEN** the registry can use Cloud SQL/Postgres and run Alembic before deployment rollout.

<!-- Provenance: migrated from docs/development/TODO.md and linked ad hoc design notes. -->
