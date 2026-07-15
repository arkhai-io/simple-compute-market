# Arkhai OpenSpec Index

OpenSpec is the canonical home for normative system behavior and planned changes.

- `specs/` describes current, implemented capability contracts.
- `changes/` describes proposed deltas and their implementation tasks.
- `changes/archive/` records completed changes after their deltas are synchronized.
- `config.yaml` supplies repository context and artifact-quality rules.

Use `bunx @fission-ai/openspec@latest list` to inspect active changes, `show <name>` to read one, and `validate --all --strict` before review.

## Current capability specifications

| Capability | Contract |
|---|---|
| [Market composition](specs/market-composition/spec.md) | Core/kit/domain dependency direction, role ownership, and plugins |
| [Registry discovery](specs/registry-discovery/spec.md) | Publication, filter-spec validation, identity, and compatibility |
| [Negotiation protocol](specs/negotiation-protocol/spec.md) | Signed synchronous rounds, policy hooks, and deterministic Terms |
| [Settlement servicing](specs/settlement-servicing/spec.md) | Plans, claims, mechanism codecs, and heartbeats |
| [Storefront publication](specs/storefront-publication/spec.md) | Seller surfaces, listing reconciliation, and domain runtimes |
| [Site capacity](specs/site-capacity/spec.md) | Capacity authority, reservations, aggregation, and events |
| [Physical provisioning](specs/physical-provisioning/spec.md) | Scheduling, fulfillment, jobs, and lease release |
| [Buyer orchestration](specs/buyer-orchestration/spec.md) | Plugins, policy selection, aggregation, and recovery |
| [Deployment and state](specs/deployment-state/spec.md) | Topology, persistence, migrations, and packaging |
| [Testing and compatibility](specs/test-compatibility/spec.md) | Test levels, fixtures, e2e staging, and rollout contracts |
| [Planning governance](specs/planning-governance/spec.md) | Specification ownership, evidence, and change readiness |

## Active changes

### Market platform initiative — audited

**Goal:** Establish one core market-domain contract implemented by VM, bare metal, and API credits, plus an optional shared compute-provisioning contract and service used by VM and bare metal.

The change artifacts own requirements, design, readiness, and task state. This section is navigation and sequencing only.

#### Domain composition

1. [`market-platform-domain-10-contract`](changes/market-platform-domain-10-contract/) — define and adopt the common core/domain API and versioned provision-terms envelope.

#### Compute provisioning

1. [`market-platform-compute-10-site-lifecycle`](changes/market-platform-compute-10-site-lifecycle/) — separate site authority from executor lease and release policy.
2. [`market-platform-compute-20-provisioning-contract`](changes/market-platform-compute-20-provisioning-contract/) — define the common VM/bare-metal command, job, lease, result, credential, and event wire.
3. [`market-platform-compute-30-extract-service`](changes/market-platform-compute-30-extract-service/) — extract the shared service, package, image, and VM/bare-metal adapter composition.
4. [`market-platform-compute-40-multi-domain-proof`](changes/market-platform-compute-40-multi-domain-proof/) — prove concurrent adapters, ownership-aware event routing, and cross-mode physical accounting.

The two tracks can start independently. Compute changes are ordered by their numeric prefix; the final proof also depends on the domain contract. A newly discovered prerequisite stays in the current task list when required for that change's acceptance criteria, otherwise it receives the same initiative prefix and is cross-linked as an independently archivable change.

### Resource pool physical settlement

**Goal:** Move from operator-managed pool administration to pool-aware
physical settlement resource selection, provider execution, and a cleaned
-up storefront capacity boundary.

1. `pools-1-resource-pool-foundation` — archived
   ([`changes/archive/2026-07-13-pools-1-resource-pool-foundation/`](changes/archive/2026-07-13-pools-1-resource-pool-foundation/)).
   Resource pools, provider configuration, host membership, and the
   administrative API.
2. [`pools-2-physical-settlement-scheduler`](changes/pools-2-physical-settlement-scheduler/) —
   bind a capacity reservation to a specific settlement resource through
   `PhysicalSettlementScheduler`, without yet persisting the binding or
   executing fulfillment against it. Design-reviewed; entering planning.
3. [`pools-3-fulfillment-provider`](changes/pools-3-fulfillment-provider/) —
   `FulfillmentProvider` ABC, `ProviderRegistry`, the Ansible provider, and
   durable `SettlementRecord` persistence. Proposal/design recovered from
   pre-migration planning and verified against current code; still carries
   one unresolved design-review topic (`SettlementRecord` vs. the
   storefront's `settlement_claims`/`ClaimsEngine` ownership boundary) and
   has not had its own design-review session yet.
4. [`pools-4-storefront-capacity-boundary`](changes/pools-4-storefront-capacity-boundary/) —
   remove host-specific placement from the ordinary storefront reservation
   path and apply `pools-2`'s reservation-expiry model storefront-side.
   Recovered and corrected against current code (the `SiteLedger`/
   `SiteResourcesService` rename it originally called for is already done).
5. [`pools-5-shared-provisioning-package`](changes/pools-5-shared-provisioning-package/) —
   **largely superseded.** The originally-planned `core/provisioning`
   package already exists in a different shape
   (`provisioning/compute`/`compute_provisioning`), and its remaining
   extraction goal is already covered by the active
   `market-platform-compute-30-extract-service` change. Taskless and
   activation-gated; see its proposal.md.

Final e2e verification (originally POOLS-6) is not yet drafted as a change
directory.

### Imported change index — specification required

The following proposals/designs are a normalized index of the former TODO and design documents, not implementation-ready plans. Their generated task lists were removed. Before implementation, audit the proposal against current code, rewrite its delta requirements and acceptance scenarios, make its design decisions explicit, and only then create a concrete task artifact. The audited market-platform changes above are no longer part of this imported set.
- `add-database-migration-commands`
- `migrate-registry-to-postgres` — application work; Cloud SQL provisioning remains externally blocked
- `add-settlement-plan-shapes`
- `finish-buyer-cli-residue`
- `configure-pypi-trusted-publishing`
- `type-core-packages`
- `remove-relative-uv-sources`
- `prune-storefront-database`
- `deduplicate-dynaconf-bootstrap`
- `separate-marketplace-registry`
- `fix-golden-image-config`
- `automate-seller-spot`
- `complete-development-documentation`

### Deferred, conditional, or design-gated

These also require the same specification audit, and their activation condition must be satisfied before tasks are created:

- `index-registry-filters` — activate when measured `/listings` latency requires indexes
- `extract-e2e-project` — activate when external operators need an independent runner
- `add-host-capacity-filters` — expand tasks after its API/ranking design review

## Contributor workflow

1. Audit the owning capability spec against current code and focused evidence.
2. Update one independently archivable change with concrete delta requirements and design decisions.
3. Keep imported, deferred, conditional, and externally blocked changes taskless.
4. Create implementation tasks only after the proposal, delta spec, and design are implementation-ready.
5. Implement from that audited task list and run focused behavioral checks.
6. Synchronize the verified delta and archive the completed change.

`docs/development/ARCHITECTURE.md` is the non-normative orientation page. User-facing current behavior and troubleshooting belong in the relevant buyer, seller, or registry documentation; intended changes and their current behavioral context belong in OpenSpec.
