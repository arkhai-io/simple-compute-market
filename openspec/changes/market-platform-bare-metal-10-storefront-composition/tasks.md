## 1. Baseline and package boundary

- [x] 1.1 Correct `openspec/specs/storefront-publication/spec.md` and verify `openspec/specs/market-composition/spec.md` distinguish the current bare-metal publication plugin from a complete storefront composition.
- [x] 1.2 Inventory VM storefront services by core orchestration, VM semantics, and composition wiring; record exact reuse/refactor decisions in `design.md` before moving code.
- [x] 1.3 Turn `domains/bare_metal/storefront` into a buildable Python distribution with `src/`, tests, entry point, wheel-only internal dependencies, Makefile init/reinit/build/test targets, and no editable sibling sources.
- [x] 1.4 Add package/import-boundary tests proving core and kit packages do not import the bare-metal storefront and the composition does not import VM implementations.

## 2. Complete bare-metal seller contract

- [x] 2.1 Add the bare-metal storefront composition root and inject its validated `MarketDomainContract` through `core_storefront.app_composition.build_storefront_app`.
- [x] 2.2 Implement deterministic bare-metal negotiation policy for listing constraints, lease duration, access method, and buyer access input, with accepted and rejected round tests.
- [x] 2.3 Implement settlement verification and plan construction for bare-metal agreed terms using shared settlement ports and versioned domain envelopes.
- [x] 2.4 Implement schema-opaque persistence/use of bare-metal listing, message, terms, materialization, receipt, and result payloads without adding VM-shaped columns or generic branches.
- [x] 2.5 Define the opt-in per-resource bare-metal projection carrier with distinct `site_id` provenance, `physical_resource_id`, `physical_host_id`, and executor-local `machine_id`, plus same-generation availability, allocation mode, access methods, capacity, and allowlisted capabilities.
- [x] 2.6 Extend site/compute projection production, revision/digest behavior, and redaction so complete and authoritative-empty generations preserve the bare-metal contract without exposing credentials, URLs, provider configuration, or private inventory.
- [x] 2.7 Implement the domain projection interpreter with no identity fallback, site-scoped derivation keys, explicit capacity/capability conflict rejection, and unavailable/stale/authoritative-empty generation semantics.
- [x] 2.8 Move derived bare-metal publication tracking into the storefront migration chain and add injected core publication selection/runner wiring without runtime DDL or VM imports.
- [x] 2.9 Add producer, projection-carrier, interpreter, digest/redaction, publication, migration, and two-site collision tests proving exact opaque listing payloads.
- [x] 2.10 Implement the runnable listing, negotiation, commercial-settlement, persistent operator-state, and health HTTP surface, then add contract tests for successful flows, authentication, restart persistence, truthful pre-fulfillment responses, and domain-validation failures.

## 3. Trusted multi-site composition

- [x] 3.1 Add bare-metal storefront configuration for stable `site_id` to provisioning authority URL and credential bindings, including startup validation and redacted diagnostics.
- [x] 3.2 Reuse or extract schema-opaque aggregate capacity/projection wiring so the bare-metal storefront can load, poll, reserve, and retain independent generations from several sites.
- [x] 3.3 Persist the selected trusted site with agreement lifecycle correlation and reject buyer-controlled URL, credential, or conflicting site assertions as routing authority.
- [x] 3.4 Add focused tests for placement across two sites, selected-site write routing after restart, projection staleness, and conflicting untrusted routing data.

## 4. POOLS-7 fulfillment integration

- [ ] 4.1 Reconcile this design against the accepted POOLS-7 public scheduling, fulfillment, status/result, and teardown contracts before production wiring; do not copy its repositories or recovery workers into the storefront. **Blocked: the 2026-07-23 audit confirms durable internal scheduling has landed, but POOLS-7 Sections 6–8 and 10 have not yet published the required HTTP/client contracts. See `design.md`, “POOLS-7 public-contract reconciliation — 2026-07-23.”**
- [ ] 4.2 Translate accepted `BareMetalMaterialization` into generic Physical Settlement requirements and schedule at the selected provisioning site.
- [ ] 4.3 Begin fulfillment through the recorded bare-metal executor identity and persist only the returned reservation, settlement, fulfillment, receipt, and result references needed for recovery.
- [ ] 4.4 Poll normalized fulfillment status/result and expose `BareMetalReceipt` and `BareMetalAccessResult` without requiring reverse push delivery.
- [ ] 4.5 Route teardown/reclaim through the recorded fulfillment and bare-metal executor identity, preserving capacity until authoritative teardown policy permits release.
- [ ] 4.6 Add restart, duplicate-call, failure, result-security, and exactly-once release integration tests against the real compute-provisioning service.

## 5. Packaging and deployment

- [ ] 5.1 Add root `.dist` build/reinit ordering for the bare-metal storefront and verify installation from built wheels without source-tree imports.
- [ ] 5.2 Add the bare-metal storefront image/entry point and choose the dedicated-image versus shared-image packaging decision in `design.md` from measured build/dependency evidence.
- [ ] 5.3 Add independently selectable deployment values, persistence, Secret-backed seller/site configuration, service, health checks, and migration phase for the bare-metal role.
- [ ] 5.4 Add deployment render tests proving VM-only, bare-metal-only, and combined seller profiles contain no waits or references to disabled storefront roles.
- [ ] 5.5 Add operator configuration examples that expose separately composed VM and bare-metal roles through explicit URLs or gateway paths without sharing writable state.

## 6. Lifecycle and campaign verification

- [ ] 6.1 Run bare-metal domain, publication, storefront unit/integration, shared core storefront, compute contract, site capacity, and POOLS-7 fulfillment suites.
- [ ] 6.2 Run a complete one-storefront/one-site bare-metal agreement from publication through negotiation, settlement, reservation, fulfillment result, teardown, and capacity restoration.
- [ ] 6.3 Rebuild affected wheels/images and run packaging, import-boundary, migration, and deployment-render checks.
- [ ] 6.4 Add this completed composition as prerequisite evidence in `market-platform-compute-40-multi-domain-proof` without duplicating the final many-to-many topology scenario here.

## 7. Permanent documentation promotion

- [ ] 7.1 Promote the one-domain-per-process composition and bare-metal seller boundary to `openspec/specs/market-composition/spec.md` and `openspec/specs/market-composition/architecture.md`.
- [ ] 7.2 Promote complete seller lifecycle and trusted selected-site behavior to `openspec/specs/storefront-publication/spec.md` and `openspec/specs/storefront-publication/architecture.md`.
- [ ] 7.3 Promote package/deployment topology to `openspec/specs/deployment-state/spec.md`, `openspec/specs/deployment-state/architecture.md`, and the role map in `docs/development/ARCHITECTURE.md`.
- [ ] 7.4 Update `openspec/specs/physical-provisioning/architecture.md` and `openspec/specs/fulfillment/architecture.md` with the accepted pull-based composition boundary and any remaining result-delivery limitation.
- [ ] 7.5 Record every promoted decision in `design.md`, run strict validation for the change and affected permanent specs, and archive only after current-state documentation matches verified behavior.
