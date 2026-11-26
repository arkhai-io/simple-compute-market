## Disposition (2026-11-27)

Archived as delivered, in a documentation pass outside the workflow's closeout steps, with no closeout review. Below this section is the proposal as written on 2026-08-15, annotated where it no longer holds.

**Delivered, and carried by marketplace 0.3.0 and 0.4.0.** A frozen registry of storefront contributions, each binding one offering mode to one exact domain identity and contract version (`core_storefront.domain_registry` and `core_storefront.domain_plugins`, entry-point group `market.storefront_contributions`); the explicit `[[storefront_domains]]` selection; an immutable binding on every listing, copied into every negotiation in the opening transaction, with database triggers refusing a change; settlement, fulfillment, result, recovery, and teardown resolving the contract from the recorded binding; the derivation key namespaced by site, offering mode, and domain binding; exact-site routing of every capacity and fulfillment call for accepted work; the public `listing_resource.offering_mode` projected from the binding; and a VM storefront image that installs the bare-metal contribution beside the VM one. The VM, bare-metal, and API-credit storefronts each hold such a registry.

**Built, then removed.** The legacy single-domain migration — `market-storefront config migrate --scope storefront-domains`, `market_storefront.domain_migration`, its tests, and the requirement "Legacy storefront domain migration is transactional" — was removed by `add-database-migration-commands` (archived 2026-11-09). Marketplace 0.3.0 carries it and 0.4.0 does not: its only input is a storefront database from before marketplace 0.3.0, which every storefront's migration baseline refuses. The legacy mapping table this change left in place beside the common binding, `derived_compute_listings`, lost its readers and writers to `unbacked-listing-publication` (archived 2026-09-24) and was dropped by `adopt-databases-upgraded-through-the-floor` (archived 2026-11-26).

**Never built.**

- One storefront process serving both domains. A VM storefront may register the bare-metal contribution, and the lane's and the chart's Bob does: the registration is validated at startup and reported in system status, and serves nothing. The VM executable builds its services, routes, publication loop, and migration chain for the `vm` registration and refuses a record bound to another.
- The bare-metal executable reduced to the shared factory. Bare metal keeps its own executable, server, runtime, listing and negotiate routes, chart, and compose stack, over a registry of its one registration.
- The one-process end-to-end scenario of both lifecycles (task 9.4).

**Who owns it.** `unify-vm-and-bare-metal-storefronts` owns all three. It is the change these documents call `market-platform-compute-40-multi-domain-proof`, rescoped into Goal 3's completing change and renamed. It makes one compute storefront executable serve VM and bare metal, the domains it serves chosen by configuration, so that no dedicated bare-metal storefront remains, and proves it in a lane on every pipeline run: one storefront process publishes a VM listing and a bare-metal listing from one site's hardware, completes a deal of each, and the site refuses the cross-mode conflict. It takes `bare-metal-and-credits-domain-stacks` 4a.3–4a.6 and is gated on `kit-owned-storefront-shell`.

**The delta specifications.** The six deltas written with this proposal were not what reached the permanent specifications on 2026-08-15: those received a shorter set of requirements under other titles, written by hand. `design.md`, "Disposition of the original delta requirements", says where each rule lives. The archive merges a corrective pair instead: `storefront-publication`'s "Commercial mapping identity" gains the offering mode and domain binding in the derivation key, and `test-compatibility`'s "Multi-domain storefront selection has focused compatibility coverage" loses its migration coverage and states what blocks a one-process proof.

## Why

The shared storefront shell accepts one `MarketDomainContract`, while durable listings and accepted negotiations carry no exact domain binding. A process therefore cannot safely publish, negotiate, settle, fulfill, recover, return results, or tear down both VM and bare-metal records without relying on a singleton, payload inference, or domain-specific route copies.

## What Changes

- Require the accepted `storefront-domain-parameterization` seam before implementation, then replace its one injected VM contract with an immutable startup registry of explicit compute-family registrations. Each registration binds one pool offering mode to one exact `DomainIdentity`, supported market-contract version, and complete storefront capability set.
- Require `pool-declared-offering-modes` to make requested mode explicit and enforce it at reservation, scheduling, and provisioning. Publication admits a VM or bare-metal candidate only when its Resource Pool declares that exact mode; withdrawal closes new offers but does not reinterpret accepted work.
- **BREAKING**: remove the storefront's implicit single VM contract, module-global contract lookup, default domain, payload-kind inference, and executor fallback. Missing, duplicate, unknown, unsupported, or mismatched registrations and record bindings fail before domain policy or physical effects.
  *2026-11-27:* delivered in the VM storefront. The bare-metal and API-credit storefronts build their one-registration registry from a module-level contract getter, as `bare-metal-and-credits-domain-stacks`' Section 4a notes.
