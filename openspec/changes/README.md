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
| 2 | [`pool-declared-offering-modes`](pool-declared-offering-modes/) | active; no blocking dependency | A pool declares which offering modes it can deliver; reservations, scheduling, and provisioning each reject an undeclared mode; the requested mode is supplied rather than inferred from a `vm_host` attribute. Removes both implicit VM executor fallbacks. Prerequisite of `multi-domain-storefront-composition` |
| [`storefront-domain-parameterization`](storefront-domain-parameterization/) | active; no blocking dependency | Composes the VM storefront around an injected market-domain contract, matching the shape the bare-metal runtime already uses. Behavior-preserving refactor; prerequisite of `multi-domain-storefront-composition` |
| [`multi-domain-storefront-composition`](multi-domain-storefront-composition/) | active; depends on `storefront-domain-parameterization` and `pool-declared-offering-modes` | Hosts several compute-family contracts in one storefront process, resolving each record's contract from the listing's recorded offering mode. Supersedes the one-contract-per-process position; requires scope review of `market-platform-compute-40-multi-domain-proof` |
| [`bare-metal-buyer-domain`](bare-metal-buyer-domain/) | active; sequenced with `multi-domain-storefront-composition` | Adds the missing bare-metal buyer package and widens the registry's declared schema identity to scope the compute family, so one catalogue serves both form factors |
| [`market-platform-compute-40-multi-domain-proof`](market-platform-compute-40-multi-domain-proof/) | blocked on bare-metal-10 and POOLS-7 | Deterministic 2×2 VM/bare-metal storefront-to-provisioner lifecycle proof with strict executor and selected-site identity |

Compute-40 uses pull reconciliation as the correctness baseline. Reverse result delivery is a POOLS follow-on and does not block the proof.

## POOLS capacity and fulfillment campaign

```text
archived POOLS-1…6 foundations
              │
              ▼
POOLS-7 durable fulfillment cutover
      ├──► POOLS-8 projection consumption and hints ──┐
      │                                               ├──► POOLS-9 retire local physical authority
      │         capacity-resource-administration ─────┘
      ├──► fair scheduling policy
      ├──► add-buyer-vm-connectivity-terms
      ├──► add-storefront-principal-authentication ──► result push delivery
      └──► result push delivery
```

