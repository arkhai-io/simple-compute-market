## Why

The e2e harness is a recognizable in-repository project, but it still depends on root `.dist`, monorepo build/Compose targets, private storefront imports/data, local topology assumptions, and stale nested workflow/docs. No external-operator demand currently justifies an independent release.

## What Changes

- Preserve extraction as a conditional future outcome rather than active implementation.
- Activate only when a named external operator needs a versioned black-box suite installable outside the monorepo.
- On activation, remove private service imports and checkout-relative wheel/binary/config assumptions, declare required test-control capabilities, and define deployment/version compatibility.
- Keep current root CI/Helm consumers supported through a coordinated image/release cutover rather than immediate path deletion.
- State: **Deferred/conditional; activation evidence is absent and no implementation tasks are present.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-compatibility`: Define measurable conditions for a separately installable external black-box harness.

## Dependencies and Related Changes

- Wheel-only package cleanup and complete trusted publishing are prerequisites for external installation.
- Current in-repository e2e behavior remains owned by `test-compatibility` baseline and root workflows.

## Non-Goals

- Do not claim arbitrary-deployment compatibility without a declared profile/version contract.
- Do not break root CI or Helm e2e consumption before a versioned replacement exists.
- Do not activate solely to clean stale nested docs/workflow; those may be corrected independently.

## Impact

No current runtime impact. Future activation affects e2e packaging/image/release, private imports, test-control APIs, configuration profiles, root CI/Helm integration, and external compatibility support.
