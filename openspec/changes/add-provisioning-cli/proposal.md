## Why

Operators can install the provisioning wheel and launch API and worker processes through supported console commands.

## What Changes

- Add serve and worker subcommands and migrate compose/Helm invocations from raw uvicorn.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `physical-provisioning`: Operators can install the provisioning wheel and launch API and worker processes through supported console commands.

## Non-Goals

- Do not merge storefront and provisioning distributions.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
