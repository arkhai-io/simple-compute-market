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
storefront-domain-parameterization ──► multi-domain-storefront-composition ────┐
market-platform-bare-metal-10 ─────────────────────────────────────────────────┼──► compute-40
bare-metal-buyer-domain ───────────────────────────────────────────────────────┘
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`market-platform-bare-metal-10-storefront-composition`](market-platform-bare-metal-10-storefront-composition/) | active; production fulfillment tasks depend on POOLS-7 | Independently deployable bare-metal seller composition with trusted multi-site bindings. Its one-contract-per-process scope fence was struck 2026-08-06 as superseded |
| [`storefront-domain-parameterization`](storefront-domain-parameterization/) | active; no blocking dependency | Composes the VM storefront around an injected market-domain contract, matching the bare-metal runtime's existing shape. Behavior-preserving refactor |
| [`multi-domain-storefront-composition`](multi-domain-storefront-composition/) | active; depends on `storefront-domain-parameterization`; its `pool-declared-offering-modes` prerequisite archived 2026-09-04 | Hosts several compute-family contracts in one storefront process, resolving each record's contract from the listing's recorded offering mode |
| [`bare-metal-buyer-domain`](bare-metal-buyer-domain/) | active; sequenced with `multi-domain-storefront-composition` | Adds the missing bare-metal buyer package and widens the registry's declared schema identity to scope the compute family, so one catalogue serves both form factors |
| [`market-platform-compute-40-multi-domain-proof`](market-platform-compute-40-multi-domain-proof/) | blocked on its prerequisites | Deterministic proof of one multi-domain storefront against two provisioning authorities. Rewritten 2026-08-06: most of its implementation work has shipped, and many-to-many storefront-to-authority ownership was removed from scope rather than deferred |

## Roadmap goal — Make a domain a composition of kit

```text
kit-storefront-composition-seam
      ├──► kit-owned-negotiation-runtime ─────────┐
      └──► kit-owned-capacity-and-publication ────┴──► bare-metal-and-credits-domain-stacks

kit-owned-settlement-runtime archived 2026-08-10
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`kit-storefront-composition-seam`](kit-storefront-composition-seam/) | active; depends on `storefront-domain-parameterization` | Defines where kit-owned storefront runtime sits and proves it with the two smallest duplicated concerns, composing all three domains. Establishes the rule that an extracted concern leaves no domain-local copy |
| [`kit-owned-negotiation-runtime`](kit-owned-negotiation-runtime/) | active; depends on the seam | Extracts the synchronous negotiation runtime. Largest of the extractions; collides with in-flight Goal 2 and Goal 5 negotiation work |
| [`kit-owned-capacity-and-publication`](kit-owned-capacity-and-publication/) | active; depends on the seam | Extracts the storefront capacity client and publication runtime; the capacity client's size gap needs per-capability judgment rather than a whole-file move |
| [`bare-metal-and-credits-domain-stacks`](bare-metal-and-credits-domain-stacks/) | active; depends on the two remaining extractions and on `bare-metal-buyer-domain`; the settlement-runtime extraction archived 2026-08-10 | A bare-metal deployable stack, per-domain end-to-end deal paths, and API-credits recomposition onto kit. Delivers the goal's completion test |

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

## Roadmap goal — Make the settlement mechanism a composed choice

Delivered; no active change remains. Both changes were archived 2026-08-19:
[`finish-settlement-mechanism-neutrality`](archive/2026-08-19-finish-settlement-mechanism-neutrality/)
and [`contact-exchange-settlement-mechanism`](archive/2026-08-19-contact-exchange-settlement-mechanism/).
[`ROADMAP.md`](../../docs/development/ROADMAP.md)'s Goal 6 carries the current state and names the one
remaining gap — cross-domain contact-exchange composition beyond bare metal, and contact-payload
retention automation — as unowned and needing a new change.

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

**What it adds up to.** Settlement handles one escrow shape well. Generalizing it to arbitrary obligation plans landed with `add-settlement-plan-shapes` (archived 2026-08-10). The changes still open here add the automation a seller needs to run spot inventory without manual intervention, and close a recovery gap where an ambiguous on-chain submission can currently only be resolved by an operator. Not a roadmap goal — the market's capabilities are unchanged — but every goal that touches money lands on this machinery, and `billable-capacity-reservations` reuses its per-obligation lifecycle directly.

| Change | Status | Acceptance boundary |
|---|---|---|
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

Two changes joined this campaign on 2026-09-02. The first has since largely landed: the settlement client is published to the public index at `0.4.2`, the release gate is off the build and test path, `.dist` holds only what this repository builds, and as of 2026-09-04 all seven consuming lockfiles resolve the client from the index with their suites re-run green against it. What remains there is a dead make variable, its closeout, and an interpreter-selection defect that stops those suites resolving on a default `uv` Python. Separately, twenty-eight distributions reach public PyPI on every merge to `main` with no gate — which is how `arkhai-kit-hosted-settlement` 0.1.4 came to be published declaring a dependency PyPI does not carry, uninstallable for everyone outside this repository and, because PyPI is write-once, not correctable in place.

```text
resolve-hosted-client-from-an-index ──► publish-wheels-through-a-gate
remove-relative-uv-sources ──► type-core-packages ──► configure-pypi-trusted-publishing
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`resolve-hosted-client-from-an-index`](resolve-hosted-client-from-an-index/) | active; producer dependency resolved and all consumer locks migrated; blocked acceptance is now an interpreter-selection defect | The externally produced settlement client resolves from a declared index like any other dependency; release verification leaves `init`, `reinit`, and `dist-release`; the staged-release path leaves the `dist` graph and `.dist` holds only what this repository builds. `make dist` and `make test` succeed from a clean checkout, on a fork, with no producer access |
| 2 | [`publish-wheels-through-a-gate`](publish-wheels-through-a-gate/) | active; the interim half needs no prerequisite | Automated publication to PyPI stops; merge to `main` publishes all twenty-eight distributions to the development registry; one inventory-derived list replaces the two enumerations; a human-invoked promotion copies bytes to PyPI and fails the whole set if any version there holds different content |
| 1 | [`remove-relative-uv-sources`](remove-relative-uv-sources/) | active | Remove remaining internal parent-path sources and enforce wheel-only resolution. Re-inventoried 2026-08-06: one confirmed project remains and one named target no longer exists at its recorded path |
| 2 | [`type-core-packages`](type-core-packages/) | active after affected public surfaces stabilize | Restore advertised checks, ratchet package by package, verify `py.typed` in installed wheels. Its deferred `kit/site` question should wait for the kit-composition goal's extraction scope |
| 3 | [`configure-pypi-trusted-publishing`](configure-pypi-trusted-publishing/) | externally blocked | Reconcile the consumable distribution graph and verify trusted publishers plus PyPI-only downstream installation. Should follow the kit extraction, which changes wheel contents |

