## Why

`arkhai-core` and the registry client already declare typing, but the core typecheck currently fails, marker contents are not verified in wheels, and other public core packages remain unmarked. Typing must be restored and expanded package by package after public buyer interfaces stabilize, without falsely advertising unchecked exports.

## What Changes

- Restore the existing core and registry-client typecheck baseline and verify `py.typed` in built wheels.
- Type and mark public packages incrementally: storefront client, buyer/core storefront contracts, then the FastAPI registry shell.
- Decide separately whether `kit/site` belongs in this core campaign or a later kit ratchet.
- Add one aggregate CI check only after every included package passes its declared level.
- Keep runtime behavioral contracts and domain conformance as separate evidence.
- State: **Planned after buyer preference and wheel-only packaging stabilize included public surfaces.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: Public core/domain carrier boundaries use intentional typed contracts without replacing behavioral conformance.
- `test-compatibility`: Included packages pass declared package-level typechecks and wheel marker verification in CI.
- `deployment-state`: Published typed distributions include correct `py.typed` metadata and install independently.

## Dependencies and Related Changes

- Follows `finish-buyer-cli-residue` for the affected buyer-policy surface and `remove-relative-uv-sources` for wheel-based package evidence.
- Archived domain-contract work remains the behavioral authority; typing declarations cannot substitute for contract tests.
- Precedes final trusted publication reconciliation.

## Non-Goals

- Do not impose repository-wide strict mode at once.
- Do not add `py.typed` before a package's exported surface is intentionally supported.
- Do not silence errors broadly with `Any`, blanket ignores, or exclusion of public modules.

## Impact

Touches core package metadata, annotations/configuration, shared typing targets, wheel-content tests, CI, and stable public client/carrier interfaces. Runtime behavior should not change.
