## Why

Earlier buyer/registry/storefront projects now consume internal wheels correctly, but five newer domain/provisioning projects encode editable parent-directory sources in `pyproject.toml` and locks. This violates package-layer testing and makes installations depend on repository layout; release documentation also contradicts the wheel-only rule.

## What Changes

- Remove internal path sources from API-credit domain, bare-metal provisioning adapter, VM provisioning adapter, compute-provisioning contract, and compute-provisioning service projects.
- Add or repair local init/reinit targets so changed internal wheels are built into `.dist` and explicitly upgraded/reinstalled.
- Regenerate only affected locks against built wheels and preserve unrelated external index sources such as PyTorch CPU selection.
- Add a repository check rejecting parent-directory internal `tool.uv.sources` entries in consumable projects.
- Correct release documentation to match wheel-only internal dependency policy.
- State: **Planned and first in the release-readiness campaign.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Consumable projects resolve internal dependencies from built distributions rather than editable parent paths.

## Dependencies and Related Changes

- Precedes `type-core-packages` packaging verification and `configure-pypi-trusted-publishing`.
- Coordinates with newly extracted packages but does not change their runtime contracts.

## Non-Goals

- Do not remove non-path source/index selectors for external dependencies.
- Do not change dependency versions except where deterministic lock regeneration requires it and the change is reviewed.
- Do not publish packages in this change.

## Impact

Touches five project/lock pairs, local Make/build orchestration, repository packaging checks, CI, and `docs/development/RELEASING.md`. Runtime APIs are unchanged.
