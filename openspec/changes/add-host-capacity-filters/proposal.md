## Why

The capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts.

## What Changes

- Define and implement the currently review-needed host filter contract.
- State: **Deferred/conditional: activation criteria are not yet satisfied.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: The capacity check accepts optional vCPU, RAM, and GPU requirements and returns eligible ranked hosts.

## Related Changes

- `market-platform-compute-30-extract-service` may provide the eventual placement-service composition point, but host ranking remains a separate conditional capability. It is not required for service extraction and MUST receive its own design and activation evidence before tasks are added.

## Non-Goals

- This change requires design review before implementation tasks are expanded.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
