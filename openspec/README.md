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

### Imported change index — specification required

The following proposals/designs are a normalized index of the former TODO and design documents, not implementation-ready plans. Their generated task lists were removed. Before implementation, audit the proposal against current code, rewrite its delta requirements and acceptance scenarios, make its design decisions explicit, and only then create a concrete task artifact.
- `add-database-migration-commands`
- `migrate-registry-to-postgres` — application work; Cloud SQL provisioning remains externally blocked
- `add-settlement-plan-shapes`
- `prove-multi-domain-capacity`
- `genericize-storefront-client-wire`
- `finish-buyer-cli-residue`
- `configure-pypi-trusted-publishing`
- `type-core-packages`
- `add-provisioning-cli`
- `remove-relative-uv-sources`
- `prune-storefront-database`
- `deduplicate-dynaconf-bootstrap`
- `separate-marketplace-registry`
- `fix-golden-image-config`
- `separate-site-resource-lifecycle`
- `automate-seller-spot`
- `migrate-compute-provisioning`
- `complete-development-documentation`

### Deferred, conditional, or design-gated

These also require the same specification audit, and their activation condition must be satisfied before tasks are created:

- `index-registry-filters` — activate when measured `/listings` latency requires indexes
- `extract-e2e-project` — activate when external operators need an independent runner
- `extract-storefront-callback-client` — activate if the dependency becomes a demonstrated maintenance problem
- `add-host-capacity-filters` — expand tasks after its API/ranking design review

## Contributor workflow

1. Audit the owning capability spec against current code and focused evidence.
2. Update one independently archivable change with concrete delta requirements and design decisions.
3. Keep imported, deferred, conditional, and externally blocked changes taskless.
4. Create implementation tasks only after the proposal, delta spec, and design are implementation-ready.
5. Implement from that audited task list and run focused behavioral checks.
6. Synchronize the verified delta and archive the completed change.

`docs/development/ARCHITECTURE.md` is the non-normative orientation page. User-facing current behavior and troubleshooting belong in the relevant buyer, seller, or registry documentation; intended changes and their current behavioral context belong in OpenSpec.
