## Why

Provisioning may replace its storefront-client dependency with a narrow local HTTP client if dependency direction becomes costly.

## What Changes

- Preserve the conditional extraction with deal-ref routing as a possible reason it dissolves.
- State: **Deferred/conditional: activation criteria are not yet satisfied.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Provisioning may replace its storefront-client dependency with a narrow local HTTP client if dependency direction becomes costly.

## Non-Goals

- This change is conditional and has no implementation tasks until the dependency becomes a demonstrated maintenance problem.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
