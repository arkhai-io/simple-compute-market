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

Buyer-access infrastructure is provisioning-owned. A tunnel relay is a resource in the provisioning service, referenced by the pools whose hosts dial it, holding its own rendezvous address, port window, and admission token. The VM storefront names no relay and holds no relay credential: which relay serves a host is a physical fact about where that host is, and a storefront selecting one per request would make a fleet-wide property depend on a commercial caller's configuration.

The committed claim now governs the fulfillment request. A reservation carries its admitted claim -- dimensions and categorical constraints both -- and the scheduler reads it back rather than trusting the request, so a GPU-reserving listing can no longer fulfill without a GPU, and the durable create handle is written by the service that dispatches it. A reservation's release handle has one name, `release_job_id`, on every lease contract and for every offering mode sharing the reservation table.

Sellable capacity is declared in the site authority, across every dimension a resource names — GPUs, vCPU, RAM, disk, or a domain's own units — and host inventory is connection identity only. Operators declare through the registration API or a capacity-definitions document, mounted through the provisioning chart or submitted to its import API; a host's legacy INI GPU count is derived into a declaration once, where it enters or at upgrade. So the storefront CSV is no longer the only operator-facing expression of multi-dimensional capacity, which was the prerequisite its retirement waited on.

Host records are used only where a connection is made. The resource-pool projection is built from capacity declarations alone and carries no host connection identity, and execution renders its inventory solely from the registered host record the work names, refusing a host with none. An inventory file seeds the host registry at first boot and is never read at execution.

The VM development scenario runs two storefronts against separate provisioning
authorities. Both derive listings from their respective site projections, and
the scenario covers registry publication, buyer discovery, and negotiations.
This establishes a working two-storefront topology. Multiple storefronts per
site remain outside its scope.

| Open gap | Owned by |
|---|---|
| The VM storefront retains local physical tables, the local-table derivation path, CSV import and its deployment contract, and a legacy home-site override record beneath the site-scoped override store | [`pools-9-retire-local-physical-authority`](../../openspec/changes/pools-9-retire-local-physical-authority/) |
| The VM storefront retains a dead execution ledger, an orphaned physical admin surface, and dead physical-identity plumbing | [`remove-dead-storefront-physical-surfaces`](../../openspec/changes/remove-dead-storefront-physical-surfaces/) |
| A Resource Pool's provider can be swapped in place, silently reinterpreting which executor its members belong to | [`fix-resource-pool-provider-at-creation`](../../openspec/changes/fix-resource-pool-provider-at-creation/) |
| The relay path is implemented but unverified on a rented host: reload preservation of live sessions, the port window, teardown release, and relay deletion under live leases remain to be proved or decided | [`relay-vm-access-without-a-dashboard`](../../openspec/changes/relay-vm-access-without-a-dashboard/) |
| Host inventory seeds the host registry only when it is empty and is never reconciled against its file, so editing a running deployment's inventory changes nothing | [`bring-host-inventory-under-definition-documents`](../../openspec/changes/bring-host-inventory-under-definition-documents/) |
| One SSH key reaches every host in an environment, so a host prepared by another party cannot be registered with its own credential | [`contain-embedded-host-key-material`](../../openspec/changes/contain-embedded-host-key-material/) |

A schema drop of the frozen columns is deliberately excluded from the retirement and belongs to a later follow-up, after a deployment cycle confirms the freeze never needed rolling back.

Reaching hosts and VMs that have no inbound route is not a separate goal. The product already sells VMs on hosts it reaches by tunnel; what the relay and host-key work fixes is that the existing mechanism required a relay to expose a management surface and required the storefront to hold physical facts. Those are defects in how the mechanism was built, and they belong to this goal's consolidation rather than to a capability the product does not yet have.

---

## Goal 2 — Negotiate full compute capability, not GPU count alone

**Value.** This is the difference between a market that sells fixed SKUs and one that sells capacity. Hardware is heterogeneous and buyer requirements are multi-dimensional; negotiating on GPU count alone forces sellers to pre-partition inventory into fixed shapes and forces buyers to over-buy on every dimension they did not need. Supporting the full shape raises fill rate and utilization revenue on hardware the seller already owns.

**Current state.** The lower layers already carry the full shape. The VM domain defines canonical dimensions for GPU count, vCPU count, RAM, and disk, and a family-grouped capability shape (`gpu`, `cpu`, `memory`, `storage`) with a shared, schema-driven flattener into those flat names; the offering mode is a required field on the claim wire, distinct from the site's inventory discriminator; the site authority admits and matches multidimensionally; scheduling fit-checks every requested dimension and treats the dimensions actually scheduled as authoritative; capacity reservations can be resized by supersede rather than mutation; and the Ansible playbooks create VMs with variable shapes.

