# Arkhai Market Stack — Directional Roadmap

> **Purpose:** The goals currently being pursued, the value each delivers, what is true today, and which OpenSpec change owns each open gap. This document carries no readiness status, no delivery sequencing, no acceptance criteria, and no implementation tasks — those belong to the changes themselves and to [`openspec/changes/README.md`](../../openspec/changes/README.md).

## How this document relates to the others

Three cross-cutting documents divide the work between them. Each answers a different question and changes at a different rate.

| Document | Answers | Corrected when |
|---|---|---|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | What is the system, and why do its boundaries exist? | The system changes |
| `ROADMAP.md` (this document) | Which goals are being pursued, and why? | A goal's truth changes |
| [`openspec/changes/README.md`](../../openspec/changes/README.md) | What can I start, and what is it blocked on? | Changes start, block, and finish |

To find out whether work on a goal is ready, blocked, or deferred, follow the change link and read the active-change index. This document deliberately does not say.

Each goal below carries a present-tense **current state** grounded in the code as it is, and a table of **open gaps** with the change that owns each. When a change completes, its row leaves the table and the result is absorbed into the current-state prose — so this document shows where things stand, not a history of how they got there. Progress is visible in the current-state paragraphs growing and the gap tables shrinking.

A gap identified without an owning change does not become a standing entry here; an OpenSpec change is opened for it and linked. Where a goal has known work that no change yet owns, the current-state section says so plainly rather than the gap table implying coverage that does not exist.

When every gap for a goal closes, the goal is removed. Its durable result is by then in `ARCHITECTURE.md` or the owning capability's specification through the ordinary promotion path, and the record of the work is in Git history and the archived changes.

---

## Goal 1 — Consolidate physical-resource authority in the provisioning service

**Value.** One authority for physical state removes a whole class of divergence bugs, and — less obviously but more consequentially — it is what makes the storefront substitutable. A storefront that owns hardware inventory cannot become a multi-domain storefront (Goal 3), cannot be replaced by a different commercial front-end over the same hardware, and forces every seller to maintain the same facts in two places. It also shrinks the seller's operational surface: hardware inventory stops being something an operator imports into a commercial service.

