# Active Change Campaigns

This index groups active OpenSpec changes by delivery sequence. It is a planning map, not a normative specification or an umbrella change. Each linked change retains its own acceptance, validation, synchronization, and archive boundary. Capability behavior remains authoritative under [`openspec/specs/`](../specs/README.md).

Statuses here describe readiness, not merely whether a checklist exists:

- **active** — implementation may proceed subject to dependencies in the change;
- **blocked** — retain design/specification, but do not begin blocked implementation;
- **deferred** — no implementation checklist until the recorded activation condition is met.

## How this index is organized

Campaigns come in two kinds.

**Roadmap goals** are the directional goals in [`docs/development/ROADMAP.md`](../../docs/development/ROADMAP.md). Those sections carry sequencing and readiness only — why a goal exists, the value it delivers, and what is still true today all live in the roadmap, which is the single place they are maintained.

**Lesser goals** are coherent bodies of work with no roadmap goal behind them. Each gets a short summary, because a reader landing on four registry changes deserves to know what they add up to. A lesser goal is not a smaller roadmap goal: it is work that improves how the system is built without changing what the market can do.

A change appears exactly once, in its primary home. Where a change serves more than one goal, the other goal notes it rather than listing it again.

## Roadmap goal — Consolidate physical-resource authority in the provisioning service

```text
capacity-resource-administration ──► pools-9-retire-local-physical-authority
fix-vm-fulfillment-capacity-boundary (independent)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`capacity-resource-administration`](capacity-resource-administration/) | active; no blocking dependency | Site capacity resources become the single authoritative declaration of sellable capacity across every dimension, with a startup import, an operator administration surface, and a migration deriving declarations from legacy host GPU columns |
| [`pools-9-retire-local-physical-authority`](pools-9-retire-local-physical-authority/) | planned; blocked on `capacity-resource-administration` | Retires every remaining physical-resource concern from the VM storefront: local physical-authority tables, `compute_allocations`, CSV import and its deployment contract, the orphaned physical admin surface, and the always-`None` `vm_host` plumbing. The deployment-bake trigger for its own start remains undefined by design; the dependency is a necessary gate, not a sufficient one |
| [`fix-vm-fulfillment-capacity-boundary`](fix-vm-fulfillment-capacity-boundary/) | active | Removes stale physical-placement fields from the current fulfillment path and derives fulfillment shape from committed reservation dimensions. Also serves Goal 2 |

## Roadmap goal — Negotiate full compute capability, not GPU count alone

```text
publish-multidimensional-listing-shape ──┐
structured-capacity-requirements ────────┴──► capacity-shape-pricing ──► negotiation-driven-capacity-resize §2
capacity-shape-envelope, negotiation-capacity-feasibility-probe (independent)
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`publish-multidimensional-listing-shape`](publish-multidimensional-listing-shape/) | active; no blocking dependency | Publishes the capacity dimensions and offering mode a projection declares into each listing's `offer_resource`. Fixes a live defect: the registry's dimension and form-factor filters fail closed on missing fields, so they match nothing today. Also serves Goal 3 |
| [`structured-capacity-requirements`](structured-capacity-requirements/) | design phase; not yet planned | Structured buyer-facing `requirements` shape, `offering_type` separated from the site-inventory `resource_type` discriminator, canonical claim vocabulary. Rates became a third consumer of its family-grouped shape (2026-08-06), so `capacity-shape-pricing` waits on this vocabulary before extending pricing beyond the `gpu` family |
| [`capacity-shape-pricing`](capacity-shape-pricing/) | active; depends on `publish-multidimensional-listing-shape` and `structured-capacity-requirements`' vocabulary | Per-dimension rates carried inside the family-grouped capability shape, a replaceable price aggregator, and the negotiated quantity becoming a rate multiplier so concessions stay comparable when the shape changes |
| [`capacity-shape-envelope`](capacity-shape-envelope/) | active; independent | Kit-level admissibility: whether a whole shape is one the seller will consider, and what range remains admissible for one dimension given the rest, behind an interface shaped for the occupancy-dependent feasible region expected later |
| [`negotiation-capacity-feasibility-probe`](negotiation-capacity-feasibility-probe/) | active; independent | Verifies a requested shape against the authoritative site before terms are agreed, consuming nothing, reporting unservable distinctly from seller-declined. Shared prerequisite: also required before a held reservation can be billed |
| [`negotiation-driven-capacity-resize`](negotiation-driven-capacity-resize/) | Sections 0–1 complete; Section 2 unblocked 2026-08-06, not yet planned | Round-0 shape-mismatch guard shipped. Section 2 — a revised-terms field carrying a shape change between rounds, and `resize_reservation`'s first caller — was parked until seller policy could price an alternative shape; `capacity-shape-pricing` now owns that policy |
| [`add-buyer-vm-connectivity-terms`](add-buyer-vm-connectivity-terms/) | design phase; not yet planned | Buyer-specified, negotiated VM connectivity terms replacing storefront-operator-only configuration; depends on POOLS-7 Section 9's `connectivity` field shape |

