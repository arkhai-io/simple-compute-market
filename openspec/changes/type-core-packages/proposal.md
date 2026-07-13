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

## Related Changes

- `market-platform-domain-10-contract` defines the semantic core/domain protocols and their conformance behavior. This typing change remains independently archivable and MUST NOT substitute typing declarations for that behavioral contract.

## Non-Goals

- Do not impose a repository-wide strictness cliff.

## Impact

Planning migration source: `docs/development/TODO.md` and its linked design notes. Runtime impact is limited to the capability above when this change is applied.
