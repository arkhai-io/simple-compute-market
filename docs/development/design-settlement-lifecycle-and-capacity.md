# Settlement lifecycles + shared capacity — design + scope

Companion to `design-market-core-extraction.md`. That doc reorganizes
existing behavior (the core/kit/domain extraction); this doc plans the
behavior the reorganization should leave room for:

1. **Settlement as a lifecycle, not an event** — asynchronous arbiters,
   composed microconditions, heartbeat-gated collection, multi-escrow
   plans.
2. **Shared underlying capacity** — one hardware pool selling through
   multiple market domains (raw VMs, inference, …), multiple sites
   aggregating under one storefront, and the service topology that makes
   both safe.

The two parts interlock at one joint: the settlement lifecycle decides
when a deal ends, and the capacity layer must learn that to release the
allocation. They are otherwise independently landable.

Decisions recorded here (rationale in the body):

- The buyer executable is core-owned with schema plugins; storefront
  executables are domain-owned, one process per market domain; the
  registry stays core + schema config. (Recorded in the extraction doc's
  "Packaging decisions"; restated here only as context.)
- `Terms` generalizes to a **settlement plan**; the buyer pipeline gains
  a third phase: `discover → negotiate → settle → service`.
- The plan carrier is **settlement-mechanism-neutral**: lifecycle
  universals (payer/claimant, amount/asset, expiration, conditions) as
  typed fields, everything mechanism-specific behind a
  `{mechanism, params}` envelope interpreted by kit codecs. Alkahest is
  the first mechanism, not the structural assumption; fiat escrow is
  the second (already customer-requested).
- The authoritative capacity ledger moves out of the storefront into a
  per-site **site authority**; storefronts keep a market-domain
  **aggregation view**. Executors become stateless workers behind the
  ledger.
