## Why

The repository now has shared domain contracts, an extracted compute service, concurrent VM/bare-metal adapters, and multi-site capacity aggregation, but those pieces have not been proven as one seller-to-site topology. A deterministic proof must show that separately composed VM and bare-metal storefronts can each use several provisioning authorities, that each authority can serve both storefronts, and that selected-site, executor, and Physical Resource ownership survive the full lifecycle without global defaults.

## What Changes

- Add a deterministic 2×2 topology with VM and bare-metal storefronts connected to two compute provisioning authorities.
- Exercise all four storefront-to-site edges through reservation, scheduling, fulfillment, result observation, teardown, and capacity restoration.
- Require dispatch and release from recorded executor identity; remove or reject the remaining implicit `"vm"` fallback when durable executor identity is absent.
- Verify selected-site routing survives storefront restart and never falls back to another authority after reservation.
- Verify each provisioner concurrently loads VM and bare-metal adapters without provider/executor conflation.
- Exercise VM-shareable and bare-metal-exclusive claims against one Physical Resource within an authority and reject conflicts before executor work.
- Use pull-based status/result reconciliation as the correctness baseline; authenticated reverse delivery remains a separate follow-on.
- State: **Blocked on `pools-7-storefront-fulfillment-cutover` and `market-platform-bare-metal-10-storefront-composition`; already-landed prerequisite evidence is recorded in `tasks.md`.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `site-capacity`: Prove trusted selected-site ownership and no post-reservation fallback across a many-to-many storefront/site topology.
- `physical-provisioning`: Require durable executor identity without VM fallback and prove both provisioners serve both compute domains concurrently.
- `test-compatibility`: Add a deterministic 2×2 topology scenario covering all storefront/provisioner relationships and lifecycle isolation.

## Non-Goals

- Do not host VM and bare-metal market contracts in one storefront process.
- Do not add another resource domain, a third provisioning API, or cross-seller capacity markets.
- Do not implement the bare-metal storefront, POOLS-7 lifecycle, or result-push delivery inside this proof.
- Do not require provider-backed fulfillment for every executor or infer executor identity from a fulfillment provider.
- Do not use real hardware timing as the sole acceptance evidence.

## Dependencies and Related Changes

- Archived Market Platform domain/compute changes and POOLS-3/4/6 provide the shared contracts, extracted service, adapters, capacity identity, and cross-mode admission foundation.
- `market-platform-bare-metal-10-storefront-composition` provides the second complete storefront composition.
- `pools-7-storefront-fulfillment-cutover` provides durable selected-site scheduling, fulfillment status/result, restart recovery, and teardown.
- `provisioning-result-push-delivery` may later add authenticated reverse delivery, but this proof uses pull reconciliation and does not block on it.
- `pools-8-capacity-projection-and-listing-hints` may improve publication inputs but is not required if deterministic proof listings are created from authoritative fixtures.

## Impact

- Affected tests/topology: two storefront applications, two compute provisioning services, VM and bare-metal adapters, site-capacity fixtures, fulfillment clients, and lifecycle result polling.
- Runtime behavior changes only where the proof exposes invalid VM-default dispatch or missing durable selected-site routing; those fixes belong to the owning capability rather than test-only branches.
- Deployment/test configuration gains explicit per-storefront site bindings for the deterministic 2×2 scenario.
