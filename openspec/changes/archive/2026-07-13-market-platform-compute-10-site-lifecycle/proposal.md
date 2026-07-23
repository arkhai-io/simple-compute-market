## Why

Generic site resource, reservation, allocation, and event authority is currently entangled with compute lease watchdog and executor teardown behavior. Stabilizing the lower site boundary first prevents the extracted compute provisioner from carrying a hidden VM lifecycle dependency.

## What Changes

- Define a narrow site-authority contract for resource inventory, hold/commit/release allocation lifecycle, versioned capacity events, and deal ownership references.
- Move lease watchdog, executor release dispatch, and failed-release policy behind a compute-provisioning lifecycle boundary.
- Replace re-export shims and direct lifecycle reach-through with explicit injected ports, then remove the obsolete paths after callers migrate.
- Preserve allocation identifiers, reservation idempotency, capacity conflict behavior, and externally visible HTTP semantics.
- State: **Planned and independently implementable.** This is the prerequisite for the shared compute-provisioning contract.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: Site authority owns resources, reservations, allocations, versioned capacity events, and deal routing without understanding executor teardown states.
- `physical-provisioning`: Compute lease lifecycle consumes the site-authority port and retains capacity until executor release succeeds or an operator explicitly force-releases it.

## Non-Goals

- Do not move the site authority into a storefront database.
- Do not make the generic site layer understand VM teardown, bare-metal reclaim, job runners, credentials, or watchdog scheduling.
- Do not change reservation, allocation, or release wire formats unless required to remove an ownership violation.
- Do not extract the deployable provisioning service in this change.

## Dependencies and Related Changes

- `market-platform-compute-20-provisioning-contract` requires this stable allocation and event boundary.
- `market-platform-compute-30-extract-service` consumes the separated lifecycle ports.
- `market-platform-compute-40-multi-domain-proof` verifies cross-mode physical accounting after extraction.

## Impact

- Affected packages: `kit/site`, `core/storefront` site and lifecycle helpers, and `domains/vms/provisioning/service` composition and tests.
- Wire compatibility: existing capacity and lease routes remain compatible; internal Python ports change by clean cutover.
- Persistence: existing site and lease records retain identifiers and lifecycle meaning.
- Deployment and packaging remain unchanged.
