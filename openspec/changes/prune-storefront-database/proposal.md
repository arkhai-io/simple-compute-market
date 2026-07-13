## Why

Storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification.

## What Changes

- Verify each candidate table, delete dead writes and migrations, and retain negotiation threads.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `storefront-publication`: Storefront persistence contains only production-read state; write-only dormant audit/config tables are removed after reader verification.

## Non-Goals

- Do not drop any table with a production reader or unresolved recovery contract.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
