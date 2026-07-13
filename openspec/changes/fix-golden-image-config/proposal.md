## Why

Golden-image automation emits Dynaconf key names consumed directly by provisioning and documents secret transfer.

## What Changes

- Rename generated management-vars keys and document the operator Secret workflow.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Golden-image automation emits Dynaconf key names consumed directly by provisioning and documents secret transfer.

## Non-Goals

- No adapter or second configuration format.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