The top of the stack does not. A buyer that names a resource shape disagreeing with the listing's own shape is rejected outright at negotiation round zero, deliberately and loudly, because no round can carry a shape for seller policy to evaluate and price. Rounds after the first carry only price and escrow terms, with no field for a shape change. Reservation resizing is implemented and has no caller anywhere in the repository.

Publication carries the shape it is given. Every VM listing is a listing shape, stated by the storefront's site-scoped pool override, else by the pool's `listing_shapes` hint, else generated by the VM domain's default. A listing publishes and reserves exactly the quantities its shape declares, and is published only where a source member is feasible for it. A stated shape that declares vCPU, RAM, or disk is therefore found by the registry's existing dimension filters. A pool with no stated shape still publishes the GPU-only default, so a dimension filter excludes it, as the filters' fail-closed semantics intend, rather than advertising a value nothing declared. How many of a shape fit is derived from the site's declarations, never published.

What is agreed reaches the provisioning request: once a claim is admitted, the reservation is authoritative for it through scheduling and dispatch, and a dimension the listing's shape omits is outside that commitment: fulfillment may supply it from the pool's configured VM defaults or leave it to the provisioning playbook.

A seller can price a shape. Rates are stated per capacity family -- per card-hour for a GPU model, per vCPU-hour, per GiB-hour of memory and of storage -- in an asset, and resolve per family through the site-scoped storefront override, the pool hint, and the configured default; a rate that cannot be read holds the pool rather than falling through. A listing for which any family resolves rates is shape-priced: each settlement option's rate is composed from the listing's own shape through a replaceable, exact aggregator, a family without a rate is not charged, and a listing that would be free is never posted. Every resolved family's rates are recorded on the storefront's listing record, without reaching a registry, so a revised shape can be priced from them. Every other listing keeps its clause's flat rate, unchanged. The seller negotiates from the rate of the option the buyer selected. Negotiation still carries exactly one degree of freedom, a scalar amount moved by the concession middleware, so no seller policy can evaluate a counter-offer that changes RAM or disk — which is why a buyer naming any shape is rejected at round zero, deliberately and with the reason recorded in the guard itself. The seller's own feasibility check compares region and GPU model by equality and no quantitative dimension. Nothing consults the authoritative site until a hold is placed at terms acceptance, so an unservable shape surfaces after both parties have committed.

| Open gap | Owned by |
|---|---|
| Nothing expresses which shapes a seller will consider, or what range remains admissible for one dimension given the rest | [`capacity-shape-envelope`](../../openspec/changes/capacity-shape-envelope/) |
| The authoritative site is not consulted until terms are already agreed, so an unservable shape fails after both parties commit | [`negotiation-capacity-feasibility-probe`](../../openspec/changes/negotiation-capacity-feasibility-probe/) |
| The storefront persists the whole capacity claim under a key named for its categorical half, and the compute family's flat dimension names, which the VM and bare-metal domains share from one schema, are a recorded exception to the family-prefixed convention | [`settle-capacity-claim-vocabulary`](../../openspec/changes/settle-capacity-claim-vocabulary/) |
| No negotiation round after the first can express a shape change, the negotiated quantity is an absolute amount that stops being comparable once shape varies, and the agreed shape does not reach the claim | [`negotiation-driven-capacity-resize`](../../openspec/changes/negotiation-driven-capacity-resize/) |

`negotiation-capacity-feasibility-probe` is a shared prerequisite rather than exclusively this goal's: charging for a held reservation also requires a buyer to learn feasibility before any hold, and therefore any charge, exists. Not every change belongs to a roadmap goal, and this one is listed here because this goal consumes it, not because it is owned by it.

Reservation resizing keeps having no caller within this goal, deliberately: both storefronts place no hold before settlement, so the reservation created at settlement is built from the agreed shape and there is nothing to resize during negotiation. The first caller is Goal 5's `negotiation-time-capacity-hold`, the change that holds capacity before the shape is final.

Buyer-negotiated VM connectivity terms are no longer a gap of this goal. The relay a VM's tunnel uses is a physical fact recorded at the provisioning service and is not selectable per request, and the tunnel client runs on the host with one relay for every rented VM. The seller's relay is the bootstrap path to every VM; a buyer who wants their own relay reaches the VM through its relay port once and starts a client inside the guest. Avoiding the seller relay entirely would be guest-side first-boot configuration, a "Reach hosts" concern rather than a negotiation one.

---

## Goal 3 — One storefront serving several compute-family domains

