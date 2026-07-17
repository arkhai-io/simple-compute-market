## Why

Provisioning and e2e settings use one kit/config loader with unchanged layering.

## What Changes

- Extract profile resolution and layered loader construction into kit/config and migrate both consumers.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Provisioning and e2e settings use one kit/config loader with unchanged layering.

## Non-Goals

- Storefront profile-free loading is not part of this deduplication.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
