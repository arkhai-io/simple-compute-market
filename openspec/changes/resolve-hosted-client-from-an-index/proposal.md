## Why

`arkhai-hosted-settlement-client==0.4.2` is produced outside this repository and
resolves from nowhere. No index is configured for it anywhere in the tree — the
only `[[tool.uv.index]]` entries are PyTorch — so the wheel is expected to be
*staged into* `.dist` by a step that runs outside a checkout. A fresh clone has
no way to obtain it, and eight projects depend on it.

The result is two failure modes that look like one. Projects including
`make/hosted-release.mk` gate `init` on verifying a signed release manifest and
fail with a missing-manifest error before their environment is built. Projects
that omit the gate fail later inside `uv sync` with "not found in the package
registry", which reads like a registry outage and is not one. Six suites cannot
run; `domains/vms/storefront`'s cannot, which leaves changes there unverified.

Two structural mistakes sit under this. Release verification is attached to
`init` and `dist-release`, so an artifact that describes a *deployed* authority
became a prerequisite of *building and testing* — a publication-time concern
placed on the development path. And `.dist` serves as both a build output
directory for every wheel this repository compiles and a delivery inbox for one
it does not, with nothing distinguishing them; `dist-hosted-client` copies
nothing when the two paths coincide, so `make dist` reports success having
produced no client at all.

## What Changes

- The client resolves from the public package index like any other external
  dependency, requiring no index configuration at all. The staged-release path
  stops being how a build obtains it.
- Release verification is removed from `init`, `reinit`, and `dist-release`.
  Nothing on the build or test path verifies a signed release, because nothing
  on the build or test path deploys anything.
- `dist-hosted-client` and the seven-file staging derivation leave the `dist`
  graph. `HOSTED_RELEASE_DIR` staging remains available to the end-to-end
  harness targets, which are the only remaining consumers of the release
  documents.
- The `HOSTED_*` variables in the root `Makefile` reduce to those the harness
  targets and the deployment-attestation targets still read. The variables that
  existed only to derive and verify a staged release are removed with it.
- `make dist` and `make test` succeed from a fresh checkout with no access to
  the producer repository, on a fork, and with no credential.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `deployment-state`: an externally produced dependency is resolved from a
  declared index rather than staged into the build output directory, and
  verification of a producer's signed release is a publication-time activity
  that no build or test target performs.

## Dependencies and Related Changes

- Requires the client published to the public index. That publication is
  provided outside this repository and is not in this repository's gift. Every
  code change here is complete; the suites pass once the client resolves.
- Precedes `publish-wheels-through-a-gate`, which owns publication and the
  release inventory this repository produces.
- Relates to `remove-relative-uv-sources`: both make internal and external
  dependencies wheel-resolvable rather than path-resolvable.
- Relates to `configure-pypi-trusted-publishing`, which cannot succeed while a
  published distribution declares a dependency no public index carries.

## Non-Goals

- Do not delete or modify the end-to-end harness. It predates this work, is
  owned elsewhere, and is downstream of every change here. Its two targets
  (`hosted-stripe-test`, `hosted-stripe-test-local`) keep working.
- Do not remove the harness's locally built producer path, notwithstanding that
  it reads a sibling checkout by relative path and parses that repository's
  Makefile for a version. That path is the harness's and moves with it.
- Do not weaken the release verifier. `scripts/verify-hosted-release.py` keeps
  its behaviour and its tests; what changes is which targets invoke it.
- Do not vendor the client's source into this repository. The contract has one
  home, and it is not here.
- Do not resolve the hardcoded producer repository name in
  `e2e-tests/src/hosted_real_stripe/gates.py`. It is a real
  public-repository-discipline defect and it belongs to the inventory work that
  replaces it.

## Impact

Touches the root `Makefile`, `make/hosted-release.mk`,
`kit/hosted-settlement/Makefile`, `domains/vms/storefront/Makefile`, the
`pyproject.toml` files declaring the client, `.github/workflows/tests.yml`, and
`docs/development/DEPLOYMENT_AND_CONFIG.md`. Six blocked suites become runnable
and are expected to surface real failures that the packaging gap has been
hiding; those are separate findings and not this change's to fix. No runtime
API changes.