**Value.** This decouples *how hardware is sold* from *how hardware is partitioned*. Today the listing form factor is a deployment boundary, so a site owner must physically dedicate hosts to VMs rather than bare metal rather than pods. Removing that lets one pool of hardware be offered concurrently as several form factors, priced independently, with the site authority arbitrating exclusivity between them — higher utilization and better price discovery without buying more hardware.

**Current state.** The common storefront shell now discovers installed domain
contributions, applies explicit public registrations, and freezes an exact
mode/domain/version registry. VM and bare-metal publication sources can share
one process. Listings, negotiation threads, and fulfillment contexts carry
immutable domain, offering-mode, selected-site, and provenance bindings;
negotiation, settlement, fulfillment, result recovery, and teardown route from
those records rather than payload guessing, installed order, or a VM default.
Existing single-domain VM databases enter this schema only through the
explicit, preview-first, backed-up transactional migration.

Resource Pools already declare exact deliverable offering modes. Capacity
claims carry that mode through reservation, scheduling, and provider dispatch,
and accepted records retain it when publication changes. The shared
storefront-to-site clients pin mapped work to one trusted authority with no
cross-site fallback. The registry catalogue can now receive the public
`listing_resource.offering_mode` projected from the frozen binding.

Goal 3's shared storefront boundary is therefore implemented and promoted. The
bare-metal producer has landed too: an installable buyer contribution, a seller
composition that starts through the shared shell and composes kit publication, a
compose stack and its own end-to-end lane, and a real-host deal scenario. Complete
product acceptance still depends on bare metal negotiating through the kit runtime
rather than its own service, and on the topology proof below; the shell deliberately
does not fake either.

| Open gap | Owned by |
|---|---|
| The bare-metal contribution negotiates through a domain-local service and its own negotiate and listing routes beside the shared shell, rather than through the kit negotiation runtime every other domain composes | [`bare-metal-and-credits-domain-stacks`](../../openspec/changes/bare-metal-and-credits-domain-stacks/) (Goal 4, Section 4a) |
| One-process VM/bare-metal behavior across more than one authority needs live selected-authority, cross-mode, execution-dispatch, teardown, and capacity-restoration evidence | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

---

## Goal 4 — Make a domain a composition of kit

**Value.** The architecture's layering is core for what applies to every domain, kit for composable functionality many domains share, and the domain layer for instantiating and configuring kit. The storefront role does not follow it, so the marginal cost of a market domain is roughly three thousand lines of negotiation, settlement, capacity, publication, and failure-handling machinery that is identical in every domain but its codecs.

That cost is why bare metal has been a storefront skeleton and why API credits carries a full parallel copy of eight VM services. It compounds: every defect fixed in one copy stays live in the other, and every new cross-cutting capability — billable holds, shape-aware pricing, feasibility verification — must be built once per domain or silently skip the domains that lack it. A capability that reads as "the market does X" is often really "the VM market does X."

Extracting that machinery into kit changes what adding a domain means. A Kubernetes-pod domain, an inference-token domain, or a model-training domain becomes codecs, a contract, and configuration rather than a fork of the VM storefront. The two domains delivered here are both the beneficiaries and the proof: bare metal because it has none of the machinery, API credits because it has a complete parallel copy, so composing them exercises both directions.

**Current state.** Kit's layering discipline now includes `kit/storefront`,
`kit/negotiation-runtime`, `kit/settlement-runtime`, and
`kit/capacity-publication`. The storefront kit owns application/lifespan
assembly, container construction, route and middleware contribution, Alkahest
client construction, and the stale-negotiation watchdog; VM and API-credit
storefronts contribute their domain routes and timing, while bare metal
composes the shared watchdog and chain factory.

The negotiation kit owns signed round ordering, canonical-principal and
terminal-state guards, durable transcript recovery, and the acceptance
chokepoint. VM and API-credit storefronts inject their listing resolution,
codecs, seller policy, configuration, accepted-artifact construction, and
persistence/effect hooks, so neither retains a lifecycle copy. The settlement
kit owns one stable per-obligation operation journal, conditional-escrow client
port, servicing worker, and failure dispatcher.

The capacity/publication kit owns exact site projections, event-driven
reconciliation, registry fan-out, publication result recording, and
close/reopen mechanics over injected schema-opaque candidate and binding hooks.
VM and API-credit storefronts compose those runtimes rather than maintaining
local copies; pool-declared offering mode and persisted selected-site binding
remain authoritative through publication and recovery. Bare metal composes the
same capacity and publication seams, the shared watchdog and chain factory, and
selected-site fulfillment, result, and teardown, and has a deployable stack with
its own end-to-end lane; it still carries a domain-local negotiation service and
its own negotiate and listing routes beside the negotiation kit. `kit/policy`,
`kit/identity`, `kit/fulfillment`, `kit/config`, and `kit/alkahest` likewise
carry no domain vocabulary.