- Notifications split into **deal-scoped events** (point-to-point, to
  the deal's owning storefront) and **capacity-scoped events**
  (pub/sub, anonymous versioned deltas to all subscribed storefronts).

## Part I — Settlement lifecycles

### Background: arbiters are microconditions

Alkahest escrow demands are arbiter trees
(`~/dev/arkhai/alkahest/contracts/src/arbiters/`):

- `attestation-properties/RecipientArbiter.sol` — synchronous: checks a
  property of the fulfillment attestation; collection can succeed in the
  same transaction flow that created the fulfillment. This is the only
  arbiter the current policies know, which is why the whole flow assumes
  immediate settlement.
- `TrustedOracleArbiter.sol` — asynchronous: `checkObligation` returns
  whatever the named oracle last `arbitrate()`d for the
  `(obligation, demand)` key. Collection is impossible until an
  off-chain actor acts, possibly long after fulfillment, possibly
  repeatedly (per interval).
- `logical/AllArbiter.sol` — conjunction: demand is
  `{address[] arbiters, bytes[] demands}`; the obligation passes only
  when every microcondition passes.

The code already touches this surface:
`domains/vms/settlement/fulfillment.py::submit_compute_fulfillment`
submits the fulfillment obligation and then calls
`client.oracle.request_arbitration(...)` — but it is fire-and-forget.
Nothing watches `ArbitrationMade`, retries collection, tracks which
conditions are pending, or reacts when a condition flips false. That is
the gap this part closes.

Example lifecycles in scope:

- **Heartbeat-gated collection:** the buyer sends signed heartbeats to
  the seller while the service is healthy; the seller bundles them as
  evidence to an oracle, which `arbitrate()`s true; the seller then
  collects. Missing heartbeats ⇒ the seller cannot collect (and should
  treat the deal as ending).
- **Interval escrows:** one negotiated transaction materializes as N
  escrows, one per service interval; the seller collects each interval
  as it is earned.
- **Penalty bonds:** the seller posts a bond the buyer can claim on
  seller failure — an escrow whose claimant is the counterparty.

### `Terms` becomes a settlement plan

Today `Terms` materializes to one escrow collected once. The general
carrier is a **plan**:

- a set of obligations (escrows/bonds), each with: payer, claimant,
  amount/asset, expiration, a condition set, and a **settlement
  mechanism tag with opaque mechanism params**;
- the off-chain obligations each party takes on: heartbeat cadence and
  schema, oracle identity, evidence format, interval boundaries.

**The plan carrier is mechanism-neutral by construction.** Alkahest
must not be the only structurally supported settlement mechanism —
fiat escrow is already requested by customers, and it follows the same
lifecycle (payer/claimant, amount, expiration, conditions gate
collect-vs-reclaim) with a different identifier scheme and different
verification semantics: provider + account/payment refs instead of
chain id + contract address, and "the provider object satisfies the
agreed terms" (an adapter call against the provider API) instead of
byte-compare against a chain read, because a fiat materialization
creates a provider-side object whose id is generated, not derivable.
The trust model also shifts — the chain is a neutral arbiter, a
payment provider is a trusted third party — which changes how penalty
bonds and heartbeat-gated collection cash out, but not the engine's
shape. So the carrier keeps only the lifecycle universals as typed
fields and pushes everything mechanism-specific into a
`{mechanism, params}` envelope whose deterministic interpretation
lives in kit codecs — the same pattern as the `ProvisionTerms`
`{kind, payload}` envelope. `kit/alkahest` is the first codec; a
`kit/fiat-<provider>` package is the second, with no further carrier
surgery. The current flat alkahest shapes (`EscrowTerms` mirroring
`doObligation`, `EscrowProposal`/`AcceptedEscrow` keyed on
`(chain_name, escrow_address)`) become a marked legacy coercion into
the envelope, exactly like the flat compute provision terms.

The determinism contract extends unchanged in kind: both sides must
derive the same *plan* from the shared message history, not just the
same single escrow — for mechanisms whose materialization is not
independently derivable (fiat), determinism covers the agreed terms,
and verification of the materialized object against those terms is the
mechanism codec's job. Negotiation vocabulary for proposing/accepting
plan shapes (intervals, bond sizes, oracle choice, *mechanism choice*)
is schema policy, exactly like price; a listing's accepted-escrows set
generalizes to advertising accepted settlement mechanisms.

### `Receipt` is not terminal: deal servicing engines

Each side needs a long-running, persistent, restartable engine — the
same animal as the lease watchdog, but for money:

| Side   | Engine            | Responsibilities                                                                                                                                                          |
| ------ | ----------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Seller | claims agent      | per interval: submit fulfillment attestations, gather/verify buyer heartbeats, request arbitration, watch `ArbitrationMade`, collect when the condition tree goes true, claim penalty bonds on buyer default, escalate/stop service on non-payment |
| Buyer  | heartbeat + watch | emit signed heartbeats while the service is healthy, stop when it is not, reclaim uncollected/expired escrows, claim the seller's bond on seller failure                   |

**Degenerate case = current behavior.** A RecipientArbiter-only deal is
a plan with one escrow whose condition is immediately true; servicing
collapses to a single collect. The current flow becomes the trivial
instance of the engine, not a parallel code path.

### Heartbeat transport

Heartbeats are off-chain signed messages from buyer to seller. The
natural transport is a new authenticated storefront endpoint (e.g.
`POST /deals/{id}/heartbeat`): `core_storefront.auth` already does
framework-free signed-request verification, so the endpoint shell,
persistence, and replay protection are core mechanics; what a heartbeat
attests and how evidence bundles are built/verified is domain policy.
The seller persists heartbeats as evidence; the oracle verifies bundles
and calls `arbitrate()`. Oracle interaction lives in kit.

**The oracle must be a party that doesn't benefit from the decision** —
in practice a third party. A seller-operated oracle gates nothing (the
collector authorizes its own collection); a buyer-operated oracle is a
unilateral payment hold-up. Party-operated verification only works in
shapes where the chain itself checks the evidence — see the
heartbeat-verification alternatives under work item 5.

### Filing (core / kit / domain)

Same filing test as the extraction doc: core requires the hook, below
implements it.

| Layer         | Owns                                                                                                                                                                       |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| core          | the lifecycle engine mechanics: deal → obligations → conditions → claims as a persisted state machine; scheduling/retry; event subscription points; the `service` phase contract and its injection points. Drives injected per-mechanism `materialize`/`check conditions`/`collect`/`reclaim` hooks and never learns which mechanism it is driving. Same altitude as `negotiation_sync`/`stage_log` — mechanics, no vocabulary. |
| kit (one package per settlement mechanism) | `kit/alkahest` is the first mechanism codec: arbiter demand-tree codec (AllArbiter `DemandData` encode/decode), `TrustedOracleArbiter` interaction (`arbitrate`, `requestArbitration`, `ArbitrationMade`/`ArbitrationRequested` watching), collection/reclaim call primitives, byte-compare verification. A future `kit/fiat-<provider>` is the second: payment-intent/hold materialization, provider-API condition checks and terms verification, capture/payout vs refund primitives. |
| domains/vms   | which conditions a VM lease uses; heartbeat schema and verification; interval/bond split policy; oracle/mechanism selection; evidence bundle construction                                                                                                                    |

### Pipeline: a third phase

By the extraction doc's merge-vs-separate test, servicing is a separate
phase, not a fattening of `settle`: core machinery (persistence,
scheduling, chain watching) sits in the gap between "escrows
materialized" and "funds collected." The buyer pipeline becomes

```
listings = discover(query)
terms    = aggregate(negotiate, listings)
plan     = settle(terms)         # materialize escrows/bonds
receipt  = service(plan)         # drive obligations + claims to completion
```

`settle` returns the active plan; `service` consumes it and is the
long-running part. The seller side mirrors this behind the storefront:
fulfillment submission (today's
`domains/vms/settlement/fulfillment.py`) becomes the first step of the
claims agent rather than the last step of settlement.

### Coupling to capacity

Non-payment ends the deal early: heartbeats stop, collection fails, the
claims agent decides the deal is over. The *deal lifecycle*, not a fixed
`lease_end_utc`, is what should drive capacity release — the storefront
asks the site authority (Part II) to truncate the lease, which takes the
normal teardown path. Until the site authority exists, the same call
lands on the storefront's local allocation tables; the seam is the
callable, so Part I does not block on Part II.

### Work items

1. **Plan carrier.** Done for the single-mechanism case:
   `market_core.schemas.SettlementObligation`/`SettlementPlan` carry
   the lifecycle universals as typed fields plus the
   `{mechanism, params}` envelope, with the flat `EscrowTerms` shapes
   surviving as marked legacy coercions (the ProvisionTerms pattern);
   `kit/alkahest/plans.py` is the first mechanism codec (structural
   carrier mirror, envelope↔terms converters, deterministic plan
   materialization); the `/negotiate/*` responses, seller artifacts,
   buyer outcome, deal context, and run-log all carry
   `settlement_plan`, with the flat terms list kept as a legacy wire
   mirror that leaves with the client-wheel wire bump. Still open
   under this item: the proposal/listing vocabulary
   (`EscrowProposal`/`AcceptedEscrow` still key on
   `(chain_name, escrow_address)`; a listing's accepted-escrows set
   has not yet generalized to advertising accepted mechanisms) — that
   churn rides whichever lifecycle policy first needs a second
   mechanism or plan shape proposed in-band (I.5).
2. **kit/alkahest codecs.** Done: `market_alkahest.claims` adds
   TrustedOracleArbiter and AllArbiter codecs to the arbiter registry
   (explicit demand_data, both directions), oracle wrappers
   (`request_arbitration`, oracle-side `arbitrate`, and a
   timeout-bounded `arbitration_status` probe over the SDK's
   `wait_for_arbitration`), and `collect_escrow_with_codec` — the
   collection mirror of the existing reclaim dispatcher. Nothing in the
   repo collected escrows before this.
3. **Core lifecycle engine.** Seller half done:
   `core_storefront.settlement_lifecycle.ClaimsEngine` is the persisted
   claim state machine (awaiting_conditions → collectable → collected /
   abandoned) with backoff scheduling, expiration-grace abandonment,
   hook-owned `mechanism_state` scratch, and stage-event hook points;
   it drives injected per-mechanism `check_conditions`/`collect` hooks
   and never learns the mechanism. The alkahest hooks live in
   `domains/vms/settlement/claims.py` (recipient → ready;
   trusted-oracle → request-once + `ArbitrationMade` poll; all_arbiter
   recurses); the storefront embeds the engine as a watchdog-style
   startup task over a `settlement_claims` SQLite table, and settlement
   jobs submit a claim (obligation re-materialized from the pinned
   proposal — the plan carrier feeding the engine) on fulfillment.
   The buyer-side engine is `market service --from <run-id>`
   (domains/vms/buyer/service_cli.py): a foreground loop over the deal
   run-log that emits signed heartbeats at the agreed cadence until the
   plan obligation's expiration, then attempts post-expiry reclaim when
   the seller never collected (`--once` for single-shot, `--no-reclaim`
   to opt out). Still open: `materialize`/`reclaim` hook driving on the
   seller engine (today it services claimant-side collection only;
   materialization stays in the settle phase until interval escrows
   need engine-driven materialization).
4. **Heartbeat endpoint.** Done: `core_storefront.heartbeats` owns the
   mechanics (per-deal strict monotonicity on the signed timestamp —
   replay protection covering exactly what the request signature
   covers — skew bounds, store protocol, and the
   `heartbeat_gap_seconds` primitive lifecycle policies will read);
   `POST /api/v1/deals/{escrow_uid}/heartbeat` rides the standard
   signed-request verification plus a binding check against the deal's
   recorded buyer, persists to a `deal_heartbeats` table, and emits
   `service`-stage events. `domains/vms/settlement/heartbeats.py` is
   the first payload vocabulary (`vms.heartbeat.v1`: bare liveness +
   status). Evidence-bundle construction for oracle arbitration is
   I.5's.
5. **VM lifecycle policies.** First instantiation done: the
   **deferring-third-party-oracle single escrow**. A seller opts in via
   `oracle_gated_listings` + `trusted_oracle_address` (the publish path
   rejects a missing oracle and rejects the seller's own wallet — the
   party collecting cannot also be the party deciding collection);
   listings then advertise a `TrustedOracleArbiter(oracle)` demand,
   which flows through the existing codec registry into materialized
   escrows, and the claims engine requests arbitration once and polls.
   The oracle is assumed to `arbitrate()` true at end of lease unless a
   dispute was raised — manual for now via the kit's `alkahest-oracle`
   CLI (arbitrate/status); the production follow-up is an oracle
   *service* that auto-arbitrates true at lease end and parks disputes
   for a human, with the buyer's signed heartbeats and the seller's
   persisted evidence informing dispute handling. The accepted plan's
   `service_terms.heartbeat` carries the cadence; the buyer's
   `market service` follows it.

   True *heartbeat-gated* collection (where missing heartbeats
   mechanically block payment rather than ground a dispute) needs one
   of: (a) a heartbeat-verifying **arbiter contract** checking buyer
   signatures on-chain, with the deal split into per-interval escrows
   so a dead buyer costs the seller at most one interval; or (b) the
   **splitter contracts**
   (`~/dev/arkhai/alkahest/contracts/src/utils/splitters/`, not yet
   fully audited and under security patching) with an off-chain oracle
   service. Both are future plan shapes, as are interval escrows and
   penalty bonds generally.
6. **Wire `request_arbitration` into the engine.** Done:
   `submit_compute_fulfillment` submits the fulfillment and nothing
   else; the claims engine owns arbitration (requested once per
   fulfillment, recorded in `mechanism_state`, polled via the bounded
   `ArbitrationMade` probe with engine backoff) and collection. The
   old call also pointed the oracle at the seller's own wallet with the
   order JSON as demand — request theater that nothing answered; the
   oracle now comes from the escrow's decoded demand tree.

## Part II — Shared capacity and the site authority

### Today (what the code does)

The storefront is the sole capacity owner. Its SQLite
(`domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`)
holds both:

- **physical truth:** `hosts`, `compute_allocations` (the holds ledger:
  `reserved → provisioning → leased → releasing/released`, with
  `escrow_uid`, `provider_lease_id`, `lease_end_utc`);
- **market view:** `resources` (pricing, `accepted_escrows`),
  `compute_inventory_pools` / `compute_pool_members` (fungible pooling),
  `derived_compute_listings` (listings auto-derived from pool
  availability).

The provisioning service
(`domains/vms/provisioning/service/`) is capacity-blind: it runs jobs,
tracks `vm_leases`, and its watchdog calls *back up* to the storefront
(`PATCH /api/v1/admin/portfolio/resources/{id}`, fulfillment events to
`/api/v1/admin/portfolio/compute/events`) so the storefront can release
holds and reconcile listings. Negotiation reads an availability snapshot
(`domains/vms/listings/reconciler.py::available_compute_slices`, taken
at round start in
`domains/vms/negotiation/storefront_round.py`); the authoritative
check-and-reserve happens at fulfillment
(`sqlite_client.reserve_available_compute_vm`, called from
`domains/vms/provisioning/fulfillment.py`), and stale derived listings
are closed *inline* after the storefront's own reservation
(`market_storefront/services/publication_service.py::close_stale_compute_listings_after_capacity_change`).

This works only because there is exactly one storefront and it owns the
ledger. Two storefronts selling from the same machines (VMs + inference)
make either one's SQLite a double-sell; one storefront aggregating two
datacenters has no single place to put "available."

### Two domain axes

"Domain" means two different things here, deliberately decoupled:

- **Market schema domain** (VM listings vs inference listings): the
  vocabulary of listings, negotiation messages, settlement plans.
  Chosen per storefront.
- **Resource domain** (compute hosts: GPUs/RAM/disk/region): the
  vocabulary the capacity ledger counts. Chosen per site authority.

VMs and inference are different market domains over the *same* resource
domain — that is the whole point. Market-domain coupling appears at
exactly two pluggable joints: offer → claim conversion (a domain hook on
the storefront side) and job-kind → executor (a plugin registered at the
site). Everything between is resource-domain only.

### Components and authority

| Component        | Owns (authoritative)                                                                                                       | Domain axis                          | Deployment                                                       |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- | ----------------------------------------------------------------- |
| Site authority   | per-site resource ledger: hosts, allocations (incl. lease timing), job queue, watchdog/scheduler; emits all events           | resource domain only; no market schema | own service (HTTP/RPC); one per datacenter / failure domain        |
| Executor         | nothing durable — pulls jobs, drives infra, reports status to the ledger                                                     | one per fulfillment kind (job kind)    | worker behind the site authority; in-process plugin until needed elsewhere |
| Aggregator       | nothing authoritative — fungible pool view over N sites, placement/routing policy, listing derivation                        | follows its storefront's market domain | library module inside the storefront process                       |
| Storefront       | market state: listings, pricing/terms, negotiation threads, deals, settlement lifecycle                                      | one market schema domain per process   | domain-owned executable                                            |

**The lease DB merges into the ledger.** A lease is the temporal tail of
an allocation; today `lease_end_utc`/`provider_lease_id` are duplicated
across `compute_allocations` (storefront) and `vm_leases` (provisioning
service), synced by callbacks. In the target they are one row in the
site authority. The watchdog becomes the ledger's own scheduler: at
`lease_end_utc` (or on early termination from the settlement lifecycle)
enqueue a teardown job; when the executor reports done, release the
allocation in a *local transaction* and emit events. Today's
executor→storefront callbacks disappear as a pattern; everything routes
through the ledger so every notification is consistent with a snapshot.

**Executors are stateless, with two qualifications about where state
goes.** Durable job state (spec, status, progress, results such as
IP/connection details) lives on the job/allocation row, pulled with
ack/visibility-timeout so a crashed executor's job re-delivers. The
price is idempotency: derive infra names deterministically from
`allocation_id` so re-delivered creates detect-or-create. Machine truth
(what is actually running) lives in the infrastructure itself
(hypervisor / app control plane), never in an executor DB — which makes
reconciliation a comparison of exactly two real sources: ledger says
leased but no VM ⇒ mark failed + release; VM with no live allocation ⇒
orphan teardown/alert.

### Event model

Today's single callback channel conflates two kinds of notification that
want different delivery semantics:

- **Deal-scoped events** (job submitted / provisioning failed / usage
  started / lease expired *for allocation X*): point-to-point to the
  storefront that owns the deal (recorded on the allocation at reserve
  time). They carry deal context and feed the stage log, failure policy,
  and the claims agent. Never broadcast — noise at best, a cross-seller
  leak at worst.
- **Capacity-scoped events** (availability for host/pool changed, for
  *any* reason: a reserve by any storefront, a release, an expiry, an
  operator adding/draining a host): pub/sub to all subscribed
  storefronts, **anonymous** — new availability plus a version number,
  never whose deal caused it. Aggregators refresh a view; they do not
  reconstruct a ledger. Versioned deltas with a pull-snapshot resync on
  version gap; optional subscription filters (only claim shapes the
  storefront sells) as scale demands.

```
executor ──job status──▶ site authority (ledger txn)
                              ├─ deal event ────────▶ owning storefront
                              └─ capacity delta ────▶ all subscribed storefronts
                                                       └ aggregator refresh →
                                                         derived-listing reconcile →
                                                         publish/close to registries
```

Stale-listing closure stops being inline-after-own-reservation and
becomes each storefront's reaction to capacity events — necessarily so,
because the *other* storefront's sale also invalidates your listings.

### Reservation protocol

Negotiation-time availability stays advisory; reservation stays
authoritative — the current design already tolerates staleness (the
inventory guard works off a round-start snapshot), so semantics don't
change:

1. **Round start:** the seller round hook fetches the snapshot from the
   site authority's client instead of local SQLite. The seam already
   exists — the snapshot is captured behind the injectable round-hook
   callable.
2. **Terms accepted:** optional **TTL'd soft hold** (`reserve` with
   expiry) — closes the window where escrow settles but capacity is
   gone, which widens under cross-domain contention. Auto-expires if
   settlement never lands.
