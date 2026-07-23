## Why

The registry has a PostgreSQL engine seam and partial Alembic history, but production defaults remain SQLite and a clean Alembic upgrade does not create the current ORM schema. A safe shared-registry rollout requires a complete migration chain, explicit command/guard, preserved existing state, Secret-backed connectivity, and external Cloud SQL readiness.

## What Changes

- Repair Alembic so blank and representative existing databases reach the complete current registry schema without `create_all` assumptions.
- Add a packaged registry migration command and read-only runtime schema guard.
- Preserve publishers, listings, demands, API keys/scopes, and sequence/identity state during SQLite-to-PostgreSQL cutover.
- Add Secret-backed PostgreSQL configuration and a pre-rollout migration Job.
- Remove SQLite PVC, `Recreate`, and in-process bootstrap assumptions from PostgreSQL deployments and prove rolling old/new pod coexistence where compatible.
- State: **Blocked on external Cloud SQL/IAM/network readiness and completion of `separate-marketplace-registry`; no implementation checklist until those inputs and a rehearsed cutover design are approved.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Run the independently operated registry on PostgreSQL with complete Alembic migration, preserved state, and migration-before-rollout deployment semantics.

## Dependencies and Related Changes

- Follows `separate-marketplace-registry` so PostgreSQL targets the independently operated registry role.
- Uses migration-command/runtime-guard conventions from `add-database-migration-commands` while retaining Alembic ownership in the registry.
- `index-registry-filters` remains deferred until PostgreSQL is stable and measured query latency crosses its trigger.
- Cloud SQL instance, IAM, networking, backup, and secret provisioning are external prerequisites.

## Non-Goals

- Do not provision Cloud SQL from this repository.
- Do not discard existing registry state by default.
- Do not add filter indexes or change listing/publication APIs.
- Do not remove SQLite development support unless a later change makes that decision explicitly.

## Impact

Touches registry models/Alembic/bootstrap/startup, image packaging, database fixtures and integration tests, Helm Secrets/jobs/deployment/PVC strategy, Compose defaults, cutover tooling, backup/rollback procedure, and operator documentation.