The boundary this goal draws is between *physical* and *commercial* authority, not between the two services generally. Per [`ARCHITECTURE.md`'s authority boundaries](ARCHITECTURE.md#authority-boundaries), pricing, seller policy, and listing state are correctly storefront-owned. The goal is that the storefront holds no physical authority — not that it holds no per-pool records.

**Current state.** The provisioning service is authoritative for hosts, resource pools, capacity admission, scheduling, and the fulfillment lifecycle. Storefronts consume physical facts through the site resource-pool and capacity-bucket projections, and projection-backed listing derivation is the default path. The bare-metal storefront is fully projection-native and holds no local physical tables at all.

The VM storefront still holds physical state the projection has superseded. It retains `resources`, `hosts`, `compute_pool_members`, and `resource_transition_events`, a local-table listing-derivation path behind a configuration flag, and CSV import as the operator path for seeding inventory — including a startup seeding step and Helm and compose wiring, so retiring it is an operator-facing contract change rather than only a code deletion. It also retains surfaces whose callers are already gone: `compute_allocations`, an execution ledger that `kit/site`'s `CapacityReservation` supersedes and that no production code writes to; admin endpoints for reading and patching resource state whose documented caller no longer makes that call; and a physical-host identifier threaded across the storefront-to-provisioning boundary that the capacity boundary strips, so it is always absent.

Capacity declaration is the one place the provisioning service is not yet the fuller authority. Host inventory carries GPU count and model only, so the projection's host-derived fallback cannot express vCPU, RAM, or disk. The retiring storefront CSV has been the system's only operator-facing expression of multi-dimensional capacity — which is why capacity administration is a prerequisite of the retirement rather than a parallel improvement.

| Open gap | Owned by |
|---|---|
| Sellable capacity has no authoritative multi-dimensional declaration or operator path in the provisioning service | [`capacity-resource-administration`](../../openspec/changes/capacity-resource-administration/) |
| The VM storefront retains local physical tables, the local-table derivation path, CSV import and its deployment contract, the dead execution ledger, the orphaned physical admin surface, and dead physical-identity plumbing | [`pools-9-retire-local-physical-authority`](../../openspec/changes/pools-9-retire-local-physical-authority/) |
| Stale physical-placement fields on the current fulfillment path, and VM shape not reaching the provisioning request | [`fix-vm-fulfillment-capacity-boundary`](../../openspec/changes/fix-vm-fulfillment-capacity-boundary/) |

A schema drop of the frozen columns is deliberately excluded from the retirement and belongs to a later follow-up, after a deployment cycle confirms the freeze never needed rolling back.

---

## Goal 2 — Negotiate full compute capability, not GPU count alone

**Value.** This is the difference between a market that sells fixed SKUs and one that sells capacity. Hardware is heterogeneous and buyer requirements are multi-dimensional; negotiating on GPU count alone forces sellers to pre-partition inventory into fixed shapes and forces buyers to over-buy on every dimension they did not need. Supporting the full shape raises fill rate and utilization revenue on hardware the seller already owns.

**Current state.** The lower layers already carry the full shape. The VM domain defines canonical dimensions for GPU count, vCPU count, RAM, and disk; the site authority admits and matches multidimensionally; scheduling fit-checks every requested dimension and treats the dimensions actually scheduled as authoritative; capacity reservations can be resized by supersede rather than mutation; and the Ansible playbooks create VMs with variable shapes.

The top of the stack does not. A buyer that names a resource shape disagreeing with the listing's own shape is rejected outright at negotiation round zero, deliberately and loudly, because seller policy has no way to price an alternative shape. Rounds after the first carry only price and escrow terms, with no field for a shape change. Reservation resizing is implemented and has no caller anywhere in the repository.

Publication is where the shape is first lost. A listing's `offer_resource` carries GPU model, count, SLA, region, and pool identity only — vCPU, RAM, and disk are never published, though the projection's capacity map reaches the storefront and the listing model declares all three as optional fields. Because the registry's dimension filters fail closed on a missing field, a buyer filtering on RAM matches nothing at all today, despite the registry schema and buyer CLI both supporting it.

Pricing is the binding constraint on negotiating the shape. Commercial resolution produces a single price per GPU model through a three-tier chain of storefront override, pool hint, and configured default; rates scale by duration only. Negotiation carries exactly one degree of freedom, a scalar amount moved by the concession middleware, so no seller policy can evaluate a counter-offer that changes RAM or disk — which is why a buyer naming any shape is rejected at round zero, deliberately and with the reason recorded in the guard itself. The seller's own feasibility check compares region and GPU model by equality and no quantitative dimension. Nothing consults the authoritative site until a hold is placed at terms acceptance, so an unservable shape surfaces after both parties have committed.

| Open gap | Owned by |
|---|---|
| Listings advertise a GPU-only shape, so the registry's existing dimension filters match nothing | [`publish-multidimensional-listing-shape`](../../openspec/changes/publish-multidimensional-listing-shape/) |
| No seller can price a shape other than the one advertised, and negotiation has one degree of freedom where two are needed | [`capacity-shape-pricing`](../../openspec/changes/capacity-shape-pricing/) |
| Nothing expresses which shapes a seller will consider, or what range remains admissible for one dimension given the rest | [`capacity-shape-envelope`](../../openspec/changes/capacity-shape-envelope/) |
| The authoritative site is not consulted until terms are already agreed, so an unservable shape fails after both parties commit | [`negotiation-capacity-feasibility-probe`](../../openspec/changes/negotiation-capacity-feasibility-probe/) |
| Buyer-facing requirement shape is flat and ambiguous; `offering_type` is conflated with the site-inventory `resource_type` discriminator; claim vocabulary is inconsistent across the codebase | [`structured-capacity-requirements`](../../openspec/changes/structured-capacity-requirements/) |
| No negotiation round after the first can express a shape change, and reservation resizing has no caller | [`negotiation-driven-capacity-resize`](../../openspec/changes/negotiation-driven-capacity-resize/) |
| The accepted VM shape does not reach the provisioning request, so a GPU-reserving listing can fulfill without a GPU | [`fix-vm-fulfillment-capacity-boundary`](../../openspec/changes/fix-vm-fulfillment-capacity-boundary/) |
| Buyer-negotiated VM connectivity terms, currently operator-configured only | [`add-buyer-vm-connectivity-terms`](../../openspec/changes/add-buyer-vm-connectivity-terms/) |

`negotiation-capacity-feasibility-probe` is a shared prerequisite rather than exclusively this goal's: charging for a held reservation also requires a buyer to learn feasibility before any hold, and therefore any charge, exists. Not every change belongs to a roadmap goal, and this one is listed here because this goal consumes it, not because it is owned by it.

---

## Goal 3 — One storefront serving several compute-family domains

**Value.** This decouples *how hardware is sold* from *how hardware is partitioned*. Today the listing form factor is a deployment boundary, so a site owner must physically dedicate hosts to VMs rather than bare metal rather than pods. Removing that lets one pool of hardware be offered concurrently as several form factors, priced independently, with the site authority arbitrating exclusivity between them — higher utilization and better price discovery without buying more hardware.

**Current state.** The storefront-to-site direction is already one-to-many: a storefront aggregates several configured site clients, ranks them per request, routes each reservation to one authority, and persists the selected binding. A single provisioner can register VM and bare-metal adapters concurrently, and the site authority already resolves cross-mode conflicts over one physical resource. The buyer CLI already loads several market-domain contracts in one process, and the core carrier already validates a set of contracts and rejects duplicate identities.

The site-to-storefront direction remains **one-to-one**. A provisioning service still binds to one `storefront_url`, and the reverse channel's per-deal override for that URL exists in the event sink but no storefront populates it, so it always falls through to the global setting. Authentication no longer forces both directions to share one secret: each peer has its own Secret-backed signer, and exact scheme-tagged trust pins bind requests and signed responses. Making one site serve several storefronts therefore requires explicit topology and routing work, not another identity path.

The site models this correctly already. A capacity resource carries `publication_views` keyed by view identity — `bare_metal.v1`, `vm.ansible_pool_defaults.v1` — off one row per host identity, with a guard rejecting several capacity resources mapping to the same host, and `Cross-mode physical accounting` requires a shareable VM slice and an exclusive bare-metal claim on one host to conflict before executor work starts. One physical resource, several form-factor projections, is how inventory is already represented.

The storefront cannot consume it. The VM storefront resolves its market-domain contract from a module-level singleton at five call sites; the bare-metal storefront is already domain-parameterized, carrying the contract as a runtime field, so the two roles disagree on how a contract arrives. No storefront table carries a domain discriminator.

The site also does not bound what may be sold. Pool policy declares listing mode, region, SLA, pricing, and hold caps, but not which offering modes a pool can deliver; `executor_kind` is recorded on reservations but never validated, and at reserve time it is inferred from whether the matched resource carries a `vm_host` attribute rather than supplied by the caller. A request for capacity a pool cannot deliver is admitted, held, scheduled, and fails at provisioning.

Discovery is closer than it looks. The registry's listing shape already constrains `virtualization_type` to `[bare_metal, vm, container]`, carries host-level fields alongside slice-level ones, and already exposes that field in its filter vocabulary — the catalogue is family-shaped. What is missing is that nothing publishes the field, the registry's declared identity names one domain (`vms.compute`), and bare metal has no buyer package at all.

The direction is settled: several compute-family contracts hosted in one storefront process, rather than federating single-domain storefronts over one site. Federation would require several storefronts to share one site authority, and that relationship is one-to-one today. Both the bare-metal composition and the multi-domain topology proof recorded one-contract-per-process as a non-goal. Both are now reconciled: the first struck as a superseded scope fence, the second rewritten against current code — its topology is now one multi-domain storefront against two authorities, and its many-to-many storefront-to-authority axis was removed rather than deferred, since there are no plans to support it.

| Open gap | Owned by |
|---|---|
| Pools do not declare which offering modes they can deliver, and nothing rejects a request for capacity a pool cannot serve | [`pool-declared-offering-modes`](../../openspec/changes/pool-declared-offering-modes/) |
| The VM storefront resolves its contract from module scope, so it cannot be selected per record | [`storefront-domain-parameterization`](../../openspec/changes/storefront-domain-parameterization/) |
| A storefront serves one market domain, forcing hardware to be partitioned by how it is sold | [`multi-domain-storefront-composition`](../../openspec/changes/multi-domain-storefront-composition/) |
| Bare metal has no buyer package, and no registry identity admits a bare-metal buyer | [`bare-metal-buyer-domain`](../../openspec/changes/bare-metal-buyer-domain/) |
| Listings do not publish their offering mode, so the registry's form-factor filter matches nothing | [`publish-multidimensional-listing-shape`](../../openspec/changes/publish-multidimensional-listing-shape/) |
| Bare metal has no runnable seller storefront composition; the trusted per-resource projection and selected-site fulfillment routing it needs are incomplete | [`market-platform-bare-metal-10-storefront-composition`](../../openspec/changes/market-platform-bare-metal-10-storefront-composition/) |
| Selected-authority ownership, cross-mode rejection, and executor strictness have never been exercised together across more than one authority | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Goal 4 — Make a domain a composition of kit

**Value.** The architecture's layering is core for what applies to every domain, kit for composable functionality many domains share, and the domain layer for instantiating and configuring kit. The storefront role does not follow it, so the marginal cost of a market domain is roughly three thousand lines of negotiation, settlement, capacity, publication, and failure-handling machinery that is identical in every domain but its codecs.

That cost is why bare metal has been a storefront skeleton and why API credits carries a full parallel copy of eight VM services. It compounds: every defect fixed in one copy stays live in the other, and every new cross-cutting capability — billable holds, shape-aware pricing, feasibility verification — must be built once per domain or silently skip the domains that lack it. A capability that reads as "the market does X" is often really "the VM market does X."

Extracting that machinery into kit changes what adding a domain means. A Kubernetes-pod domain, an inference-token domain, or a model-training domain becomes codecs, a contract, and configuration rather than a fork of the VM storefront. The two domains delivered here are both the beneficiaries and the proof: bare metal because it has none of the machinery, API credits because it has a complete parallel copy, so composing them exercises both directions.

**Current state.** Kit's layering discipline now includes
`kit/settlement-runtime`: one stable per-obligation operation journal,
conditional-escrow client port, servicing worker, and failure dispatcher are
composed by VM and API-credit storefronts. Bare metal composes exact
verified-plan registration and adoption but truthfully remains
fulfillment-unavailable. `kit/policy`, `kit/identity`, `kit/fulfillment`,
`kit/config`, and `kit/alkahest` likewise carry no domain vocabulary.

The remaining cross-cutting copies are synchronous negotiation, capacity,
publication, negotiation watchdog, and chain-client construction. Those
concerns still make a new storefront domain larger than its codecs, contract,
configuration, and genuine domain actions.

Settlement assigns stable identity to every accepted-plan obligation, journals
materialize/status/check/collect/reclaim attempts, persists opaque mechanism
state across retry, preserves partial outcomes, and supports directional
interval payments and seller penalty bonds. VM and API-credit roots use this
runtime for exact verified-obligation adoption, fulfillment binding, and
collection. Their connection details, credentials, capacity repair, refund,
and issuance rollback remain at their real domain boundaries rather than
becoming generic settlement state.

Neither new domain is deployable or testable end to end. Bare metal has no stack definition, and no end-to-end scenario references either domain: every deal path the repository proves is a VM deal path.

The domain layer's own structure is better than the duplication suggests. All three domains follow one pattern — a base contract with a storefront-side extension — and all three pass the shared conformance suite, which works without assuming a repository layout. Only the directory conventions differ, and a composed domain is small enough that relocating them buys nothing.

**Completion test.** Bare metal and API credits each run a full deal through a composed storefront, with no domain-local copy of an extracted concern.

| Open gap | Owned by |
|---|---|
| No seam exists for kit-owned storefront runtime, and no rule prevents an extraction leaving copies behind | [`kit-storefront-composition-seam`](../../openspec/changes/kit-storefront-composition-seam/) |
| The synchronous negotiation runtime is implemented twice and absent once | [`kit-owned-negotiation-runtime`](../../openspec/changes/kit-owned-negotiation-runtime/) |
| The capacity client and publication runtime are implemented twice and absent once | [`kit-owned-capacity-and-publication`](../../openspec/changes/kit-owned-capacity-and-publication/) |
| Bare metal has no deployable stack, no domain has an end-to-end deal path but VM, and API credits still reimplements rather than composes | [`bare-metal-and-credits-domain-stacks`](../../openspec/changes/bare-metal-and-credits-domain-stacks/) |

A compute-dimension name leaking into every domain's capacity declaration is a real defect but too small to own a gap row here; it rides with [`capacity-resource-administration`](../../openspec/changes/capacity-resource-administration/), which already rewrites the code that causes it.

---|---|
| Executor identity falls back implicitly to VM where durable identity is absent, which a growing set of executor kinds cannot tolerate | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Goal 5 — Make capacity exclusivity compensated

**Value.** A capacity hold is exclusion: while one buyer holds capacity, no other buyer can have it. Today acquiring that exclusion costs two signed HTTP requests and nothing else — no funds, no chain interaction, and no limit on how many a single actor may hold. One adversary can therefore hold a storefront's entire sellable inventory indefinitely, at no cost, denying every legitimate buyer. Shortening the hold window does not fix this; it only raises the request rate the attacker needs.

Pricing held time closes that vector structurally rather than defensively. Cost scales with capacity-time held, so minting identities buys an attacker nothing and no rate limit has to punish a buyer who genuinely wants a lot of capacity. It is the only mechanism that stops the attack without also constraining the customer.

Having closed it, the same mechanism unlocks what the market cannot currently afford to do. Holding capacity earlier — failing a deal at reservation rather than after payment, letting a buyer negotiate seriously over specific hardware, closing the race between two buyers wanting the same machine — is unaffordable today precisely because exclusivity is free. Once it is paid for, capacity can be held for as long as someone is willing to pay, which is the precondition for early reservation and eventually for forward reservation of future capacity windows. A pool whose holds are expensive also becomes a visible scarcity signal before any deal settles.

**Current state.** The vector is closed by denying the capability: both storefronts now ship `capacity.hold_ttl_seconds = 0`, so no capacity is held before the buyer's escrow settles and exclusivity arises only from a settled deal. The two-phase reserve implementation remains and is exercised by local end-to-end profiles that deliberately override the default. The cost of that posture is a reopened race — a buyer whose escrow settles may find the capacity taken and need a refund — which is accepted as a bounded, recoverable failure against an unbounded one.

Nothing else about a hold has changed. A reservation carries no rate, no funding reference, and no price; its duration comes from configuration capped by pool policy rather than from anything the holder committed. Held time is never charged and an early release returns nothing, because there is nothing to return. Hold placement during negotiation bypasses the reservation ledger's idempotency guard entirely, since that guard keys on a settlement identity that does not yet exist, so a retried placement mints a second reservation. Expiry loads every outstanding held reservation on every ledger operation and compares timestamps in application code, and terminal reservations are never pruned — both tolerable only because the population is currently small.

| Open gap | Owned by |
|---|---|
| Holds bypass reservation idempotency; expiry scans all held rows on every operation; terminal reservations accumulate without bound | [`capacity-reservation-lifecycle-hardening`](../../openspec/changes/capacity-reservation-lifecycle-hardening/) |
| Holding capacity is free, so exclusivity cannot be granted before payment without exposing the denial vector | [`billable-capacity-reservations`](../../openspec/changes/billable-capacity-reservations/) |
| Capacity is not held while a buyer is negotiating for it, so two buyers can negotiate the same capacity to completion | [`negotiation-time-capacity-hold`](../../openspec/changes/negotiation-time-capacity-hold/) |
| The shipped default granted unfunded exclusivity, and framed the safe value as a performance trade | [`default-no-pre-settlement-capacity-hold`](../../openspec/changes/default-no-pre-settlement-capacity-hold/) |

Restoring a non-zero hold default is `billable-capacity-reservations`' own work: the posture above is a denial of capability that this goal exists to buy back.

---

## Buyer identity lifecycle status

Buyer marketplace identity is now a core-owned durable profile rather than
repeated domain-local `[Identity]` configuration. The XDG profile store keeps a
stable random UUID, canonical principal history, redacted credential-provider
references, lifecycle/selection, and opaque authority bindings. Fresh VM and
API-credit work uses the selected primary; version-3 run recovery resolves the
recorded retained principal. Installed buyer plugins must declare the shared
resolved-identity injection contract.

The implemented change mapping is
[`add-persistent-buyer-profiles`](../../openspec/changes/add-persistent-buyer-profiles/).
Remaining external operational evidence belongs to that change's unchecked
verification tasks; it does not restore legacy identity precedence.

---

## Hosted settlement release status

The marketplace consumes `fiat.stripe.v1` through the signed
hosted-settlement client and image contract described by
[`settlement-servicing`](../../openspec/specs/settlement-servicing/spec.md).
The platform authority owns Checkout, Connect transfer, refund, and recovery
state; portable attestations and EAS arbiters supply condition evidence without
turning provider-custodied funds into on-chain or segregated escrow. New hosted
mechanisms must preserve that authority boundary and the immutable
manifest/capability verification path.

---

## Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the current system and its boundaries.
- [`openspec/changes/README.md`](../../openspec/changes/README.md) — delivery campaigns, readiness, and blocking.
- [`openspec/specs/README.md`](../../openspec/specs/README.md) — the normative contract for each capability.