The storefront kit also owns the timer-loop lifecycle. Each VM, bare-metal, and
API-credit storefront holds its loops with one kit loop controller, under one
pause and a step per loop served on the same routes, so a scenario can hold and
advance any storefront through the canonical client; the capacity kit owns the
per-site poller aggregate both capacity-publishing storefronts compose.

Beneath the extracted runtimes each storefront still duplicates its shell — a
route set over the same core models, executable assembly, and health — its
seller listing lifecycle and restart-safe fulfillment convergence,
its authentication middleware, and a persistence client beside core's. Those are
the next wave of extraction; each follows the rule that an extracted concern
leaves no domain-local copy.

Settlement assigns stable identity to every accepted-plan obligation, journals
materialize/status/check/collect/reclaim attempts, persists opaque mechanism
state across retry, preserves partial outcomes, and supports directional
interval payments and seller penalty bonds. VM and API-credit roots use this
runtime for exact verified-obligation adoption, fulfillment binding, and
collection. Their connection details, credentials, capacity repair, refund,
and issuance rollback remain at their real domain boundaries rather than
becoming generic settlement state.

VMs, bare metal, and API credits compose Arkhai payments and Alkahest as peer settlement mechanisms. Exact Agreements and seller-derived mandates feed receipt-gated selected-site fulfillment or idempotent credit issuance. Payment-only Ed25519 paths need no wallet or chain; live ledger and domain delivery qualification remain separate evidence boundaries.

The domain layer's own structure is better than the duplication suggests. All three domains follow one pattern — a base contract with a storefront-side extension — and all three pass the shared conformance suite, which works without assuming a repository layout. Only the directory conventions differ, and a composed domain is small enough that relocating them buys nothing.

**Completion test.** Bare metal and API credits each run a full deal through a composed storefront, with no domain-local copy of an extracted concern.

| Open gap | Owned by |
|---|---|
| Live Arkhai payment qualification across VM delivery, API-credit issuance, and bare-metal selected-site access/teardown | [`settle-through-arkhai-payments`](../../openspec/changes/archive/2026-10-08-settle-through-arkhai-payments/) |
| Production buyers build storefront requests by hand instead of using the storefront's typed client, so the route contract has two independent implementations | [`buyers-use-the-storefront-client`](../../openspec/changes/buyers-use-the-storefront-client/) |
| The bare-metal storefront negotiates through a domain-local service and routes rather than the negotiation kit every other domain composes | [`bare-metal-and-credits-domain-stacks`](../../openspec/changes/bare-metal-and-credits-domain-stacks/) |
| API credits has no end-to-end lane of its own — its scenario rides the VM lane — and its storefront has no test that runs the production application | [`apicredits-end-to-end-lane`](../../openspec/changes/apicredits-end-to-end-lane/) |
| Every storefront carries its own route set, executable assembly, and health service | [`kit-owned-storefront-shell`](../../openspec/changes/kit-owned-storefront-shell/) |
| Every storefront reimplements the seller listing lifecycle and restart-safe fulfillment convergence; VM keeps its own per-site projection cache | [`kit-owned-listing-and-fulfillment-lifecycles`](../../openspec/changes/kit-owned-listing-and-fulfillment-lifecycles/) |
| Every storefront carries its own authentication middleware and a persistence client whose boundary with core's is unstated | [`kit-owned-storefront-auth-and-persistence`](../../openspec/changes/kit-owned-storefront-auth-and-persistence/) |
| No bare-metal deal runs in the pipeline: the only complete-deal scenario needs a real host | [`bare-metal-mock-provisioned-deal`](../../openspec/changes/bare-metal-mock-provisioned-deal/) |

**Design promotion (2026-08-15).** `kit-storefront-composition-seam`,
`kit-owned-negotiation-runtime`, and `kit-owned-capacity-and-publication` are now
implemented by `kit/storefront`, `kit/negotiation-runtime`, and
`kit/capacity-publication` and recorded permanently in the market composition,
negotiation, and storefront-publication specifications and architecture. VM and
API credits preserve their one-domain route and timing behavior through
explicit storefront contributions, inject domain hooks into the shared
negotiation lifecycle, and use the shared durable capacity/publication binding;
bare metal composes the previously missing watchdog and chain factory and the
same capacity seams. The remaining multi-domain, domain-stack, and live
settlement qualification gaps build on these seams rather than reopening them.

