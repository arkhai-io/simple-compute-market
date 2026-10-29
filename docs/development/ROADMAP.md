# Arkhai Market Stack — Directional Roadmap

> **Purpose:** The goals currently being pursued, and those completed, the value each delivers, what is true today, and which OpenSpec change owns each open gap. This document carries no readiness status, no delivery sequencing, no acceptance criteria, and no implementation tasks — those belong to the changes themselves and to [`openspec/changes/README.md`](../../openspec/changes/README.md).

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

When every gap for a goal closes, the goal moves to [Completed goals](#completed-goals) and is no longer updated. Its durable result is by then in `ARCHITECTURE.md` or the owning capability's specification through the ordinary promotion path, and the record of the work is in Git history and the archived changes.

---

## Goal 1 — Consolidate physical-resource authority in the provisioning service

**Value.** One authority for physical state removes a whole class of divergence bugs, and — less obviously but more consequentially — it is what makes the storefront substitutable. A storefront that owns hardware inventory cannot become a multi-domain storefront (Goal 3), cannot be replaced by a different commercial front-end over the same hardware, and forces every seller to maintain the same facts in two places. It also shrinks the seller's operational surface: hardware inventory stops being something an operator imports into a commercial service.

The boundary this goal draws is between *physical* and *commercial* authority, not between the two services generally. Per [`ARCHITECTURE.md`'s authority boundaries](ARCHITECTURE.md#authority-boundaries), pricing, seller policy, and listing state are correctly storefront-owned. The goal is that the storefront holds no physical authority — not that it holds no per-pool records.

**Current state.** The provisioning service is authoritative for hosts, resource pools, capacity admission, scheduling, and the fulfillment lifecycle. Storefronts consume physical facts through the site resource-pool and capacity-bucket projections, and derive every listing from them; no storefront holds physical state.

A Resource Pool's provider is fixed at creation on every administration path: the API and definition documents alike refuse to change it. Moving inventory to a different provider therefore takes a second pool and explicit member reassignment, under the site's live-obligation guard for capacity resources and the host pool-change hooks for hosts. The VM provider is named `vm.ansible` beside `bare_metal.ansible`. Migration reads no operational configuration and creates no pool, and no pool name is special: a fresh site creates its pools from its mounted pool document, or, with none, is seeded at startup from a pool document packaged with the service (`vm-default` and `bare-metal-default`), which an operator may replace or disable. A VM pool may leave its playbook to the service, and every job's playbook is fixed when the job is prepared.

The VM storefront has no inventory tables, CSV import, or local listing-derivation path, and its site-scoped pool overrides are its only per-pool terms. It holds no allocation ledger, resource administration routes, or host identity on the fulfillment path. Fresh databases omit `compute_allocations`, which `kit/site`'s `CapacityReservation` supersedes, and the retired inventory tables. Older databases keep those tables frozen, with nothing reading or writing them, as input an operator may extract into provisioning.

Buyer-access infrastructure is provisioning-owned. A tunnel relay is a resource in the provisioning service, referenced by the pools whose hosts dial it, holding its own rendezvous address, port window, and admission token. The VM storefront names no relay and holds no relay credential: which relay serves a host is a physical fact about where that host is, and a storefront selecting one per request would make a fleet-wide property depend on a commercial caller's configuration.

The committed claim now governs the fulfillment request. A reservation carries its admitted claim -- dimensions and categorical constraints both -- and the scheduler reads it back rather than trusting the request, so a GPU-reserving listing can no longer fulfill without a GPU, and the durable create handle is written by the service that dispatches it. A reservation's release handle has one name, `release_job_id`, on every lease contract and for every offering mode sharing the reservation table.

Sellable capacity is declared in the site authority, across every dimension a resource names — GPUs, vCPU, RAM, disk, or a domain's own units — and host inventory is connection identity only. Operators declare through the registration API or a capacity-definitions document, mounted through the provisioning chart or submitted to its import API. No host write declares capacity or places a host in a pool it does not name: a host's GPU count is descriptive, and was derived into a declaration only once, at upgrade. This is the only operator-facing expression of capacity; the storefront's CSV inventory is retired.

Hosts are placed explicitly: a host names its pool or is unplaced, and a host sells only through a capacity declaration. Host records are used only where a connection is made. The resource-pool projection is built from capacity declarations alone and carries no host connection identity, and execution renders its inventory solely from the registered host record the work names, refusing a host with none. An inventory file seeds the host registry at first boot and is never read at execution.

The VM development scenario runs two storefronts against separate provisioning
authorities. Both derive listings from their respective site projections, and
the scenario covers registry publication, buyer discovery, and negotiations.
This establishes a working two-storefront topology. Multiple storefronts per
site remain outside its scope.

The provisioning service and the site authorities answer a request that matches
no route by what failed to match — 404 for an unknown path, 405 naming the
allowed methods, 400 for an unbindable body resource — and the provisioning
service refuses overlapping route contributions when it composes its table. The
compute family owns its mock mechanism's routes whole, with typed answers and one
typed client, and the worker controls answer typed models. The compute
provisioning contract is major 3: the schedule response names the scheduled
resource's host, bare-metal begin reads the scheduled identity, and a provisioning
service and the storefronts calling it upgrade together.

| Open gap | Owned by |
|---|---|
| The relay path is implemented but unverified on a rented host: reload preservation of live sessions, the port window, teardown release, and relay deletion under live leases remain to be proved or decided | [`relay-vm-access-without-a-dashboard`](../../openspec/changes/relay-vm-access-without-a-dashboard/) |
| Host inventory seeds the host registry only when it is empty and is never reconciled against its file, so editing a running deployment's inventory changes nothing | [`bring-host-inventory-under-definition-documents`](../../openspec/changes/bring-host-inventory-under-definition-documents/) |
| One SSH key reaches every host in an environment, so a host prepared by another party cannot be registered with its own credential | [`contain-embedded-host-key-material`](../../openspec/changes/contain-embedded-host-key-material/) |
| An embedded host credential crosses the operator-to-provisioning hop in plaintext, protected only by the authenticated transport, and `fernet-v1` is one service-held symmetric key. Sealed submission to the service's public key, references to a secret authority, or managed envelope encryption each need only a new protected-value scheme and its codec | Unowned — needs a new change; background in [`bare-metal-mock-provisioned-deal`](../../openspec/changes/archive/2026-10-09-bare-metal-mock-provisioned-deal/) |
| The real runner reports no structured terminal-failure evidence, so the transport, codec, and operator failure patterns classify only mocked failures | Unowned — needs a new change |
| VM guests attach to libvirt's `default` NAT network, one bridge per host with no isolation rule, so guests on one host, including different buyers', share a layer-2 segment | Unowned — needs a new change, with VM's provisioning owner |
| Site admission and scheduling never read a host record's enabled flag, so a create can be admitted and placed on a disabled host and its dispatch retries until an operator re-enables it | Unowned — needs a new change |
| No end-to-end lane runs a relay-backed pool, which is why a relay-backed VM's wrong delivered address went unnoticed | Unowned — needs a new change, beside [`relay-vm-access-without-a-dashboard`](../../openspec/changes/relay-vm-access-without-a-dashboard/) |
| Every provisioning route admits the administrator; whether every other service should take the same stance has not been decided | Unowned — needs a repository-wide decision |
| Under a bare-metal delivery conflict — the site reporting a delivery other than the recorded result — the buyer's teardown answers the 409 `delivery_conflict` refusal instead of ending the lease, since it reads the fulfillment's status first. Whether teardown proceeds past a conflict is undecided | Unowned — needs a new change |
| A concurrent dispatch retry for one owner can end as a false `RelayWindowExhaustedError`: `RelayPortAllocator.allocate_in_session` retries the next port on every `IntegrityError`, including the one an owner's own concurrent allocation raises. Whether it re-reads the owner's lease or refuses as a conflict is undecided | Unowned — needs a new change, with VM's provisioning owner, or whichever change next touches relay allocation |

Dropping the frozen tables is deliberately excluded from the retirement and belongs to a later follow-up, once operators have had a deployment cycle to extract what they need from them.

Reaching hosts and VMs that have no inbound route is not a separate goal. The product already sells VMs on hosts it reaches by tunnel; what the relay and host-key work fixes is that the existing mechanism required a relay to expose a management surface and required the storefront to hold physical facts. Those are defects in how the mechanism was built, and they belong to this goal's consolidation rather than to a capability the product does not yet have.

---

## Goal 2 — Negotiate full compute capability, not GPU count alone

**Value.** This is the difference between a market that sells fixed SKUs and one that sells capacity. Hardware is heterogeneous and buyer requirements are multi-dimensional; negotiating on GPU count alone forces sellers to pre-partition inventory into fixed shapes and forces buyers to over-buy on every dimension they did not need. Supporting the full shape raises fill rate and utilization revenue on hardware the seller already owns.

**Current state.** The lower layers already carry the full shape. The VM domain defines canonical dimensions for GPU count, vCPU count, RAM, and disk, and a family-grouped capability shape (`gpu`, `cpu`, `memory`, `storage`) with a shared, schema-driven flattener into those flat names; the offering mode is a required field on the claim wire, distinct from the site's inventory discriminator; the site authority admits and matches multidimensionally; scheduling fit-checks every requested dimension and treats the dimensions actually scheduled as authoritative; capacity reservations can be resized by supersede rather than mutation; and the Ansible playbooks create VMs with variable shapes.

The top of the stack does not. A buyer that names a resource shape disagreeing with the listing's own shape is rejected outright at negotiation round zero, deliberately and loudly, because no round can carry a shape for seller policy to evaluate and price. Rounds after the first carry only price and escrow terms, with no field for a shape change. Reservation resizing is implemented and has no caller anywhere in the repository.

Publication carries the shape it is given. Every VM listing is a listing shape, stated by the storefront's site-scoped pool override, else by the pool's `listing_shapes` hint, else generated by the VM domain's default. A listing publishes and reserves exactly the quantities its shape declares, and is published only where a source member is feasible for it. A stated shape that declares vCPU, RAM, or disk is therefore found by the registry's existing dimension filters. A pool with no stated shape still publishes the GPU-only default, so a dimension filter excludes it, as the filters' fail-closed semantics intend, rather than advertising a value nothing declared. How many of a shape fit is derived from the site's declarations, never published.

A seller can say which shapes it would sell. A stated shape may bound each quantity inline, as `{offer, min, max}`, and the VM storefront's configured default, `[admissibility.defaults.vm]`, fills the bounds a listing leaves unstated; a site's constraints are advisory input to that storefront policy, and site admission is unchanged. One foundation kit evaluates the policy over whole shapes and answers which values one dimension may take given the rest, never a bare range, so coupled constraints and counter-proposals need no new interface. Publication never advertises an offer the policy excludes: such a listing closes, as does one whose policy cannot be computed, while the pool's other listings publish, and the default generator yields only the GPU counts the default admits. Pool and override writes refuse a list that contradicts itself. Nothing in negotiation evaluates the policy yet, since no round carries a shape.

What is agreed reaches the provisioning request: once a claim is admitted, the reservation is authoritative for it through scheduling and dispatch, and a dimension the listing's shape omits is outside that commitment: fulfillment may supply it from the pool's configured VM defaults or leave it to the provisioning playbook.

A seller can price a shape. Rates are stated per capacity family -- per card-hour for a GPU model, per vCPU-hour, per GiB-hour of memory and of storage -- in an asset, and resolve per family through the site-scoped storefront override, the pool hint, and the configured default; a rate that cannot be read holds the pool rather than falling through. A listing for which any family resolves rates is shape-priced: each settlement option's rate is composed from the listing's own shape through a replaceable, exact aggregator, a family without a rate is not charged, and a listing that would be free is never posted. Every resolved family's rates are recorded on the storefront's listing record, without reaching a registry, so a revised shape can be priced from them. Every other listing keeps its clause's flat rate, unchanged. The seller negotiates from the rate of the option the buyer selected. Negotiation still carries exactly one degree of freedom, a scalar amount moved by the concession middleware, so no seller policy can evaluate a counter-offer that changes RAM or disk — which is why a buyer naming any shape is rejected at round zero, deliberately and with the reason recorded in the guard itself. The seller's own feasibility check compares region and GPU model by equality and checks that the listing's published quantity still fits what its source declares and, for a capacity-backed listing, is free at its site; it never judges a shape a buyer proposes. Nothing consults the authoritative site until a hold is placed at terms acceptance, so an unservable shape surfaces after both parties have committed.

| Open gap | Owned by |
|---|---|
| A buyer cannot discover which shapes a seller would sell, so it learns a listing's admissible range only from refusals | [`publish-shape-bounds`](../../openspec/changes/publish-shape-bounds/) |
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
| The bare-metal contribution serves its own negotiate and listing routes over the kit negotiation runtime, beside the shared shell's routes | [`bare-metal-and-credits-domain-stacks`](../../openspec/changes/bare-metal-and-credits-domain-stacks/) (Goal 4, Section 4a) |
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

The capacity/publication kit owns per-site projection state, event-driven
reconciliation, registry fan-out, publication result recording, and
close/reopen mechanics over injected schema-opaque candidate and binding hooks.
VM and API-credit storefronts compose those runtimes rather than maintaining
local copies, and VM and bare metal each hold one injected projection state,
for both families of every site, that publication, source checks, and status
read; pool-declared offering mode and persisted selected-site binding
remain authoritative through publication and recovery. Bare metal composes the
same capacity and publication seams, the shared watchdog and chain factory, and
selected-site fulfillment, result, and teardown, and has a deployable stack with
its own end-to-end lane, which runs a mock-provisioned deal stage for stage with
VM's. It negotiates through the kit negotiation runtime, as VM and API credits do,
serving its own negotiate and listing routes over it. `kit/policy`,
`kit/identity`, `kit/fulfillment`, `kit/config`, and `kit/alkahest` likewise
carry no domain vocabulary.

The storefront kit also owns the timer-loop lifecycle. Each VM, bare-metal, and
API-credit storefront holds its loops with one kit loop controller, under one
pause and a step per loop served on the same routes, so a scenario can hold and
advance any storefront through the canonical client. The controller is the one
place a cycle runs and records each cycle's outcome, which every storefront's
system status reports; a loop registers as a timer loop or as a fan-out, such as
the per-site capacity-event poller aggregate the capacity kit owns.

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
| The bare-metal storefront serves its own negotiate and listing routes over the kit negotiation runtime rather than the shell's shared routes | [`bare-metal-and-credits-domain-stacks`](../../openspec/changes/bare-metal-and-credits-domain-stacks/) |
| The API-credit lane does not hold and step its storefront's loops, and the storefront has no test that runs the production application | [`apicredits-end-to-end-lane`](../../openspec/changes/apicredits-end-to-end-lane/) |
| Every storefront carries its own route set, executable assembly, and health service | [`kit-owned-storefront-shell`](../../openspec/changes/kit-owned-storefront-shell/) |
| Every storefront reimplements the seller listing lifecycle and restart-safe fulfillment convergence | [`kit-owned-listing-and-fulfillment-lifecycles`](../../openspec/changes/kit-owned-listing-and-fulfillment-lifecycles/) |
| ~~VM keeps its own per-site projection cache~~ — closed: per-site projection state is kit-owned, one injected instance per storefront process holding both families for every site, and VM and bare metal both publish on a loop over it | [`share-site-projection-state`](../../openspec/changes/archive/2026-10-19-share-site-projection-state/) |
| Every storefront carries its own authentication middleware and a persistence client whose boundary with core's is unstated | [`kit-owned-storefront-auth-and-persistence`](../../openspec/changes/kit-owned-storefront-auth-and-persistence/) |
| ~~API credits has no end-to-end lane of its own: its scenario rides the VM lane~~ — closed: each market domain runs in its own pipeline lane, building and composing only its own stack, and the API-credit lane routes its deal's discovery across a compute registry of its own | [`bare-metal-mock-provisioned-deal`](../../openspec/changes/archive/2026-10-09-bare-metal-mock-provisioned-deal/) |
| ~~No bare-metal deal runs in the pipeline: the only complete-deal scenario needs a real host~~ — closed: the bare-metal lane runs a mock-provisioned whole-host deal on the compute deal stages VM's lane runs, from publication through settlement, on-chain evidence publication, lease expiry and release, and a second deal | [`bare-metal-mock-provisioned-deal`](../../openspec/changes/archive/2026-10-09-bare-metal-mock-provisioned-deal/) |
| A negotiation's continuation is resolved against the listing as currently stored in VM and against the opening's in bare metal, so a repriced option ends a VM negotiation that bare metal would continue | Unowned — needs a new change |
| CLI tests replace library names, names a command module imports, or names inside core, rather than the module's own factories | Unowned — needs a new change. A command module's factory functions are its one test seam ([`TESTING.md`](TESTING.md)); the bare-metal buyer CLI has that shape, and every other CLI's tests, and the bare-metal buyer package's older unit test, still patch around it |
| API credits classifies an unknown mechanism with its own predicate rather than the kit's `MechanismReadiness.unknown`; VM's text `settlement status` prints each blocker's code and message but not its kind, which only its JSON carries; API-credit tests leak dotted `settings_overrides` keys; and no test covers a typed-client VM settle after a listing change, contact exchange's blockers beside `disabled`, or API credits' `negotiate` run-log recording and `--from` carry-forward | Unowned — needs a new change |

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
| A lease with no negotiated start begins at commit; a storefront cannot choose to start it on activation, as its own policy with an optional pool hint, which provisioning would carry out in the activation transaction | Unowned — needs a new change, with capacity-reservation pricing. Goal 8's [`renewable-compute-lease-deadlines`](../../openspec/changes/renewable-compute-lease-deadlines/) records the activation instant and an activation deadline at the site and leaves the lease's start at commit; a start-on-activation would be designed against its activation transition |
| The shipped default granted unfunded exclusivity, and framed the safe value as a performance trade | [`default-no-pre-settlement-capacity-hold`](../../openspec/changes/default-no-pre-settlement-capacity-hold/) |

Restoring a non-zero hold default is `billable-capacity-reservations`' own work: the posture above is a denial of capability that this goal exists to buy back.

---

## Goal 6 — Make the settlement mechanism a composed choice

**Value.** Escrow is one way to close a deal, not the definition of one. Charge-first payments and durable introductions serve different commercial agreements. Much capacity trade is arranged person-to-person, where the marketplace supplies discovery, negotiation, and a trustworthy introduction rather than payment custody or provisioning. Mechanism registration keeps shared option/configuration work reusable; each supporting domain composes the selected settlement evidence with its own delivery.

**Current state.** `alkahest.v1` and `arkhai.payments.v1` are peer registrations in VM, bare-metal, and API-credit compositions. Shared configuration owns readiness, publication options, and buyer compatibility, not a universal escrow API. Negotiation emits exact Agreement bytes; the selected settlement stage produces evidence consumed by domain provisioning. Arkhai payments stores the seller-derived mandate in shared negotiation `settlement_data`, approves and polls a deterministic transaction, and gates provisioning or issuance on a verified signed receipt. It creates no settlement plan or obligation and runs no servicing daemon. `fiat.stripe.v1` and its hosted client, funding profiles, setup, and recovery commands are not part of the installed system. Buyers settle an Agreement deal through the typed storefront client's `settle_agreement`, over the settle route contract shared by the client and every storefront's authentication. Agreement attachment is owned by each side: the buyer attaches only by its own `attach_agreement` policy, and a seller whose option sets `deposit_agreement` attaches it before delivering. Refunds are seller-initiated reversals, ordered against delivery start, with an opt-in `refund` failure action; each domain's reconciliation pass converges approved deals a buyer never settles.

Alkahest and `contact-exchange.v1` retain the shared obligation journal and escrow-oriented carriers. A third mechanism now exists: `contact-exchange.v1` completes a deal by durable, authenticated introduction — rateless options, a scalar-declining registration, one non-financial obligation, a persisted reveal surface (`/api/v1/introductions`), and a loose-listing discovery profile — composed end-to-end on bare metal and VM. Interpreting a domain's accepted state for it, including the re-derivation of the obligation reference a reveal names, lives once in the mechanism kit; a composing storefront supplies only its persistence reads, configuration, and route bindings. The buyer's introduction commands are the mechanism's own, mounted by each domain buyer. A seller's default negotiation policy accepts an exact selection of an option that bargains no amount, so an introduction reaches acceptance on the published terms instead of being countered by a policy waiting for an amount it never carries. All three storefront domains now dispatch exact-selection acceptance through the registration's accepted-obligation builder with no per-mechanism arm: the mechanism resolves once from the selection, rate arithmetic (duration-scaled and counted-unit alike) lives inside the mechanism, and each domain keeps only its own service terms and scaling input. Scalar participation is a declinable registration capability carried to counterparties through the option shape. Core carries public options, accepted Agreements, immutable role-stage tables and opaque seller evidence. Agreement-selected entries own revalidation and continuations; common VM/bare-metal delivery and credit issuance consume validated facts without concrete-mechanism switches. Buyer recovery retains exact accepted inputs and opaque references, not seller SettlementEvidence. Domain evidence/progress records are separate from genuine escrow servicing.

An Alkahest deal settles against the plan committed at acceptance in VM, bare metal, and API credits, so a seller changing its release policy, wallet, or listing after acceptance cannot block a correctly funded escrow. What an Agreement and its listing determine each party derives for itself: the accept reply carries no escrow terms, and a buyer funds only the escrow it derives from its acceptance and the listing, held to the seller's plan before funding on every path, resume included. An escrow proposal naming no escrow contract is refused. An Alkahest section that parses but cannot settle — no oracle, an oracle equal to the wallet, no wallet, no chains, an undeliverable release model — makes Alkahest unready rather than stopping the storefront, so its options are not published; every readiness blocker states whether it is a configuration or a reachability blocker, and a `kit/alkahest` chain probe, a loop each storefront registers, supplies reachability.

Each recipient can deliver its revealed introduction: each side hands its own copy of the reveal to sinks its operator configured locally, through an installed-plugin contract that grows a destination by installing a package rather than editing the marketplace. `kit/delivery` owns a mechanism-neutral event, the sink protocol, discovery, and four protocol-thin built-ins (file, local program, webhook, mail); the seller dispatches off the reveal's critical path from the introduction route service, the buyer dispatches inline after printing. Seller-side dispatch is the delivery kit's, shared by every composing storefront; sinks are named instances of installed sinks, routed by the origin site of the listing a deal came from; a webhook can sign its request with the storefront's marketplace signer; and an installable Apprise sink reaches the services Apprise supports. A storefront's deployment schema types each installed sink's settings by discovery, so its secret settings stay out of public configuration. Delivery is never authoritative — the durable, re-readable reveal is what makes best-effort delivery safe — and the mechanism kit gained no delivery dependency, because its dispatch is injected. Every storefront composing contact exchange delivers, routed per origin.

Revealed contacts are now kept for a bounded window. A storefront sets `retention_seconds` in its contact settlement section, 30 days by default or `indefinite`, as an aggregate policy that also applies to introductions revealed before a change to it. Deletion redacts both payloads in place and leaves a tombstone, which database triggers keep one-way, so the deal and its obligation record survive and a deleted introduction can never be revealed or delivered again. One deletion operation in `kit/contact-exchange` serves a held-and-stepped sweep and an operator deleting one introduction early, and the window is disclosed on the public readiness projection, before a buyer commits a contact, and again at reveal. Bare metal composes all of it; the bare-metal lane carries the first introduction scenario.

Current limits: escrow claimant, expiration, and condition fields remain in existing core carriers, and `kit/settlement-runtime` remains shared by Alkahest and contact exchange. Moving those escrow semantics fully into Alkahest is a separate refactor. The `escrows` table and the `/api/v1/settle/{escrow_uid}` route family remain the Alkahest mechanism surface (retirement needs deployment evidence), and pre-plan legacy escrow rows keep only their mechanism-surface identity. Payment evidence and delivery/issuance progress no longer occupy escrow rows.

| Open gap | Owned by |
|---|---|
| Live Arkhai payment and domain delivery qualification | The payments service's end-to-end tests, which import this repository's published packages; this repository's payment scenario runs only against a configured target |
| ~~An escrow proposal naming no contract is priced, in every compute domain, from the listing's first accepted escrow; which escrow prices it, or whether it is refused, is undecided~~ — closed: such a proposal is refused, by the escrow-shape guard and at `kit/alkahest`'s materialization chokepoint whatever policies ran, and nothing prices one | [`unbacked-bare-metal-listings`](../../openspec/changes/archive/2026-10-27-unbacked-bare-metal-listings/) |
| An API-credit listing's options are fixed at creation, so an unready mechanism's option stays advertised until the seller closes it | Unowned — needs a new change. Deals accepted on such a listing verify against their committed plan and settle as before; API credits has no re-deriving publication path |
| Post-commitment lifecycle: early ends, per-deal dispute authorities with per-case hold extensions, and kept evidence | [`agreed-evidence-and-early-termination`](../../openspec/changes/agreed-evidence-and-early-termination/), the foundation of Goal 8 |
| A seller cannot receive Alkahest settlement at an account other than its signing key, such as a multisig or treasury: the published recipient is the wallet address, the fulfillment attestation names the account that submits it, and refunds are sent from the signing account. Alkahest's model can express a separate recipient; the storefronts would need a payout setting, attestations naming it, and refunds from or gated on it | Unowned — needs a new change |
| A wallet key `kit/alkahest` cannot parse is read as present: beside a configured address no mismatch is judged, and without one readiness reports the address missing rather than the key. No readiness blocker names an unreadable key | Unowned — needs a new change |
| Isolate escrow carriers and the conditional-escrow port fully within Alkahest | [`move-escrow-into-alkahest`](../../openspec/changes/move-escrow-into-alkahest/) |
| Escrow fields in listing, registry and storefront-client wire formats | [`drop-escrow-from-shared-wire`](../../openspec/changes/drop-escrow-from-shared-wire/) |
| Recorded responses kept for exact retry — every introduction reveal and read included — are never bounded, so a revealed contact outlives the introduction retention window there. The disclosure is scoped to the introduction record accordingly | [`redesign-authenticated-requests`](../../openspec/changes/redesign-authenticated-requests/), which redesigns replay state for every authority; [`retain-authenticated-request-outcomes`](../../openspec/changes/retain-authenticated-request-outcomes/) is blocked on it |
| A second delivery event producer (a settled charge, a completed escrow) | Unowned — needs a new change. Delivery sinks are event-driven and non-authoritative: a sink consumes a durable delivery event and re-delivery reads the persisted reveal, so a second producer adds an event source, not a second delivery path. A storefront with more than one origin refuses seller-side sinks unless an origin routing table is configured, unconditionally rather than per event kind, because introductions are the only events today; a second producer should revisit whether its events are origin-scoped and whether that refusal should follow the event rather than the sink set |

Deals paid per period until stopped, over Arkhai payments' rate parts, are no longer this goal's: they are the settlement half of Goal 8, which owns the mechanics in both compute domains.

---

## Goal 8 — Sell compute by the period until either party stops

**Value.** Buyers get the two products that make up most compute demand outside committed offtake: **on-demand** — the compute now, for as long as they want it, paid per hour from a prepaid balance and stopped whenever they choose, up to a date the seller sets that may be days or years away — and **spot** — the same at the lowest price, on the understanding the seller may take it back on notice. Sellers get to sell idle capacity without a buyer committing to a term, to keep the right to withdraw hardware for maintenance or failure, and to price the two products separately from one pool. Both rest on the post-commitment lifecycle: each deal states which ends its terms entitle, names a dispute authority, and keeps earnings held through a dispute window, so that a buyer's protection against a seller who fails or misbehaves is its own stop at the payment authority and a case over held money, not the seller's software. Both are built in full and switched on by one small change once the payments contract revision with per-part authorities and hold extensions is deployed on the hosted service.

What lands before the switch is on, and is worth having on its own: a VM buyer can end delivery, and bare metal's buyer does it through the canonical client, with the end backed by the buyer's own stop or a case; every compute deal records who ended it and why, and the site signs a report of an end the moment it intends one; a seller that learns of an end its terms do not entitle files a dispute against itself, so an honest seller returns what it did not earn without the buyer filing; a lease the storefront abandons before delivery expires at the site instead of holding capacity to its agreed end; both compute domains deliver through one path with one window; and every payment and dispute scenario runs in the pipeline against in-lane doubles of the payments service and the dispute authority instead of skipping.

Demand arrives through Arkhai payments on fiat rails: a prepaid balance the service funds through Stripe and reserves from one period ahead, with the deal stopping when the balance cannot reserve the next period or when either party stops it. Postpaid monthly invoicing — usage accrued, invoiced, and collected later — is deliberately outside this goal; it needs a payments-service contract that does not exist and must not be mistaken for prepaid rate parts. On-chain settlement of an open-ended deal is outside it too: an escrow is sized to a duration, and a streaming primitive Alkahest lacks would be needed first.

**Current state.** The site expires leases by the clock and ends one early through one path; bare metal's buyer can end a running lease through a domain route. The payments contract revision this goal needs is published: per-part authorities with stop notice, per-part ends, holds that release a set time after a part stops, per-part hold extensions, and per-part snapshots. Nothing above those foundations uses them: every layer requires a buyer-named duration, amounts are totals, the payments kit derives one `once` part per deal and has no `start` or `stop`, no storefront watches a transaction after delivery, a VM buyer cannot end a lease, no deal names a dispute authority, the one seller interrupt route is Alkahest's and looks reservations up by an identity negotiated deals do not record, no listing can say how a deal is billed or whether the seller may take it back, and every payment scenario skips for want of a target.

The changes, in the order they land; each design holds the decisions and their reasoning, and each row says what its closeout must show:

| Open gap | Owned by | Its closeout shows |
|---|---|---|
| A committed deal has no early ends, no dispute authority and no kept evidence; a VM buyer cannot end a lease, bare metal's teardown is outside the canonical client, and ends lack attributed causes and a site-signed report returned to the buyer | [`agreed-evidence-and-early-termination`](../../openspec/changes/agreed-evidence-and-early-termination/) | both buyer paths ending delivery, backed by a stop or a case; ends attributed; the signed site report retrieved; cases filed and held per part; a seller's self-filed end |
| Payment scenarios skip without a target, and hostile payment and dispute-authority cases cannot be driven deterministically | [`add-arkhai-payments-lane-double`](../../openspec/changes/add-arkhai-payments-lane-double/) | the existing payment scenarios running against isolated HTTP payment and mediation doubles, with signed records, controllable failures and published or proposed evidence attribution |
| No listing can say how a deal is billed or whether the seller may end it; the buyer CLIs require a duration; the Agreement's price has no stated unit | [`negotiate-open-ended-compute-terms`](../../openspec/changes/negotiate-open-ended-compute-terms/) | per-period and spot options published, and refused at every door where servicing is undeclared |
| A buyer cannot find a per-period or preemptible option or the seller's bounds | [`discover-open-ended-compute-listings`](../../openspec/changes/discover-open-ended-compute-listings/) | the registry filters and `--class` finding them |
| The payments kit derives only `once` parts and has no rate-part lifecycle calls; a seller cannot preempt under the terms the buyer accepted | [`spot-deals-through-arkhai-payments`](../../openspec/changes/spot-deals-through-arkhai-payments/) | a rate part and setup part derived in both domains, every operation proven against the double, a spot deal preempted with notice, a rotation re-anchored |
| A storefront lost between capacity commit and delivery holds capacity until the agreed end | [`renewable-compute-lease-deadlines`](../../openspec/changes/renewable-compute-lease-deadlines/) | the site's suite: activation racing expiry in both orders, idempotent activation, an activation deadline lapsing |
| The two domains deliver through different code with different windows, and nothing activates a lease after delivery | [`unify-compute-delivery-path`](../../openspec/changes/unify-compute-delivery-path/) | both domains on one path; a deal activated to its agreed end; an undelivered deal handed to end service's self-filing |
| No storefront services a running rate part: nothing watches a transaction after approval, and physical and payment work after an end are not tracked apart | [`converge-ongoing-compute-leases`](../../openspec/changes/converge-ongoing-compute-leases/) | the nine scenarios in both lanes against the doubles |
| The product is dark until the payments contract revision is deployed on the hosted service | [`activate-per-period-compute-servicing`](../../openspec/changes/activate-per-period-compute-servicing/) — blocked on the deployment | every per-period scenario as live evidence |

**Done when** `activate-per-period-compute-servicing` closes out: per-period servicing declared in both compute compositions against the deployed contract, every per-period scenario recorded as live evidence, and the scenario diagrams promoted.

**Accepted limitations**, each stated with its bound by the change that owns it: a buyer whose stop or case the authorities never receive is protected only by the evidence it kept, ruled after the fact; a seller serves unpaid between a buyer's stop and its own reaction, bounded by the buyer's notice period, which the seller prices; a seller collects a running deal's earnings only after the part's stop plus the dispute window; a storefront that is absent after activation leaves the lease running to its agreed end, with the buyer's stop as the buyer's lever; and an Arkhai dispute authority whose address or signing key changes mid-deal is not followed.

Work this goal found and leaves unowned:

| Item | Status |
|---|---|
| Renewal of an active site lease, with a lapse policy, so a site bounds its exposure to a storefront that has gone | Deferred in [`renewable-compute-lease-deadlines`](../../openspec/changes/renewable-compute-lease-deadlines/) as the seller's own choice; revisit when a site operator separate from the storefront operator needs it. Without a billing horizon, reclaiming costs the buyer a working VM and the storefront's honest recovery is a self-penalty |
| Pooled funding: one balance behind several leases | Unowned — the payments service would own a per-transaction funded figure from a shared balance |
| A storefront–site liability ledger, once a site and a storefront are not one business | Unowned — the storefront holds the site's money today, which makes it unnecessary for now |
| The VM admin interrupt route looks reservations up by `escrow_uid`, which negotiated VM deals do not record, and never submits the splitter declaration it announces | Unowned — Alkahest's, beside [`automate-seller-spot`](../../openspec/changes/automate-seller-spot/) |
| A stated cancellation term for a buyer leaving a reserved deal early | Unowned — the consequence today is the mechanism's: a prepaid part is forfeited and a refund stays seller-initiated |
| A true minimum spend at the payments service, so a short deal pays at least a stated amount rather than a setup fee beside usage | Unowned — revisit if buyers balk at setup fees or churn measurably costs sellers; sellers may also refuse churning buyers in negotiation policy |
| Automatic rulings for a buyer's case backed by a seller-signed record of the end | Unowned — little value while the seller files its own ends; revisit with the managed metering gateway, which gathers its own evidence |

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

---

## Completed goals

A goal moves here when its last open gap closes. Its current state is kept as it stood at completion, so a reader can see what the goal delivered and what it deliberately left unowned; the system as it is now is described by `ARCHITECTURE.md` and the capability specifications, which are kept current.

### Goal 7 — Sell capacity the marketplace cannot admit against

**Completed 2026-10-27**, when [`unbacked-bare-metal-listings`](../../openspec/changes/archive/2026-10-27-unbacked-bare-metal-listings/) closed its last open gap. The text below describes the goal as it stood then; work it left unowned is listed in its closing paragraphs.

**Value.** A large share of real capacity trade is arranged directly between the parties, on terms too exotic to parametrize and with no escrow, payment custody, or automated provisioning anywhere in the deal. The marketplace's value there is discovery and a trustworthy introduction. Without an explicit notion of backing such a seller could not list at all: every listing had to name a trusted site and an admissible source, so a seller with nothing to admit against had to either fabricate an authority that admits forever — a value the admission, commit, release, and restart-recovery paths would then trust — or stay out of the market.

Making backing an explicit property is what lets that seller in without weakening the promise for everyone else. A listing that claims admissible capacity still gets every check it gets today; a listing that claims nothing gets none, because there is nothing to check. The gain is supply-side: a seller who will not integrate escrow or hand over SSH credentials can still be discovered, and a buyer gets one catalogue to compare rates across both kinds of supply.

The same property serves market families with no physical supply behind them at all, which is where the qualifier originated. Nothing about it is compute-specific.

Bare metal is this goal's primary target domain: supply arranged directly between the parties is overwhelmingly whole machines. VM and bare metal reach the goal through the same kit mechanisms — publication runtime, declaration reader, capability shapes, pool overrides, and introduction composition — rather than each solving it separately.

**Current state.** Backing is a property of both pools and listings. A Resource Pool declares whether it is capacity-backed and which offering modes its listings may advertise, separately from the modes its provider can deliver. A listing records its backing on its immutable binding, derived from that declaration, and its origin site is kept distinct from any admission authority; [`ARCHITECTURE.md`](ARCHITECTURE.md) defines both. What backing means is decided in one place: every decision that differs between backed and unbacked supply — admitting a capacity effect, placing a hold, judging availability, which listings availability reconciliation touches, and which settlement options a listing keeps — belongs to one backing delegate the declared label selects, and VM, bare metal, and API credits ask it rather than branching on the label. Every capacity effect passes one guarded boundary in the publication kit, and a listing's backing is compared with its source's before anything else, so supply that changes backing closes its listing for good. The compute registry schema publishes each listing's backing with an exact filter, so a buyer can exclude supply nothing stands behind.

Settlement by introduction is a working mechanism with rateless options, a durable authenticated reveal, and delivery to each side, so the settlement half of an out-of-band deal already exists, and so does the unbacked listing shape it attaches to. VM composes introduction, so an unbacked VM listing publishes an introduction option and settles by it; the seller's contact is resolved from the listing's origin site, so one storefront publishing for several seller sites reveals each deal's own seller. Bare metal composes introduction too and publishes unbacked listings from unbacked pools through the same kit runtime, binding, and reconciliation as VM, so an unbacked bare-metal listing publishes an introduction option and settles by it. A deal settled by introduction has no settlement or fulfillment in either domain: its settle request and bare metal's fulfillment routes refuse it, deciding by the accepted stage's own declaration. Bare metal's backed deal runs on every pipeline run too: the bare-metal lane publishes a whole host, negotiates and settles it through Alkahest, delivers it through a mock-provisioned site, and releases it at expiry and at teardown, on the compute deal stages VM's lane runs.

An unbacked pool — one that declares no deliverable mode, and so is kept out of every capacity path — advertises modes on its own declaration, naming a configuration-free provider rather than fabricated configuration, and a capacity declaration with no host behind it reaches storefronts through the resource-pool projection. A storefront now publishes on its own from the projections of the sites it trusts: it derives listings from every advertisable pool, refreshes their terms, closes those whose source no longer supports them, and keeps each registry converged on its listings' status, with a seller's close durable against every reconciliation. An unbacked listing is never admitted against and publishes only settlement options its domain does not fulfil through capacity. The VM storefront composes contact exchange, which it does not fulfil through capacity, so an unbacked VM listing publishes an introduction option and settles by it. Bare-metal publication runs on its own, as a timer loop over the site projections the storefront holds, so a withdrawn pool's listings close without an operator's command; it reads pool declarations through the shared reader and publishes through the kit runtime. It records listings locally before registry publication, converges registry state, and holds listings when their site's projection is not held. Its opening recheck reads the held projection too, so an opening does not depend on its site being reachable, and it confirms a listing only from a generation polled within the storefront's confirmation window. Bare metal derives listings from every enabled pool advertising `bare_metal`, whatever its backing, and asks the backing delegate every backing question, as VM does. Which fields commit the marketplace to delivering something — a bare-metal listing's host identity, physical host identity, and access methods — is the delegate's decision too: a backed listing carries every one and an unbacked listing none, even where its declaration names a host, and the storefront refuses a site's generation whose view contradicts its pool's backing. An unbacked listing's opening recheck reads only its declaration in the held projection, never availability. A compute candidate with no settlement option yields no listing: an open one closes when the storefront's configuration rules out every mechanism it could publish, and is held while any of them cannot be reached. A bare-metal listing's shape is derived from its Physical Resource's declaration through the compute-family schema both compute domains share. It is published under the same top-level fields as a VM listing's, with its pool's region, so a buyer filtering compute supply by GPU model, count, region, or any other dimension finds whole machines and VM slices alike. A compute listing can publish its seller's asking rate for its shape: an exact decimal amount, the asset it is quoted in, and the period it is quoted per. It is a listing attribute rather than a settlement option rate, so supply that settles by introduction, whose options are rateless by design, can carry one too. A site declares rates per shape on its pools, and a storefront's per-site override has final authority over them for VM and bare metal alike; no configuration default supplies one. A buyer bounds a query by rate in a named asset and period, compared exactly, and a listing publishing no rate is excluded from such a query. Comparing unbacked supply on rate in a running stack is proven in both domains: each domain's introduction scenario finds its backed and unbacked listings with one rate-bounded query, and leaves out a listing publishing no rate.

The hint that governs how many candidates a pool yields is named `listing_cardinality_mode`, and its scope is stated normatively, so a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. The earlier name read as though it governed how a pool is listed generally, and that ambiguity had already produced a proposal to encode backing or settlement inside the hint, which would have coupled inventory declaration to settlement mechanism.

| Open gap | Owned by |
|---|---|
| ~~Four names refer to the offering mode and `offer` refers to three different things~~ — closed: the offering mode is `offering_mode` on every surface, a seller's published shape is `listing_resource`, and `offer` means a negotiation message | [`settle-listing-vocabulary`](../../openspec/changes/archive/2026-09-15-settle-listing-vocabulary/) |
| ~~Bare-metal listings form no capability shape and publish their hardware where the compute schema's filters cannot see it~~ — closed: a bare-metal listing's shape is derived from its declaration through the shared compute-family schema and published where the compute filters read it | [`bare-metal-listing-shapes`](../../openspec/changes/archive/2026-09-27-bare-metal-listing-shapes/) |
| ~~Bare metal, the primary target domain, cannot publish an unbacked listing~~ — closed: bare metal publishes unbacked listings from unbacked pools through the same kit runtime and backing delegate as VM, carrying no delivery terms, and settles them by introduction | [`unbacked-bare-metal-listings`](../../openspec/changes/archive/2026-10-27-unbacked-bare-metal-listings/) |
| ~~A seller price is published only inside settlement carriers and no filter reads a rate value, so supply cannot be compared on rate~~ — closed: a listing publishes an asking rate per shape, declared by its site and overridable by its storefront, and buyers filter on it exactly | [`publish-indicative-listing-rates`](../../openspec/changes/archive/2026-10-01-publish-indicative-listing-rates/) |

The published rate is one number per listing shape, not a per-dimension structure. A seller pricing RAM and GPUs differently cannot express that, and a buyer comparing two listings that bundle different RAM is comparing bundled prices — an accepted limitation for this goal. Unbundling is per-family rates, from [`capacity-shape-pricing`](../../openspec/changes/archive/2026-10-01-capacity-shape-pricing/), which let a seller price a shape a buyer proposes during negotiation; that is a different surface from a published asking price, and this goal does not wait on it.

This goal is not complete on a queryable listing alone. Its value statement is discovery *and* a trustworthy introduction, so closing it requires a release-qualified business scenario in which unbacked discovery reaches a usable introduction. For VM that scenario runs in the VM end-to-end lane and against a local Helm release: backed and unbacked VM listings are found by one rate-bounded query, and the unbacked one is negotiated, revealed through the buyer CLI, and delivered to both sides. For bare metal, the primary target, it runs in the bare-metal end-to-end lane as `e2e_bare_metal_unbacked_introduction`, on the same introduction stages as VM's: backed and unbacked bare-metal listings are found by one rate-bounded query, a `capacity_backing=unbacked` query returns only the unbacked one, which publishes no host fields and only an introduction option, and it is negotiated, revealed through the buyer CLI, and delivered to both sides, with no fulfillment.

The multi-seller shape this goal requires is in place in both domains: the seller's contact is resolved per listing origin, never from one storefront-wide value, and seller-side delivery is routed per origin. In the topology supported today — one registry with several storefronts, each holding its own site — every storefront reveals its own seller's contact by construction. One storefront serving several seller sites is not supported and is not yet a goal, so the live scenario for that shape is recorded as unowned in the [change index](../../openspec/changes/README.md), and this goal closes without it.

Finite unbacked listings, and payment settlement over them, are anticipated and unowned. They are the reason backing is modelled as a listing property rather than as a domain: a seller's supply becomes capacity-backed later without a new domain, a new registry, or a migration unwinding a fabricated site. Backing itself is immutable per durable listing — an unbacked listing does not become backed, it closes and a backed one is published in its place — because moving from no admission guarantee to a named authority is a material provenance change a buyer holding a listing reference should not have happen underneath them.

Two consequences of this posture are accepted rather than solved. Nothing keeps a listed rate current or honest, since a seller pays nothing to advertise one they will not honour; the intended control is registry curation, which sits outside the registry service boundary and is not implemented here. And an unbacked listing cannot be exhausted, which closes capacity-exhaustion abuse but not abuse of whatever the settlement mechanism reveals.

---

## Related documents

- [`ARCHITECTURE.md`](ARCHITECTURE.md) — the current system and its boundaries.
- [`openspec/changes/README.md`](../../openspec/changes/README.md) — delivery campaigns, readiness, and blocking.
- [`openspec/specs/README.md`](../../openspec/specs/README.md) — the normative contract for each capability.