- Persist an immutable offering-mode/domain binding on every listing and copy it transactionally into every negotiation at creation. Accepted Terms, settlement plans, servicing/recovery state, fulfillment request/result decoding, and teardown resolve the exact recorded binding rather than current publication configuration or request payloads.
- ~~Replace request-time VM-versus-bare-metal branches and parallel role flows with one schema-opaque selector around the injected contract capabilities and codecs.~~ One-element deployments remain valid only as an explicit one-registration instance of the same registry.
  *2026-11-27:* the struck sentence was not delivered. Every storefront is a one-registration instance in what it serves, and VM, bare metal, and API credits each keep their own route set and executable ("Never built", above).
- Publish the canonical registry field `listing_resource.offering_mode` from the recorded offering mode, namespace derivation identity by site, offering mode, and domain binding, and route capacity and fulfillment through the listing's operator-configured trusted site with no cross-site fallback.
- ~~Add ordered storefront migrations for legacy single-domain listings, derived mappings, negotiations, and recoverable settlement state. Migration requires an explicit legacy binding, validates the complete population before commit, preserves stable listing/negotiation/settlement/fulfillment identifiers, and refuses ambiguous, unknown, or cross-domain rows instead of classifying them as VM.~~
  *2026-11-27:* built, then removed by `add-database-migration-commands` ("Built, then removed", above). The binding tables are part of the storefront's marketplace 0.3.0 baseline.
- Package VM and bare-metal domain wheels into one compute-family storefront image and expose explicit registration and trusted-site configuration in TOML, Compose, Helm values/schema/templates, generated examples, health/status, and startup diagnostics without provider credentials or domain secrets in durable bindings.
  *2026-11-27:* delivered. The image's second registration serves nothing ("Never built", above).
- ~~Prove one running storefront handles complete VM and bare-metal publication, negotiation, settlement, reservation, fulfillment, result, restart recovery, and teardown while keeping records, codecs, sites, pool modes, operation identities, and failures isolated across domains.~~
  *2026-11-27:* not delivered: no storefront process serves both domains ("Never built", above). A VM deal and a bare-metal deal each complete in their own lane, through their own storefront.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

*2026-11-27:* the six capabilities below are those the change wrote to by hand on 2026-08-15. The deltas the archive merges modify `storefront-publication` and `test-compatibility` alone ("The delta specifications", above).

- `market-composition`: allow one storefront shell to register several exact versioned domain contracts and resolve only from an immutable record binding.
- `storefront-publication`: bind listings and trusted site mappings to explicit pool offering modes/domain contracts, publish the exact mode, and prohibit cross-mode or cross-site fallback.
- `negotiation-protocol`: persist the listing's binding on thread creation and reject provision envelopes or continuations that do not match it.
- `settlement-servicing`: retain the accepted binding through plan construction, durable servicing, fulfillment result decoding, recovery, and teardown.
- `deployment-state`: define the transactional legacy-state migration, explicit registration configuration, combined package/image, and coordinated rollout/rollback boundary.
- `test-compatibility`: require focused mismatch/unknown/legacy/restart coverage and a complete cross-domain isolation proof through both lifecycles.

## Non-Goals

- Do not add a bare-metal buyer, change the registry's declared compute-family schema identity, or prove buyer CLI discovery; `bare-metal-buyer-domain` owns that role. *2026-11-27:* archived 2026-09-26 as delivered.
- Do not add another offering mode, generalize this composition to API credits, or make compute provisioning mandatory for non-compute storefronts.
- Do not implement pool mode declaration/enforcement, selected-site scheduling, bare-metal provider behavior, or physical conflict accounting here; this change consumes their accepted contracts.
- Do not support one provisioning authority serving several storefronts, many-to-many storefront/authority ownership, buyer-selected site routing, or fallback to another site, domain, contract version, pool mode, or executor.
- Do not merge two independently live writable storefront databases. Rollout selects and transactionally migrates one quiesced database; any other role is drained/closed under its existing recovery contract before the combined process becomes authoritative.
- Do not introduce VM/bare-metal conditionals in shared handlers, copy domain route stacks, reconstruct contracts from stored strings, or preserve singleton compatibility aliases.

## Dependencies and Related Changes