API-credit issuance uses canonical principal ownership, deterministic fulfillment/grant identities, request digests, unknown-outcome retrieval, and a private credential result channel. Arkhai payment receipts gate issuance; Alkahest retains its own condition and collection path.

No domain's capacity declaration carries another domain's dimension name: the dimension the legacy scalar total mirrors is supplied by each composition, and a declaration holds exactly the dimensions it names.

---|---|
| The offering mode falls back implicitly to VM where durable identity is absent, which a growing set of offering modes cannot tolerate | [`market-platform-compute-40-multi-domain-proof`](../../openspec/changes/market-platform-compute-40-multi-domain-proof/) |

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
| Holding capacity is free, so exclusivity cannot be granted before payment without exposing the denial vector; no posted hold rate exists beside the lease rate | [`billable-capacity-reservations`](../../openspec/changes/billable-capacity-reservations/) |
| Capacity is not held while a buyer is negotiating for it, so two buyers can negotiate the same capacity to completion | [`negotiation-time-capacity-hold`](../../openspec/changes/negotiation-time-capacity-hold/) |
| The shipped default granted unfunded exclusivity, and framed the safe value as a performance trade | [`default-no-pre-settlement-capacity-hold`](../../openspec/changes/default-no-pre-settlement-capacity-hold/) |

Restoring a non-zero hold default is `billable-capacity-reservations`' own work: the posture above is a denial of capability that this goal exists to buy back.

---

## Goal 6 — Make the settlement mechanism a composed choice

**Value.** Escrow is one way to close a deal, not the definition of one. Charge-first payments and durable introductions serve different commercial agreements. Much capacity trade is arranged person-to-person, where the marketplace supplies discovery, negotiation, and a trustworthy introduction rather than payment custody or provisioning. Mechanism registration keeps shared option/configuration work reusable; each supporting domain composes the selected settlement evidence with its own delivery.

**Current state.** `alkahest.v1` and `arkhai.payments.v1` are peer registrations in VM, bare-metal, and API-credit compositions. Shared configuration owns readiness, publication options, and buyer compatibility, not a universal escrow API. Negotiation emits exact Agreement bytes; the selected settlement stage produces evidence consumed by domain provisioning. Arkhai payments stores the seller-derived mandate in shared negotiation `settlement_data`, approves and polls a deterministic transaction, and gates provisioning or issuance on a verified signed receipt. It creates no settlement plan or obligation and runs no servicing daemon. `fiat.stripe.v1` and its hosted client, funding profiles, setup, and recovery commands are not part of the installed system. Buyers settle an Agreement deal through the typed storefront client's `settle_agreement`, over the settle route contract shared by the client and every storefront's authentication. Agreement attachment is owned by each side: the buyer attaches only by its own `attach_agreement` policy, and a seller whose option sets `deposit_agreement` attaches it before delivering. Refunds are seller-initiated reversals, ordered against delivery start, with an opt-in `refund` failure action; each domain's reconciliation pass converges approved deals a buyer never settles.

Alkahest and `contact-exchange.v1` retain the shared obligation journal and escrow-oriented carriers. A third mechanism now exists: `contact-exchange.v1` completes a deal by durable, authenticated introduction — rateless options, a scalar-declining registration, one non-financial obligation, a persisted reveal surface (`/api/v1/introductions`), and a loose-listing discovery profile — composed end-to-end on bare metal and VM. Interpreting a domain's accepted state for it, including the re-derivation of the obligation reference a reveal names, lives once in the mechanism kit; a composing storefront supplies only its persistence reads, configuration, and route bindings. The buyer's introduction commands are the mechanism's own, mounted by each domain buyer. A seller's default negotiation policy accepts an exact selection of an option that bargains no amount, so an introduction reaches acceptance on the published terms instead of being countered by a policy waiting for an amount it never carries. All three storefront domains now dispatch exact-selection acceptance through the registration's accepted-obligation builder with no per-mechanism arm: the mechanism resolves once from the selection, rate arithmetic (duration-scaled and counted-unit alike) lives inside the mechanism, and each domain keeps only its own service terms and scaling input. Scalar participation is a declinable registration capability carried to counterparties through the option shape. Core carries public options, accepted Agreements, immutable role-stage tables and opaque seller evidence. Agreement-selected entries own revalidation and continuations; common VM/bare-metal delivery and credit issuance consume validated facts without concrete-mechanism switches. Buyer recovery retains exact accepted inputs and opaque references, not seller SettlementEvidence. Domain evidence/progress records are separate from genuine escrow servicing.