The two sequences are independent of each other and share this campaign because they share its completion test: nothing outside this repository can install what it publishes.

`resolve-hosted-client-from-an-index` is no longer externally blocked. The producer published the client to the public index, and the wheel the index serves hashes to the digest the trust configuration pins, so attestation still comes from the manifest. Four consuming lockfiles had never been re-locked on this branch despite task 4.2 reading as though they had been; that was corrected on 2026-09-04 and their suites pass against the index (see its task 4.8). One blocker to its acceptance survives and is not about the client: `requires-python = ">=3.12"` lets `uv` select a Python for which `pydantic-core` ships no wheel, so these suites need a pinned interpreter to resolve at all (task 4.9). `publish-wheels-through-a-gate` reads its package list from the cross-repository release inventory format, which is defined outside this repository, and uses a plain manifest until that lands.

`configure-pypi-trusted-publishing` overlaps `publish-wheels-through-a-gate` on the distribution inventory and on proving PyPI-only installation. Reconcile the two before either is archived rather than letting both claim the same acceptance.

## Lesser goal — End-to-end harness determinism

**What it adds up to.** End-to-end scenarios assert on internal identifiers and advance by waiting for poll intervals, which makes them slow, timing-sensitive, and expensive to extend to a second domain. These changes align scenarios with the fulfillment lifecycle contract and decide whether the harness becomes an independently consumable project. Not a roadmap goal, but three goal-owned changes each carry a task requiring observable barriers rather than sleeps, and all of them land here.

| Change | Status | Acceptance boundary |
|---|---|---|
| [`refactor-e2e-fulfillment-lifecycle`](refactor-e2e-fulfillment-lifecycle/) | active; 22 of 25 tasks complete | Scenarios assert on fulfillment identity rather than provisioning job identity. Its three open tasks are all blocked on a live docker-compose run, unavailable since 2026-07-29 |
| [`extract-e2e-project`](extract-e2e-project/) | deferred | Activate only for a named external consumer, compatibility profile, and release owner |

## Lesser goal — Agent-driven issue-discovery harness

