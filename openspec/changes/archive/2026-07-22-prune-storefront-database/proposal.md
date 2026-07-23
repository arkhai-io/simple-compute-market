## Why

Storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification.

## What Changes

- Audit each migrated candidate against current readers, idempotency constraints, recovery behavior, and already-applied schema cleanup.
- State: **Closed as already completed or rejected; archive without synchronizing the broad pruning delta.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: Storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification.

## Non-Goals

- Do not drop `negotiation_messages`, which is required for negotiation continuation and inspection.
- Do not drop `resource_transition_events`, whose uniqueness constraint provides atomic idempotency even without ordinary query readers.
- Do not drop `stage_events` while authenticated operator and e2e readers remain.
- Do not synchronize the broad production-read-only criterion; persistence may validly enforce idempotency or constraints without a conventional reader.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