Each recipient can deliver its revealed introduction: each side hands its own copy of the reveal to sinks its operator configured locally, through an installed-plugin contract that grows a destination by installing a package rather than editing the marketplace. `kit/delivery` owns a mechanism-neutral event, the sink protocol, discovery, and four protocol-thin built-ins (file, local program, webhook, mail); the seller dispatches off the reveal's critical path from the introduction route service, the buyer dispatches inline after printing. Delivery is never authoritative — the durable, re-readable reveal is what makes best-effort delivery safe — and the mechanism kit has no delivery dependency because dispatch is injected.

Current limits: escrow claimant, expiration, and condition fields remain in existing core carriers, and `kit/settlement-runtime` remains shared by Alkahest and contact exchange. Moving those escrow semantics fully into Alkahest is a separate refactor. The legacy `/api/v1/settle/{escrow_uid}` family remains the Alkahest surface.
Payment evidence and delivery/issuance progress no longer occupy escrow rows.

| Open gap | Owned by |
|---|---|
| Live Arkhai payment and domain delivery qualification | The payments service's end-to-end tests, which import this repository's published packages; this repository's payment scenario runs only against a configured target |
| Spot / interruptible deals on payment rate parts, with teardown on stop | [`spot-deals-through-arkhai-payments`](../../openspec/changes/spot-deals-through-arkhai-payments/) |
| Isolate escrow carriers and the conditional-escrow port fully within Alkahest | [`move-escrow-into-alkahest`](../../openspec/changes/move-escrow-into-alkahest/) |
| Escrow fields in listing, registry and storefront-client wire formats | [`drop-escrow-from-shared-wire`](../../openspec/changes/drop-escrow-from-shared-wire/) |
| Cross-domain contact-exchange composition beyond bare metal; contact-payload retention automation | Unowned — needs a new change; background in [`contact-exchange-settlement-mechanism`](../../openspec/changes/archive/2026-08-19-contact-exchange-settlement-mechanism/) |
| Delivery beyond bare metal, and a second event producer (a settled charge, a completed escrow) | Unowned — needs a new change; background in [`add-introduction-delivery-sinks`](../../openspec/changes/archive/2026-08-19-add-introduction-delivery-sinks/) |

A revealed introduction now reaches its owner rather than only being readable: each side hands its own copy of the reveal to sinks its operator configured locally, through an installed-plugin contract that grows a destination by installing a package rather than editing the marketplace. `kit/delivery` owns a mechanism-neutral event, the sink protocol, discovery, and four protocol-thin built-ins (file, local program, webhook, mail); the seller dispatches off the reveal's critical path from the introduction route service, the buyer dispatches inline after printing. Seller-side dispatch is the delivery kit's, shared by every composing storefront; sinks are named instances of installed sinks, routed by the origin site of the listing a deal came from; a webhook can sign its request with the storefront's marketplace signer; and an installable Apprise sink reaches the services Apprise supports. A storefront's deployment schema types each installed sink's settings by discovery, so its secret settings stay out of public configuration. Delivery is never authoritative — the durable, re-readable reveal is what makes best-effort delivery safe — and the mechanism kit gained no delivery dependency, because its dispatch is injected.

Revealed contacts are now kept for a bounded window. A storefront sets `retention_seconds` in its contact settlement section, 30 days by default or `indefinite`, as an aggregate policy that also applies to introductions revealed before a change to it. Deletion redacts both payloads in place and leaves a tombstone, which database triggers keep one-way, so the deal and its obligation record survive and a deleted introduction can never be revealed or delivered again. One deletion operation in `kit/contact-exchange` serves a held-and-stepped sweep and an operator deleting one introduction early, and the window is disclosed on the public readiness projection, before a buyer commits a contact, and again at reveal. Bare metal composes all of it; the bare-metal lane carries the first introduction scenario.

What deliberately remains: the `escrows` table and the `/api/v1/settle/{escrow_uid}` route family serve as the Alkahest mechanism surface (retirement needs deployment evidence), and pre-plan legacy escrow rows keep only their mechanism-surface identity.

| Open gap | Owned by |
|---|---|
| Recorded responses kept for exact retry — every introduction reveal and read included — are never bounded, so a revealed contact outlives the introduction retention window there. The disclosure is scoped to the introduction record accordingly | [`redesign-authenticated-replay-state`](../../openspec/changes/redesign-authenticated-replay-state/), which redesigns replay state for every authority; [`retain-authenticated-request-outcomes`](../../openspec/changes/retain-authenticated-request-outcomes/) is blocked on it |
| A second delivery event producer (a settled charge, a completed escrow) | Unowned — needs a new change. Delivery sinks are event-driven and non-authoritative: a sink consumes a durable delivery event and re-delivery reads the persisted reveal, so a second producer adds an event source, not a second delivery path. A storefront with more than one origin refuses seller-side sinks unless an origin routing table is configured, unconditionally rather than per event kind, because introductions are the only events today; a second producer should revisit whether its events are origin-scoped and whether that refusal should follow the event rather than the sink set |

