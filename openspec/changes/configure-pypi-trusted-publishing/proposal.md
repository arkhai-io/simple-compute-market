## Why

Trusted publishing works for an older subset of distributions, but the workflow/release table omit five current runtime dependencies and ten matrix entries lack current-name PyPI projects/environments. Stale pre-rename environments and incomplete path triggers mean HEAD's package graph cannot be installed from PyPI alone.

## What Changes

- Reconcile the release inventory to every current consumable Arkhai distribution and explicitly classify excluded demo/e2e/tooling projects.
- Correct workflow matrix, path triggers, package comments, versions, and release documentation.
- Require every included distribution to build with `uv build --no-sources` and install through a downstream role from PyPI alone.
- Create missing current-name PyPI projects and GitHub environments/pending publishers, then verify trusted publication from the protected release branch.
- Retire stale pre-rename external environments only after no workflow references remain.
- State: **Externally blocked final release-readiness step; no implementation checklist until wheel-only and typing/public-interface campaign predecessors finish and external admin access is scheduled.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: Release automation and trusted publisher configuration cover the complete current consumable distribution graph and prove downstream installation without repository sources.

## Dependencies and Related Changes

- Follows `remove-relative-uv-sources`, `finish-buyer-cli-residue`, and `type-core-packages` so published artifacts represent stable wheel-only public boundaries.
- Requires PyPI owner and GitHub environment administration outside ordinary code review.

## Non-Goals

- Do not publish demo, e2e harness, sample application, or internal tooling unless explicitly reclassified as consumable.
- Do not treat workflow matrix presence as proof that the external project/environment exists.
- Do not delete stale external configuration before current-name publication succeeds.

## Impact

Touches release workflow inventory/triggers, all distribution build verification, GitHub environments, PyPI pending publishers/projects, release documentation, and downstream clean-install smoke tests. No runtime API should change.