- **Hard prerequisite:** `storefront-domain-parameterization` must be implemented, accepted, and promoted. Its exact immutable `MarketDomainContract` injection through the VM app, lifespan/container, SQLite client, listing service, negotiation helpers, and settlement composition is the seam replaced by the registry; no lower-layer getter may remain.
  *2026-11-27:* landed 2026-08-15; archived 2026-11-27 as delivered, its deltas unmerged because this change replaced its one-contract requirements with the registry form the same day.
- **Hard prerequisite:** `pool-declared-offering-modes` must be implemented, accepted, and promoted, including explicit requested mode, no VM executor fallback, legacy reservation policy, and independent reservation/scheduling/provisioning enforcement.
  *2026-11-27:* archived 2026-09-04.
- The full bare-metal lifecycle evidence reuses accepted seller hooks and trusted selected-site contracts from `market-platform-bare-metal-10-storefront-composition` plus the durable scheduling/result/recovery/teardown APIs from `pools-7-storefront-fulfillment-cutover`. Missing behavior blocks the corresponding task; it is not replaced with a no-op, test-only branch, or VM adapter.
  *2026-11-27:* `market-platform-bare-metal-10-storefront-composition` was archived 2026-09-26 as delivered and `pools-7-storefront-fulfillment-cutover` on 2026-10-27. Both lifecycles exist; what was never built is one process running both.
- `publish-multidimensional-listing-shape` owns capacity-dimension projection. Its current artifacts do not define offering-mode routing; this change uses the already canonical `offering_mode` field for its persisted discriminator and must reuse any compatible publication work that lands first rather than add a second field.
  *2026-11-27:* archived 2026-09-25; no second field exists.
- `bare-metal-buyer-domain` is independently sequenced with this change. `market-platform-compute-40-multi-domain-proof` follows both to add the separate two-authority topology proof.
  *2026-11-27:* `bare-metal-buyer-domain` was archived 2026-09-26 as delivered. The storefront that proof assumes, one process hosting both compute contracts, was not built here; that change, as `unify-vm-and-bare-metal-storefronts`, now builds it ("Who owns it", above).

## Impact

- Affected shared packages: `arkhai-core-storefront`, its SQLite migration chain and tests, and the shared storefront client/fixtures only where an observable generic carrier changes.
- Affected compositions: `domains/vms/storefront`, `domains/bare_metal/storefront`, VM and bare-metal domain entry-point packages, publication/reconciliation, negotiation, settlement, fulfillment recovery, result, and teardown wiring.
- Affected persistence: common listings and negotiation threads plus the current VM/bare-metal derived-listing mappings and recoverable lifecycle correlation. Stable public and operation identifiers are preserved; unresolved legacy classification fails atomically.
- Affected packaging/deployment: domain wheel dependencies, storefront image/build targets, `compose.vms.yml`, relevant domain Compose wiring, Helm storefront values/schema/templates/fixtures, generated configuration, and operator rollout commands. *2026-11-27:* the one rollout command, the legacy migration, is removed.
- Wire compatibility is additive for the existing canonical `listing_resource.offering_mode` field and existing versioned provision envelopes. Runtime compatibility is intentionally strict: unbound or mismatched durable records and requests are rejected rather than routed to VM.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specifications and applicable companion architectures
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge to promote

*2026-11-27:* each destination below was written on 2026-08-15 and has been kept current by later changes, with three exceptions. The migration rules were removed with the migration. `docs/development/DEPLOYMENT_AND_CONFIG.md` and `docs/development/TESTING.md` hold none of this: the configuration and evidence rules are in `openspec/specs/market-composition/configuration.md` and `openspec/specs/market-composition/testing.md`. `design.md`'s Design Promotion Record gives each decision's location.

- Explicit multi-domain registration, immutable per-record selection, and the no-fallback composition boundary — `openspec/specs/market-composition/{spec.md,architecture.md}` and `docs/development/ARCHITECTURE.md`.
- Offering-mode publication, common derived mapping identity, and trusted site routing — `openspec/specs/storefront-publication/{spec.md,architecture.md}`.
- Negotiation binding and mismatch rejection — `openspec/specs/negotiation-protocol/{spec.md,architecture.md}`.
- Accepted-domain continuity through servicing, recovery, result, and teardown — `openspec/specs/settlement-servicing/{spec.md,architecture.md}`.
- Migration, package, image, configuration, and rollout rules — `openspec/specs/deployment-state/{spec.md,architecture.md}` and `docs/development/DEPLOYMENT_AND_CONFIG.md`.
- Cross-domain focused/integration/E2E jurisdiction and evidence — `openspec/specs/test-compatibility/{spec.md,architecture.md}` and `docs/development/TESTING.md`.
- Goal 3 current state and dependency mapping at completion — `docs/development/ROADMAP.md`.
