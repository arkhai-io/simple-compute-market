# Arkhai Market Stack — Architecture Reference

> **Purpose:** Current repository-wide architecture for implementation and review. Detailed normative subsystem contracts live in [`openspec/specs/`](../../openspec/specs/); proposed transitions live in [`openspec/changes/`](../../openspec/changes/). This document describes what the system is and why its major boundaries exist. It is not a backlog or changelog.

## Document map

| Section | Purpose |
|---|---|
| [System overview](#system-overview) | Marketplace purpose and production shape |
| [Composition from above and below](#composition-from-above-and-below) | Core, kit, domain, and composition-root ownership |
| [Package and dependency layers](#package-and-dependency-layers) | Enforceable one-way package rules |
| [Runtime service map](#runtime-service-map) | Processes, authorities, and principal calls |
| [Authority boundaries](#authority-boundaries) | Which component is authoritative for each kind of state |
| [Shared vocabulary and identities](#shared-vocabulary-and-identities) | Official cross-service terms and identifiers |
| [Major lifecycle flows](#major-lifecycle-flows) | Negotiation, settlement servicing, capacity, and fulfillment |
| [Deployment topology](#deployment-topology) | Local and deployed structure |
| [Build, packaging, and initialization](#build-packaging-and-initialization) | Internal wheels, images, migrations, and reinit rules |
| [Recovery workers](#recovery-workers) | Timer-driven durable recovery: capacity, fulfillment convergence, lease expiry |
| [Testing strategy](#testing-strategy) | Test levels; see `TESTING.md` for methodology |
| [Capability documentation index](#capability-documentation-index) | Permanent detailed contracts and rationale |

## System overview

Arkhai is a reference implementation of an agent-driven marketplace. Buyers discover listings through registries, negotiate with seller storefronts through signed synchronous HTTP rounds, materialize settlement plans, and service obligations over time. Market-domain code defines what is traded; shared role packages provide schema-opaque control flow; reusable kit capabilities provide identity, policy, settlement, capacity, resource-pool, and fulfillment machinery.

Physical delivery is deliberately separate from commercial agreement. A seller may advertise fungible capacity or intentionally expose a specific resource. The storefront owns market-facing listings and deal state. Site authorities own admitted capacity. Resource-pool services own provisioning routing metadata. Fulfillment scheduling binds admitted capacity to a settlement resource, and providers execute against that selected resource.

Not every market has physical delivery. API credits reuse the same schema-opaque negotiation and settlement roles while a quota authority issues prepaid bearer-key balances. They do not acquire compute-provisioning dependencies merely to fit the physical lifecycle.

```text
buyer (`market`) ── discovery ──> registry
       │                            ▲
       └─ signed negotiation ──> storefront
                                  │
                                  ├─ settlement servicing ──> chain / mechanism provider
                                  └─ capacity + fulfillment ──> site authority / compute provisioner
```

Production permits independently operated registries and seller stacks. Buyers may be ephemeral CLI invocations or long-running agents. Local development adds an Anvil fixture and test-only composition.

## Composition from above and below

A behavior belongs in the market core when it is invariant across listing schemas. Behavior that varies by schema is supplied from below through injected domain or kit hooks.

The schema-opaque market composition is:

```text
terms   = negotiate(messages...)
plan    = settle(terms)
receipt = service(plan)
```

Core owns the structure around these phases: signed transport, round sequencing, persistence mechanics, deterministic handoffs, and lifecycle engines. Domain packages own listing vocabulary, message content, validation, deterministic interpretation of terms, fulfillment requirements, and result vocabulary. Kit packages own reusable mechanisms and authorities. Composition roots wire concrete domain and kit implementations into role packages.

Two hooks remain separate when core-owned machinery or a typed invariant sits between them. They may be merged when the core does nothing between them and the split would expose only implementation detail.

The registry is the schema-centralizing point for discovery. A registry publishes one filter/listing schema and remains opaque to market-domain payloads beyond its configured validation and filter vocabulary. A market-domain operator composes the relevant buyer and storefront plugins around that registry schema.

See the [market composition specification](../../openspec/specs/market-composition/spec.md).

## Package and dependency layers

### Repository layers

```text
composition roots / deployed services
        ↓
domain packages and role implementations
        ↓
kit capabilities
        ↓
core carrier and role contracts
```

Core carrier packages must not import domain vocabulary. Domain packages may implement core hook shapes but should not make core depend on a concrete market. Composition roots own wiring and may depend on all lower layers.

### Kit layers

Kit is not a flat peer group. It has an explicit one-way hierarchy:

1. **Foundation capabilities** — identity, configuration, generic policy, and settlement-mechanism primitives.
2. **Authority capabilities** — `kit/site` and `kit/resource-pools`, which own capacity and pool administration and depend only on foundation capabilities.
3. **Fulfillment lifecycle** — `kit/fulfillment`, which owns provider-neutral scheduling and provider execution contracts and may depend on authority capabilities.

```text
kit/fulfillment
    ├──> kit/site
    └──> kit/resource-pools

kit/site ───────────────> foundation only
kit/resource-pools ─────> foundation only
```

Dependencies never point upward. Imports guarded by `TYPE_CHECKING` still count as architectural dependencies. Kit packages never import deployed services or domain adapters.

The fulfillment distribution is `arkhai-kit-fulfillment`, imported as `market_fulfillment`. It owns both scheduling and provider-neutral fulfillment contracts. Keeping those contracts together avoids a reverse dependency from resource-pool administration into provisioning execution while preserving module-level separation between pure carriers and operational scheduling.

Within `market_fulfillment`, carrier modules such as identifiers, envelopes, requests, resources, and provider protocols must not import concrete services. Scheduler implementations may depend on the site and resource-pool authorities explicitly permitted by this layer.

## Runtime service map

```text
┌──────────────────────────────────────────────────────────────┐
│                    Settlement mechanism                      │
│          EVM / Alkahest today; other codecs possible        │
└───────────────────┬──────────────────────────┬───────────────┘
                    │                          │
          ┌─────────▼─────────┐       ┌────────▼──────────┐
          │ Registry         │       │ Seller storefront │
          │ listings/schema  │◄──────┤ publication       │
          └─────────▲─────────┘       │ negotiation       │
                    │                 │ settlement claims │
                    │                 └────────┬──────────┘
          ┌─────────┴─────────┐                │
          │ Buyer (`market`)  │                │ capacity / fulfillment
          │ discovery         │                ▼
          │ negotiation       │       ┌────────────────────┐
          │ settlement       │       │ Compute provisioner │
          └───────────────────┘       │ site authority      │
                                      │ resource pools      │
                                      │ scheduler/providers │
                                      │ jobs/lease release  │
                                      │ recovery watchdogs  │
                                      └─────────┬──────────┘
                                                │
                                      ┌─────────▼──────────┐
                                      │ VM / bare-metal /  │
                                      │ future executors   │
                                      └────────────────────┘
```

The buyer is normally a pure HTTP client. The registry is a shared discovery service. A storefront is seller-owned market state. The compute provisioner hosts the site capacity authority and shared physical-provisioning service, with concrete domain adapters registered at composition time; it also runs the timer-driven recovery watchdogs described in "Recovery workers" below. The API-credits seller stack instead composes a storefront with a credits service and quota authority; the credits service owns keys, balances, grants, and online consumption.

## Service Architecture

Within a service, controllers stay thin: HTTP routing, request/response schemas, and translating exceptions into status codes. Business rules, orchestration, and I/O composition live in the 'service' layer beneath them. A per-service breakdown of its own layers belongs in that subsystem's `architecture.md`, not here.

## Authority boundaries

| State or decision | Authority | Notes |
|---|---|---|
| Listing schema and discovery filters | Registry operator | Published through `filter-spec.yaml`; storefronts and buyers consume the schema |
| Listing, negotiation, deal, and seller policy state | Storefront | Market-facing state, not physical inventory |
| Capacity admission and reservation | Site authority | Serialization point for competing reservations |
| Resource-pool metadata and provider configuration | Resource-pool service | Provisioning routing metadata; disabled pools remain resolvable |
| Settlement-resource selection | Fulfillment scheduler | Placement occurs before provider execution |
| Provider-specific create/status/teardown | Fulfillment provider | Executes against the selected resource and does not substitute placement |
| Asynchronous infrastructure job state | Compute provisioner | Durable job identity with in-process execution queue |
| Lease expiry and physical release | Provisioning lifecycle plus fulfillment convergence | Lease lifecycle owns the release decision; fulfillment convergence owns teardown dispatch/recovery — see "Release" and "Recovery workers" |
| On-chain/mechanism claim state | Settlement servicing engine | Mechanism-neutral core with kit/domain codecs and policies |
| API keys, credit balances, grants, and consumption | API-credits service | Wallet authorization for purchase is distinct from bearer authorization for use |

### Storefront capacity boundary

The storefront owns capacity offerings and projections used to publish and negotiate listings. It is not the source of truth for physical resources. A projection may be stale; authoritative admission occurs at the site authority.

Specific-resource listings are a valid opt-in: the seller exposes a concrete resource and permits the buyer to constrain placement. The ordinary fungible path reserves capacity and lets fulfillment scheduling select a settlement resource.

Storefront capacity pools and provisioning resource pools are separate concepts. Mapping is explicit configuration or attributes, never a cross-service foreign key.

### Site authority

A site authority owns resources, allocations, reservation expiry, capacity versions, and the event feed for one failure domain or datacenter. One storefront may aggregate several sites, and one site may serve several storefronts.

Capacity events are anonymous availability deltas broadcast through a pull feed. Deal-scoped fulfillment events are point-to-point to the owning storefront and retain deal context. A storefront reconciles listings in response to capacity deltas regardless of which seller action caused the change.

A site authority's client-facing surface splits into two separately typed clients, both living in `kit/site-client`: a buyer-facing read/reserve/commit client (`SiteCapacityClient`) never used for operator writes, and a typed capacity-administration client (`SiteCapacityAdminClient`) for operator resource registration and update. Neither client depends on the other's implementation.

### Resource pools

Resource pools group physical settlement candidates and identify the provider plus provider-specific configuration used after selection. Pool disablement prevents new assignment but does not erase existing host membership or lifecycle records. Pool administration is distinct from scheduling policy.

## Shared vocabulary and identities

### Terms

| Term | Definition | Primary authority |
|---|---|---|
| **Market Agreement** | Commercial terms accepted after negotiation | Core/domain and storefront |
| **Capacity Offering** | Market-facing representation of sellable capacity | Storefront |
| **Capacity Projection** | Storefront view of capacity believed sellable | Storefront, sourced from sites |
| **Capacity Reservation** | Admitted hold against authoritative capacity | Site authority |
| **Physical Resource** | Real supply resource such as host, pod allocation, storage, power, or bandwidth | Site/provisioning |
| **Resource Pool** | Provisioning-owned group and provider-routing context | Resource-pool service |
| **Capacity Settlement Assignment** | Durable binding of a capacity reservation to one settlement resource | Site/fulfillment boundary |
| **Settlement Resource** | Physical resource selected to satisfy a reservation | Fulfillment scheduler |
| **Physical Settlement** | Provider-specific execution that makes the agreed resource available | Fulfillment provider |
| **Fulfillment** | Post-acceptance lifecycle encompassing assignment, provider execution, status, teardown, and results | Fulfillment capability |
| **Provisioned Resource** | One output created by fulfillment, such as a VM or pod | Domain/provider |
| **Settlement Record** | Durable lifecycle record linking reservation, resource, provider snapshot, operations, and results | Compute provisioning lifecycle |

Avoid `SettlementTarget` as a noun. Use `SettlementResource`; method names may use `select_target_resource` only where it improves call-site clarity.

### Identifiers

Fulfillment lifecycle identifiers are opaque UUIDv7 strings. They are not encoded composite keys and callers must not derive routing data from them.

| Identifier | Meaning |
|---|---|
| `capacity_reservation_id` | Admitted capacity and idempotency boundary for scheduling/begin fulfillment |
| `fulfillment_id` | Durable post-acceptance fulfillment aggregate |
| `settlement_resource_id` | Selected underlying supply resource |
| `provisioned_resource_id` | One provider-created output; one fulfillment may create several |
| `result_id` | One durable settlement/fulfillment result |
| `site_id` | Explicit authority/routing identity; never encoded into another ID |
| `pool_id` | Globally unique pool identity with explicit site ownership where required |

`fulfillment_uid` is a distinct, older identifier predating `fulfillment_id`: the on-chain settlement-claim identity a storefront's settlement mechanism (Alkahest today) issues for escrow arbitration. It is not part of the fulfillment-lifecycle UUIDv7 family above, is owned by the settlement mechanism rather than the fulfillment capability, and MUST NOT be confused with `fulfillment_id` — a storefront workflow row may legitimately carry both, for the same deal, meaning two different things.

`site_id` is owned at the storefront aggregation boundary and bound to a configured provisioning connection. Provisioning-local capacity persistence is already scoped by its database authority and does not duplicate that storefront-owned identity on every pool, resource, or reservation row. Counterparties cannot self-assert the routing identity used by the storefront.

Commercial agreement identity does not cross the generic provisioning boundary merely for correlation. Storefronts retain commercial context and translate it into fulfillment requirements. The capacity reservation is the generic physical-lifecycle identity.

## Major lifecycle flows

### Discovery and negotiation

The buyer discovers listings from a registry and drives signed synchronous request/response rounds against a storefront. Negotiation is a deterministic reduction of the shared message history to agreed terms. Seller policy evaluates listing data, captured side inputs, and the message history; protocol infrastructure does not reinterpret domain policy.

Negotiation is a conversation of counter-offers over what capacity is being sold, not over which specific physical resource serves it. A buyer and seller negotiate pooled capacity ("4 GPUs", not "host `kvm-17`"); a counter-offer that changes the requested shape (fewer/more units, a different dimension mix) is a negotiation event, and a durable shape change is expressed by resizing the reservation for that negotiation, never by mutating an existing reservation or committed settlement assignment in place (see "Capacity reservation" below, and `openspec/specs/site-capacity/spec.md`'s reservation-supersede requirement). Today's negotiation rounds exchange hard counters; the same model extends to richer forms (a buyer asking what shape a given price can buy, or what price a given shape costs) without changing this premise.

Physical resource identity (`resource_id`, `vm_host`, and equivalent per-domain identifiers) is an optional pinning/telemetry pathway, not the unit buyers and sellers negotiate over. It is deliberately not exposed across the capacity-reservation boundary (`openspec/specs/site-capacity/spec.md`'s opaque-reservation requirement) for exactly this reason: the storefront and buyer should not need to know or care which physical resource ultimately serves a deal in the ordinary case. Code that makes ordinary fulfillment depend on a physical resource identity being present is very likely encoding the wrong unit of negotiation.

```text
registry listing
    ↓
buyer opening message
    ↓
signed synchronous rounds
    ↓
shared canonical history
    ↓
Terms
```

### Settlement servicing

Settlement materializes agreed terms into a mechanism-neutral plan. Servicing may outlive fulfillment and repeatedly evaluate conditions, collect claims, accept heartbeats, or abandon/reclaim expired obligations. Core owns the lifecycle engine; kit codecs own mechanism translation; domain policy selects and interprets conditions.

```text
Terms → SettlementPlan → active obligations → Receipt
                         ├─ condition checks
                         ├─ claims / collection
                         ├─ heartbeats
                         └─ expiry / reclaim
```

### Capacity reservation

Negotiation-time availability is advisory. Authoritative reservation occurs at a site authority.

1. The storefront reads snapshots for listing and policy decisions.
2. Accepted terms create a TTL soft hold where required.
3. Settlement commits or recreates the reservation before physical execution.
4. Fulfillment runs against the committed reservation.
5. Lease expiry or early termination invokes physical teardown before capacity release.

A reservation whose negotiated shape changes is superseded, never mutated: `CapacityLedgerService.resize_reservation` atomically releases the old reservation and admits a new one under a new `capacity_reservation_id`, so the reservation's committed dimensions always reflect the shape actually being negotiated. Scheduling (see "Fulfillment" below) MAY further narrow within a reservation's bound for a placement or pricing check against a candidate shape; a scheduling narrower than the reservation reports back exactly what it scheduled, not the reservation's original shape, since that is what gets provisioned if accepted (`openspec/specs/site-capacity/spec.md`'s committed-dimensions-through-scheduling requirement). As of this writing, `resize_reservation` has no negotiation-side caller — this describes the intended negotiation model, not yet-implemented wiring between negotiation and reservation resizing.

#### Layered placement ownership

Which physical resource ultimately serves a deal is decided up to three separate times, by two different processes, and these decisions must not be conflated:

| Decision | Owned by | When | Mechanism |
|---|---|---|---|
| Which pool/resource a listing represents | Storefront | Publish time | Baked into the listing's `offer_resource` at creation |
| Which site to route a reserve/probe call to | Storefront (`AggregateCapacityClient`) | Reserve/negotiate time | `fill_first`/`most_available` ranking policies over a live per-request snapshot |
| Which concrete host within that pool fulfills the reservation | Provisioning service (`PhysicalSettlementScheduler`) | Schedule time | Deterministic round-robin (or a replaceable fairness policy) |

The second layer stays storefront-owned rather than moving into the provisioning service alongside the third: pooling/placement ranking is a commercial judgment a seller makes about their own sites, not a physical-fulfillment concern, so it lives in the storefront process. The second and third layers pick among fundamentally different things — sites versus hosts within one already-chosen site — and are correctly separated by process boundary, not merely by convention.

The second layer's ranking policies (`fill_first`/`most_available`) read a live, per-request capacity snapshot, never a storefront's own advisory `CapacityProjection` cache — that cache is explicitly allowed to go stale for display/listing purposes, and routing a real reservation attempt through it would turn a display cache into a load-bearing admission input, defeating the reason it's allowed to be stale. The ranking policies' own claim-matching is deliberately a *coarse, best-effort hint*, not shared code with the enforcement-level predicates `kit/site` and fulfillment scheduling use: a wrong ranking costs one extra round-trip when the aggregator falls through to the next site, not an incorrect admission, so the two matchers are allowed to diverge in a way an actual eligibility gate never could.

### Fulfillment

```text
Capacity Reservation
        ↓
PhysicalSettlementRequest
        ↓
PhysicalSettlementScheduler.schedule_resource(...)
        ↓
Capacity Settlement Assignment / SettlementResource
        ↓
FulfillmentProvider.create(...)
        ↓
Provider result + zero or more Provisioned Resources
        ↓
status / teardown / durable results
```

Scheduling and provider execution are separate. The scheduler selects and binds a resource. The provider may validate the selected resource but must not choose a substitute. Retries for the same reservation and equivalent request return the existing assignment or operation result; conflicting retries are rejected.

Provider-specific dictionaries crossing domain or persistence boundaries use a versioned envelope with a non-empty `kind`, positive `schema_version`, and typed or explicitly validated payload. Readers reject unknown `(kind, schema_version)` pairs rather than guessing.

The current round-robin scheduling policy is deterministic for the same candidate order and state. Multidimensional fit checks every requested dimension; a candidate missing a requested dimension has zero availability for that dimension.

### Fulfillment status and results

A caller observes fulfillment progress by pulling `GET /fulfillment/{fulfillment_id}/status` and `GET /fulfillment/{fulfillment_id}/result` from the durable aggregate — there is no push channel from provisioning to the storefront today. `status` is a plain read with no provider call. `result` returns a provider-neutral `fulfillment.result.v1` envelope; for a fulfillment in `active` state it also performs a live, uncached credential fetch against the provider (never persisted) outside any open database transaction, so every read reflects current provider-reported credentials rather than a value captured once at creation. A live credential-fetch failure on an otherwise-healthy `active` fulfillment is its own stable error category (`credential_fetch_failed`), distinct from a create/status/teardown failure.

Push-based result delivery (provisioning notifying the storefront rather than the storefront polling) is planned future work, tracked as `provisioning-result-push-delivery`, and requires a new provisioning→storefront authenticated channel that does not exist yet. It does not change the durable persistence this section describes, only the delivery transport.

### Release

Physical release is proof-driven and split across two cooperating state machines with distinct retry ownership. Lease lifecycle (site/provisioning-lease layer) owns `releasing`/`released` and the final capacity-return decision; it never dispatches a second teardown operation itself. Fulfillment convergence (see "Recovery workers" below) owns dispatch, requeue, and recovery of the teardown states themselves (`teardown_dispatch_pending` → `tearing_down` → `torn_down`/`teardown_failed`). Lease-side retry re-observes the same fulfillment aggregate by its durable `fulfillment_id` rather than resubmitting a teardown.

A kind-routed `ReleaseJobPort` connects the two: for VM-backed reservations it reads the fulfillment aggregate's teardown state (`torn_down` → succeeded, `teardown_failed` → failed, otherwise pending); other executor kinds continue to resolve through the shared job queue unchanged. Capacity is never returned to scheduling until the aggregate reaches `torn_down` or an operator explicitly force-releases after external verification; the audit state distinguishes forced release from proven teardown.

`begin_fulfillment_teardown(fulfillment_id)` is the whole-fulfillment teardown entrypoint: it resolves the aggregate, reuses an already-prepared teardown operation when present (as legacy-backfilled rows carry) or prepares one via the provider when a native row reaches teardown for the first time, then hands off to convergence for dispatch — it never dispatches to the provider inline.

## Deployment topology

### Local development

Compose is organized by market domain and includes the shared development chain. There is no required long-running buyer service. Domain stacks contain their registry schema, storefront, and supporting services. The root compose file combines the domain stacks for full e2e work.

### Production and staging

The Helm umbrella chart composes registry, storefront, compute provisioning, and optional development/test components.

Configuration resolution, ConfigMap/Secret mounting, stateful-service persistence strategy, and migration-at-startup conventions are covered in [`docs/development/DEPLOYMENT_AND_CONFIG.md`](DEPLOYMENT_AND_CONFIG.md) and [the deployment and state specification](../../openspec/specs/deployment-state/spec.md).

## Build, packaging, and initialization

Internal Python packages are built as wheels into the repository `.dist` directory. Consumers install those wheels with `--find-links`; they do not use editable relative sibling paths.

The required development pattern is:

```text
build prerequisite internal wheels
        ↓
uv sync --find-links <repo>/.dist
        ↓
--upgrade-package / --reinstall-package changed internal distributions
        ↓
run focused tests
```

Docker builds copy `.dist` from the build context in every stage that resolves internal packages. Using a sibling source path forces an unnecessarily broad Docker context and can allow local source layout to differ from packaged behavior.

Aggregate Make targets must run every included subproject's default tests. A standalone subproject target remains useful for focused work, but the aggregate contract is complete coverage, not a curated subset.

Schema changes are additive by default. Non-additive changes use expand/contract across releases. Config-driven operational seeding belongs in runtime initialization; migrations may seed only deterministic system rows required to satisfy a new schema constraint.

See the [deployment and state specification](../../openspec/specs/deployment-state/spec.md).

## Recovery workers

The compute provisioner runs three independent timer-driven workers, composed once at startup alongside the request-serving app, each owning a distinct slice of durable recovery:

| Worker | Owns |
|---|---|
| `CapacityReservationWatchdog` | Expiring stale/unconfirmed capacity holds |
| `FulfillmentConvergenceWatchdog` | Create and teardown dispatch/status convergence for the fulfillment aggregate (see "Fulfillment" and "Release" above) |
| `LeaseWatchdog` | Lease expiry detection that triggers release |

`FulfillmentConvergenceWatchdog` runs four handler passes each cycle — create-submission recovery, create-status convergence, teardown-submission recovery, teardown-status convergence — plus a `teardown_failed` requeue step, sharing one timer rather than one watchdog per pass. Each pass claims eligible rows durably (a short transaction reserving the row with a lease and worker identity), performs any provider call entirely outside a database transaction, and applies the outcome in a second short transaction only if the claim is still owned — a claim whose lease lapsed before the provider call returns is silently superseded, not double-applied. No attempt-count ceiling exists anywhere in this recovery path; a fresh worker instance resumes purely from durable claim state after a restart, with per-row exponential backoff and jitter between attempts.

## Operator lifecycle controls

Long-running lifecycle workers may expose authenticated one-cycle controls when deterministic recovery, testability, or customer-issue diagnosis requires them. A manual cycle must invoke the same production handler as the timer-driven worker; it must not implement alternate lifecycle transitions. Diagnostic responses are bounded and may expose aggregate state counts, claim ages, and failure counts, but not credentials or unbounded provider payloads.

## Testing strategy

Tests belong at the lowest level that can prove the behavior: unit, integration, smoke, and end-to-end, each defending the narrowest observable contract appropriate to its level — no level should rely on end-to-end tests alone for behavior it could prove itself. See [`docs/development/TESTING.md`](TESTING.md) for the level definitions, coverage jurisdiction between them, the client-contract "no raw calls" rule, contract fixtures, boundary-change validation, cross-language conformance, and offline review validation, and [the testing and compatibility specification](../../openspec/specs/test-compatibility/spec.md) for the normative requirements.

## Capability documentation index

The canonical [capability documentation index](../../openspec/specs/README.md) links each normative `spec.md` and its optional freeform `architecture.md` companion. Capability contracts own detailed behavior; companions own durable subsystem models and rationale; this document remains the cross-system map.

## Deterministic database-concurrency tests

Database-concurrency tests use independent sessions and connections against the same database, establish transaction ownership through explicit synchronization at a semantic persistence boundary, and assert final durable state. Tests must not depend on uncontrolled thread races, scheduler timing, or elapsed-time ordering. Synchronization waits are bounded so lock regressions fail rather than hang. Test-only subclasses or adapters may pause a narrow persistence interface after a meaningful write; production code must not expose test-only hooks.



### Durable fulfillment acceptance

The fulfillment kit owns provider-neutral acceptance orchestration. It loads an already-selected settlement resource, freezes provider-specific prepared input and pool configuration in one transaction, dispatches after commit, and acknowledges provider metadata in a second transaction. Domain adapters own provider-specific payloads and metadata interpretation. Provisioning composition supplies the database unit of work and concrete providers; storefront code does not import provider-specific types.

### Atomic workload-lifecycle cutovers

A schema cutover that transfers ownership of active workloads between persistence models must treat the workload and its known provider-operation identity as authoritative. The compute provisioner's legacy VM lease conversion validates the complete candidate population and writes fulfillment aggregates atomically before retiring the legacy table. Any unsafe ambiguity rolls back the entire conversion; unused pre-release reservation rows must not override or obscure an active lease.