**What it adds up to.** `tools/issue-discovery` runs build and environment phases and turns failures into deduplicated issue candidates. It has no actor in it, its phase configuration names three directories that no longer exist, and no Make target invokes it. These changes repair it, declare a finite set of capacity scenarios it can validate without executing, establish who is allowed to perform which action, make a recorded run project into one deterministic result, and prove that supporting a second domain costs an adapter rather than a core edit. Not a roadmap goal — the harness is a tool and changes nothing the market can do. Its jurisdiction is documented in [`docs/development/TESTING.md`](../../docs/development/TESTING.md), which places it outside the four test levels rather than beside them.

```text
restore-issue-discovery-thin-runner ──► add-harness-scenario-contract ──┬──► add-harness-findings-projection ──► add-deterministic-regression-contract
                                                                        └──► add-harness-buyer-action-slice ──► add-future-domain-shape-validation
```

| Order | Change | Status | Acceptance boundary |
|---|---|---|---|
| 1 | [`restore-issue-discovery-thin-runner`](restore-issue-discovery-thin-runner/) | active | The inherited runner resolves against the current tree, drift fails at load rather than at runtime, and Make targets exist to invoke it. Removes the `TESTING.md` section describing a subsystem that has never existed on `dev`. Carries one open design question: the successor of the removed `service` workdir |
| 2 | [`add-harness-scenario-contract`](add-harness-scenario-contract/) | active | A finite set of capacity scenarios is declared and validated, executing nothing. Scenarios declare the hold posture they assume, name a refusal match mode rather than an exact string, and require per-buyer discovery evidence. Contention is declared over markets, not seller processes |
| 3a | [`add-harness-findings-projection`](add-harness-findings-projection/) | active | A recorded event corpus projects to one deterministic result. Offered demand, served capacity, and load-generator limit stay distinct and are never derived from one another. The existing issue engine gains update and reopen and no other mutation |
| 3b | [`add-harness-buyer-action-slice`](add-harness-buyer-action-slice/) | active | Documented buyer actions are performed by the actor through the entry points the quickstart names; the controller has no code path that performs one. Requests are frozen before release, observation is independent of the observed, and live adapters fail closed on configuration |
| 4 | [`add-deterministic-regression-contract`](add-deterministic-regression-contract/) | active | What a generated regression must be: representation separated from its execution adapter, evidence that it fails without the fix it protects, an evidence class travelling with the artifact that refuses a concurrency or capacity claim, sanitization through the same allowlist as any other crossing, and placement at the level owning the behaviour it protects. Generates nothing |
| 4 | [`add-future-domain-shape-validation`](add-future-domain-shape-validation/) | active | An adapter the runtime has never seen round-trips an opaque payload with no core edit. Prepared domains validate and dry-plan with zero effect on attempted execution. A testing seam, not a plugin platform |

Two dependencies point outside this campaign. No scenario can assert that the GPU reserved is the GPU received until [`fix-vm-fulfillment-capacity-boundary`](fix-vm-fulfillment-capacity-boundary/) closes. Separately, nothing the harness exercises can complete a buyer journey until a composed domain wheel-and-policy path exists here — and that dependency has no owner on this branch. The change previously named for it has never existed on `dev`, so the citation is not a stale link but an unowned requirement; `add-harness-buyer-action-slice` still names it in its proposal, design, and task 1.4, and cannot bind to a real target until a change on this branch owns the work. The `reinit` coverage gap the harness surfaced is owned by [`remove-relative-uv-sources`](remove-relative-uv-sources/) task 2.5, not by this campaign.

## Lesser goal — Reach hosts and VMs that have no inbound route

A rented node typically sits behind a firewall or NAT with nothing listening
from outside. Two consequences run through the provisioning path and neither is
currently satisfied: the provisioner cannot name a host whose SSH answers on a
tunnel port, and the VM-creation path coordinates buyer tunnels through a relay
management dashboard that a relay is not obliged to expose. Both are defects in
how the existing mechanism is built rather than new market capability — the
product already sells VMs on hosts it reaches by tunnel; it simply cannot do so
against a relay deployed without a management surface.

