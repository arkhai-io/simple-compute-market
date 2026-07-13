## Why

The storefront client sends domain-enveloped provision terms without compute-specific parameters.

## What Changes

- Replace the flat legacy compute provision-terms request, migrate callers, and bump client compatibility once.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `negotiation-protocol`: The storefront client sends domain-enveloped provision terms without compute-specific parameters.

## Non-Goals

- No compatibility shim remains after all in-repo callers migrate.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
