## Why

Provider nodes default to an external registry while marketplace operators may enable the registry chart.

## What Changes

- Make the registry subchart conditional with default disabled and document operator/provider topology values.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Provider nodes default to an external registry while marketplace operators may enable the registry chart.

## Non-Goals

- No registry runtime API change.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
