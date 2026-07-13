## Why

Core currently exposes a codec-only `StorefrontDomainRuntime`, while buyer plugins, negotiation envelopes, storefront policies, publication sources, settlement hooks, and fulfillment results use adjacent conventions rather than one enforceable market-domain contract. Defining that contract against the existing VM, bare-metal, and API-credit implementations gives future domains one extension surface without importing concrete domains into core.

## What Changes

- Extend the core market-domain contract from normalization codecs to explicit identity/version, buyer, storefront, publication, settlement, fulfillment, and optional-capability surfaces.
- Fit the VM, bare-metal, and API-credit packages to the same contract and conformance suite.
- Replace the flat compute-shaped storefront-client provision-terms request with a versioned domain envelope, migrating every in-repository caller in one compatibility cutover.
- Define capability discovery so domains that do not use compute provisioning do not implement placeholder provisioning methods.
- **BREAKING**: remove the legacy flat provision-terms wire and obsolete domain integration entry points after all in-repository callers migrate.
- State: **Planned and independently implementable.**

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: Core exposes one versioned market-domain contract that concrete domain packages implement without reverse dependencies.
- `buyer-orchestration`: Domain plugins provide buyer command, terms-construction, policy, and result-decoding hooks through the common contract.
- `storefront-publication`: Storefront composition consumes domain publication, policy, settlement, fulfillment, and codec capabilities through the common contract.
- `negotiation-protocol`: Provision terms use one versioned domain envelope without compute-specific fields in the shared client wire.

## Non-Goals

- Do not require every market domain to use a provisioning service, capacity ledger, Alkahest, or any particular settlement mechanism.
- Do not move deterministic domain schemas or policies into core.
- Do not make one process host multiple storefront domains; this change standardizes composition contracts, not deployment topology.
- Do not impose repository-wide strict typing beyond the changed public contract; broader ratcheting remains in `type-core-packages`.

## Dependencies and Related Changes

- `market-platform-compute-40-multi-domain-proof` later verifies that VM and bare-metal storefronts compose this contract while sharing compute infrastructure.
- `type-core-packages` may extend static enforcement after this contract is established.

## Impact

- Affected packages: `core/src/market_core`, `core/buyer`, `core/storefront`, the three current domain packages, and the core storefront client.
- Wire compatibility: one coordinated non-additive provision-terms cutover across all in-repository clients and servers.
- Packaging: domain entry-point metadata and public typed exports change.
- Persistence and deployment topology remain unchanged.
