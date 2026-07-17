## Why

Measured listing-query latency can activate scalar generated indexes and array side indexes declared by indexed:true.

## What Changes

- Preserve the design with a measurable activation gate; no implementation begins before query latency requires it.
- State: **Deferred/conditional: activation criteria are not yet satisfied.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `registry-discovery`: Measured listing-query latency can activate scalar generated indexes and array side indexes declared by indexed:true.

## Non-Goals

- This change is deferred and has no implementation tasks until the trigger is met.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
