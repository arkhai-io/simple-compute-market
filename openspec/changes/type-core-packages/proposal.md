## Why

Core public APIs are marked typed and checked through a shared pragmatic type-check target.

## What Changes

- Add py.typed packaging, shared baseline configuration, typed carrier/client boundaries, and package-by-package strictness ratchets.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: Core public APIs are marked typed and checked through a shared pragmatic type-check target.

## Non-Goals

- Do not impose a repository-wide strictness cliff.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