## Roadmap goal — One storefront serving several compute-family domains

```text
pool-declared-offering-modes ───────┐
storefront-domain-parameterization ─┴──► multi-domain-storefront-composition ──┐
market-platform-bare-metal-10 ─────────────────────────────────────────────────┼──► compute-40
bare-metal-buyer-domain ───────────────────────────────────────────────────────┘
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`market-platform-bare-metal-10-storefront-composition`](market-platform-bare-metal-10-storefront-composition/) | active; production fulfillment tasks depend on POOLS-7 | Independently deployable bare-metal seller composition with trusted multi-site bindings. Its one-contract-per-process scope fence was struck 2026-08-06 as superseded |
| [`pool-declared-offering-modes`](pool-declared-offering-modes/) | active; no blocking dependency | A pool declares which offering modes it can deliver; reservation, scheduling, and provisioning each reject an undeclared mode; the requested mode is supplied rather than inferred. Removes both implicit VM executor fallbacks and owns the legacy-row migration for reservations lacking executor identity |
| [`storefront-domain-parameterization`](storefront-domain-parameterization/) | active; no blocking dependency | Composes the VM storefront around an injected market-domain contract, matching the bare-metal runtime's existing shape. Behavior-preserving refactor |
| [`multi-domain-storefront-composition`](multi-domain-storefront-composition/) | active; depends on `storefront-domain-parameterization` and `pool-declared-offering-modes` | Hosts several compute-family contracts in one storefront process, resolving each record's contract from the listing's recorded offering mode |
| [`bare-metal-buyer-domain`](bare-metal-buyer-domain/) | active; sequenced with `multi-domain-storefront-composition` | Adds the missing bare-metal buyer package and widens the registry's declared schema identity to scope the compute family, so one catalogue serves both form factors |
| [`market-platform-compute-40-multi-domain-proof`](market-platform-compute-40-multi-domain-proof/) | blocked on its prerequisites | Deterministic proof of one multi-domain storefront against two provisioning authorities. Rewritten 2026-08-06: most of its implementation work has shipped, and many-to-many storefront-to-authority ownership was removed from scope rather than deferred |

## Roadmap goal — Make a domain a composition of kit

```text
kit-storefront-composition-seam
      ├──► kit-owned-negotiation-runtime ─────────┐
      ├──► kit-owned-settlement-runtime ──────────┼──► bare-metal-and-credits-domain-stacks
      └──► kit-owned-capacity-and-publication ────┘
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`kit-storefront-composition-seam`](kit-storefront-composition-seam/) | active; depends on `storefront-domain-parameterization` | Defines where kit-owned storefront runtime sits and proves it with the two smallest duplicated concerns, composing all three domains. Establishes the rule that an extracted concern leaves no domain-local copy |
| [`kit-owned-negotiation-runtime`](kit-owned-negotiation-runtime/) | active; depends on the seam | Extracts the synchronous negotiation runtime. Largest of the extractions; collides with in-flight Goal 2 and Goal 5 negotiation work |
| [`kit-owned-settlement-runtime`](kit-owned-settlement-runtime/) | active; depends on the seam | Extracts settlement job orchestration, claim servicing, and failure handling as one control flow. Coordinate with `add-settlement-plan-shapes` |
| [`kit-owned-capacity-and-publication`](kit-owned-capacity-and-publication/) | active; depends on the seam | Extracts the storefront capacity client and publication runtime; the capacity client's size gap needs per-capability judgment rather than a whole-file move |
| [`bare-metal-and-credits-domain-stacks`](bare-metal-and-credits-domain-stacks/) | active; depends on all four extractions and on `bare-metal-buyer-domain` | A bare-metal deployable stack, per-domain end-to-end deal paths, and API-credits recomposition onto kit. Delivers the goal's completion test |

