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

Pricing is the binding constraint. Commercial resolution produces a single price per GPU model through a three-tier chain of storefront override, pool hint, and configured default. There is no per-dimension pricing and no price-as-a-function-of-shape anywhere, so no seller policy can evaluate a counter-offer that changes RAM or disk. **No active change owns that pricing and negotiation-policy work**; the changes below cover the vocabulary, the guard, and the end-to-end wiring around it.

| Open gap | Owned by |
|---|---|
| Buyer-facing requirement shape is flat and ambiguous; `offering_type` is conflated with the site-inventory `resource_type` discriminator; claim vocabulary is inconsistent across the codebase | [`structured-capacity-requirements`](../../openspec/changes/structured-capacity-requirements/) |
| No negotiation round after the first can express a shape change, and reservation resizing has no caller | [`negotiation-driven-capacity-resize`](../../openspec/changes/negotiation-driven-capacity-resize/) |
| The accepted VM shape does not reach the provisioning request, so a GPU-reserving listing can fulfill without a GPU | [`fix-vm-fulfillment-capacity-boundary`](../../openspec/changes/fix-vm-fulfillment-capacity-boundary/) |
| Buyer-negotiated VM connectivity terms, currently operator-configured only | [`add-buyer-vm-connectivity-terms`](../../openspec/changes/add-buyer-vm-connectivity-terms/) |

---

## Goal 3 — One storefront serving several compute-family domains

**Value.** This decouples *how hardware is sold* from *how hardware is partitioned*. Today the listing form factor is a deployment boundary, so a site owner must physically dedicate hosts to VMs rather than bare metal rather than pods. Removing that lets one pool of hardware be offered concurrently as several form factors, priced independently, with the site authority arbitrating exclusivity between them — higher utilization and better price discovery without buying more hardware.

**Current state.** The provisioning side is already many-to-many. One storefront may aggregate several sites and one site may serve several storefronts; storefronts route reservations to a selected site and persist that binding; a single provisioner can register VM and bare-metal adapters concurrently; and the site authority already resolves cross-mode conflicts over one physical resource. The buyer CLI already loads several market-domain contracts in one process, and the core carrier already validates a set of contracts and rejects duplicate identities.

The storefront does not. Each storefront composition root injects exactly one market-domain contract, and both the bare-metal composition and the multi-domain topology proof record one-market-domain-per-storefront-process as an explicit non-goal. Those positions predate the decision to pursue this goal and are **unreconciled**: they are recorded architectural direction that this goal supersedes, and reconciling each change's own documents is part of the work rather than an oversight to be assumed away.

Two questions are open and not yet answered by any change. Whether a multi-domain storefront multiplexes several contracts in one process or federates single-domain processes behind a shared publication surface is undecided, and the two shapes imply substantially different work. Discovery is also unaddressed: a registry publishes one filter and listing schema, so a storefront spanning several domains either publishes to several registries or the compute family needs a shared discovery schema.

| Open gap | Owned by |
|---|---|
| Bare metal has no runnable seller storefront composition; the trusted per-resource projection and selected-site fulfillment routing it needs are incomplete | [`market-platform-bare-metal-10-storefront-composition`](../../openspec/changes/market-platform-bare-metal-10-storefront-composition/) |
| Many-to-many storefront-to-site ownership, strict recorded executor identity, and concurrent domain execution are not proven as one topology | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |
| Storefront request identity is a single shared key, with no per-record ownership | [`add-storefront-principal-authentication`](../../openspec/changes/add-storefront-principal-authentication/) |

---

## Goal 4 — Prepare the kit layer for new market domains

**Value.** This lowers the marginal cost of every domain added after it. If a shared capability carries one domain's vocabulary, each new domain either inherits defaults that mean nothing to it or forks the capability. The goal is making the fifth domain cheap, not making the second one possible — planned additions include a Kubernetes pod domain in the compute family, an inference-token domain, and a model-training domain.

**Current state.** The kit layer has an explicit one-way hierarchy — foundation capabilities, then the site and resource-pool authorities, then the fulfillment lifecycle — and the boundary holds: kit packages do not import deployed services or domain adapters, and type-only imports obey the same direction. Resource pools are provider-neutral, carrying provider kind and provider-owned configuration generically. Publication and reservation-hold hints are domain-neutral by construction, validating only what has a universal meaning and leaving domain-specific content opaque. The API-credits domain demonstrates that a market with no physical delivery reuses the same negotiation and settlement roles without acquiring compute dependencies.

The site authority is where compute vocabulary has not finished leaving. GPU count is a module-level primary dimension, resource type defaults to a GPU-specific value, and VM host identity is special-cased in attribute extraction, with dimension fallbacks that assume GPU counting. Composition roots already supply some of this from above, so the genericization is partly done rather than absent.

The domain layer's own organization is uneven. The API-credits domain is partially in place, and the in-tree domains do not share one structure — which matters more as the number of domains grows than it did with two.

No active change owns the kit reorganization or the new domains. The gap below is adjacent work already in flight.

| Open gap | Owned by |
|---|---|
| Executor identity falls back implicitly to VM where durable identity is absent, which a growing set of executor kinds cannot tolerate | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the current system and its boundaries.
- [`openspec/changes/README.md`](../../openspec/changes/README.md) — delivery campaigns, readiness, and blocking.
- [`openspec/specs/README.md`](../../openspec/specs/README.md) — the normative contract for each capability.