```text
never-strand-the-host-on-passthrough ──► (prerequisite for exercising any below on real hardware)
contain-embedded-host-key-material (independent)
relay-vm-access-without-a-dashboard ──► add-buyer-vm-connectivity-terms
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`never-strand-the-host-on-passthrough`](never-strand-the-host-on-passthrough/) | implemented; promoted; live verification outstanding | Host preparation cannot render a rented machine unreachable. Passthrough viability is audited read-only before anything is written, unsafe IOMMU groups are refused rather than bound, device binding is scoped to a PCI address and applied after boot, and the rollback target is a state that contends for no device |
| [`contain-embedded-host-key-material`](contain-embedded-host-key-material/) | in design | A host may be reached with its own SSH key rather than the deployment's shared one. Decrypted key material exists only for the operation that needs it, on failing paths as well as succeeding ones. Takes no position on who generates a host's keypair |
| [`relay-vm-access-without-a-dashboard`](relay-vm-access-without-a-dashboard/) | in design; schema landed but superseded, allocator and Ansible outstanding; carries a reload verification gate | VM tunnel allocation and verification stop depending on a relay dashboard, DNS name, certificate, and second credential. A relay becomes an administered resource with its own controller, holding its own window and encrypted token, changeable against a running service rather than by redeployment, and no longer reverted when a pod restarts against an unchanged definition document. The host's management and buyer tunnel clients are split, and adding a VM stops restarting the tunnel client — and with it every buyer's live session |

`never-strand-the-host-on-passthrough` shares no code with the others and
blocks none of them. It is sequenced first because they are verified by
preparing and provisioning a real rented host, and host preparation is the step
that can lose the machine.

`contain-embedded-host-key-material` is what allows a host prepared by someone
else to be registered at all. Every host in an environment is currently reached
with one key, which is workable while one party operates them all and is not
workable for a rented machine whose operator supplies its own credential. It
shares no code with the relay work and either may land first.

`add-buyer-vm-connectivity-terms` is listed under Goal 2, where its negotiation
impact places it. It populates the same `connectivity` field this campaign
reshapes, and should follow rather than precede: settling what the field
contains is cheaper than negotiating a shape that carries a dashboard
credential no longer in use.

No roadmap goal currently covers this work. Whether one is warranted is a
closeout decision for the second change rather than an omission here.

## Lesser goal — Hosted fiat settlement

**What it adds up to.** A buyer holding no wallet and no chain resources completes a deal through the shared hosted financial authority, and every refusal that path can produce is nameable from outside it. Four changes carry the funding contract itself: a durable core-owned buyer identity, the expanded signed payer/funding profiles consumed from the authority, and the two domains that compose them. The rest close gaps the protected Stripe lanes surfaced. Three landed and archived on 2026-09-04 — a refusal that names its cause instead of timing out, the return address the authority demands before it will refund a bank transfer, and one coordinate binding the hosted release. Still open are a response the client cannot authenticate, and the projections and partial dispositions those lanes assert on. Not a roadmap goal: the market sells the same things either way. It earns a campaign because these changes share one external dependency surface — an independently produced signed release and protected Stripe inputs this repository cannot supply — and because the lane work is only legible as a group.

```text
add-persistent-buyer-profiles ──► consume-expanded-stripe-funding ──┬──► add-api-credits-hosted-settlement
                                                                    └──► add-bare-metal-hosted-settlement

