## Context

The common market-domain and compute-provisioning contracts, extracted compute service, concurrent VM/bare-metal adapter registration, cross-mode site admission, and multi-site storefront capacity aggregation now exist. Current evidence is distributed across unit and integration suites rather than one complete topology. Bare metal has publication and provisioning adapters but needs `market-platform-bare-metal-10-storefront-composition` for a runnable seller role. POOLS-7 must replace the VM storefront's process-global fulfillment URL with durable selected-site scheduling and result/teardown contracts.

A provisioning lifecycle callback can currently read a storefront URL and credential from opaque deal metadata and deduplicates in memory. That path is not a trusted ownership model. Correctness for this proof therefore uses storefront-initiated pull reconciliation; result push remains a separate hardening change.

## Goals / Non-Goals

**Goals:**

- Prove the full many-to-many relationship between two domain-specific storefronts and two provisioning authorities.
- Prove selected-site routing, strict recorded executor dispatch, and lifecycle isolation through restart.
- Prove each provisioning authority can load and execute both compute domains.
- Preserve cross-mode Physical Resource exclusion and generic dependency boundaries.
- Produce deterministic evidence that can run without physical hardware or timing sleeps.

**Non-Goals:**

- Implement prerequisite storefront or fulfillment capabilities.
- Multiplex market domains in one storefront process.
- Establish authenticated reverse push delivery.
- Add provider/executor inference, multi-provider resource aliases, or another resource domain.

## Decisions

### Use a 2×2 storefront-to-site topology

Run separately composed VM and bare-metal storefronts, each configured with trusted bindings to site A and site B. Run one compute provisioning service per site with VM and bare-metal adapter bundles registered in each service.

```text
VM storefront ─────────┬──► site A provisioner [VM, bare metal]
                       └──► site B provisioner [VM, bare metal]
Bare-metal storefront ─┬──► site A provisioner [VM, bare metal]
                       └──► site B provisioner [VM, bare metal]
```

The proof exercises all four edges rather than merely configuring them. This is the smallest topology that proves both one-storefront/many-sites and one-site/many-storefronts. A one-site proof was rejected because it cannot expose selected-site fallback, binding persistence, or cross-authority ID assumptions.

### Keep one market domain per storefront process

The VM and bare-metal applications each inject one complete `MarketDomainContract`. They may belong to one seller and may share a gateway, registry, and provisioning authorities, but they do not share writable storefront state. Multi-domain process multiplexing is a different architecture and is not necessary to prove shared provisioning.

### Make the storefront the aggregation and routing authority

Each storefront selects a configured site before Capacity Reservation and persists the selected binding with lifecycle correlation. Scheduling, fulfillment, polling, and teardown use that binding. A provisioning service does not choose a storefront or another site, and no cross-site retry occurs after reservation.

Cold-start recovery reloads durable ownership rather than fanning a state-changing operation to every site. Read-only discovery may query several sites. This strengthens the current in-memory reservation-to-site cache behavior for production lifecycle operations.

### Use pull reconciliation for correctness

Each storefront polls the selected site's POOLS-7 fulfillment status/result endpoint and applies idempotent local transitions. This proves many-to-many ownership without trusting callback URLs or credentials carried in deal metadata. Optional push delivery can accelerate observation later but must converge with the same durable result.

Reverse capacity/result event authentication, durable outbox delivery, and receiver deduplication remain in `provisioning-result-push-delivery`.

### Require explicit durable executor identity

Submission, result interpretation, teardown, and release select adapters from executor identity persisted with the allocation/fulfillment record. Missing, unknown, or conflicting executor identity fails safely and does not default to VM. Migration or compatibility handling for legacy rows must be explicit and bounded; a process-global default is not accepted evidence.

Fulfillment-provider identity remains an independent mechanism namespace and cannot infer or override domain executor identity.

### Prove domain concurrency at both sites

Each provisioner executes at least one VM and one bare-metal lifecycle during the scenario. The four-edge matrix is arranged so both storefronts use both sites while each site observes both executor kinds. Controlled production adapter backends preserve payload validation, job state, and release behavior without requiring real infrastructure.

### Keep cross-mode conflicts authority-local

Within one site, VM-shareable and bare-metal-exclusive representations of the same Physical Resource resolve to one authoritative identity. Both conflict directions fail before executor work, and release advances capacity state before later admission. IDs from separate site authorities are not assumed to share one database namespace merely because their textual values match.

### Combine behavioral and architecture evidence

The scenario complements, rather than replaces, focused suites for adapter registration, domain conformance, import boundaries, capacity admission, restart recovery, and package installation. Observable barriers and injected deterministic controls replace sleeps.

## Risks / Trade-offs

- **[The 2×2 scenario is expensive]** → Use in-process or containerized deterministic services with controlled adapters and reserve real-backend suites for domain-specific validation.
- **[POOLS-7 contracts evolve]** → Keep this change blocked until its public selected-site lifecycle is accepted; do not add proof-only APIs.
- **[Bare-metal composition duplicates VM behavior]** → Require its prerequisite to extract only proven schema-opaque seams and retain import-boundary tests.
- **[Textually equal IDs across sites are confused]** → Treat the configured authority binding plus authority-issued ID as the routing key where identities are not globally guaranteed.
- **[Pull polling conceals push bugs]** → Record push delivery as separate evidence; do not claim reverse-channel correctness here.
- **[Legacy VM fallback removal breaks old rows]** → Require an explicit migration/quarantine policy and focused compatibility tests before rejecting missing identity in production.

## Migration Plan

1. Complete and archive the bare-metal storefront and POOLS-7 prerequisites.
2. Remove or migrate implicit VM executor fallback in the owning provisioning change.
3. Add deterministic 2×2 fixtures and controlled adapter backends.
4. Prove each edge and both executor kinds before adding restart/failure cases.
5. Run the complete matrix, focused suites, package checks, and strict OpenSpec validation.

Rollback removes only proof topology configuration. Any runtime fix discovered by the proof must have its own compatibility and rollback path in the owning capability.

## Permanent Documentation Promotion

| Decision | Permanent destination |
|---|---|
| One-domain storefront processes sharing several provisioning authorities | `openspec/specs/market-composition/architecture.md` and `docs/development/ARCHITECTURE.md` |
| Trusted selected-site routing and no post-reservation fallback | `openspec/specs/site-capacity/spec.md` and `architecture.md` |
| Mandatory recorded executor identity | `openspec/specs/physical-provisioning/spec.md` and `architecture.md` |
| Deterministic 2×2 lifecycle evidence | `openspec/specs/test-compatibility/spec.md` and `architecture.md` |
| Pull correctness baseline and deferred push acceleration | `openspec/specs/fulfillment/architecture.md` and `physical-provisioning/architecture.md` |
