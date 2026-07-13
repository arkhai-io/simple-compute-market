## Why

The registry can use Cloud SQL/Postgres and run Alembic before deployment rollout.

## What Changes

- Wire the existing Postgres engine path, replace create-all bootstrap, and add a Helm pre-install/pre-upgrade migration Job.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: The registry can use Cloud SQL/Postgres and run Alembic before deployment rollout.

## Non-Goals

- Provisioning Cloud SQL itself remains in the external infrastructure repository.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