3. **Settlement:** commit the hold (or plain atomic `reserve` where soft
   holds aren't used). Cross-storefront contention resolves here, at one
   site's local transaction.
4. **Fulfillment:** submit job referencing `allocation_id`; lease
   registered against it; teardown at expiry/termination as above.

### Aggregation and fungibility

The aggregator answers "two machines in two datacenters, one listing,
depletes only when both are depleted": availability is a sum over member
sites; a reserve is routed to one site (placement is seller policy:
fill-first, spread, cheapest-power, …) and falls back to the next on
refusal; the listing closes only when every member refuses. The pool
holds no capacity — soft-state view over hard-state site ledgers, so
there are no distributed transactions to invent.

**Fungibility rule:** resources may share a pool exactly when no
attribute advertised or negotiable in the listing schema distinguishes
them. If `region` is in the listing, two regions cannot pool; if only
`gpu_model` + SLA are advertised, they can. Pooling policy is therefore
a market-domain decision, which is why the aggregator belongs to the
storefront, not to a site (a site cannot know it is interchangeable with
another) and not to a neutral shared service (interchangeability is a
commercial judgment per seller).

The storefront's current tables already contain this split in embryo:
`compute_inventory_pools` / `compute_pool_members` /
`derived_compute_listings` *are* the aggregator;
`hosts` / `compute_allocations` are a site ledger fused into the same
file. The migration cuts along that existing boundary, with pool members
referencing `(site, resource_id)` instead of local rows.

### Topology and deployment collapse

```
VM storefront ────┐                 ┌── site authority, DC-A
  [aggregator:VM] ├──── claims ─────┤   [ledger+jobs | vm-exec, inference-exec]
inference sf ─────┤    (neutral)    ├── site authority, DC-B
  [aggregator:inf]┘                 └   [ledger+jobs | vm-exec, inference-exec]
```

M storefronts × N sites; each aggregator subscribes to its seller's
sites; each site serves whichever storefronts sell from it; neither
count constrains the other.

The ledger must be its own service the moment it does its job (it is the
serialization point for reserves across processes, and allocations
outlive any deal flow); the aggregator must *not* be one (soft state +
per-seller policy; an HTTP hop to your own cache buys nothing). For the
degenerate single-storefront deployment, keep the site-authority
boundary as a client interface with an embedded same-process
implementation — but never let storefront B reach the ledger through
storefront A's process; embedded mode is for a provably single
consumer.

### Work items

1. **Site authority client interface.** Done:
   `core_storefront.capacity` defines the `CapacityClient` contract
   (snapshot/probe/reserve(+TTL)/commit/release/truncate-lease/
   subscribe) plus the anonymous versioned `CapacityDelta` carrier and
   in-process event bus;
   `market_storefront.services.capacity_client.EmbeddedCapacityClient`
   is the single-consumer adapter over the existing storefront tables.
   TTL holds raise until item 6; the job API joins with item 4 (the
   embedded adapter has no queue to front).
2. **Swap the snapshot source.** Done: the seller round hook takes a
   capacity client and feeds the inventory guard from
   `capacity.snapshot()`; the fulfillment path's
   check-and-reserve/commit went through the same boundary
   (`capacity.reserve(claim, deal_ref)` / `capacity.commit`).
3. **Event channel.** Capacity half done: every embedded
   reserve/commit/release/truncation emits a versioned delta, and
   `close_stale_compute_listings_after_capacity_change` runs as a delta
   subscriber instead of inline-after-reservation. Deal-scoped events
   still arrive as the provisioning service's admin HTTP callbacks and
   move behind the interface with item 4.
4. **Stand up the site authority service.** Done, hosted by the
   provisioning service process (the executor stays an in-process
   plugin, per the components table): `site_resources`/`site_allocations`
   (the storefront's hold and the lease's temporal tail as one row,
   TTL soft holds supported at the ledger) plus the `capacity_events`
   pull feed, exposed at `/api/v1/capacity/*` mirroring the
   `CapacityClient` contract. The storefront's `[capacity] mode="site"`
   swaps in `RemoteCapacityClient` + an event-feed poller (embedded
   stays the fallback and the default for single-process deployments);
   inventory mirrors into the ledger at startup and after admin
   imports/patches. Lease registration attaches to the ledger
   allocation; at expiry the watchdog releases it in a local
   transaction and posts a deal-scoped capacity-released event to the
   owning storefront — the `PATCH /admin/portfolio/resources` callback
   is retired for ledger-held allocations (it remains only as the
   embedded-mode expiry path). The canonical e2e runs in remote mode.
   Open edges: operator reservations (`/admin/portfolio/reservations`)
   still write the local tables (listing reconciliation merges site +
   local holds until II.5 re-homes the aggregator); job submission
   still goes through the VM-specific `/hosts/{host}/vms` API rather
   than a job-kind queue keyed by `allocation_id` (revisit with the
   second executor, II.7); the owning storefront comes from service
   settings, not yet from the deal_ref recorded at reserve time.
5. **Aggregator module.** Done: `core_storefront.aggregation` defines
   `AggregateCapacityClient` — the soft-state view over N hard-state
   site ledgers, implementing the same `CapacityClient` protocol it
   consumes (site-tagged union reads; reserves walk sites in
   placement-policy order and fall back on refusal, None only when
   every member refuses; writes route to the owning site).
   `[capacity.sites]` names the authorities (one site is the degenerate
   aggregation; the first is the home site, where local inventory
   mirrors), placement is selectable (`fill_first`, `most_available`),
   one event poller per site feeds site-tagged deltas, and
   `compute_pool_members` is keyed by `(site, resource_id)` (NULL =
   home). Slice derivation takes consumption from the aggregated
   snapshots per member key while totals and market attributes stay
   local. Open edges: operator reservations and the publish CLI's
   availability still read local tables; a second *physical* site in
   the e2e topology waits for II.7, so multi-site routing is proven at
   the unit level only.
6. **Two-phase reserve.** Done: every accept chokepoint places a TTL'd
   soft hold (`capacity.reserve` with `ttl_seconds`; `hold_ttl_seconds`
   defaults to 900, 0 disables) and settlement consumes it by
   committing the held allocation into a lease *before* provisioning —
   securing capacity up front removes the lapse-mid-provision race, and
   the post-provision commit just refreshes the window. Lapsed/refused
   holds fall back to the plain atomic reserve; unsettled deals lapse
   at the ledger (the embedded ledger gained the same TTL semantics:
   `hold_expires_at` + lazy sweep). The lifecycle coupling is wired:
   `claim_abandoned` truncates the deal's lease to now, handing teardown
   to the ledger's expiry machinery. Embedded-mode limitation: the
   legacy `vm_leases` teardown keeps its original schedule (no merged
   lease row to truncate); remote mode ends the lease fully.
7. **Second executor.** The inference (or other) executor as the proof
   that job-kind dispatch and the neutral ledger hold; only then a
   second market-domain storefront sharing the pool end-to-end.

## Ordering and dependencies

Part I and Part II proceed independently; item I.3's "deal is over"
signal targets the site-authority client interface but degrades to the
storefront-local tables until II.4 lands. Within Part II the client
interface (II.1–II.3) deliberately preceded the physical service (II.4)
— same playbook as the extraction doc: make the code boundary express
the target graph first, so the move is a move and not also a behavior
change. That paid off as intended: II.4 landed as four slices (ledger +
API, remote client, watchdog/deal-event rewire, e2e topology flip),
each keeping the branch green, with the embedded adapter retained as
the single-process fallback and the full-deal e2e scenarios asserting
the lease lifecycle through a mode-agnostic view so both topologies
stay covered.

## Non-goals / deferred

- **Fractional/shared claims and packing.** Claims stay coarse
  (whole-GPU, exclusive) until inference packing is concrete; the claim
  schema gets a mode field then, not a general scheduler now.
- **Cross-seller capacity markets** (sites serving storefronts of
  different operators). The deal/capacity event split already keeps
  deal privacy, but pricing/quota between operators is out of scope.
- **A second resource domain** (storage, bandwidth). Same stance as the
  extraction doc: validate with heterogeneous compute first.
- **Generic oracle implementations.** Kit owns talking *to*
  `TrustedOracleArbiter`; operating an oracle (heartbeat verification
  service) starts as a domain-side tool.
- **A concrete fiat mechanism codec.** The plan carrier's mechanism
  envelope is in scope now (item I.1) precisely so fiat support later
  is additive — a `kit/fiat-<provider>` codec plus a domain policy that
  proposes/accepts the mechanism — but building a specific provider
  integration waits for a committed customer/provider pairing.

## References

- `docs/development/design-market-core-extraction.md` — the
  reorganization this builds on; filing principle; entrypoint decisions
- `~/dev/arkhai/alkahest/contracts/src/arbiters/` —
  `TrustedOracleArbiter.sol`, `logical/AllArbiter.sol`,
  `attestation-properties/RecipientArbiter.sol`
- `domains/vms/settlement/fulfillment.py` — current fire-and-forget
  `request_arbitration` touchpoint
- `domains/vms/storefront/src/market_storefront/utils/sqlite_client.py`
  — current fused ledger + market-view tables
- `domains/vms/listings/reconciler.py`,
  `domains/vms/negotiation/storefront_round.py` — advisory snapshot seam
- `domains/vms/provisioning/fulfillment.py`,
  `market_storefront/services/publication_service.py` — reserve +
  inline stale-listing closure to be made event-driven
- `domains/vms/provisioning/service/` — today's capacity-blind executor
  + `vm_leases`/watchdog to merge into the site authority