Delivery follows composition: every storefront composing contact exchange delivers, routed per origin.

---

## Goal 7 — Sell capacity the marketplace cannot admit against

**Value.** A large share of real capacity trade is arranged directly between the parties, on terms too exotic to parametrize and with no escrow, payment custody, or automated provisioning anywhere in the deal. The marketplace's value there is discovery and a trustworthy introduction. Without an explicit notion of backing such a seller could not list at all: every listing had to name a trusted site and an admissible source, so a seller with nothing to admit against had to either fabricate an authority that admits forever — a value the admission, commit, release, and restart-recovery paths would then trust — or stay out of the market.

Making backing an explicit property is what lets that seller in without weakening the promise for everyone else. A listing that claims admissible capacity still gets every check it gets today; a listing that claims nothing gets none, because there is nothing to check. The gain is supply-side: a seller who will not integrate escrow or hand over SSH credentials can still be discovered, and a buyer gets one catalogue to compare rates across both kinds of supply.

The same property serves market families with no physical supply behind them at all, which is where the qualifier originated. Nothing about it is compute-specific.

Bare metal is this goal's primary target domain: supply arranged directly between the parties is overwhelmingly whole machines. VM and bare metal reach the goal through the same kit mechanisms — publication runtime, declaration reader, capability shapes, pool overrides, and introduction composition — rather than each solving it separately.

**Current state.** Backing is a property of both pools and listings. A Resource Pool declares whether it is capacity-backed and which offering modes its listings may advertise, separately from the modes its provider can deliver. A listing records its backing on its immutable binding, derived from that declaration, and its origin site is kept distinct from any admission authority; [`ARCHITECTURE.md`](ARCHITECTURE.md) defines both. The compute registry schema publishes each listing's backing with an exact filter, so a buyer can exclude supply nothing stands behind.

Settlement by introduction is a working mechanism with rateless options, a durable authenticated reveal, and delivery to each side, so the settlement half of an out-of-band deal already exists, and so does the unbacked listing shape it attaches to. VM composes introduction, so an unbacked VM listing publishes an introduction option and settles by it; the seller's contact is resolved from the listing's origin site, so one storefront publishing for several seller sites reveals each deal's own seller. Bare metal composes introduction and reads its pools' projected declarations through the kit publication runtime, and its listings carry capability shapes, but it publishes no unbacked listing to attach an introduction to.

An unbacked pool — one that declares no deliverable mode, and so is kept out of every capacity path — advertises modes on its own declaration, naming a configuration-free provider rather than fabricated configuration, and a capacity declaration with no host behind it reaches storefronts through the resource-pool projection. A storefront now publishes on its own from the projections of the sites it trusts: it derives listings from every advertisable pool, refreshes their terms, closes those whose source no longer supports them, and keeps each registry converged on its listings' status, with a seller's close durable against every reconciliation. An unbacked listing is never admitted against and publishes only settlement options its domain does not fulfil through capacity. The VM storefront composes contact exchange, which it does not fulfil through capacity, so an unbacked VM listing publishes an introduction option and settles by it. Bare-metal publication reads pool declarations from each site through the shared reader and publishes through the kit runtime. It records listings locally before registry publication, converges registry state, and holds listings when their site cannot be read. Every bare-metal listing remains backed by construction, so the primary target domain cannot publish unbacked supply yet. A bare-metal listing's shape is derived from its Physical Resource's declaration through the compute-family schema both compute domains share. It is published under the same top-level fields as a VM listing's, with its pool's region, so a buyer filtering compute supply by GPU model, count, region, or any other dimension finds whole machines and VM slices alike. A compute listing can publish its seller's asking rate for its shape: an exact decimal amount, the asset it is quoted in, and the period it is quoted per. It is a listing attribute rather than a settlement option rate, so supply that settles by introduction, whose options are rateless by design, can carry one too. A site declares rates per shape on its pools, and a storefront's per-site override has final authority over them for VM and bare metal alike; no configuration default supplies one. A buyer bounds a query by rate in a named asset and period, compared exactly, and a listing publishing no rate is excluded from such a query. Comparing unbacked supply on rate in a running stack is proven for VM: the VM introduction scenario finds backed and unbacked VM listings with one rate-bounded query. The bare-metal proof belongs to [`unbacked-bare-metal-listings`](../../openspec/changes/unbacked-bare-metal-listings/).

