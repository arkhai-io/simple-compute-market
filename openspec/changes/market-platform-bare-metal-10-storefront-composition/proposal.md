## Why

Bare metal already has deterministic domain codecs, publication semantics, and a compute-provisioning adapter, but it has no runnable seller storefront that can negotiate, settle, fulfill, and recover a bare-metal agreement. Compute-40 cannot prove VM and bare-metal storefronts against shared provisioning authorities until bare metal has an equivalent composition root.

## What Changes

- Add a deployable bare-metal storefront composition that injects the bare-metal market-domain contract into the shared storefront role.
- Complete bare-metal seller hooks for negotiation policy, settlement verification and plan construction, fulfillment, receipt/result normalization, and teardown without importing VM semantics.
- Extend the trusted site projection producer with an opt-in, complete per-resource bare-metal view containing distinct site, Physical Resource, physical-host, and executor-machine identities plus authoritative availability, allocation mode, access methods, capacity, and allowlisted capabilities.
- Configure the storefront to consume one or more trusted provisioning-site bindings and route fulfillment through the site selected by the Capacity Reservation.
- Package and deploy the composition independently from the VM storefront while allowing one seller or gateway to operate both roles.
- Add focused contract, integration, packaging, and deployment-render evidence for a complete bare-metal seller lifecycle.
- Preserve one market-domain contract per storefront process; multiplexing VM and bare-metal semantics inside one process is not part of this change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: Add a runnable bare-metal seller composition over the shared storefront and compute-provisioning contracts.
- `storefront-publication`: Require the bare-metal composition to expose the complete seller protocol surface and domain-owned lifecycle hooks, not publication alone.
- `deployment-state`: Package and configure the bare-metal storefront as an independently deployable seller role with trusted provisioning-site bindings.

## Non-Goals

- Do not make compute provisioning mandatory for API-credit or other non-compute domains.
- Do not host several market-domain contracts in one storefront process.
- Do not implement POOLS-7 durable scheduling, generic fulfillment recovery, multi-storefront result delivery, or the final Compute-40 topology proof in this change.
- Do not add provider-backed bare-metal fulfillment by inferring a relationship between fulfillment-provider and executor identities.
- Do not create a separate bare-metal capacity authority; VM and bare-metal may consume the same site authority and Physical Resource identities.

## Dependencies and Related Changes

- Archived Market Platform domain and compute extraction changes provide the common contracts and deployable compute service.
- `pools-7-storefront-fulfillment-cutover` owns the durable selected-site fulfillment path. Composition and protocol work may begin earlier, but production cutover and final lifecycle evidence depend on its public scheduling, fulfillment, result, and teardown contracts.
- This change owns the bare-metal-specific per-resource projection producer/consumer contract needed for publication. POOLS-8 continues to own generic durable projection consumption, commercial mapping, and advisory listing hints.
- `market-platform-compute-40-multi-domain-proof` follows this change and POOLS-7 to prove VM and bare-metal storefronts across shared provisioning authorities.
- `provisioning-result-push-delivery` owns authenticated reverse delivery and is not required for the pull-based lifecycle baseline.

## Impact

- Affected packages: `domains/bare_metal`, `core/storefront`, the concrete bare-metal storefront package/composition root, site projection carriers, compute-provisioning projection producers, shared storefront clients, and compute-provisioning clients.
- Affected deployment: seller image/build targets, configuration profiles, Helm or equivalent role composition, health checks, and trusted site credentials.
- Affected tests: bare-metal domain conformance, storefront protocol/integration suites, selected-site fulfillment, packaging, deployment rendering, and later Compute-40 topology scenarios.
- Persistence and wire compatibility must reuse shared storefront schemas and versioned domain envelopes; any unavoidable domain-specific persistence requires an explicit migration and compatibility plan.
