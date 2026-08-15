## Why

The shared storefront shell accepts one `MarketDomainContract`, while durable listings and accepted negotiations carry no exact domain binding. A process therefore cannot safely publish, negotiate, settle, fulfill, recover, return results, or tear down both VM and bare-metal records without relying on a singleton, payload inference, or domain-specific route copies.

## What Changes

- Require the accepted `storefront-domain-parameterization` seam before implementation, then replace its one injected VM contract with an immutable startup registry of explicit compute-family registrations. Each registration binds one pool offering mode to one exact `DomainIdentity`, supported market-contract version, and complete storefront capability set.
- Require `pool-declared-offering-modes` to make requested mode explicit and enforce it at reservation, scheduling, and provisioning. Publication admits a VM or bare-metal candidate only when its Resource Pool declares that exact mode; withdrawal closes new offers but does not reinterpret accepted work.
- **BREAKING**: remove the storefront's implicit single VM contract, module-global contract lookup, default domain, payload-kind inference, and executor fallback. Missing, duplicate, unknown, unsupported, or mismatched registrations and record bindings fail before domain policy or physical effects.
- Persist an immutable offering-mode/domain binding on every listing and copy it transactionally into every negotiation at creation. Accepted Terms, settlement plans, servicing/recovery state, fulfillment request/result decoding, and teardown resolve the exact recorded binding rather than current publication configuration or request payloads.
- Replace request-time VM-versus-bare-metal branches and parallel role flows with one schema-opaque selector around the injected contract capabilities and codecs. One-element deployments remain valid only as an explicit one-registration instance of the same registry.
- Publish the canonical registry field `offer_resource.virtualization_type` from the recorded offering mode, namespace derivation identity by site, offering mode, and domain binding, and route capacity and fulfillment through the listing's operator-configured trusted site with no cross-site fallback.
- Add ordered storefront migrations for legacy single-domain listings, derived mappings, negotiations, and recoverable settlement state. Migration requires an explicit legacy binding, validates the complete population before commit, preserves stable listing/negotiation/settlement/fulfillment identifiers, and refuses ambiguous, unknown, or cross-domain rows instead of classifying them as VM.
- Package VM and bare-metal domain wheels into one compute-family storefront image and expose explicit registration and trusted-site configuration in TOML, Compose, Helm values/schema/templates, generated examples, health/status, and startup diagnostics without provider credentials or domain secrets in durable bindings.
- Prove one running storefront handles complete VM and bare-metal publication, negotiation, settlement, reservation, fulfillment, result, restart recovery, and teardown while keeping records, codecs, sites, pool modes, operation identities, and failures isolated across domains.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `market-composition`: allow one storefront shell to register several exact versioned domain contracts and resolve only from an immutable record binding.
- `storefront-publication`: bind listings and trusted site mappings to explicit pool offering modes/domain contracts, publish the exact mode, and prohibit cross-mode or cross-site fallback.
- `negotiation-protocol`: persist the listing's binding on thread creation and reject provision envelopes or continuations that do not match it.
- `settlement-servicing`: retain the accepted binding through plan construction, durable servicing, fulfillment result decoding, recovery, and teardown.
- `deployment-state`: define the transactional legacy-state migration, explicit registration configuration, combined package/image, and coordinated rollout/rollback boundary.
- `test-compatibility`: require focused mismatch/unknown/legacy/restart coverage and a complete cross-domain isolation proof through both lifecycles.

## Non-Goals

- Do not add a bare-metal buyer, change the registry's declared compute-family schema identity, or prove buyer CLI discovery; `bare-metal-buyer-domain` owns that role.
- Do not add another offering mode, generalize this composition to API credits, or make compute provisioning mandatory for non-compute storefronts.
- Do not implement pool mode declaration/enforcement, selected-site scheduling, bare-metal provider behavior, or physical conflict accounting here; this change consumes their accepted contracts.
- Do not support one provisioning authority serving several storefronts, many-to-many storefront/authority ownership, buyer-selected site routing, or fallback to another site, domain, contract version, pool mode, or executor.
- Do not merge two independently live writable storefront databases. Rollout selects and transactionally migrates one quiesced database; any other role is drained/closed under its existing recovery contract before the combined process becomes authoritative.
- Do not introduce VM/bare-metal conditionals in shared handlers, copy domain route stacks, reconstruct contracts from stored strings, or preserve singleton compatibility aliases.