## Roadmap goal — Make capacity exclusivity compensated

```text
default-no-pre-settlement-capacity-hold (interim posture, reversed by billing)
capacity-reservation-lifecycle-hardening ──► billable-capacity-reservations ──► negotiation-time-capacity-hold
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`default-no-pre-settlement-capacity-hold`](default-no-pre-settlement-capacity-hold/) | active; configuration applied 2026-08-06, validation outstanding | Ships `capacity.hold_ttl_seconds = 0` for both storefronts, closing a denial vector by denying the capability. Reversed by `billable-capacity-reservations` once holding is charged |
| [`capacity-reservation-lifecycle-hardening`](capacity-reservation-lifecycle-hardening/) | active; no blocking dependency | Fixes three reservation-row defects: holds placed during negotiation bypass the idempotency guard, expiry scans all held rows on every ledger operation, and terminal reservations accumulate without bound |
| [`billable-capacity-reservations`](billable-capacity-reservations/) | active; depends on `capacity-shape-pricing` and `capacity-reservation-lifecycle-hardening` | A hold carries a burn rate from the commercial rate structure; maximum duration derives from committed funds rather than a configured TTL; held time is charged as a serviced obligation with the remainder returned |
| [`negotiation-time-capacity-hold`](negotiation-time-capacity-hold/) | active; depends on `billable-capacity-reservations` and `capacity-reservation-lifecycle-hardening` | Moves the hold from terms acceptance to the counterparty's first differing-terms proposal, one superseded reservation per negotiation, released on abandonment. Inquiry stays unheld and unfunded |

## Lesser goal — POOLS capacity and fulfillment foundation

**What it adds up to.** The durable capacity and fulfillment substrate every roadmap goal builds on: a central Settlement Record, transactional scheduling and assignment, pull-correct fulfillment results, recovery, and the projections a storefront consumes instead of owning hardware itself. POOLS-1 through POOLS-6's foundations are archived. This is not a roadmap goal because it changes how the system is built rather than what the market can do — but nearly every goal has a dependency edge into it.

```text
archived POOLS-1…6 foundations ──► POOLS-7 durable fulfillment cutover ──► POOLS-8 projection consumption
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`pools-7-storefront-fulfillment-cutover`](pools-7-storefront-fulfillment-cutover/) | active; 72 prerequisite tasks completed | Central durable Settlement Record, scheduling, fulfillment, pull result, recovery, storefront cutover, and teardown path |
| [`pools-8-capacity-projection-and-listing-hints`](pools-8-capacity-projection-and-listing-hints/) | active | Persists already-produced projections, maps them into commercial publication and claims, and adds advisory domain-owned hints |

`add-host-capacity-filters` was archived as superseded by site admission and fulfillment scheduling.

## Lesser goal — Service-to-service trust and event delivery