lane legibility:  name-unverifiable-responses
lifecycle depth:  project-an-authoritative-funding-loss, disburse-a-settlement-disposition
```

| Change | Status | Acceptance boundary |
|---|---|---|
| [`add-persistent-buyer-profiles`](add-persistent-buyer-profiles/) | active; no blocking dependency | A core-owned buyer profile selects a stable local buyer, retains exact signer history across rotation, and associates authority-owned opaque payer bindings without putting secrets in marketplace state |
| [`consume-expanded-stripe-funding`](consume-expanded-stripe-funding/) | active; depends on `add-persistent-buyer-profiles` and on an externally produced signed release | Exact versioned payer/funding profiles with persistent buyer ownership and off-session authorization, importing no Stripe models and weakening no storefront mediation or fulfillment gate |
| [`add-api-credits-hosted-settlement`](add-api-credits-hosted-settlement/) | active; local work complete, qualification externally blocked | A non-EVM buyer purchases and tops up API credits through the shared hosted authority by composing the mechanism-neutral seams rather than copying VM lifecycle code. Its open tasks need protected Stripe inputs and a signed producer acceptance record this checkout does not carry |
| [`add-bare-metal-hosted-settlement`](add-bare-metal-hosted-settlement/) | active; local work complete, qualification externally blocked | Bare-metal hosted settlement. Production qualification waits on operator-supplied signed manifests and protected Stripe inputs, plus a disposable real host on which access and later revocation can be observed |
| [`name-unverifiable-responses`](name-unverifiable-responses/) | active; no blocking dependency | A client refusing a response it cannot authenticate distinguishes that case from a malformed or legacy one, so an ordinary `404` stops being reported as a protocol fault |
| [`project-an-authoritative-funding-loss`](project-an-authoritative-funding-loss/) | active; no blocking dependency, and explicitly not externally blocked | Incident and blocked-delivery projections become readable on the public settlement payload rather than dropped by the hosted adapter. Unblocks the two `us_ach_debit.v1` lanes withheld as `loss_projection_unimplemented` |
| [`disburse-a-settlement-disposition`](disburse-a-settlement-disposition/) | active; no blocking dependency | An obligation's amount moves partially and in more than one direction; expiry becomes a mechanism's answer; the hosted rail gates on a declared capability, and rollback stays safe only while every disposition is degenerate |

The two qualification-blocked changes are blocked on inputs, not on each other: local deterministic contracts and generated configuration are complete in both, and neither substitutes for a protected run. `project-an-authoritative-funding-loss` states in its own proposal that nothing external blocks it — the producer release already carries what it consumes — which makes it the cheapest way to retire two permanently-excluded lanes.

## Independent active changes

Changes with no campaign; each stands alone.

| Change | Status | Audited scope |
|---|---|---|
| [`pools-6-fair-scheduling-policy`](pools-6-fair-scheduling-policy/) | design-gated; POOLS-7 blocker cleared 2026-08-06 | Fairness policy over contended capacity. Its stated blocker — transactional assignment state — has landed, but its design inputs changed: negotiable shapes and negotiation-time holds alter what contention means, so the fairness subject should be chosen against those rather than against July's inputs |
| [`fix-golden-image-config`](fix-golden-image-config/) | active | Align generated and consumed keys and deliver secrets through the provisioning Secret profile |
| [`deduplicate-dynaconf-bootstrap`](deduplicate-dynaconf-bootstrap/) | active | Parameterized kit/config construction with exact provisioning and e2e parity; storefront loader excluded. Useful precedent for the kit-composition extractions |
| [`add-registry-self-description`](add-registry-self-description/) | active; no blocking dependency | Publishes one strict operator-authored registry descriptor through the existing signed registry exchange, with schema, access posture, and authority pins derived from their active sources |

## Archived and superseded

`prune-storefront-database` was archived because dead policy tables are already gone and the remaining candidates carry continuation, idempotency, or observability state. `complete-development-documentation` was synchronized and archived after audience-owned documentation became permanent planning governance. `add-storefront-principal-authentication` and `provisioning-result-push-delivery` were superseded on 2026-08-06 by `service-identity-signing` and `replace-polling-with-authenticated-push` respectively.

Five changes this index still listed as active had in fact been archived, and their rows were removed on 2026-09-04: `add-settlement-plan-shapes`, `finish-buyer-cli-residue`, and `kit-owned-settlement-runtime` (all 2026-08-10), and `finish-settlement-mechanism-neutrality` and `contact-exchange-settlement-mechanism` (both 2026-08-19). Each is under [`archive/`](archive/) with its completion date. [`add-development-roadmap`](archive/2026-09-04-add-development-roadmap/) was archived 2026-09-04, synchronizing the two `planning-governance` requirements that authorize `docs/development/ROADMAP.md` and make roadmap currency owed — neither had reached the permanent spec before archival. [`add-host-ssh-port`](archive/2026-09-04-add-host-ssh-port/) and [`pool-declared-offering-modes`](archive/2026-09-04-pool-declared-offering-modes/) were archived the same day; their delta requirements had been promoted early but had since diverged from the change's accepted text, so the four affected requirements in `physical-provisioning`, `resource-pool-management`, and `site-capacity` were brought up to it first — recovering the repository's official capacity vocabulary and one missing scenario. Three hosted-settlement changes were archived the same day once their closeouts were worked: [`bind-one-hosted-release-coordinate`](archive/2026-09-04-bind-one-hosted-release-coordinate/), [`carry-the-payer-return-address`](archive/2026-09-04-carry-the-payer-return-address/), and [`name-a-refusal-that-will-not-converge`](archive/2026-09-04-name-a-refusal-that-will-not-converge/). The last two modify the same `test-compatibility` requirement from diverged bases, so the permanent spec carries the union of both rather than whichever archived last. They persisted here because campaign-index currency was owed by no closeout step until `openspec/README.md#plan-closeout-requirements` gained part 6.