The hint that governs how many candidates a pool yields is named `listing_cardinality_mode`, and its scope is stated normatively, so a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. The earlier name read as though it governed how a pool is listed generally, and that ambiguity had already produced a proposal to encode backing or settlement inside the hint, which would have coupled inventory declaration to settlement mechanism.

| Open gap | Owned by |
|---|---|
| ~~Four names refer to the offering mode and `offer` refers to three different things~~ — closed: the offering mode is `offering_mode` on every surface, a seller's published shape is `listing_resource`, and `offer` means a negotiation message | [`settle-listing-vocabulary`](../../openspec/changes/archive/2026-09-15-settle-listing-vocabulary/) |
| ~~Bare-metal listings form no capability shape and publish their hardware where the compute schema's filters cannot see it~~ — closed: a bare-metal listing's shape is derived from its declaration through the shared compute-family schema and published where the compute filters read it | [`bare-metal-listing-shapes`](../../openspec/changes/archive/2026-09-27-bare-metal-listing-shapes/) |
| Bare metal, the primary target domain, cannot publish an unbacked listing | [`unbacked-bare-metal-listings`](../../openspec/changes/unbacked-bare-metal-listings/) |
| ~~A seller price is published only inside settlement carriers and no filter reads a rate value, so supply cannot be compared on rate~~ — closed: a listing publishes an asking rate per shape, declared by its site and overridable by its storefront, and buyers filter on it exactly | [`publish-indicative-listing-rates`](../../openspec/changes/archive/2026-10-01-publish-indicative-listing-rates/) |

The published rate is one number per listing shape, not a per-dimension structure. A seller pricing RAM and GPUs differently cannot express that, and a buyer comparing two listings that bundle different RAM is comparing bundled prices — an accepted limitation for this goal. Unbundling is per-family rates, from [`capacity-shape-pricing`](../../openspec/changes/archive/2026-10-01-capacity-shape-pricing/), which let a seller price a shape a buyer proposes during negotiation; that is a different surface from a published asking price, and this goal does not wait on it.

This goal is not complete on a queryable listing alone. Its value statement is discovery *and* a trustworthy introduction, so closing it requires a release-qualified business scenario in which unbacked discovery reaches a usable introduction. For VM that scenario runs in the VM end-to-end lane and against a local Helm release: backed and unbacked VM listings are found by one rate-bounded query, and the unbacked one is negotiated, revealed through the buyer CLI, and delivered to both sides. For bare metal, the primary target, it belongs to [`unbacked-bare-metal-listings`](../../openspec/changes/unbacked-bare-metal-listings/).

The multi-seller shape this goal requires is in place in both domains: the seller's contact is resolved per listing origin, never from one storefront-wide value, and seller-side delivery is routed per origin. The live scenario proving it across running services — two seller sites behind one storefront, each revealing its own contact — belongs to [`unbacked-bare-metal-listings`](../../openspec/changes/unbacked-bare-metal-listings/) for both domains, since it needs a lane topology neither lane has yet.

Finite unbacked listings, and payment settlement over them, are anticipated and unowned. They are the reason backing is modelled as a listing property rather than as a domain: a seller's supply becomes capacity-backed later without a new domain, a new registry, or a migration unwinding a fabricated site. Backing itself is immutable per durable listing — an unbacked listing does not become backed, it closes and a backed one is published in its place — because moving from no admission guarantee to a named authority is a material provenance change a buyer holding a listing reference should not have happen underneath them.

Two consequences of this posture are accepted rather than solved. Nothing keeps a listed rate current or honest, since a seller pays nothing to advertise one they will not honour; the intended control is registry curation, which sits outside the registry service boundary and is not implemented here. And an unbacked listing cannot be exhausted, which closes capacity-exhaustion abuse but not abuse of whatever the settlement mechanism reveals.

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

## Payment qualification boundaries

Local focused suites exercise Agreement retention, mandate validation, signed receipts, retryable pending, and idempotent physical/grant progress. The controlled VM smoke reaches pending → provisioning → ready with one delivery; it is not live-ledger or hardware acceptance. Bare-metal and API-credit package tests likewise do not establish external payments or delivery qualification.

A qualified payment run needs the intended owned payments target, owner-scoped credentials, observed readiness, and the actual domain delivery authority. VM delivery, API-key use and top-up, and bare-metal authenticated access, revocation, teardown, and capacity release remain separate outcomes. Unavailable service or hardware prerequisites remain named evidence gaps, not permission to claim a simulated result.

## Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the current system and its boundaries.
- [`openspec/changes/README.md`](../../openspec/changes/README.md) — delivery campaigns, readiness, and blocking.
- [`openspec/specs/README.md`](../../openspec/specs/README.md) — the normative contract for each capability.