**What it adds up to.** A storefront and its site authorities authenticate each other with one shared secret that both gates inbound requests and signs outbound callbacks, and the storefront learns about everything by polling. These two changes replace the secret with mutual asymmetric identity, then replace three polling loops with authenticated delivery. Not a roadmap goal — no market behavior changes — but it closes an impersonation path, makes key rotation possible without downtime, gives each site a wallet identity that later collateral work can build on, and is what lets end-to-end scenarios wait on facts rather than intervals.

```text
service-identity-signing ──► replace-polling-with-authenticated-push
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`service-identity-signing`](service-identity-signing/) | active; supersedes `add-storefront-principal-authentication` (2026-08-06) | Asymmetric eip191 request signing in both directions; storefronts hold a `(site_id, url, identity)` registry; identities rotate through overlapping acceptance |
| [`replace-polling-with-authenticated-push`](replace-polling-with-authenticated-push/) | active; supersedes `provisioning-result-push-delivery` (2026-08-06); depends on `service-identity-signing` and POOLS-7 | Replaces all three cross-service polling loops with authenticated delivery from a transactional outbox, and refactors scenarios to await events. Pull and the local resume sweep stay authoritative; disabling delivery must leave the system correct and only slower |

## Lesser goal — Settlement and deal servicing depth

**What it adds up to.** Settlement handles one escrow shape well. These changes generalize it to arbitrary obligation plans, add the automation a seller needs to run spot inventory without manual intervention, and close a recovery gap where an ambiguous on-chain submission can currently only be resolved by an operator. Not a roadmap goal — the market's capabilities are unchanged — but every goal that touches money lands on this machinery, and `billable-capacity-reservations` reuses its per-obligation lifecycle directly.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`add-settlement-plan-shapes`](add-settlement-plan-shapes/) | active | Generic per-obligation lifecycle plus interval escrow and seller-funded bond policies; heartbeat adjudication and oracle automation deferred |
| [`automate-seller-spot`](automate-seller-spot/) | active | Residual active-deal view and client, splitter execution, reference runner, and durable cross-authority decision evidence |
| [`add-alkahest-attestation-reference-query`](add-alkahest-attestation-reference-query/) | externally blocked | Bounded attestation lookup by reference UID, making ambiguous submissions automatically reconcilable. Blocked on an upstream release; nothing in this repository can unblock it |

## Lesser goal — Registry productionization

**What it adds up to.** The registry runs on SQLite with an embedded-by-default topology suited to development and not to a shared marketplace. This sequence makes migrations explicit, separates the registry into a genuinely shared external service, moves it to PostgreSQL, and only then indexes filters against measured load. Not a roadmap goal — discovery semantics do not change — but it is what lets one registry serve more than one seller's storefront.

```text
add-database-migration-commands ──► separate-marketplace-registry ──► migrate-registry-to-postgres ──► index-registry-filters
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`add-database-migration-commands`](add-database-migration-commands/) | active | Explicit migration and runtime-guard behavior for VM and API-credit stateful roles; provisioning is the reference baseline. Five in-flight changes each add a migration that would have to conform, so landing this first is materially cheaper than retrofitting them |
| 2 | [`separate-marketplace-registry`](separate-marketplace-registry/) | active | External-registry provider default, explicit embedded profiles, and one canonical full URL |
| 3 | [`migrate-registry-to-postgres`](migrate-registry-to-postgres/) | blocked | Complete Alembic chain, preserved SQLite state, Secret-backed PostgreSQL rollout; waits for external infrastructure and step 2 |
| 4 | [`index-registry-filters`](index-registry-filters/) | deferred | Activate only after PostgreSQL workload measurements exceed a named p95/SLO threshold |

## Lesser goal — Package and release readiness

**What it adds up to.** The repository cannot publish a coherent set of installable distributions: internal dependencies resolve through relative paths, type checking is advertised but not enforced, and the publisher inventory does not match the packages that exist. This sequence makes every internal dependency wheel-resolvable, restores the checks, and reconciles the distribution graph. Not a roadmap goal — no behavior changes — but nothing outside this repository can consume the packages until it is done.