## Dependencies and Related Changes

- **Hard prerequisite:** `storefront-domain-parameterization` must be implemented, accepted, and promoted. Its exact immutable `MarketDomainContract` injection through the VM app, lifespan/container, SQLite client, listing service, negotiation helpers, and settlement composition is the seam replaced by the registry; no lower-layer getter may remain.
- **Hard prerequisite:** `pool-declared-offering-modes` must be implemented, accepted, and promoted, including explicit requested mode, no VM executor fallback, legacy reservation policy, and independent reservation/scheduling/provisioning enforcement.
- The full bare-metal lifecycle evidence reuses accepted seller hooks and trusted selected-site contracts from `market-platform-bare-metal-10-storefront-composition` plus the durable scheduling/result/recovery/teardown APIs from `pools-7-storefront-fulfillment-cutover`. Missing behavior blocks the corresponding task; it is not replaced with a no-op, test-only branch, or VM adapter.
- `publish-multidimensional-listing-shape` owns capacity-dimension projection. Its current artifacts do not define offering-mode routing; this change uses the already canonical `virtualization_type` field for its persisted discriminator and must reuse any compatible publication work that lands first rather than add a second field.
- `bare-metal-buyer-domain` is independently sequenced with this change. `market-platform-compute-40-multi-domain-proof` follows both to add the separate two-authority topology proof.

## Impact

- Affected shared packages: `arkhai-core-storefront`, its SQLite migration chain and tests, and the shared storefront client/fixtures only where an observable generic carrier changes.
- Affected compositions: `domains/vms/storefront`, `domains/bare_metal/storefront`, VM and bare-metal domain entry-point packages, publication/reconciliation, negotiation, settlement, fulfillment recovery, result, and teardown wiring.
- Affected persistence: common listings and negotiation threads plus the current VM/bare-metal derived-listing mappings and recoverable lifecycle correlation. Stable public and operation identifiers are preserved; unresolved legacy classification fails atomically.
- Affected packaging/deployment: domain wheel dependencies, storefront image/build targets, `compose.vms.yml`, relevant domain Compose wiring, Helm storefront values/schema/templates/fixtures, generated configuration, and operator rollout commands.
- Wire compatibility is additive for the existing canonical `offer_resource.virtualization_type` field and existing versioned provision envelopes. Runtime compatibility is intentionally strict: unbound or mismatched durable records and requests are rejected rather than routed to VM.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specifications and applicable companion architectures
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

- Explicit multi-domain registration, immutable per-record selection, and the no-fallback composition boundary — `openspec/specs/market-composition/{spec.md,architecture.md}` and `docs/development/ARCHITECTURE.md`.
- Offering-mode publication, common derived mapping identity, and trusted site routing — `openspec/specs/storefront-publication/{spec.md,architecture.md}`.
- Negotiation binding and mismatch rejection — `openspec/specs/negotiation-protocol/{spec.md,architecture.md}`.
- Accepted-domain continuity through servicing, recovery, result, and teardown — `openspec/specs/settlement-servicing/{spec.md,architecture.md}`.
- Migration, package, image, configuration, and rollout rules — `openspec/specs/deployment-state/{spec.md,architecture.md}` and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Cross-domain focused/integration/E2E jurisdiction and evidence — `openspec/specs/test-compatibility/{spec.md,architecture.md}` and `docs/development/TESTING.md`.
- Goal 3 current state and dependency mapping at completion — `docs/development/ROADMAP.md`.
