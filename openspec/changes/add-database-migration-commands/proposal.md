## Why

Compute provisioning already separates deterministic migration from runtime startup, but VM/API-credit storefront and API-credit ledger construction still create or alter schema during ordinary process initialization. Stateful roles need explicit migration commands, startup schema guards, and deployment phases so failures are visible before application crash loops.

## What Changes

- Treat the compute provisioning command, startup guard, and init container as the implemented reference pattern and add missing direct CLI/render evidence.
- Separate VM storefront core/domain migration from normal SQLite client construction and add a standalone command plus read-only startup guard.
- Add an equivalent explicit migration/guard boundary for the API-credit storefront and API-credit service rather than leaving `create_all` at runtime.
- Add migration init phases before application startup in deployment templates.
- Preserve existing databases through additive versioned migrations and actionable schema-drift errors.
- State: **Planned; provisioning is complete baseline, storefront and API-credit roles remain.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Stateful SQLite roles migrate explicitly before runtime and reject incompatible schema without mutating it during ordinary startup.

## Dependencies and Related Changes

- Establishes the migration/runtime convention used later by `migrate-registry-to-postgres`; registry Alembic repair remains in that separate change.
- Coordinates with POOLS-7 and bare-metal storefront persistence migrations but does not implement their schemas.

## Non-Goals

- Do not change business schemas except for migration metadata needed to represent current state deterministically.
- Do not run destructive downgrade automatically.
- Do not fold the registry's PostgreSQL cutover or external database provisioning into this change.

## Impact

Touches core/VM/API-credit storefront database construction, API-credit service database initialization, console entry points, deployment init phases, migration tests, and operator commands. Startup ordering changes, but runtime APIs do not.