| Change | Status | Relationship |
|---|---|---|
| [`pools-7-storefront-fulfillment-cutover`](pools-7-storefront-fulfillment-cutover/) | active; 72 prerequisite tasks completed | Central durable Settlement Record, scheduling, fulfillment, pull result, recovery, storefront cutover, and teardown path |
| [`pools-8-capacity-projection-and-listing-hints`](pools-8-capacity-projection-and-listing-hints/) | active; may overlap after identity decisions | Persists already-produced projections, maps them into commercial publication/claims, and adds advisory domain-owned hints |
| [`capacity-resource-administration`](capacity-resource-administration/) | active; no blocking dependency | Makes the site-ledger capacity resource the single authoritative declaration of sellable capacity across every dimension, with a startup import, an operator administration surface, and a migration deriving declarations from legacy host GPU columns. Prerequisite of `pools-9` |
| [`pools-9-retire-local-physical-authority`](pools-9-retire-local-physical-authority/) | planned; blocked on `capacity-resource-administration` | Retires every remaining physical-resource concern from the VM storefront: the local physical-authority tables, `compute_allocations`, CSV import and its deployment contract, the orphaned physical admin surface, and the always-`None` `vm_host` plumbing. Requires a direct pool-commercial-metadata admin endpoint as a prerequisite of removing CSV import, not an optional follow-up. Expanded 2026-08-06 by the Goal 1 sweep. The deployment-bake trigger for its own start remains undefined by design; the dependency above is a necessary gate, not a sufficient one |
| [`structured-capacity-requirements`](structured-capacity-requirements/) | design phase; not yet planned | Structured buyer-facing `requirements` shape, `offering_type` separated from the site-inventory `resource_type` discriminator, and canonical `ResourceRequirement`/`CapacityClaim` vocabulary; carries forward design decisions from POOLS-7 Section 11.2's code review. Coordinate final shape with `pools-8`'s claim-construction work before implementing. Rates are now a third consumer of the family-grouped shape (2026-08-06), so `capacity-shape-pricing` waits on this vocabulary before extending pricing configuration beyond the `gpu` family |
| [`publish-multidimensional-listing-shape`](publish-multidimensional-listing-shape/) | active; no blocking dependency | Publishes the capacity dimensions a projection declares into each listing's `offer_resource`. Fixes a live defect: the registry's `vcpu_count_min`/`ram_gb_min`/`disk_gb_min` filters fail closed on the missing field, so a buyer filtering on RAM matches nothing today. Value is realised once `capacity-resource-administration` makes declarations exist; correctness does not depend on it |
| [`capacity-shape-pricing`](capacity-shape-pricing/) | active; depends on `publish-multidimensional-listing-shape` and on `structured-capacity-requirements`' vocabulary | Per-dimension rates carried inside the family-grouped capability shape, a replaceable price aggregator, and the negotiated quantity becoming a rate multiplier over the listing's advertised minimum so concessions stay comparable when the shape changes. Unblocks `negotiation-driven-capacity-resize` Section 2 |
| [`capacity-shape-envelope`](capacity-shape-envelope/) | active; independent | Kit-level admissibility: whether a whole shape is one the seller will consider, and what range remains admissible for one dimension given the rest. Static min/max ships behind a predicate-and-range interface shaped for the occupancy-dependent feasible region expected later |
| [`negotiation-capacity-feasibility-probe`](negotiation-capacity-feasibility-probe/) | active; independent | Verifies a requested shape against the authoritative site before terms are agreed, consuming nothing, reporting unservable distinctly from seller-declined. Shared prerequisite: also required before a held reservation can be billed |
| [`pools-6-fair-scheduling-policy`](pools-6-fair-scheduling-policy/) | blocked/design-gated | Simulation/decisions may proceed; production policy waits for POOLS-7 transactional assignment state and a selected fairness subject |
| [`add-buyer-vm-connectivity-terms`](add-buyer-vm-connectivity-terms/) | design phase; not yet planned | Buyer-specified, negotiated VM connectivity (FRP relay) terms, replacing storefront-operator-only configuration as the sole source; depends on POOLS-7 Section 9's `connectivity` field shape |
| [`add-storefront-principal-authentication`](add-storefront-principal-authentication/) | design phase; not yet planned | Multi-principal storefront request identity and per-record `owner_principal` ownership, extending the existing single-shared-key model; unblocks real ownership enforcement for POOLS-7 Section 8's pull endpoints and supplies the identity half of push delivery's trust model |
| [`provisioning-result-push-delivery`](provisioning-result-push-delivery/) | deferred follow-on | Hardens the existing reverse callback with trusted authentication, durable outbox, and receiver deduplication after POOLS-7 results exist; also depends on `add-storefront-principal-authentication` for owner/site identity |
| [`fix-vm-fulfillment-capacity-boundary`](fix-vm-fulfillment-capacity-boundary/) | active; independent of POOLS-7 | Fixes three current-path defects an external pre-qualification review found on `dev`: stale `resource_id`/`vm_host` requirements left over from the opaque-reservation cutover, VM shape (GPU/CPU/RAM/disk) never reaching the provisioning request, and a corrupted GPU-attachment-discovery shell task. No dependency on or from POOLS-7 Sections 10/11; the review's fourth finding stays as POOLS-7 task 10.14 |

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
| [`kit-storefront-composition-seam`](kit-storefront-composition-seam/) | active; depends on `storefront-domain-parameterization` | Defines where kit-owned storefront runtime sits and proves it with the two smallest duplicated concerns, composing all three domains. Establishes the rule that an extracted concern leaves no domain-local copy |
| [`kit-owned-negotiation-runtime`](kit-owned-negotiation-runtime/) | active; depends on the seam | Extracts the synchronous negotiation runtime (914 lines in VM, 609 in API credits, absent in bare metal). Largest of the extractions; collides with in-flight Goal 2 and Goal 5 negotiation work |
| [`kit-owned-settlement-runtime`](kit-owned-settlement-runtime/) | active; depends on the seam | Extracts settlement job orchestration, claim servicing, and failure handling as one control flow. Coordinate with `add-settlement-plan-shapes` |
| [`kit-owned-capacity-and-publication`](kit-owned-capacity-and-publication/) | active; depends on the seam | Extracts the storefront capacity client and publication runtime; the capacity client's 556-vs-217-line gap needs per-capability judgment rather than a whole-file move |
| [`bare-metal-and-credits-domain-stacks`](bare-metal-and-credits-domain-stacks/) | active; depends on all four extractions and on `bare-metal-buyer-domain` | Delivers Goal 4's capability: a bare-metal deployable stack, per-domain end-to-end deal paths, and API-credits recomposition onto kit |
| [`default-no-pre-settlement-capacity-hold`](default-no-pre-settlement-capacity-hold/) | active; configuration change applied 2026-08-06, validation outstanding | Ships `capacity.hold_ttl_seconds = 0` for both storefronts. Acquiring a hold costs two signed requests with no funds, escrow, or rate limit, so one actor could hold an entire storefront's inventory indefinitely at no cost; shortening the window only raises the request rate needed. Reversed by `billable-capacity-reservations` once holding is charged |
| [`capacity-reservation-lifecycle-hardening`](capacity-reservation-lifecycle-hardening/) | active; no blocking dependency | Fixes three reservation-row defects found in the 2026-08-06 capacity-economics sweep: holds placed during negotiation bypass `reserve()`'s idempotency guard entirely, expiry is a full scan of held rows on every ledger operation, and terminal reservations accumulate without bound. Prerequisite for `negotiation-time-capacity-hold` |
| [`billable-capacity-reservations`](billable-capacity-reservations/) | active; depends on `capacity-shape-pricing` and `capacity-reservation-lifecycle-hardening` | A hold carries a burn rate from the commercial rate structure; maximum duration derives from committed funds rather than a configured TTL; held time is charged as a serviced obligation with the remainder returned. Prices exclusivity instead of rate-limiting identity |
| [`negotiation-time-capacity-hold`](negotiation-time-capacity-hold/) | active; depends on `billable-capacity-reservations` and `capacity-reservation-lifecycle-hardening` | Moves the hold from terms acceptance to the counterparty's first differing-terms proposal, one superseded reservation per negotiation, released on abandonment. Inquiry stays unheld and unfunded |
| [`automate-seller-spot`](automate-seller-spot/) | active | Residual active-deal view/client, splitter execution, reference runner, and durable cross-authority decision evidence |
| [`negotiation-driven-capacity-resize`](negotiation-driven-capacity-resize/) | Sections 0–1 complete; Section 2 unblocked 2026-08-06, not yet planned | Round-0 shape-mismatch guard shipped; Section 2 (a revised-terms field carrying a shape change between rounds, and `resize_reservation`'s first caller) was parked until seller policy could price an alternative shape. `capacity-shape-pricing` now owns that policy, so the discuss-phase trigger has fired; planning waits on the three new Goal 2 changes' decisions |
| [`add-settlement-plan-shapes`](add-settlement-plan-shapes/) | active | Generic per-obligation lifecycle plus interval escrow and seller-funded bond policies; heartbeat adjudication/oracle automation deferred |
| [`fix-golden-image-config`](fix-golden-image-config/) | active | Align generated/consumed keys and deliver secrets through the provisioning Secret profile |
| [`deduplicate-dynaconf-bootstrap`](deduplicate-dynaconf-bootstrap/) | active | Parameterized kit/config construction with exact provisioning/e2e parity; storefront loader excluded |
| [`extract-e2e-project`](extract-e2e-project/) | deferred | Activate only for a named external consumer, compatibility profile, and release owner |

`prune-storefront-database` was archived because dead policy tables are already gone and the remaining candidates carry continuation, idempotency, or observability state. `complete-development-documentation` was synchronized and archived after audience-owned documentation became permanent planning governance.
