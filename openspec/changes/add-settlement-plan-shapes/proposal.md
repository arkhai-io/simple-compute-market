## Why

Servicing supports oracle operation, heartbeat-gated claims, interval escrows, and penalty bonds as independently materialized obligations.

## What Changes

- Add the next committed lifecycle plan shapes and engine-driven materialize/reclaim behavior.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settlement-servicing`: Servicing supports oracle operation, heartbeat-gated claims, interval escrows, and penalty bonds as independently materialized obligations.

## Non-Goals

- A fiat codec remains deferred until a provider/customer pairing is committed.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
