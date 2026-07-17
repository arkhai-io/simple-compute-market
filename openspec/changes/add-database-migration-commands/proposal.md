## Why

Services can run migrations separately from application startup and reject schema drift.

## What Changes

- Add standalone migration entrypoints for SQLite services, Helm init containers, and actionable startup version guards.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Services can run migrations separately from application startup and reject schema drift.

## Non-Goals

- Runtime service behavior and schemas remain unchanged apart from migration enforcement.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
