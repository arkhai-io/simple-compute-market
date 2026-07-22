# Active Change Campaigns

This index groups active OpenSpec changes by delivery sequence. It is a planning map, not a normative specification or an umbrella change. Each linked change retains its own acceptance, validation, synchronization, and archive boundary. Capability behavior remains authoritative under [`openspec/specs/`](../specs/README.md).

Statuses here describe readiness, not merely whether a checklist exists:

- **active** — implementation may proceed subject to dependencies in the change;
- **blocked** — retain design/specification, but do not begin blocked implementation;
- **deferred** — no implementation checklist until the recorded activation condition is met.

## Market Platform compute campaign

```text
market-platform-bare-metal-10 ──┐
                                ├──► market-platform-compute-40
POOLS-7 durable lifecycle ──────┘
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`market-platform-bare-metal-10-storefront-composition`](market-platform-bare-metal-10-storefront-composition/) | active; production fulfillment tasks depend on POOLS-7 | Complete independently deployable bare-metal seller composition with one domain contract per process and trusted multi-site bindings |
| 2 | [`market-platform-compute-40-multi-domain-proof`](market-platform-compute-40-multi-domain-proof/) | blocked on bare-metal-10 and POOLS-7 | Deterministic 2×2 VM/bare-metal storefront-to-provisioner lifecycle proof with strict executor and selected-site identity |

Compute-40 uses pull reconciliation as the correctness baseline. Reverse result delivery is a POOLS follow-on and does not block the proof.

## POOLS capacity and fulfillment campaign

```text
archived POOLS-1…6 foundations
              │
              ▼
POOLS-7 durable fulfillment cutover
      ├──► POOLS-8 projection consumption and hints
      ├──► fair scheduling policy
      └──► result push delivery
```

| Change | Status | Relationship |
|---|---|---|
| [`pools-7-storefront-fulfillment-cutover`](pools-7-storefront-fulfillment-cutover/) | active; 72 prerequisite tasks completed | Central durable Settlement Record, scheduling, fulfillment, pull result, recovery, storefront cutover, and teardown path |
| [`pools-8-capacity-projection-and-listing-hints`](pools-8-capacity-projection-and-listing-hints/) | active; may overlap after identity decisions | Persists already-produced projections, maps them into commercial publication/claims, and adds advisory domain-owned hints |
| [`pools-6-fair-scheduling-policy`](pools-6-fair-scheduling-policy/) | blocked/design-gated | Simulation/decisions may proceed; production policy waits for POOLS-7 transactional assignment state and a selected fairness subject |
| [`provisioning-result-push-delivery`](provisioning-result-push-delivery/) | deferred follow-on | Hardens the existing reverse callback with trusted authentication, durable outbox, and receiver deduplication after POOLS-7 results exist |

`add-host-capacity-filters` was archived as superseded by site admission and fulfillment scheduling.

## Registry productionization campaign

```text
migration command convention
          │
          ▼
separate shared registry topology
          │
          ▼
PostgreSQL migration ──► measured filter indexes
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`add-database-migration-commands`](add-database-migration-commands/) | active | Complete explicit migration/runtime-guard behavior for VM and API-credit stateful roles; provisioning is the reference baseline |
| 2 | [`separate-marketplace-registry`](separate-marketplace-registry/) | active | External-registry provider default, explicit embedded profiles, and one canonical full URL |
| 3 | [`migrate-registry-to-postgres`](migrate-registry-to-postgres/) | blocked | Complete Alembic chain, preserved SQLite state, Secret-backed PostgreSQL rollout; waits for external infrastructure and step 2 |
| 4 | [`index-registry-filters`](index-registry-filters/) | deferred | Activate only after PostgreSQL workload measurements exceed a named p95/SLO threshold |

## Package and release-readiness campaign

```text
wheel-only internal dependencies
      ├──► buyer preference hook ──► typed core packages
      └──────────────────────────────────────┬──► trusted PyPI publishing
                                             ┘
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`remove-relative-uv-sources`](remove-relative-uv-sources/) | active | Remove the five remaining internal parent-path sources and enforce wheel-only resolution |
| 2 | [`finish-buyer-cli-residue`](finish-buyer-cli-residue/) | active | Add only the remaining constrained settlement-preference hook; listing rendering and run-log compatibility are baseline |
| 3 | [`type-core-packages`](type-core-packages/) | active after affected public surfaces stabilize | Restore advertised checks, ratchet package by package, and verify `py.typed` in installed wheels |
| 4 | [`configure-pypi-trusted-publishing`](configure-pypi-trusted-publishing/) | externally blocked | Reconcile the complete consumable distribution graph and verify current-name trusted publishers plus PyPI-only downstream installation |

## Independent active changes

| Change | Status | Audited scope |
|---|---|---|
| [`automate-seller-spot`](automate-seller-spot/) | active | Residual active-deal view/client, splitter execution, reference runner, and durable cross-authority decision evidence |
| [`add-settlement-plan-shapes`](add-settlement-plan-shapes/) | active | Generic per-obligation lifecycle plus interval escrow and seller-funded bond policies; heartbeat adjudication/oracle automation deferred |
| [`fix-golden-image-config`](fix-golden-image-config/) | active | Align generated/consumed keys and deliver secrets through the provisioning Secret profile |
| [`deduplicate-dynaconf-bootstrap`](deduplicate-dynaconf-bootstrap/) | active | Parameterized kit/config construction with exact provisioning/e2e parity; storefront loader excluded |
| [`extract-e2e-project`](extract-e2e-project/) | deferred | Activate only for a named external consumer, compatibility profile, and release owner |

`prune-storefront-database` was archived because dead policy tables are already gone and the remaining candidates carry continuation, idempotency, or observability state. `complete-development-documentation` was synchronized and archived after audience-owned documentation became permanent planning governance.
