## Why

Customer-facing and service package locks no longer encode parent-directory uv sources.

## What Changes

- Remove relative tool.uv.sources entries, use the dist wheel directory via --find-links, and regenerate locks.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Customer-facing and service package locks no longer encode parent-directory uv sources.

## Non-Goals

- Do not change runtime dependency versions except as required by lock regeneration.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