```text
remove-relative-uv-sources ──► finish-buyer-cli-residue ──► type-core-packages ──► configure-pypi-trusted-publishing
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`remove-relative-uv-sources`](remove-relative-uv-sources/) | active | Remove remaining internal parent-path sources and enforce wheel-only resolution. Re-inventoried 2026-08-06: one confirmed project remains and one named target no longer exists at its recorded path |
| 2 | [`finish-buyer-cli-residue`](finish-buyer-cli-residue/) | active | Add only the remaining constrained settlement-preference hook; listing rendering and run-log compatibility are baseline |
| 3 | [`type-core-packages`](type-core-packages/) | active after affected public surfaces stabilize | Restore advertised checks, ratchet package by package, verify `py.typed` in installed wheels. Its deferred `kit/site` question should wait for the kit-composition goal's extraction scope |
| 4 | [`configure-pypi-trusted-publishing`](configure-pypi-trusted-publishing/) | externally blocked | Reconcile the consumable distribution graph and verify trusted publishers plus PyPI-only downstream installation. Should follow the kit extraction, which changes wheel contents |

## Lesser goal — End-to-end harness determinism

**What it adds up to.** End-to-end scenarios assert on internal identifiers and advance by waiting for poll intervals, which makes them slow, timing-sensitive, and expensive to extend to a second domain. These changes align scenarios with the fulfillment lifecycle contract, extend deterministic assertion to the agent-driven capacity harness, and decide whether the harness becomes an independently consumable project. Not a roadmap goal, but three goal-owned changes each carry a task requiring observable barriers rather than sleeps, and all of them land here.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`refactor-e2e-fulfillment-lifecycle`](refactor-e2e-fulfillment-lifecycle/) | active; 22 of 25 tasks complete | Scenarios assert on fulfillment identity rather than provisioning job identity. Its three open tasks are all blocked on a live docker-compose run, unavailable since 2026-07-29 |
| [`reconcile-agent-driven-vm-harness`](reconcile-agent-driven-vm-harness/) | active; preparation only | Rebuilds the public issue-discovery VM/G1 capacity contracts against current `dev`: the finite scenario matrix, reservation and fulfillment lifecycle correlation, typed scarcity, deterministic sanitized findings, and mocked issue and guarded fix planning. Prepares only — no live stage, no authenticated GitHub mutation, no product change |
| [`extract-e2e-project`](extract-e2e-project/) | deferred | Activate only for a named external consumer, compatibility profile, and release owner |

## Independent active changes

Changes with no campaign; each stands alone.

| Change | Status | Audited scope |
|---|---|---|
| [`pools-6-fair-scheduling-policy`](pools-6-fair-scheduling-policy/) | design-gated; POOLS-7 blocker cleared 2026-08-06 | Fairness policy over contended capacity. Its stated blocker — transactional assignment state — has landed, but its design inputs changed: negotiable shapes and negotiation-time holds alter what contention means, so the fairness subject should be chosen against those rather than against July's inputs |
| [`add-development-roadmap`](add-development-roadmap/) | implemented 2026-08-06; pending archive | Establishes `docs/development/ROADMAP.md`, the governance permitting it, and the closeout roadmap-currency step |
| [`fix-golden-image-config`](fix-golden-image-config/) | active | Align generated and consumed keys and deliver secrets through the provisioning Secret profile |
| [`deduplicate-dynaconf-bootstrap`](deduplicate-dynaconf-bootstrap/) | active | Parameterized kit/config construction with exact provisioning and e2e parity; storefront loader excluded. Useful precedent for the kit-composition extractions |

## Archived and superseded

`prune-storefront-database` was archived because dead policy tables are already gone and the remaining candidates carry continuation, idempotency, or observability state. `complete-development-documentation` was synchronized and archived after audience-owned documentation became permanent planning governance. `add-storefront-principal-authentication` and `provisioning-result-push-delivery` were superseded on 2026-08-06 by `service-identity-signing` and `replace-polling-with-authenticated-push` respectively.
