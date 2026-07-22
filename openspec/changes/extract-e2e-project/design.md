## Context

The harness has its own project metadata, image, settings, tests, and role/domain layout, but builds from the monorepo root and imports private service implementation/data in some scenarios. Root workflows orchestrate the complete repository stack. The nested workflow and several README commands are stale. No named external consumer or compatibility commitment exists.

## Goals / Non-Goals

**Goals:** retain a measurable activation boundary and required extraction guarantees.

**Non-Goals:** activate now, promise arbitrary deployments, or remove root consumers prematurely.

## Decisions

### Keep the change deferred and taskless

Activation requires a named external operator/use case, supported deployment/version profile, release owner, and evidence that independent execution is worth the compatibility burden.

### Require true outside-repository installation

When activated, a clean environment must install the harness and published dependencies without checkout-relative wheels, binaries, Compose files, generated address data, or service implementation modules. Only published clients/contracts and explicitly declared test-control capabilities are allowed.

### Preserve current scenario architecture

Role/domain layering and black-box suites remain useful and migrate to a versioned package/image. Root CI and Helm switch to that artifact only after parity, so extraction does not remove current coverage in one step.

### Define compatibility rather than “arbitrary” support

The release declares supported deployment/API versions, required optional test-control capabilities, and profiles. External failures outside that matrix are not silently treated as product regressions.

## Risks / Trade-offs

- **[Private imports hide missing public contracts]** → Inventory each and either publish a stable contract/client or redesign the scenario.
- **[Independent release doubles CI]** → Keep one canonical suite artifact consumed internally and externally.
- **[No external maintainer exists]** → Do not activate without a release/support owner.

## Activation Record Required

- Named external operator and scenarios.
- Supported deployment/version matrix.
- Release/compatibility owner.
- Published dependency availability.
- Inventory/disposition of private imports and test-control routes.

## Permanent Documentation Promotion

No current behavior changes. If activated, installability and compatibility guarantees belong in `test-compatibility` spec/architecture; release/topology behavior belongs in `deployment-state` where material.
