## Rebaseline — 2026-07-22

Sections 1–2 of `tasks.md` have landed, including the shared fulfillment package, capacity-model cutover, feasibility predicate, projection producer endpoints, and in-memory storefront projection caches. References below that describe those pieces as future design are retained as rationale; remaining implementation starts with durable Settlement Record/fulfillment persistence and tasks 3–12. POOLS-8 has been narrowed to durable projection consumption, commercial mapping, and listing hints rather than rebuilding producer/cache mechanics.

The current provisioning→storefront lifecycle callback is also acknowledged as an existing transport seam. It is not durable or sufficiently authenticated for Settlement Result delivery; the follow-on push change hardens that seam rather than inventing a first reverse channel.

## Context

POOLS-7 cuts the storefront and provisioning services over from the current
direct executor path to durable physical-resource scheduling, fulfillment,
result delivery, and teardown. This document records the design decisions
approved during the POOLS-7 discuss phase and is the design basis for the
implementation plan.

**Implementation baseline after Compute-30:** service composition, persistence,
migrations, generic APIs, and workers now live in
`provisioning/compute/service`; VM/Ansible implementations and operator routes
live in `domains/vms/provisioning/adapter`; bare-metal implementations live in
`domains/bare_metal/provisioning/adapter`. Historical discussion below that says
"VM provisioning service" describes the pre-extraction code but does not assign
new POOLS-7 work back to the removed package. POOLS-7 applies those decisions to
the extracted service and adapter entry points.

## Current storefront fulfillment path (verified, not assumed)

1. `vm_fulfillment_service.py` reserves capacity against the site
   authority. The claim shape includes `required_attributes=("vm_host",)`
   — a specific physical host is chosen **before** any provisioning call,
   using `AggregateCapacityClient` placement policies (`fill_first`,
   `most_available`, `core_storefront/aggregation.py`). This is the
   layering issue `pools-4-storefront-capacity-boundary` targets.
2. `reserved_allocation_id` (from the reservation response) threads through
   the whole fulfillment flow — the storefront already carries
   `allocation_id` end to end today. That part is not new work.
3. `provisioning_orchestration_service.create_vm_and_wait_with_credentials`
   submits `ExecutorActionEnvelope(allocation_id=..., executor_kind="vm",
   action_kind="create", ...)` directly via `ComputeProvisioningClient`,
   then polls `client.poll_until_complete(...)` and fetches credentials
   itself. This is a complete, working, **already-async, caller-polls**
   pattern — the same shape `pools-3`'s `create()`/`get_status()` contract
   was designed to match, just against a different (lower-level, executor-
   kind-dispatched) entry point than `PhysicalSettlementScheduler` +
   `FulfillmentProvider`.

None of this touches `PhysicalSettlementScheduler` or any
`FulfillmentProvider`. The scheduler/provider path introduced by
`pools-2`/`pools-3` and the path the storefront actually uses are two
parallel systems today.

## `executor_kind` vs. `provider` — confirmed orthogonal, not layered

Raised and resolved during the `pools-3` design review: these are
different axes, and neither should be collapsed into the other by this
cutover.

- `executor_kind` (`"vm"` / `"bare_metal"`) is a **domain allocation
  semantics** distinction — VM allocations are shareable (many VMs per
  physical host), bare-metal allocations are exclusive (one allocation
  locks the whole host). It also selects which wire/request models and
  job actions are valid. It's decided once, at lease-registration time, by
  the market domain, and it's a pure lookup key for
  `ExecutorReleaseDispatcher` — the dispatcher doesn't choose a physical
  resource or a mechanism.
- `provider` (`"ansible"` today) is an **infrastructure mechanism**
  distinction — how to reach a resource (playbook and executor variables from the pool
  provider-configuration envelope). `ProviderRegistry` dispatches on this.
- `market-platform-compute-40-multi-domain-proof` is explicit evidence
  these coexist rather than one replacing the other: it proves
  "VM-shareable and bare-metal-exclusive allocations against the same
  physical host," in "one extracted compute provisioner [that] loads VM
  and bare-metal adapters concurrently." Bare-metal is planned to stay a
  separate *domain package*, not a separate *deployed provisioning
  service* — `domains/bare_metal` (`arkhai_bare_metal`) is a library today
  with no service/container of its own; it's imported by the VM
  provisioning service's `container.py` alongside VM release wiring, in
  the same process.

Implication for this change: when it wires release through
`ProviderRegistry`, that wiring is additive to (not a replacement for)
`ExecutorReleaseDispatcher`'s existing `executor_kind` routing — a
`SettlementRecord`-backed allocation resolves its provider via the
registry; an allocation with no `SettlementRecord` (not yet migrated to
the settlement path, or never will be) keeps using today's direct
`VmReleaseExecutor`/`BareMetalReleaseExecutor` behavior unchanged.

## Deferred items this change inherits

From `pools-3-fulfillment-provider` (see its `design.md` Decision 5 and
Risks):

- Wiring `VmReleaseExecutor` (or whatever replaces it) to resolve
  `SettlementRecord` → `ProviderRegistry.require(provider).teardown(...)`.
  `pools-3` built `FulfillmentProvider`/`ProviderRegistry` with no
  production caller and explicitly left the release path untouched to
  avoid designing that wiring against a guessed call shape.

From `pools-2-physical-settlement-scheduler` (see its `tasks.md`
"Remaining follow-on work"):

- "Persist Capacity Settlement Assignments and round-robin cursors
  transactionally." `select_resource()` has no production caller today
  (only tests call it), so this was low-urgency when `pools-2` and
  `pools-3` were built, but a production caller changes that — restart
  safety starts to matter once real reservations flow through it. Decide
  at that point whether `PhysicalSettlementScheduler` should write through
  `SettlementRecord` directly (one durable table, `pending` state before
  a provider ever executes) or keep separate assignment storage.
- "Move the concrete resource capacity claim from initial reservation into
  the assignment transaction" and "Enforce exactly-one-pool membership at
  the database layer" are also still open per that task list and are
  relevant once reservations stop being host-shaped (`pools-4`).

## Durable idempotency and dispatch recovery decisions

POOLS-7 MUST make the database the correctness boundary for fulfillment
idempotency. Process-local or asynchronous locks are insufficient because the
provisioning service may restart between steps, and because the database is
the only durable state this service has — not because multiple replicas run
concurrently against it. The compute provisioner is a SQLite-backed
single-writer service deployed with `Recreate` and a `ReadWriteOnce` volume
(`docs/development/ARCHITECTURE.md`, "Production and staging"): two replicas
never run against the same database at once by construction. Durability
across restarts is the real requirement this section serves; treat any
"multi-replica" language elsewhere in this change's history as an earlier,
imprecise framing of that same requirement (see the Section 6 resolution
below, "What 'multi-replica-safe' means against this service's actual
deployment topology").

The durable fulfillment identity is keyed by `allocation_id`:

```text
allocation_id -> settlement/fulfillment record -> provider operation metadata
```

The persistence design MUST enforce these semantics transactionally:

- an equivalent retry returns the existing fulfillment and does not dispatch a
  second provider operation;
- a request that reuses the allocation with a different agreement, selected
  resource, provider, or fulfillment identity fails with a conflict; and
- teardown is similarly idempotent and does not dispatch uncontrolled duplicate
  work.

The design must explicitly handle the failure window between committing the
fulfillment identity and recording the asynchronous provider operation. A small
durable dispatch state machine or equivalent outbox/recovery pattern is
required. Executor-level deterministic command identity may be used as a final
defense around recovery, but `AnsibleJobService` is not the primary business
idempotency authority.

Pool provider configuration is resolved and snapshotted into executor inputs at
dispatch time so later pool edits cannot change accepted work. The persisted
record must retain the original selected resource, provider, and sufficient
provider metadata for later asynchronous teardown. Final teardown states and
record retention are designed here when the real lease-release call path is
wired.

## Accepted provider configuration

Durable fulfillment persistence must snapshot the accepted provider inputs needed for recovery and teardown so later pool edits cannot reinterpret already accepted work. Database uniqueness and dispatch recovery remain the cross-process idempotency boundary; POOLS-3's in-memory service intentionally provides only sequential retry behavior.

## Scope decision: retrofit, not compute-30 extraction (design review, 2026-07-17)

This session scoped POOLS-7 to retrofitting the existing VM domain
storefront and provisioning service onto the POOLS 1-4 machinery, not to
`market-platform-compute-30-extract-service`'s service extraction. kit
packages (`kit/site`, `kit/resource-pools`) and the `apicredits` domain
may be modified where genuinely cross-domain — this is permitted, not
required, and several of the decisions below exercise that permission.
The remainder of this section records what that design review settled.

### `SiteResource` is retired; replaced by two distinct, differently-scoped entities

Tracing why `PhysicalSettlementScheduler` and the storefront's local CSV
inventory could disagree about `pool_id` (see "Operator listing-mode
hints" above) surfaced a bigger problem than a missing sync: the
storefront was maintaining its own shadow copy of physical inventory
(`resources` table, hand-curated CSV) instead of treating the
provisioning service's `hosts`/`resource_pools` tables as authoritative.
Fixing the sync gap without fixing the ownership inversion would just
move where the drift originates.

Resolved shape:

- **`site_resource_pools`** (renamed from `SiteResource`, `kit/site`,
  hosted by the provisioning service) — stays **host-granular**, one row
  per physical resource, exactly as `SiteResource` is today. It is no
  longer independently authored by the storefront's CSV push; it is
  derived from the provisioning service's own `hosts` + `resource_pools`
  tables (POOLS-1), which are the actual single source of truth for host
  inventory and pool membership. `pool_id` becomes a real, enforced
  attribute rather than a storefront-authored guess that happens to
  collide with an operator pool ID.
- **`CapacityReservation`** (renamed from `SiteAllocation`) — the
  hold/lease-tail row. `resource_id` still binds **immediately**, at
  `reserve()` time, to one concrete, feasibility-verified host — exactly
  as `SiteAllocation` does today (see "Host-granular matching is a
  feasibility guarantee" below for why this must not change to a
  pool-only claim). `pool_id` is carried alongside it, denormalized from
  that resource, so pool-scoped queries don't need a join.
  `settlement_resource_id` is a separate, nullable field: NULL until
  `PhysicalSettlementScheduler` runs, then set by
  `assign_settlement_resource` — in the common case equal to `resource_id`
  (the scheduler confirms the host `reserve()` already picked), differing
  only when round-robin fairness reassigns to a different, equally
  eligible host. This is Option A (reserve against one concrete resource
  up front; the scheduler reassigns among *equally eligible* resources),
  not Option B (reserve against a pool-level aggregate with no concrete
  resource until scheduling) from this change's earlier draft.
- **`CapacityProjection`** (storefront-side) — **split out of this
  change, see "Scope split: CapacityProjection and hints move to
  `pools-8`" below.** Briefly: the storefront's read-only mirror of every
  connected provisioning service's pool/capacity state, for
  pricing/listing display only, never for admission.
- **Physical Resource** (vocabulary term, unchanged) — already used
  across kit with per-domain implementations; no change needed.

This decision explicitly extends beyond the VM domain: `apicredits`
today calls `CapacityLedgerService` directly with no pool concept at all
("token quota resources carry no host"). The intent is for `apicredits`
to also adopt a capacity-reservation-against-a-pooled-view shape, not
just the VM domain — `kit/site`'s reshape must stay generic enough to
carry a non-physical, non-host-shaped notion of "pool" (a quota bucket)
as well as VM's host-shaped one.

### Host-granular matching is a feasibility guarantee, not an aggregation choice (design review, 2026-07-17)

An earlier draft of this review proposed collapsing `site_resource_pools`
into one row per pool (aggregate `total_units`). **This is wrong and MUST
NOT be implemented**: today's row-per-host matching
(`_resource_matches`/`_find_candidate` in `kit/site/ledger.py`) is what
guarantees a reservation for N units only succeeds when *some single
host* actually has N units free — the arithmetic never sums across rows.
Replacing that with one pool-level aggregate row would let a reservation
succeed against a pool's total free capacity even when no single host in
that pool can serve the shape (e.g. 500 units free scattered one-per-host
across 500 machines, and a request for 4 units on one host). This is the
`pools-6` risk *"pool-level aggregation can hide that dimensions live on
different physical resources"* realized at **reservation** time instead
of scheduling time — worse, because it means accepting a deal the system
cannot structurally fulfill.

**Resolved:** `site_resource_pools` rows stay host-granular.
`CapacityReservation` binds to one concrete, feasibility-verified host at
reservation time (today's mechanism, just correctly sourced from
`hosts`/`resource_pools` instead of storefront CSV). This is "Option A"
from this change's earlier draft, not "Option B" (deferring all resource
selection to scheduling) — Option B is deferred to `pools-6` alongside
multidimensional capacity, not attempted here. `assign_settlement_resource`
remains a real, atomic capacity-transfer mechanism, but its role is
narrowed: a **fairness reassignment among already-equally-eligible
hosts**, not a relaxation of feasibility that reservation-time admission
already established.

### Reservation-time admission and scheduling-time eligibility MUST share one predicate

`kit/site/ledger.py`'s `_resource_matches` (reservation admission) and
`PhysicalSettlementScheduler._eligible_candidates` (scheduling
eligibility) are two independent implementations of "does this shape fit
this resource" today. This is the same class of bug as the `pool_id`
mismatch this review started from: two things that must agree, with
nothing forcing them to. Resolved direction: extract a single
`resource_satisfies_requirement(resource, requirement) -> bool` predicate
that both call sites use — reservation calls it to gate admission ("does
at least one host qualify"), scheduling calls it to build the eligible
set for policy selection. The predicate belongs with the authoritative site-capacity model in
`kit/site`; `kit/fulfillment` consumes it for scheduling so reservation-time
admission and scheduling-time eligibility cannot drift.

### `PhysicalSettlementScheduler` and `DeterministicRoundRobinPolicy`: package destination — SUPERSEDED, see "Shared package boundary" below

**Superseded by "Final planning decisions" → "Shared package boundary,"
below — this section's conclusion (`compute_provisioning`) is no longer
correct; kept for the historical reasoning, which still explains *why*
`kit/resource-pools` doesn't work.** The final decision moved these (and
the `pools-2` request/resource types that previously lived in
`compute_provisioning`) into a new dedicated package,
`kit/fulfillment`, instead — a cleaner fix to the same circular-
dependency problem identified below, and a better scope fit than
growing `compute_provisioning` (which was scoped as a thin cross-domain
HTTP-helpers package, not a scheduling/persistence engine).

Both are already effectively domain-neutral (`DeterministicRoundRobinPolicy`
verified to contain zero VM-specific logic — it only sorts `pool_id`/
`resource_id` strings). Moving them out of VM-service-local code was
considered for `kit/resource-pools` (where `FulfillmentProvider`/
`ProviderRegistry` already live, per `pools-3`), but that destination is
**not viable**: `PhysicalSettlementScheduler` needs real runtime imports
from `compute_provisioning` (`SettlementCandidate`, `SettlementRequirement`,
`SettlementResource`, `PhysicalSettlementRequest` — constructed, not just
type-hinted, unlike `FulfillmentProvider`'s string-quoted forward
references), and `compute_provisioning` already depends on
`kit/resource-pools` (`provisioning/compute/pyproject.toml`). Adding the
reverse edge would close a cycle.

`compute_provisioning` has no such problem — it already depends on both
`kit/site` and `kit/resource-pools`, and the settlement types the
scheduler operates on already lived there (`pools-2`). At the time this
was written, the conclusion was that `PhysicalSettlementScheduler` and
`DeterministicRoundRobinPolicy` should move into `compute_provisioning`
on that basis. **This conclusion is superseded** — see the note at the
top of this section: the same reasoning (avoid the `kit/resource-pools`
cycle) is satisfied more cleanly by a new dedicated package,
`kit/fulfillment`, which also took the `pools-2` request/resource
types with it rather than leaving them in `compute_provisioning`.

This incidentally resolves part of the open, unresolved question
`market-platform-compute-30-extract-service` inherited from the closed
`pools-5-shared-provisioning-package` ("should `PhysicalSettlementScheduler`
... consolidate into `compute_provisioning`") — without POOLS-7 taking on
compute-30's actual service-extraction scope. This is the same kind of
narrow, deliberate override `pools-3` already made once for
`FulfillmentProvider`/`ProviderRegistry`; see that change's `design.md`,
"Domain-neutral contracts vs. domain-specific payloads." `compute-30`'s
proposal has been updated (2026-07-21, corrected from an earlier pass
that said `compute_provisioning` and was never actually applied) to
reflect this as resolved — landing in `kit/fulfillment`, not
`compute_provisioning` — rather than open.

Two pre-existing domain leaks were found while confirming this move is
safe, and should be fixed as part of it rather than carried into a
supposedly domain-neutral shared package:

- `kit/site/ledger.py`'s `_UNIT_CLAIM_KEYS = ("units", "gpu_count")` is a
  module-level constant hardcoding a VM-specific alias into otherwise
  domain-neutral ledger code. Should become a `CapacityLedgerService.__init__`
  parameter (default `("units",)`), with the VM composition root supplying
  `("units", "gpu_count")` explicitly — same pattern already used for
  `required_attributes`.
- `PhysicalSettlementScheduler._requirement`'s fallback
  (`resource_kind = ... or "compute.gpu"`) silently defaults to a
  VM-flavored value. Once shared across domains this default is wrong for
  `apicredits`. Should become a required field with no fallback, or an
  injected per-domain default at the composition root.

## Dependency on POOLS-6: multidimensional capacity is a prerequisite, not parallel work

Design review (2026-07-17) surfaced a correctness gap that blocks
`site_resource_pools`/`CapacityReservation` from being trustworthy even
with the host-granularity fix above: **`Host` (`domains/vms/provisioning/
service/src/db/models.py`) has no memory, disk, or vCPU capacity field —
only `gpu_count`.** Reservation admission can therefore verify GPU-count
bin-packing correctly but cannot verify that a negotiated shape
(vCPU/memory/disk, carried today only in `VmFulfillmentRequirements` at
*fulfillment* time, downstream of admission) actually fits any real
host. A reservation can be admitted for a shape no physical machine can
serve.

This is a real instance of `pools-6`'s deliberately-abstract problem
statement, not a new problem — see `pools-6-multidimensional-fair-scheduling/
proposal.md`'s "Concrete, currently-unenforced gap" addition. POOLS-7's
reservation-admission work depends on `pools-6` resolving multidimensional
capacity tracking; it is not POOLS-7's scope to solve, and POOLS-7 MUST
NOT quietly re-derive a partial answer (e.g. adding only a memory field to
`Host` without going through `pools-6`'s design questions on dimension
normalization, units, and fairness) in order to unblock itself. Sequencing:
`pools-6` resolves multidimensional capacity vectors first; POOLS-7's
reservation-admission and scheduling-eligibility work (including the
shared `resource_satisfies_requirement` predicate above) consumes that
result rather than working around its absence.

**Accepted scope for this change:** `pools-6` pass 1 — the
`dimensions`/`available` JSON-map mechanism on `SiteResource`,
`SiteAllocation`, and `CapacityEvent`, and the scheduler's per-dimension
fit check against it — is landed and is what POOLS-7 builds on. Pass 2
(real vCPU/memory/disk fields on `Host`, still carrying only `gpu_count`)
remains open `pools-6` scope; POOLS-7 proceeds against the landed pass-1
wiring rather than blocking on pass 2 or adding a partial dimension field
itself. This does not relax the prohibition above: it is a decision to
accept the current `gpu_count`-only ceiling for this change, not to fill
that ceiling in piecemeal. Admission and scheduling remain correct for
every dimension a caller actually populates; there is simply nothing to
check yet for dimensions no caller populates. Work that starts
populating additional dimensions still needs `pools-6` pass 2's design
questions on normalization, units, and fairness first.

## `SettlementRecord` shape (design review continued, 2026-07-17)

**Resolved: one row, one state machine** — not a separate
scheduler-owned assignment table plus a distinct fulfillment record.
Reasoning: `select_resource` and `FulfillmentService.create` are, per
`pools-3`'s own diagram, meant to be called in sequence by one
orchestrator as part of one fulfillment step, not separated by
meaningful business time in the common case (see "Expected time between
scheduling and dispatch" below for the one real exception). A single row
answers "does this allocation have a settlement, and what state is it
in" with one lookup, keeps both services' idempotency checks on the same
primary key, and gives an admin one row to read per allocation instead of
reconciling two tables — the same auditability property already valued
in this codebase's lease-lifecycle design (`SiteAllocation`/
`CapacityReservation` merging the hold and the lease tail into one row
for the same reason).

```python
class SettlementRecordState(str, enum.Enum):
    assigned         = "assigned"          # scheduler picked a resource,
                                            # no dispatch yet. May persist
                                            # for a real, potentially long
                                            # window (see "Expected time
                                            # between scheduling and
                                            # dispatch" below) — but is NOT
                                            # mutable: a repeat
                                            # select_resource call for this
                                            # allocation_id is an ordinary
                                            # idempotent-retry-or-conflict
                                            # check, same shape as
                                            # FulfillmentService.create's.
                                            # See "Requirements change under
                                            # negotiation" below for how a
                                            # changed shape is actually
                                            # handled (a NEW allocation_id,
                                            # never mutation of this one).
    dispatch_pending = "dispatch_pending"  # about to call provider.create();
                                            # written durably BEFORE the
                                            # call, for crash recovery
                                            # (see point 2, commit <->
                                            # async-dispatch failure window)
    dispatching      = "dispatching"       # provider accepted the job;
                                            # tracking metadata recorded
    active           = "active"            # provider reports succeeded
    failed           = "failed"            # validation rejected, or
                                            # provider reports failed
    teardown_dispatch_pending = "teardown_dispatch_pending"  # about to
                                            # call provider.teardown();
                                            # written durably BEFORE the
                                            # call — teardown's analogue of
                                            # dispatch_pending, same
                                            # recovery-sweep treatment
    tearing_down     = "tearing_down"
    torn_down        = "torn_down"
    teardown_failed  = "teardown_failed"
    abandoned        = "abandoned"         # reservation expired/released/
                                            # was superseded while still
                                            # "assigned" — no physical work
                                            # was ever dispatched. Terminal,
                                            # not re-enterable: a rejected
                                            # (expired) CapacityReservation
                                            # blocks select_resource from
                                            # ever reaching this record
                                            # again, so select_resource
                                            # itself never needs to special-
                                            # case "abandoned" vs. "no
                                            # record" — the reservation
                                            # check upstream already
                                            # distinguishes them.


class SettlementRecord(Base):
    __tablename__ = "settlement_records"

    allocation_id = Column(String, ForeignKey("capacity_reservations.allocation_id"),
                            primary_key=True)
    agreement_id = Column(String, nullable=False)
    market = Column(String, nullable=False)
    pool_id = Column(String, nullable=False)
    settlement_resource_id = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    requirements = Column(JSON, nullable=False)   # for equivalence checks;
                                                    # IMMUTABLE once written —
                                                    # a changed shape gets a
                                                    # new allocation_id, see
                                                    # "Requirements change
                                                    # under negotiation"
    provider_metadata = Column(JSON, nullable=False, default=dict)
    teardown_provider_metadata = Column(JSON, nullable=True)
    state = Column(String, nullable=False, default=SettlementRecordState.assigned.value)
    created_at = Column(DateTime, ...)
    updated_at = Column(DateTime, ...)
```

### `select_resource` idempotency is uniform — no state-dependent mutation branch

An earlier draft of this review gave `state == "assigned"` a special,
mutable carve-out — repeat calls could overwrite `pool_id`/
`settlement_resource_id`/`requirements` to accommodate negotiation
changing the deal's shape before dispatch. **Resolved: this is wrong and
is removed.** See "Requirements change under negotiation" below —
allowing in-place mutation of an admitted reservation's shape is
dangerous (the held capacity may no longer correspond to what's
recorded, and it undermines the exact auditability property motivating a
single-row state machine in the first place). The correct handling is a
new `allocation_id` entirely, never mutation of this one.

With that removed, `select_resource`'s existing-record handling is
uniform regardless of `state`:

```python
existing = db.get(SettlementRecord, request.allocation_id, with_for_update=True)
if existing is not None:
    if _is_equivalent(existing, request):
        return existing.to_settlement_resource()   # idempotent retry
    raise SettlementRequestMismatchError(...)       # conflicting reuse

# No record yet — the only path that can ever write one.
allocation = self._require_valid_allocation(db, request)   # may raise
                                                              # CapacityReservationExpiredError
...
```

`CapacityReservation` expiry (`CapacityReservationExpiredError`) is
therefore checked **only** when no `SettlementRecord` exists yet for this
`allocation_id` — an allocation whose TTL lapsed after it was already
scheduled (or dispatched) must not have its retries start failing.

**If an operator requests scheduling against an already-expired
`CapacityReservation`, `select_resource` MUST reject it.** The storefront
handles that failure by requesting a fresh `CapacityReservation` (which
may itself fail if the physical picture changed in the interim) — this
is an existing, already-designed failure path in `pools-2`'s error
taxonomy, not new work. It is deliberately the storefront's
responsibility how long a hold it asks for; see "Pool-level reservation
TTL hint" below for an operator-side lever on that.

### `abandoned` state and the lease-lifecycle watchdog

A `CapacityReservation` can expire, release, or be superseded by a fresh
reservation (see "Requirements change under negotiation" below) while its
`SettlementRecord` is still sitting in `assigned` (nothing dispatched
yet) — this is expected to be a common way to reach this state, not the
exception. The existing watchdog that already sweeps expired/released
`CapacityReservation` rows (`LeaseLifecycleService.check_leases`) should
also transition any `assigned`-state `SettlementRecord` for that
allocation to `abandoned` — reusing the existing sweep rather than adding
a second, parallel watchdog. This is also the mechanism a supersede
resolves through: releasing the *old* `allocation_id`'s reservation after
a new one succeeds runs through this same release path, and its
`SettlementRecord` (if any existed) picks up `abandoned` the same way.
No capacity cleanup is needed as part of that specific transition:
`assign_settlement_resource` only ever moves *which* resource the
reservation's already-held units point at, and the reservation's own
release path already frees whatever resource it currently points to,
independent of whether a `SettlementRecord` was ever created. `abandoned`
exists purely for audit clarity, so a `settlement_records` row never sits
at `assigned` forever with no explanation of why it stalled.

### Expected time between scheduling and dispatch

Normally short — scheduling shouldn't happen until fulfillment is about
to occur, at which point there is little reason for delay between
`select_resource` and `FulfillmentService.create`. The gap that matters
in practice is between **reservation and scheduling**, not between
scheduling and dispatch — a `CapacityReservation` may sit unscheduled for
a long time and can expire before it's ever scheduled. A real (if
uncommon) case for delay between scheduling and dispatch specifically:
scheduling happening as part of agent lease negotiation itself, most
plausibly because the storefront calls `select_resource` *before*
finalizing price — the resource actually selected can be commercially
material (see "Storefront orchestrates scheduling and dispatch as
separate calls" below) — so a real window can open between "resource is
known" and "deal is finalized and dispatch is triggered." The
still-`assigned`, non-mutable design above accommodates this without
treating it as an error case: the record simply waits in `assigned`,
idempotently, until either dispatch or a supersede/release reaches it.

### Requirements change under negotiation: supersede, never mutate (design review continued, 2026-07-17; ordering corrected 2026-07-17)

**Resolved:** if a deal's requirements change after a
`CapacityReservation`/`SettlementRecord` already exists for it (still
`assigned`, not yet dispatched), the caller mints a **new**
`allocation_id`, reserves capacity for the *new* shape under it, and the
*old* `allocation_id`'s `CapacityReservation` is released as part of the
same atomic operation. Never mutates the existing reservation or
`SettlementRecord` in place.

**The mechanism is one atomic ledger transaction, not two independently-
committed calls in a chosen order.** An earlier version of this decision
proposed "reserve-new, then release-old" as two ordinary, separate
`reserve()`/`release()` calls specifically to guarantee the old
reservation survives if the new one fails. That ordering has a real
false-negative bug: evaluating the new shape's availability *before*
releasing the old reservation means the check runs against a view where
the old hold is still artificially consuming capacity — a resource that
would satisfy the new request the moment the old hold clears can
incorrectly report as unavailable, because that capacity is invisible
until release actually happens. Reversing the order (release-then-reserve)
would fix the visibility problem but reintroduces the original risk: a
failed re-reservation would leave the negotiation with nothing, since the
old reservation is already gone.

Both properties — the new shape's availability evaluated *as if* the old
hold were already released, and the old reservation left completely
untouched if the new shape can't be satisfied — are only simultaneously
achievable via one transaction that releases-then-reserves internally,
committing only on success and rolling back in full on failure:

```python
def resize_reservation(
    self, db, *, old_allocation_id: str, new_claim: dict, ttl_seconds: int,
) -> str:
    """Atomically supersede a CapacityReservation with a new shape."""
    with db.begin():
        old = self._require_active_reservation(db, old_allocation_id, for_update=True)
        self._release_locked(db, old)          # frees old's held units,
                                                  # visible only inside
                                                  # this open transaction
        resource, available = self._find_candidate(db, new_claim)  # now
                                                  # correctly sees the
                                                  # capacity old was
                                                  # holding
        if resource is None:
            raise CapacityUnavailableError(...)  # transaction rolls back
                                                    # in full — old's
                                                    # release is undone,
                                                    # nothing commits, old
                                                    # remains exactly as
                                                    # it was
        new_allocation_id = self._reserve_locked(db, resource, new_claim, ttl_seconds)
        if old_settlement_record_exists(db, old_allocation_id):
            # mark it abandoned synchronously, in this same transaction —
            # don't wait for the lease-lifecycle watchdog's next sweep
            self._mark_settlement_abandoned(db, old_allocation_id)
        return new_allocation_id   # committed atomically with everything above
```

Row locking (`for_update=True` on the old reservation, plus whatever
locking `_find_candidate`'s candidate resources already use) prevents a
concurrent transaction from grabbing the momentarily-freed capacity while
this transaction is still open. This generalizes the atomic-rebind
pattern `assign_settlement_resource` already uses (release source,
check/claim destination, atomically) to a case that pattern doesn't
already cover: there, source and destination are always *different*
physical resources (or a true no-op when identical), so the old hold
never blocks the new claim's availability check. Here, source and
destination can legitimately be the *same* resource or same pool — which
is exactly when the false-negative risk shows up.

This is also why the `select_resource` idempotency simplification above
is correct rather than a loss of capability: every "requirements changed"
case that used to motivate mutating a record in place is now a *new*
`allocation_id`'s first-time `select_resource` call, which the ordinary
(no existing record) path already handles.

### Pool-level reservation TTL hint — split out, see `pools-8`

Moved to `pools-8-capacity-projection-and-listing-hints` alongside the
listing-mode hint, per the scope-split decision below — same
`policy_tags`-hint shape and posture, not required for POOLS-7's first
pass.

## Commit <-> async-dispatch failure window: resolved (design review continued, 2026-07-17)

**Resolved: Option 1 (durable `dispatch_pending` state + startup recovery
sweep), not Option 2 (separate outbox table).** This was previously left
open pending verification of a specific assumption: that Option 1 is
only safe if the underlying provider's job-submission path is idempotent
on a deterministic key. That assumption did not hold as found, but the
fix needed to make it hold is small, so Option 1 stands once the fix is
in.

**Confirmed gap (by inspection, not assumed):** `AnsibleJobService.submit()`
already has a real, tested idempotency mechanism — it dedupes on
`(allocation_id, action_kind, idempotency_key)` via a DB uniqueness
constraint (`uq_ansible_jobs_contract_idempotency`), including correct
handling of the concurrent-race case (catches the `IntegrityError` from
a racing duplicate insert and returns the existing job rather than
erroring). But this path only activates `if contract is not None`.
`AnsibleFulfillmentProvider.create()` and `.teardown()`
(`services/ansible_fulfillment_provider.py`) both call
`self._job_service.submit(params, self._job_queue_provider())` with no
`contract` argument — so this dedup is bypassed entirely on the
fulfillment path today. Every call, retry or not, gets a fresh
`job_id = uuid4()` and inserts a new `AnsibleJob` row. A recovery sweep
naively retrying `create()` on a `dispatch_pending` `SettlementRecord`
would therefore genuinely double-dispatch a real `vm_create`/`vm_remove`
job, not safely no-op.

**Resolved fix:** `AnsibleFulfillmentProvider.create()`/`.teardown()`
construct an `ExecutorActionEnvelope` contract and pass it to
`job_service.submit()`, with `idempotency_key=f"{allocation_id}:create"`
/ `f"{allocation_id}:teardown"` — reusing the existing, already-migrated,
already-tested-elsewhere mechanism (the storefront's current direct-dispatch
path already builds equivalent keys) rather than introducing a new one.
See `specs/physical-provisioning/spec.md`'s new "Deterministic provider
dispatch idempotency" requirement for the normative statement of this.

With that fix in place, the recovery sweep is:

```python
# Provisioning service startup, alongside the existing schema-drift check
for record in db.query(SettlementRecord).filter_by(
    state=SettlementRecordState.dispatch_pending.value
):
    # Safe to retry unconditionally: submit() with a contract either
    # returns the original job (crashed after the DB write, before or
    # during the provider call) or genuinely submits it for the first
    # time (crashed before ever calling the provider). Either way,
    # exactly one AnsibleJob is ever dispatched for this
    # allocation_id/action_kind pair.
    await fulfillment_service.create(record.to_request(), record.to_settlement_resource())
```

This closes the dispatch half of the failure window (did the provider
call actually happen). The narrower remaining window — the provider call
succeeded but the follow-up DB write recording `state="dispatching"` and
the returned job id fails — is closed by the same sweep: a record stuck
at `dispatch_pending` whose retried `create()` call finds the deduped
existing job via the uniqueness constraint and simply needs its
`provider_metadata`/`state` written correctly, which `FulfillmentService.create()`
already does on any call, first or retried.

Option 2 (a separate outbox table with a consuming worker) is not
pursued: it would solve a problem this fix closes more cheaply by
finishing the wiring of a dedup mechanism that already exists in this
codebase, without changing `create()`'s synchronous-with-side-effect API
shape.

## `fill_first`/`most_available`: resolved (design review continued, 2026-07-17)

### `CapacityProjection` MUST NOT replace the live per-request snapshot these policies read

`fill_first`/`most_available` run inside `AggregateCapacityClient.probe()`/
`.reserve()`, choosing which site to try first for one specific,
in-flight request, via a live `_snapshots()` call at request time.
`CapacityProjection` (this file's earlier "`SiteResource` is retired"
section) is explicitly advisory/display-only, refreshed on its own pull
cadence, and can be stale by design — it exists for pricing/listing
publication, never for admission. **These MUST stay two separate
mechanisms**: `CapacityProjection` for display, live per-request
`_snapshots()` for routing. A stale `CapacityProjection` entry routing a
real reservation attempt toward an empty site would turn a display cache
into a load-bearing routing input, defeating the reason it's allowed to
be stale in the first place.

### Bug fix: `most_available` ignores `claim`

Confirmed: `most_available` accepts `claim` but never uses it —
`_site_available_units` sums every row's `available_units` regardless of
pool/resource/attribute match, so a site with capacity in an unrelated
pool can look "most available" for a request it cannot serve. Fix:

```python
# core/storefront/aggregation.py

def _resource_matches_claim(row: Mapping[str, Any], claim: Mapping[str, Any] | None) -> bool:
    """Best-effort client-side ranking hint only — NOT an enforcement
    point. Deliberately does not import kit/site (the aggregator is a
    storefront-process concept and must not depend on
    provisioning-service-internal packages); operates on the plain-dict
    snapshot() payload that crosses the HTTP boundary."""
    if not claim:
        return True
    attrs = row.get("attributes") or {}
    for key, expected in claim.items():
        if key in ("units", "gpu_count"):
            continue
        if attrs.get(key, row.get(key)) != expected:
            return False
    return True

def _site_available_units(snapshot, claim):
    return sum(max(int(r.get("available_units") or 0), 0)
               for r in snapshot if _resource_matches_claim(r, claim))
```

**Deliberately NOT sharing code with `kit/site`'s `_resource_matches` or
`PhysicalSettlementScheduler`'s `resource_satisfies_requirement`**, unlike
the earlier `pool_id`-mismatch and matching-logic-duplication fixes in
this document. Those two are enforcement/eligibility gates where drift is
a correctness bug (an admitted-but-unfulfillable reservation). This one
is a best-effort ranking hint that only affects *try order* —
`probe()`/`reserve()` on the chosen site remain the real, authoritative
check, and `AggregateCapacityClient.reserve()` already falls through to
the next site on refusal. A wrong ranking here costs one extra
round-trip, not an incorrect admission. Duplicating the shape of the
check across the HTTP process boundary is an acceptable, deliberate
trade-off in this one case — do not "fix" this later by forcing a shared
predicate across that boundary.

### No bundling with the `policy_tags` listing-mode hint

Considered and rejected: `ResourcePool.policy_tags` is a property of one
pool within one site; `fill_first`/`most_available` choose among *sites*
(different provisioning services). A pool-level preference does not
translate into a site-ranking signal without aggregating every pool's
hint across every site into one score — a materially different, later
feature, not a natural extension of this fix. The listing-mode hint stays
scoped to how the storefront *publishes* listings, never to placement
ranking.

### Layered ownership model (expanded per design review request)

Three genuinely distinct decisions, at three different times, owned by
two different processes, must not be conflated:

| Decision | Owned by | When | Mechanism |
|---|---|---|---|
| Which pool/resource a listing represents | Storefront | **Publish time** | Listing-mode hint (point 4) + `CapacityProjection`, baked into the listing's `offer_resource.pool_id`/`resource_id` at creation (POOLS-4) |
| Which site to route a reserve/probe call to | Storefront (`AggregateCapacityClient`) | **Reserve/negotiate time** | `fill_first`/`most_available`, live `_snapshots()` |
| Which concrete host within that pool fulfills the reservation | Provisioning service (`PhysicalSettlementScheduler`) | **Schedule time** | Deterministic round-robin (or later, a `pools-6` policy) |

`aggregation.py`'s own docstring already states the reasoning for the
second layer staying storefront-owned rather than moving into
`compute_provisioning`/kit alongside the third: *"pooling/placement is a
commercial judgment per seller... it lives in the storefront process, not
in a site and not in a shared service."* Nothing in this session's
`compute_provisioning`/kit consolidation work changes that — the second
and third layers pick among fundamentally different things (sites vs.
hosts within one already-chosen site) and are correctly already
separated by process boundary, not just by convention.

### Site fallback after POOLS-4

Site fallback remains meaningful only before a capacity reservation exists.
Once a storefront has selected a site and that site has created the capacity
reservation, scheduling and fulfillment MUST remain with that provisioning
authority. A site receiving an unknown capacity reservation, pool, or resource
identifier returns an error and MUST NOT reinterpret or forward it.

Not resolved here — flagged for planning. Before POOLS-4, a claim could
be a generic attribute shape (`region`, `gpu_model`, `gpu_count`) with no
`pool_id`/`resource_id`, so the same claim could legitimately match
equivalent fungible capacity at more than one site, and trying sites in
ranked order with fallback-on-refusal made sense. POOLS-4 now requires
every listing's claim to carry `pool_id` and/or `resource_id`
("unscoped claims are invalid"), and `pool_id`/`resource_id` are only
unique **within one site** (this file's `CapacityProjection` section).
Once a specific listing is published, its pool/resource identity — and
therefore its owning site — is already fixed at publish time (the first
row of the table above). Trying that *same, now-pinned* claim against a
second site's `reserve()` will almost always find no matching pool/
resource there at all (a coincidental name collision aside), rather than
legitimately finding equivalent capacity elsewhere the way it could
pre-POOLS-4.

This suggests `AggregateCapacityClient`'s try-in-order-with-fallback
behavior may now be effectively vestigial for pool/resource-pinned VM
listings — the real routing decision for a specific deal may just be
"look up the one site this listing's pool/resource is known to live at"
(deterministic, since every row crossing the HTTP boundary is already
site-tagged — `_tagged(site, payload)`), not "try each site in ranked
order." Whether to keep the ranked-fallback code path for a
still-possible generic/unpinned case, special-case pinned claims to route
directly by known site, or something else, is not decided here — this is
a question for planning, not resolved by this design review.


## Listing-mode hint consumption — split out, see `pools-8`

Moved to `pools-8-capacity-projection-and-listing-hints` in full (schema,
`resolve_vm_listing_mode`/`resolve_apicredits_listing_mode`,
extensibility argument, enforcement posture), per the scope-split
decision below — it depends on `CapacityProjection` carrying
`policy_tags`, which is no longer this change's scope.

## Scope split: `CapacityProjection` and hints move to `pools-8` (design review continued, 2026-07-17)

**Resolved:** `CapacityProjection`, the listing-mode hint, and the
pool-level reservation TTL hint move to a new change,
`pools-8-capacity-projection-and-listing-hints`. Reasoning: this change
is already large (`site_resource_pools`/`CapacityReservation`/
`SettlementRecord`/scheduler-and-fulfillment orchestration/idempotent
dispatch/release-path wiring), and `CapacityProjection` is a materially
separate subsystem — pull schedules, freshness, multi-site keys,
publication reactions, its own storage and migrations — not inherently
part of the fulfillment-cutover mechanics. The two hints depend on
`CapacityProjection` carrying `policy_tags`, so they move with it.

**This split has a real consequence, not a free one, and it must stay
visible rather than be quietly absorbed:** this change's "`SiteResource`
is retired" fix makes `site_resource_pools`/`PhysicalSettlementScheduler`
correctly source `pool_id` from `hosts`/`resource_pools` — closing the
provisioning-service side of the original `pool_id`-namespace bug this
whole review started from. But the storefront's own claim-building
(`vm_job_spec_service.py`) still sources the `pool_id`/`resource_id` it
puts into a reservation request from the storefront's local, independently-
authored inventory today. Until `pools-8` lands and actually replaces
that local table with `CapacityProjection`, the storefront can still send
claims naming pool/resource identities that don't correspond to anything
real — which, after this change's fix, now fails cleanly at admission
(a real `NoEligibleSettlementResourceError`/similar) instead of silently
matching the wrong thing. That's strictly better than today's silent
mismatch risk, but it is not the same as the bug being fully closed
end-to-end. `pools-7`'s `proposal.md` Dependencies section should state
this plainly: `pools-7` alone fixes provisioning-side correctness;
`pools-8` is required for the storefront to reliably send valid claims.

## Storefront orchestrates scheduling and fulfillment as separate calls

The storefront owns progress through negotiation, site/pool selection,
capacity reservation, resource scheduling, and the decision to begin
fulfillment. The provisioning service does not receive agreement or negotiation
identity.

Two required operations remain separate because the selected physical resource
may be commercially material before fulfillment begins:

1. **`schedule_resource(capacity_reservation_id, requirements)`** — selects
   and durably assigns a settlement resource without executing a provider.
2. **`begin_fulfillment(capacity_reservation_id, request)`** — accepts the
   already-scheduled reservation and returns a durable `fulfillment_id`.

A thin convenience operation may compose them for callers that do not need the
selection preview, but it MUST use the same two application paths. After
acceptance, fulfillment status and whole-fulfillment teardown are addressed by
`fulfillment_id`; provisioned outputs receive neutral
`provisioned_resource_id` values rather than exposing VM-specific identity as
the generic contract.

## Transaction boundary and shared package ownership

`assign_settlement_resource` (capacity rebind) and settlement-record
creation/transition MUST share one database transaction. A sequence that moves
capacity, commits, and then inserts the settlement record is not acceptable.
The same atomic rule applies when abandonment releases or supersedes reserved
capacity.

The shared lifecycle and concrete reusable SQLAlchemy implementation live in a
new `kit/fulfillment` package, not `kit/resource-pools` and not the
base `compute_provisioning` package. The kit owns domain-neutral scheduling,
fulfillment persistence, repository, recovery-claim, provisioned-resource, and
durable result state read by the pull query API; v1 has no result-delivery
outbox. The extracted compute provisioning service composes the shared metadata
into its database, owns the migration, API, and worker composition, while the
VM provisioning adapter supplies VM/Ansible behavior.

## Provider input snapshot: prepare/dispatch split (design review continued, 2026-07-17)

Concretizes a principle this file already stated in passing ("Accepted
provider configuration," above) without a mechanism. **Resolved:** the
provider prepares its execution input synchronously, before the
transaction that marks a record `dispatch_pending` commits; dispatch
itself happens after commit, against the already-prepared, now-durable
input — not by re-reading live pool/host configuration during a recovery
retry.

```python
prepared = provider.prepare_create(request, resource, pool_config)
# `prepared` is a serializable, normalized representation of exactly what
# will be submitted — stored on the SettlementRecord (or a related column)
# as part of the same transaction that sets state=dispatch_pending.
...
await provider.dispatch_create(prepared)   # post-commit; safe to retry
                                             # via the recovery sweep using
                                             # the SAME stored `prepared`
                                             # value, never a fresh read
```

This is what makes the recovery sweep (point 2) correct against a pool
edited or deleted *after* a record was accepted: accepted work is
insulated from later configuration changes because it dispatches from a
frozen snapshot, not a live re-read.

## Recovery sweep: periodic, not startup-only (design review continued, 2026-07-17)

**Resolved:** the `dispatch_pending`/`teardown_dispatch_pending` recovery
sweep (point 2) runs periodically, not only at process startup. A
startup-only sweep misses the case where a provider call fails
transiently (e.g. a network blip to the Ansible controller) while the
process keeps running — that record would never be retried until the
next restart. Same query, same idempotent-retry logic as the startup
sweep; just scheduled periodically instead of once. Concurrent-claim safety
(claiming rows so overlapping claim attempts — within one process's cycle,
across a `Recreate` pod-replacement window, or from a second instance run
for diagnosis — don't double-process the same record) is required
regardless of whether the sweep is startup-only or periodic. SQLite has no
`SELECT ... FOR UPDATE SKIP LOCKED`; the claim itself is a short,
self-contained write transaction instead (see the Section 6 resolution
below). Left for planning to specify concretely at the time this note was
written; resolved in Section 6, "Claim primitive."

## Active allocation backfill during cutover

The migration uses a uniform backfill rather than a long-lived legacy release
branch or an operator-managed cutover marker. Existing hosts are first placed
in the default resource pool. Every active or releasing VM capacity reservation
then receives a settlement/fulfillment record with the selected resource,
Ansible provider, and versioned teardown input inferred from the durable fields
the current release path already uses (`vm_host`, `vm_target` or
`executor_target`, and executor identity).

Historical create input may be absent for already-running VMs. The migration
fails visibly when an active reservation cannot be mapped unambiguously and
need not fabricate records for terminal expired VMs without a retention use
case.

## Final planning decisions (design review completed 2026-07-20)

This section is authoritative where it conflicts with earlier chronological
review notes in this document.

### Cross-domain identities and terminology

The provisioning boundary is capacity-reservation-centric and MUST NOT carry
storefront commercial identities such as negotiation, buyer, deal, or
agreement identifiers.

- `allocation_id` is renamed broadly to `capacity_reservation_id`.
- `capacity_reservation_id` identifies the admitted capacity and is the
  idempotency boundary for scheduling and `begin_fulfillment`.
- `begin_fulfillment` returns a durable `fulfillment_id` identifying the
  post-acceptance provisioning lifecycle aggregate.
- A fulfillment may produce zero or more `ProvisionedResource` records, each
  with a globally unique `provisioned_resource_id` and an optional
  domain-specific `domain_resource_ref` such as a VM ID or pod UID.
- `settlement_resource_id` identifies the selected underlying physical supply
  resource. It is not the provisioned VM/pod identity.
- Whole-fulfillment status and teardown use `fulfillment_id`. The schema MUST
  support multiple provisioned resources. Per-resource teardown is a future
  extension unless implementation discovers a current caller that requires it.
- Public APIs use fulfillment-specific verbs such as `schedule_resource`,
  `begin_fulfillment`, `get_fulfillment_status`,
  `get_fulfillment_result`, and `begin_fulfillment_teardown`. “Dispatch” is
  retained only as an internal provider-command term.

A capacity reservation is owned by exactly one provisioning authority. Once a
reservation exists there is no cross-site fallback: an unknown reservation,
pool, or resource identifier is rejected rather than reinterpreted or
forwarded. Pool, resource, reservation, fulfillment, and provisioned-resource
identifiers MUST be globally unique opaque identifiers. Planning may select
UUIDv7 after reviewing repository conventions; ownership is carried by
explicit fields rather than encoded into identifier strings. Requirements MUST
also review whether any site-plus-pool composite identity is needed for
routing or integrity.

**`site_id` is a storefront-only concern, not provisioning-service schema:**
`site_id` is owned at the storefront aggregation boundary, bound to an
operator-configured provisioning connection — never read from or trusted
from a provisioning service's own report of itself, since a provisioning
service is not a trustworthy authority over its own identity (a
counterparty could otherwise spoof another site's identity). Provisioning
services' own capacity persistence is already scoped by that service's
database authority and does not duplicate the storefront-owned identity on
every pool, resource, or reservation row. See
`openspec/specs/storefront-publication/spec.md`, "Trusted provisioning-site
identity," for the enforced requirement and scenario, and
`docs/development/ARCHITECTURE.md`, "Site inventory, capacity accounting,
and projections," for where this sits repository-wide.

### Shared package boundary and kit dependency layers

Create a new `kit/fulfillment` package with distribution name
`arkhai-kit-fulfillment` and import package `market_fulfillment`. “Fulfillment”
is the repository package name; “physical settlement” remains the broader
architectural process covering scheduling, fulfillment, teardown, and physical
capacity reclamation. The package is intentionally separate from both
`kit/resource-pools` and the base `compute_provisioning` package.

Kit packages have explicit dependency layers:

1. **Foundation:** identity, configuration, policy primitives, and other
   packages that do not depend on site, pool, or fulfillment capabilities.
2. **Capability authorities:** `kit/site` and `kit/resource-pools`. These own
   physical capacity/reservations and resource-pool administration
   respectively, and may depend only on foundation packages.
3. **Provisioning lifecycle:** `kit/fulfillment`. It may depend on the site and
   resource-pool authorities and on foundation packages. Neither authority
   package may import `market_fulfillment`, and no kit package may import a
   deployed service or domain adapter, including under `TYPE_CHECKING`.

`kit/fulfillment` owns domain-neutral settlement and fulfillment lifecycle
types, `FulfillmentProvider`/`ProviderRegistry` and provider-neutral result and
status contracts, scheduler/policy code, versioned prepared-operation
contracts, SQLAlchemy mappings and generic repositories, transition
validation, recovery-claim infrastructure, provisioned-resource records, and
durable result state read by pull queries. `kit/resource-pools` retains only
resource-pool configuration, membership, and administration concerns. Moving
provider contracts into `kit/fulfillment` removes the existing reverse
`market_resource_pools -> compute_provisioning` type dependency without
replacing it with a new cycle.

Pure contracts and operational services remain in one distribution for now,
separated by modules. Contract/carrier modules must not import concrete site or
resource-pool services; scheduler and persistence modules may import the lower
layer authorities. A separate contracts/runtime distribution is deferred until
a real consumer, heavyweight dependency, independent-versioning need, or
remaining cycle requires it. Intentional plugin points such as scheduling
policies and fulfillment providers use protocols; stable internal authority
services may remain concrete dependencies rather than receiving duplicative
protocol facades solely for testability.

The concrete SQLAlchemy implementation belongs in the shared kit when it is
genuinely reusable across domains; services compose the shared metadata and
apply migrations in their own databases. V1 does not add result-delivery outbox
models. VM-specific Ansible providers and operator routes remain in the VM
provisioning adapter; generic fulfillment APIs, worker composition, and
service-owned migrations remain in the extracted compute provisioning service.

All touched Python projects use repository-local wheels from `.dist` for
internal dependencies. They must not add editable relative-path sources that
force repository-root Docker build contexts. Reinit targets build/install the
required internal wheels and explicitly upgrade/reinstall them from `.dist`.
The aggregate kit test target runs every kit subproject's default test suite and
must prepare its wheel dependencies deterministically rather than relying on a
stale `.dist` directory.

### Scheduling and fulfillment boundary

The storefront owns progress through negotiation, site/pool selection,
capacity reservation, physical-resource scheduling, and the decision to begin
fulfillment. The provisioning service only needs the local
`capacity_reservation_id` and scheduling requirements, which MUST NOT exceed
the admitted reservation.

Scheduling and fulfillment remain separate calls because the selected physical
resource may be commercially material before fulfillment begins. Scheduling
atomically rebinds capacity, where fairness requires it, and creates the
immutable assigned settlement record. A changed requirement supersedes the
reservation; it never mutates an accepted assignment under the same
`capacity_reservation_id`.

Once `begin_fulfillment` is durably accepted, the provisioning service owns all
forward progress: provider-command submission, recovery, provider-status
convergence, provisioned-resource persistence, settlement-result delivery,
teardown, and final physical-resource reclamation. The storefront is not
responsible for polling a provider job to advance this lifecycle.

### Settlement and fulfillment persistence

There is one durable settlement/fulfillment aggregate per capacity reservation.
Equivalent retries return the existing aggregate; conflicting reuse fails
before provider submission. State transition validation is implemented through
a compact table-driven service mechanism rather than stored procedures or a
method for every edge.

`assign_settlement_resource`, settlement creation/transition, and any
reservation capacity movement MUST share one database transaction. Likewise,
transitioning an unfulfilled assigned settlement to `abandoned` and releasing
or superseding its capacity reservation MUST be atomic. Lease lifecycle code
performs the transition directly where possible; watchdog processing is a
reconciliation backstop.

Prepared provider create and teardown payloads are normalized, serializable,
and versioned. Any generic dictionary persisted durably or sent cross-domain
MUST carry a schema version and kind discriminator. Provider input is frozen
before committing a pending provider-command state and is never reconstructed
from mutable live pool configuration during retry.

### Active-allocation migration and backfill

POOLS-7 performs a comprehensive breaking migration suitable for independently
operated sites without lease-expiry coordination instructions.

1. Existing hosts are migrated into a default resource pool and corresponding
   resource/pool membership records.
2. Every active or releasing VM capacity reservation is backfilled with a
   durable settlement/fulfillment record.
3. The migration derives selected resource, provider identity, and versioned
   teardown input from the same durable fields the current release path uses
   (`vm_host`, `vm_target`/`executor_target`, and executor identity).
4. Historical create input may be absent for already-active backfilled
   fulfillments; this does not prevent status representation or teardown.
5. Rows are marked as backfilled for auditability.
6. The migration fails loudly when an active reservation cannot be mapped
   unambiguously; it does not create a silently incomplete teardown record.
7. Historical terminal/expired allocations need not be fabricated unless a
   separate retention requirement exists.

After successful migration, no long-lived legacy release branch or operator
cutover marker is required.

### Provider recovery and lifecycle convergence

Pending provider commands are claimed in short transactions using a
concurrent-claim-safe claim/lease pattern (defense-in-depth under SQLite's
single-writer contract — see Section 6, "What 'multi-replica-safe' means
against this service's actual deployment topology"). Database locks are
released before any long-running external provider call. Recovery uses
bounded batches,
exponential backoff with jitter, claim expiry after worker death, and
idempotent deterministic provider command identities.

The watchdog framework has logically separate handlers for create-command
submission/recovery, provider-status convergence, teardown
submission/recovery, and abandonment reconciliation — no separate
result-delivery handler in v1, since `get_fulfillment_status`/
`get_fulfillment_result` are pull-based reads with no background delivery
work to recover (see below). Records in both pending and in-progress
states converge without depending on the storefront prompting recovery —
unrelated to, and unaffected by, the pull-vs-push question for result
delivery specifically.

### `SettlementResult` delivery: pull for v1, push deferred to a separate change

**Revised (2026-07-21):** the durable, atomic, push-based outbox design
below this note's replacement is **not implemented in POOLS-7**. Reason:
pushing `SettlementResult` requires an authenticated provisioning→storefront
channel that doesn't exist in this codebase today — every existing trust
relationship is storefront→provisioning (one shared `admin_api_key` per
site; `StorefrontAuthMiddleware`'s own docstring: *"the provisioning
service is an internal dependency of a single storefront"*). Designing
that new channel properly — including that one storefront authenticates
pushes from *N* distinct provisioning services, not a single symmetric
secret — is real scope on its own, and doing it inside POOLS-7 risked
scope creep onto an already-large change. It's split into its own
change: `provisioning-result-push-delivery` (not yet started). POOLS-7
keeps the goal in view but ships pull for v1, on the existing, already-
solved storefront→provisioning auth direction.

**What this changes, precisely — the resilience goal is not abandoned,
only the transport is:**

- `get_fulfillment_status(fulfillment_id)` and
  `get_fulfillment_result(fulfillment_id)` become real, storefront-callable
  read endpoints, using the existing auth direction. Both read directly
  from the durably persisted fulfillment/settlement aggregate (section 3
  of this file) — there is no separate outbox table for these two calls,
  because a read endpoint has nothing to retry-until-acknowledged; the
  storefront just calls again if it wants fresher information. This
  drops the delivery-worker/retry-with-backoff/acknowledgement machinery
  from the design entirely — it existed to solve a push problem
  (provisioning doesn't know if a push it can't observe an ack for
  landed) that a pull model doesn't have.
- **Credentials are fetched on read, not pre-fetched and queued.**
  `get_fulfillment_result`'s handler itself obtains or refreshes
  credentials at the moment it's called, returns them in that response,
  and does not persist them — same never-at-rest posture as the original
  push design, just triggered by the storefront's request instead of a
  background worker's schedule. This preserves "raw credentials MUST NOT
  be persisted" without needing an outbox at all.
- **`credential_generation` is dropped from this section's scope, not
  carried forward.** (Revised 2026-07-25.) The original rationale assumed
  a rotation source to detect staleness against. There isn't one: VM
  tenant credentials are created once at provisioning time and never
  rotated by this codebase — rotation, if it ever happens, is a
  site-administrator, out-of-band action against the host, invisible to
  the provisioning service. Since `get_fulfillment_result` always fetches
  live and never caches, every response is authoritative at read time by
  construction, so there is no cross-call credential staleness for a
  generation counter to detect here. Shipping the field anyway (e.g. as a
  constant) would overclaim a capability this system doesn't have and
  invite a caller to build staleness logic against a signal that never
  changes. If `provisioning-result-push-delivery` still needs a
  `credential_generation` concept for its own retry-race problem (a stale
  push overwriting a newer one — a real problem pull doesn't have), it
  defines and justifies that field itself against its own transport, not
  by inheriting this note.
- **Durable, atomic result *persistence* is unaffected** — a terminal or
  otherwise reportable fulfillment transition still commits atomically
  with whatever `SettlementResult`-shaped data `get_fulfillment_result`
  will later read (this file's "Transaction boundary" decisions,
  unchanged). What's dropped is only the *delivery* half (push worker,
  outbox-as-delivery-queue, ack tracking) — not the durability half.
- Raw job polling of the old executor path is still removed, per
  "Breaking cleanup scope" below — this is the old, VM-job-shaped
  polling being retired, not a re-introduction of it under a new name.
  `get_fulfillment_status`/`get_fulfillment_result` poll a normalized,
  durable, cross-domain fulfillment abstraction, not a raw Ansible job.

When `provisioning-result-push-delivery` lands, it adds a push transport
*alongside* pull (pull is a reasonable permanent reconciliation backstop
even after push exists, per point 2's earlier discussion of exactly this
concern) — it does not need to redesign the durable persistence layer
built here, only add the new auth channel and a delivery worker that
reads from the same already-durable state.

### Breaking cleanup scope

This work item is approved for broad schema cleanup. Planning and implementation
MUST include coherent renames and removal of superseded paths rather than
preserving ambiguous compatibility names indefinitely, including:

- `SiteAllocation` to `CapacityReservation`;
- `allocation_id` to `capacity_reservation_id`;
- retirement/replacement of `SiteResource` where the final host, pool,
  membership, and reservable-capacity model requires it;
- globally unique identifiers and explicit site ownership;
- removal of direct storefront executor submission and polling;
- replacement of the old release path after backfilled settlement teardown is
  operational;
- corresponding API/client/schema/fixture/test/architecture changes.

## Section 2 projection synchronization decisions (2026-07-22)

The provisioning service owns the authoritative resource-pool and capacity
projections consumed by the storefront. Section 2 establishes live pull-based
synchronization; Section 3 adds durable storefront persistence and restart
recovery for the accepted projection state. A later POOLS change may replace or
augment polling with push invalidation or incremental synchronization.

### Projection identity and drift detection

Each canonical projection snapshot MUST carry a monotonically increasing
`revision` and a deterministic whole-snapshot `digest`. The storefront compares
this identity in constant time to decide whether a full resynchronization is
required. A Merkle tree is intentionally deferred because Section 2 performs
whole-snapshot replacement rather than branch-level reconciliation.

Digest input MUST use canonical encoding: records and map keys are ordered by
stable identifiers, numeric values are normalized, absent and null values have
deliberate distinct meanings, and volatile fields are excluded unless they are
part of the projection contract. The lightweight version response and full
snapshot response MUST describe the same committed projection generation.

The storefront MUST build and validate a replacement generation before
atomically swapping it into active use. Requests MUST observe either the prior
complete generation or the replacement complete generation, never a partially
mutated cache. Failure to poll or refresh MUST NOT erase the last known
projection; freshness and last-error state remain distinguishable from an
authoritatively empty projection.

Topology-sensitive reservation or scheduling failures MAY trigger one bounded,
coalesced projection-identity check. A changed identity causes resynchronization.
Arbitrary provider failures MUST NOT trigger refresh storms, and a state-changing
authoritative request MUST NOT be retried automatically without an established
idempotency contract.

### Minimized Section 2 delivery boundary

Section 2 MUST:

- derive authoritative resource-pool and capacity projections from provisioning
  inventory rather than storefront-authored synchronization;
- expose canonical projection revision and digest identities;
- load projections into the storefront at startup;
- poll identities and atomically refresh changed projections;
- perform bounded drift checks for topology-sensitive authoritative failures;
- remove the storefront-to-provisioning host/resource push synchronization path.

Section 3 owns durable storefront connection identity, persisted projection
generations, restart restoration, and stale-state readiness behavior.

### Distinct pool and capacity projections

The storefront requires two related but non-equivalent views:

- a resource-pool projection describing site-to-pool membership and the
  underlying domain resources used by listing modes that publish concrete
  resources such as hosts;
- a capacity projection describing reservable multidimensional capacity used by
  listing modes that publish fungible capacity rather than concrete resources.

The remaining Section 2 design MUST preserve this distinction. A capacity-ledger
entity MUST NOT replace the resource-pool projection, and a projected physical
resource identifier MUST NOT be exposed on the storefront `CapacityReservation`
unless it is durable and commercially meaningful.

## Design promotion record

This record maps accepted durable decisions to current-state documentation. It is change history; the destination documents contain the normative present-tense contract.

| Accepted decision | Permanent location |
|---|---|
| Kit follows foundation → authority → fulfillment dependency layers | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| Scheduling and provider-neutral fulfillment contracts share `kit/fulfillment` | `openspec/specs/fulfillment/spec.md#ownership` |
| Lower authority kits may not import fulfillment, including under `TYPE_CHECKING` | `openspec/specs/fulfillment/spec.md#dependency-boundary` |
| Capacity reservation, fulfillment, settlement-resource, provisioned-resource, and result IDs are opaque UUIDv7 strings | `openspec/specs/fulfillment/spec.md#identities` |
| Commercial agreement identity stays outside the generic physical settlement request | `openspec/specs/fulfillment/spec.md#physical-settlement-request` |
| Multidimensional candidate fit treats missing dimensions as zero | `openspec/specs/fulfillment/spec.md#multidimensional-eligibility` |
| Scheduling selects a resource before provider execution; providers do not substitute placement | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| Cross-domain/durable generic payloads use immutable versioned envelopes | `openspec/specs/fulfillment/spec.md#versioned-envelopes` |
| Internal dependencies are installed from `.dist`, not editable sibling paths | `openspec/specs/deployment-state/spec.md#internal-wheel-development-contract` |
| Aggregate kit tests run every kit subproject suite | `openspec/specs/deployment-state/spec.md#internal-wheel-development-contract` |
| Provisioning-private capacity buckets and current reservation debits back reservations without leaking placement identity | `openspec/specs/site-capacity/spec.md#requirement-capacity-accounting-is-private-to-the-site-authority` |
| Physical inventory and vertically grouped capacity are independent pull projections | `openspec/specs/site-capacity/spec.md#requirement-physical-inventory-and-grouped-capacity-are-separate-projections` |
| Storefront projection caches load at startup, poll independent identities, retain stale complete generations, and refresh reactively without automatic mutation retry | `openspec/specs/storefront-publication/spec.md#requirement-storefronts-cache-independent-site-projections` |
| Repository-wide projection ownership and allocation boundary | `docs/development/ARCHITECTURE.md#site-inventory-and-capacity-projections` |
| One settlement/fulfillment aggregate keyed by `capacity_reservation_id`; `fulfillment_id` is a generated column, not a second key | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Scheduling equivalence and fulfillment equivalence are two independent, separately-persisted checks | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| No persisted `SettlementResult`; results are a read-time projection over the aggregate and its provisioned resources | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Recovery-claim fields live on the aggregate row, not a separate claims table | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| The scheduled market is immutable and every fulfillment acceptance must match it | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Settlement persistence documents and tests SQLite transaction guarantees rather than portable row-lock claims | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Recovery selection in Section 3 is provisional; Section 6 (recovery and lifecycle convergence, renumbered 2026-07-23) owns the final operational claim protocol | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Generic lifecycle updates are limited to the shared mutable lifecycle payload and cannot alter aggregate invariants | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Repository callers provide validated canonical models; persistence performs structural JSON equality rather than arbitrary-input canonicalization | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| `CapacityLedgerService` session-accepting entry points let a higher-layer caller compose one transaction across reservation state and settlement assignment | `openspec/specs/site-capacity/spec.md#relationship-to-fulfillment-scheduling` |
| `schedule_resource` is one atomic transaction (lock, enumerate, select, rebind, persist, commit/rollback together), replacing separate self-committing calls | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Round-robin fairness state is durable and scoped per `resource_kind`, read/written in the same transaction as the settlement record; the scheduling policy itself stays a pure function with no database access | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Scheduling's SQLite concurrency contract (single-writer `BEGIN IMMEDIATE`, not portable row locks) matches fulfillment acceptance's existing contract | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Scheduling uses a narrow transaction-scoped persistence boundary over the existing repositories; deterministic database-concurrency tests instrument that semantic boundary with independent sessions and explicit barriers | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`; `docs/development/ARCHITECTURE.md#deterministic-database-concurrency-tests` |
| `resize_reservation` supersedes a reservation via one self-managed-session transaction (release-then-reserve, never two independently committed calls); no `_in_session` twin is built without a real co-transactional caller | `openspec/specs/site-capacity/spec.md#requirement-reservation-supersede-and-settlement-abandonment` |
| `SettlementAbandonmentHook` is called unconditionally from every capacity-reclaiming path (TTL lapse, release, resize); `market_site` never imports `market_fulfillment` to implement it | `openspec/specs/site-capacity/spec.md#requirement-reservation-supersede-and-settlement-abandonment` |

### Section 2 projection naming and capacity aggregation decisions (2026-07-22)

The storefront projection table mapping a storefront-owned `site_id` to the
resource pools available through that site remains named `site_resource_pools`.
The projection role is documented by the surrounding contract and ownership
rules rather than encoded redundantly in the table name. Resource-pool records
contain the physical inventory facts required by listing modes that publish
individual resources.

The capacity-oriented projection is named `site_capacity_buckets`. It is a
storefront projection of currently advertisable multidimensional capacity and
is distinct from both physical inventory and the provisioning service's
internal reservation-accounting records.

Resource-pool and capacity projections have fully independent revisions and
digests. A change to one projection MUST NOT require advancing the identity of
the other when its canonical content is unchanged. The storefront polls and
refreshes each projection independently and atomically installs each complete
replacement generation.

The storefront-facing `CapacityReservation` MUST NOT expose the provisioning
service's internal capacity-accounting identifier or an initially selected
physical resource. Its durable public facts are the opaque
`capacity_reservation_id`, lifecycle status, expiry, reserved dimensions, and
other negotiation-relevant metadata. Physical placement remains non-durable
until settlement assignment.

The provisioning service uses one internal capacity bucket per host for the VM
domain. The current model assumes each host belongs to one resource pool. A
`CapacityReservationDebit` row associates a reservation with the internal
capacity bucket and records the governed dimensions currently debited. Only the
current debit mapping is required; Section 2 does not introduce append-only
ledger semantics.

The projected `site_capacity_buckets` view MAY vertically aggregate physical
resources that currently have identical capacity and listing-relevant
attributes. For example, sixteen equivalent hosts with eight available H100s
may be represented as one projected bucket with `resource_count = 16`; after a
reservation changes one host to seven available H100s, the projection becomes
one bucket for fifteen hosts at eight and one bucket for one host at seven.

Vertical aggregation MUST NOT discard the information required to create
individual-resource listings. The resource-pool projection remains the source
of per-resource identity and listing attributes. Each aggregated capacity
bucket therefore carries a deterministic grouping key or equivalent matching
criteria that can be joined to the matching members of `site_resource_pools`.
The capacity projection does not need to expose internal capacity-bucket IDs.

Section 3 owns durable persistence for both projection families and their
independent accepted revisions. The Section 2 schema cutover uses the approved
create-copy-validate-switch-retire strategy once the final internal capacity
bucket and projection schemas are settled.

### Final Section 2 capacity projection decisions (2026-07-22)

Projected `site_capacity_buckets` rows use a deterministic digest-derived
`capacity_group_key` computed from canonical grouping criteria and normalized
capacity dimensions. The key identifies an equivalent capacity shape without
embedding projection revision or physical-resource identity; projection
revision and digest identify the snapshot in which the group appears.

An aggregated capacity bucket contains only canonical grouping criteria,
normalized capacity dimensions, and the count of matching physical resources.
It MUST NOT duplicate the full list of matching physical-resource identifiers.
Individual-resource listing modes enumerate matching inventory from
`site_resource_pools` by applying the same canonical grouping vocabulary and
normalization rules.

The three capacity layers are distinct:

1. authoritative physical inventory and pool membership;
2. provisioning-private host-level `CapacityBucket` rows and current
   `CapacityReservationDebit` mappings used for admission and rebinding;
3. storefront `site_capacity_buckets` rows vertically aggregated for listing
   and negotiation.

Grouped projected capacity is never an allocation target. Reservation admission
MUST select and debit an eligible internal host-level `CapacityBucket`.
Scheduling MAY atomically rebind a reservation by validating a replacement
bucket, replacing the current debit row, and assigning the settlement resource.
The storefront remains unaware of both the initial and replacement internal
bucket identities.

The final Section 2 schema cutover uses create-copy-validate-switch-retire:
create the replacement inventory projection, capacity-bucket, debit, and
capacity-projection structures; derive authoritative rows; migrate active
reservation debits; reconstruct and validate capacity invariants; switch the
repositories; and retire `SiteResource` only after validation succeeds.

## Section 3 settlement persistence design decisions (2026-07-22)

Resolves ambiguities identified while planning `tasks.md` Section 3 ("Add
shared settlement persistence"). The earlier "`SettlementRecord` shape" and
"Final planning decisions" sections above were written at different times and
do not, on their own, fully specify the aggregate's identity shape or its
equivalence-check scope. This section is authoritative where it adds detail
those sections left implicit.

### Aggregate identity: one row keyed by `capacity_reservation_id`

The durable aggregate's primary key is `capacity_reservation_id`, not
`fulfillment_id` — consistent with task 3.4 ("enforce one fulfillment
aggregate per `capacity_reservation_id`") and the earlier "one row, one state
machine" decision. `fulfillment_id` is a nullable-until-accepted, unique
column on that same row, generated the first time `begin_fulfillment`
transitions the row past `assigned`. An idempotent `begin_fulfillment` retry
returns the stored value rather than regenerating it. This is accepted as a
soft commit: if fulfillment-side bookkeeping later needs materially more
metadata than fits one row, that is new evidence to reopen this, not a reason
to design around it now.

### Recovery-claim fields live on the aggregate row

Multi-replica claim/lease fields (`claimed_by`, `claim_expires_at`, an attempt
counter) are columns on the aggregate row, not a separate claims table. One
aggregate has at most one pending provider operation at a time, so a separate
table would only add a join with no independent-claiming benefit.

### Prepared provider input uses the existing versioned-envelope pattern

`prepared_create_operation` and `prepared_teardown_operation` are
`VersionedEnvelope`-typed JSON columns on the aggregate, populated once each,
before the transaction that marks the corresponding `*_dispatch_pending`
state commits (per "Provider input snapshot: prepare/dispatch split" above).
This is the same envelope contract already defined in
`market_fulfillment.envelopes`, extended to a new payload kind rather than
introducing a second versioning mechanism.

### No persisted `SettlementResult`

`get_fulfillment_result` (task 8.2) is a computed projection over the
aggregate's current state/failure fields and its `ProvisionedResource`
children, read on demand — it is not backed by its own persisted result row.
Persisting a `SettlementResult`-shaped object independently of the aggregate
would create a second place credential-adjacent data could live; since
credentials are fetched live and never persisted (see "`SettlementResult`
delivery" above), and there is no `SettlementResult` CRUD API planned, there
is no case that needs it durable on its own. The versioned-envelope
requirement for "settlement/fulfillment result payloads crossing a durable
boundary" is satisfied by `provider_metadata`/`teardown_provider_metadata`,
which already cross that boundary; it does not require inventing a
result object solely to have something to envelope.

### Two separate persisted requirement shapes, two separate equivalence checks

Earlier discussion conflated scheduling-time and fulfillment-time
idempotency into one comparison. They are distinct, apply to different
calls, and must be persisted and compared separately:

- **`scheduling_requirements`** — the normalized `SettlementRequirement`
  shape (`resource_kind`, `dimensions`, `attributes`) that `schedule_resource`
  evaluated. Immutable once written. A `schedule_resource` retry compares
  `market` + `scheduling_requirements` against the stored values; if the
  request also supplies a `resource_id` constraint, that is checked
  separately as consistency against the row's `settlement_resource_id`
  (once assigned), not folded into the `market`/`requirements` comparison.
  Any mismatch on either axis is a conflict, not a silent return of the
  existing assignment. (The current in-memory scheduler only performs the
  `resource_id`-consistency half of this and does not compare
  `scheduling_requirements` on retry at all — this is a real gap Section 3/4
  closes, not existing behavior to preserve.)
- **`fulfillment_request`** — the domain-specific payload passed to
  `begin_fulfillment` (the eventual replacement for today's
  `VmFulfillmentRequirements`-shaped input), persisted as its own versioned
  envelope, immutable once written. Because `begin_fulfillment` loads the
  already-scheduled `SettlementResource` from the row rather than accepting
  one from the caller (task 6.1), there is no caller-supplied resource to
  compare on this path — equivalence here is `market` + `fulfillment_request`
  only.

`PhysicalSettlementRequest.resource_id` (an optional pre-selection
constraint) and `SettlementResource.settlement_resource_id` (the confirmed
assignment) intentionally share the same physical-resource identifier space
at different lifecycle stages — a `SettlementCandidate.resource_id` is the
same value as the owning `CapacityBucket.backing_resource_id`, and scheduling
adopts it directly into `settlement_resource_id` once selected. This is not
a naming inconsistency and does not need reconciling as part of this change.

### Ledger additions needed for one atomic scheduling transaction

Task 4.3 requires locking/validating the reservation, selecting a resource,
rebinding capacity, and writing the settlement assignment in one transaction
spanning `market_site` (the reservation/ledger authority) and
`market_fulfillment` (the new aggregate). `CapacityLedgerService`'s private
helpers already thread a caller's `db: Session` through internally
(`_backing_resource_id`, `_bucket_by_backing_resource`,
`_debit_for_reservation`); every *public* method, however, opens and commits
its own session, with no seam for an external caller to fold a ledger call
into a larger transaction. `market_site` cannot depend on
`market_fulfillment` to get one, so the fix is at the `market_site` boundary,
consumed by the scheduler (which already depends on both):

- `lock_reservation(db, capacity_reservation_id) -> CapacityReservation | None`
  — new. Existing reads (`get_reservation`, `_find_reservation`) do a plain
  `db.get(...)` with no row lock; nothing today provides the locked read
  task 4.3 requires.
- `assign_settlement_resource_in_session(db, *, capacity_reservation_id,
  settlement_resource_id)` — the existing `assign_settlement_resource` body
  extracted as a session-accepting core; the public method becomes a thin
  wrapper (open session, delegate, commit) so existing callers are
  unaffected.
- `backing_resource_id_in_session(db, capacity_reservation_id) -> str | None`
  — public exposure of the existing `_backing_resource_id`, so the
  scheduler's candidate-eligibility credit-back computation can read it
  against the same open session instead of opening a second one.

The scheduler opens one session from the already-shared `session_factory`
(`compute_provisioning_service/container.py` already constructs
`CapacityLedgerService` from that same singleton) and drives both the
ledger's session-scoped core and the new fulfillment repository against it
before a single commit.

### Correction: `resize_reservation`'s settlement-abandonment call violates the dependency boundary as sketched

Recorded now, ahead of Section 4 implementing `resize_reservation` (task
4.5), because the violation is in this file's own earlier pseudocode and is
better caught before it is copied into code than after:

The "Requirements change under negotiation" section's `resize_reservation`
sketch has the ledger call `self._mark_settlement_abandoned(db,
old_allocation_id)` directly inside its own transaction. `market_site` MUST
NOT import `market_fulfillment`, including under `TYPE_CHECKING` (see
`openspec/specs/fulfillment/spec.md#dependency-boundary`) — "marking a
settlement record abandoned" is a fulfillment-layer concept, so a literal
implementation of that pseudocode would introduce exactly the reverse
dependency the layering rule exists to prevent.

**Resolved:** `resize_reservation` accepts an optional hook parameter typed
as a `Protocol` defined in `market_site` itself, referencing no fulfillment
types:

```python
class SettlementAbandonmentHook(Protocol):
    def __call__(self, db: Session, capacity_reservation_id: str) -> None: ...
```

`resize_reservation(..., on_supersede: SettlementAbandonmentHook | None =
None)` invokes the hook inside its own transaction when superseding a
reservation that may have an assigned settlement record. `market_fulfillment`
supplies the concrete implementation at composition time. `market_site`
remains ignorant of what "settlement" is; the dependency-inversion is owned
by whichever higher layer wires the two services together. This does not
change `resize_reservation`'s atomicity properties, only how it reaches the
settlement-abandonment side effect without an upward import.



## Section 3 code-review decisions (2026-07-22)

These decisions refine the Section 3 persistence design after review. They preserve the generic, domain-agnostic repository surface while protecting invariants owned by `kit/fulfillment`.

### Scheduled market is immutable through fulfillment acceptance

`market` is established when the settlement assignment is first persisted. `begin_fulfillment`/`accept_fulfillment` must match that stored market on both the first acceptance and every retry. The repository must never rewrite the aggregate's market while accepting fulfillment. A mismatch is a fulfillment conflict before provider submission.

### SQLite concurrency contract

The compute provisioning service uses SQLite and has no planned PostgreSQL deployment. Section 3 must therefore describe and test the strongest concurrency guarantee actually available in that environment rather than claiming portable `SELECT ... FOR UPDATE` semantics. Fulfillment acceptance must serialize access to the existing aggregate within an explicit SQLite transaction so concurrent callers cannot durably create or return different `fulfillment_id` values. Aggregate creation remains guarded by the `capacity_reservation_id` primary key; an observable insert race must be translated by re-reading the winning row and applying the ordinary equivalent/conflicting request rules.

### Recovery selection remains provisional until Section 6

The recovery columns belong on the aggregate row, but the Section 3 helper is not the final multi-worker claim protocol. It must be named and documented as a single-worker SQLite persistence primitive. Section 6 ("Add provisioning-owned recovery and lifecycle convergence," renumbered from 7 on 2026-07-23 — see "Section 5/6/7 resequencing decision" below) owns the operational worker model, acquisition/lease semantics, duplicate-dispatch prevention, and the tests that prove those guarantees. Permanent Section 3 documentation may describe the durable claim fields and lease intent, but must not present the provisional helper as the completed recovery algorithm.

### Generic lifecycle updates with kit-owned restrictions

The repository retains a generic `transition(..., **lifecycle_updates)` operation so domain adapters can carry versioned provider inputs and metadata without domain-specific kit methods. The generic surface does not make every aggregate column mutable.

The shared mutable lifecycle set is limited to prepared create/teardown operation envelopes, provider/teardown metadata, and failure reason/message fields. Aggregate identity, scheduled resource identity, accepted fulfillment identity and request, lifecycle state, recovery-claim fields, and database-managed timestamps are not writable through `lifecycle_updates`. Unknown fields are rejected. Validation occurs before changing state or any field so an invalid call leaves the session object unmodified.

Domain-specific structure remains inside validated versioned envelopes and metadata payloads. Adding a new top-level settlement column is a shared-schema decision and requires an explicit permanent-contract update.

### Canonical models are a caller obligation

The persistence repository accepts validated canonical Pydantic models and versioned envelopes. It serializes those models to JSON-compatible structures and compares structural equality; it does not canonicalize arbitrary dictionaries or infer equivalence among unvalidated representations. Public scheduling and fulfillment boundaries are responsible for constructing the canonical models before calling the repository.

### New-table initialization and documentation hygiene

The Section 3 tables are new and do not require versioned migration scripts. Service-level tests must nevertheless prove that provisioning database initialization mounts the fulfillment metadata, is idempotent, and leaves the expected SQLite tables, constraints, foreign keys, and operational indexes.

Production code and stable tests must reference only permanent current-state documentation. References to this change's `design.md`, POOLS task numbers, migration chronology, or review tombstones are temporary planning material and must not remain in production comments or permanent specifications.


## Section 3 correction design-promotion record

| Material decision | Permanent documentation |
|---|---|
| Scheduled market remains immutable through first fulfillment acceptance and retries | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| SQLite acceptance uses a database-wide immediate writer reservation rather than claimed row-lock semantics | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Recovery columns are durable, while the Section 3 selector is single-worker only and final acquisition semantics belong to provisioning recovery | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Generic lifecycle updates are limited to prepared operation payloads, provider metadata, and failure fields | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Repository callers supply validated canonical models and envelopes | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` and `openspec/specs/fulfillment/spec.md#versioned-envelopes` |

## Section 4 scheduling implementation — design questions (discuss phase, opened 2026-07-23)

Section 3 built the durable aggregate and repository; `tasks.md` Section 4
(`schedule_resource`, atomic assignment, requirement-supersede, watchdog
abandonment) is not yet implemented. Inspecting the current
`PhysicalSettlementScheduler`, `CapacityLedgerService`, and
`ResourcePoolService` against tasks 4.1–4.7 surfaces gaps this document's
existing sections do not resolve. These are recorded here, with a proposed
default for each, before planning Section 4's task list in detail.

### 1. Session-scoped eligible-candidate enumeration is not fully designed

Task 4.3 requires one transaction that locks/validates the reservation,
enumerates every eligible candidate, and creates the assigned settlement
row. Today, eligibility enumeration is two self-managed-session calls —
`CapacityLedgerService.list_resources()` and
`ResourcePoolService.list_pools(enabled_only=True)` — glued together in
`PhysicalSettlementScheduler._eligible_candidates`, which also re-derives
a reservation's own held-capacity credit-back by hand over the returned
dict payload. `CapacityLedgerService._find_candidate` already does
session-scoped, debit-aware availability computation through the same
canonical `resource_satisfies_requirement`/`ResourceFeasibilityView` path,
but it is private, returns only the first match, and knows nothing about
pool enablement (owned by `market_resource_pools`, a different kit
package against the same database).

**Proposed:** add two narrow, session-scoped read methods, mirroring the
`lock_reservation`/`assign_settlement_resource_in_session`/
`backing_resource_id_in_session` precedent from Section 3:

- `CapacityLedgerService.iter_scheduling_candidates_in_session(db, *, resource_kind, exclude_reservation_id) -> list[ResourceFeasibilityView]` —
  every enabled bucket's canonical feasibility view, with
  `exclude_reservation_id`'s own current debit credited back into
  `available` (replacing the scheduler's ad hoc credit-back).
- `ResourcePoolService.list_pools_in_session(db, *, enabled_only=True) -> list[ResourcePool]`.

This keeps `ResourcePool`'s row shape private to `market_resource_pools`
rather than having the fulfillment scheduler query its ORM model
directly, even though the dependency layers would permit that import.

**Resolved (2026-07-23):** `schedule_resource` is a convenience operation
— its purpose is to fold what would otherwise be several separate
storefront/provisioning round trips (each with its own error taxonomy)
into one call with one error taxonomy and one commit/rollback boundary,
so the storefront does not have to duplicate compensating error handling
across calls the provisioning service could have made atomic itself.
Given that goal, leaving reservation-lock, candidate enumeration, and
settlement-row creation as separate self-managed-session calls is
rejected: a failure partway through would leave the reservation locked
and validated but nothing rebound or recorded, and the storefront would
need its own recovery logic for that partial state — exactly the
duplicated error handling this operation exists to avoid. The two new
session-scoped read methods above are approved as designed: implement
`CapacityLedgerService.iter_scheduling_candidates_in_session` and
`ResourcePoolService.list_pools_in_session`, and drive both, plus
`lock_reservation`/`assign_settlement_resource_in_session`, from one
transaction owned by `PhysicalSettlementScheduler.schedule_resource`.

### 2. Round-robin cursor durability has no designed storage shape

`DeterministicRoundRobinPolicy` keeps `_last_pool_id`/
`_last_resource_by_pool` as plain instance attributes with no persistence.
Task 4.1 requires "deterministic persisted fairness state." The
`SettlementSchedulingPolicy` protocol is currently a pure, synchronous,
no-I/O `select(requirement, candidates) -> SettlementCandidate` call.

**Proposed:** keep the policy protocol pure (no database access; stays
unit-testable without a session). Add a new `kit/fulfillment` table,
`scheduling_cursors` (`policy_scope` primary key, `last_pool_id`,
`last_resource_by_pool` JSON), and change the protocol to
`select(requirement, candidates, cursor) -> (SettlementCandidate,
updated_cursor)`, with the scheduler reading/writing the cursor row via
the repository inside the same transaction as the assignment write.

**Genuinely open, not just a confirmation:** what is `policy_scope`?
Today one `DeterministicRoundRobinPolicy` instance is shared across every
`select_resource` call in a process regardless of `resource_kind` — but
`market-platform-compute-40-multi-domain-proof` loads VM and bare-metal
adapters concurrently in one provisioner, and those have different
`resource_kind` values. Scoping the cursor globally would let VM
scheduling activity perturb bare-metal round-robin fairness and vice
versa; scoping it per `resource_kind` matches today's de facto isolation
(each kind's eligible-candidate set never overlaps) but has no stated
requirement backing it. This needs an explicit decision, not an inferred
one, since `openspec/specs/fulfillment/spec.md` currently describes
fairness scope not at all.

**Resolved (2026-07-23):**

- **Scope:** one cursor row per `resource_kind`, all rows in a single
  `scheduling_cursors` table (`resource_kind` primary key). A buyer
  negotiates for one `resource_kind` at a time (a VM, a bare-metal
  instance, a pod), never across kinds within one reservation, so
  isolating fairness per `resource_kind` matches how demand is actually
  partitioned rather than an arbitrary finer- or coarser-grained key.
  This becomes a normative statement in
  `openspec/specs/fulfillment/spec.md`'s scheduling-and-assignment
  requirement, not just an implementation detail, since it defines the
  boundary within which round-robin fairness is guaranteed.
- **Policy stays pure; cursor read/update is the scheduler's job, inside
  the transaction:** `select_resource`'s atomic transaction reads the
  `resource_kind`'s cursor row, calls the pure
  `select(requirement, candidates, cursor) -> (candidate, updated_cursor)`,
  and writes the updated cursor back alongside the settlement-record
  insert, all before commit.
- **Concurrency:** this repository is SQLite-only (Section 3's
  established concurrency contract). `schedule_resource`'s transaction
  already reserves SQLite's single-writer slot via `BEGIN IMMEDIATE`
  (the same mechanism `accept_fulfillment` uses) before it reads the
  cursor row, so concurrent `schedule_resource` calls for the same
  `resource_kind` serialize at the database level — there is no
  additional in-application lock/release bookkeeping (owner id,
  acquisition time) to add for this repository today. That kind of
  lock/lease scheme — the same shape as the existing recovery-claim
  columns (`claimed_by`, `claim_expires_at`, `attempt_count`) — remains
  the fallback pattern to reach for only if a future deployment needs
  genuine multi-writer concurrency beyond what SQLite's single-writer
  guarantee provides; it is not needed to satisfy Section 4, and should
  not be spent now. Document this cursor's concurrency contract the same
  honest way Section 3 documented the aggregate's: a SQLite single-writer
  guarantee, not portable row-lock semantics.

### 3. `resize_reservation`'s transaction boundary and caller

Design.md's existing "Requirements change under negotiation" section
specifies `resize_reservation`'s internals (release-then-reserve in one
transaction, `on_supersede` hook) but not whether it needs a caller-supplied-
session twin the way `assign_settlement_resource` does. No current call
site invokes it — the storefront-side negotiation-resize caller is
Section 9 scope, not Section 4.

**Proposed:** `resize_reservation` ships as a single self-managed-session
method only (like `reserve()`), with no `_in_session` twin, since nothing
in this change composes it into a larger transaction. If Section 9 later
needs to fold it into a broader commit, that is new evidence to add the
twin then, not a reason to build it speculatively now.

**Resolved (2026-07-23):** confirmed as proposed. `resize_reservation`
does not need to be composable into a larger transaction for this change.
Section 4 establishes the self-managed-session/`_in_session`-twin pattern
(item 1 above, and Section 3's existing `assign_settlement_resource`
precedent) clearly enough that adding the twin later, if and when a real
co-transactional caller shows up, is a small, well-understood addition —
not a reason to build it speculatively now.

### 4. Where `on_supersede` and the abandonment hook are composed

Task 4.5's `on_supersede: SettlementAbandonmentHook | None` and task 4.6's
watchdog abandonment both need a concrete hook implemented by
`market_fulfillment` and wired at a composition root, since
`market_site` cannot import `market_fulfillment`. Inspection of
`CapacityLedgerService` shows exactly two capacity-reclaiming code paths
that can strand an `assigned` `SettlementRecord`: `_expire_stale_holds`
(TTL-hold lapse before commit) and `release()` (terminal release; reached
from both `LeaseLifecycleService`'s watchdog and `LedgerSiteAuthority.
record_release_success`). `resize_reservation`'s supersede path is a
third. All three live inside `CapacityLedgerService` itself — there is no
need for a second hook on `LeaseLifecycleService`, since it never bypasses
the ledger's `release()`.

**Proposed:** thread one `SettlementAbandonmentHook`-shaped parameter into
`CapacityLedgerService.__init__` (same `Protocol`-in-`market_site`,
implementation-in-`market_fulfillment` shape already specified), invoked
from `_expire_stale_holds`, `release()`, and `resize_reservation`. Compose
the concrete hook in `compute_provisioning_service/container.py` alongside
`capacity_ledger_service`, even though no HTTP caller reaches
`resize_reservation` yet — matching the precedent `pools-2`/`pools-3` set
by shipping the scheduler/provider ahead of a real caller.

**Resolved (2026-07-23):** the hook is called unconditionally from all
three sites, with no pre-check in `market_site` for whether a
`SettlementRecord` exists before invoking it. `market_fulfillment`'s
concrete implementation is responsible for the no-op case (no matching
row, or a row already outside `assigned`). This keeps
`CapacityLedgerService` ignorant of settlement-record existence checks
(it only knows it must offer every capacity-reclaiming site a chance to
react) and keeps the "does anything need to be abandoned" decision fully
owned by `market_fulfillment`, consistent with the dependency boundary.

### 5. Dead pool-id attribute fallback

`PhysicalSettlementScheduler._eligible_candidates` still falls back to
`attributes.get("pool_id")` when a resource payload's `pool_id` column is
absent. Section 2's `site_resource_pools`/`CapacityBucket` rework made
`pool_id` an authoritative, always-populated column sourced from
`Host`/`ResourcePool`. **Proposed:** remove the fallback as part of
Section 4's rewrite of candidate enumeration (item 1 above) rather than
carrying it forward into the new session-scoped method — flagged
separately because it is a small cleanup, not a load-bearing design
decision like items 1–4.

**Verified (2026-07-23), proposal reversed — the fallback is not dead:**

- Every production write path to `CapacityBucket` was checked. The only
  in-repository caller of `CapacityLedgerService.register_resource` is
  the compatibility HTTP endpoint (`kit/site/src/market_site/router.py`,
  `PUT /capacity/resources/{resource_id}`), which passes `pool_id` as its
  own explicit request field straight to the real column — not through
  `attributes`. No production code constructs `CapacityBucket` rows
  directly outside `ledger.py`/`db.py` (i.e., the Section 2 migration's
  Host/ResourcePool-derived rows are the only other source of truth, and
  they are out of scope for this fallback).
- However, `kit/fulfillment/tests/unit/test_scheduler.py`'s own resource
  helpers (`_resource`, `_resource_with_capacity`) register test
  resources with `attributes={"pool_id": pool_id}` and **do not** pass
  the real `pool_id=` column at all. Every existing scheduler test
  therefore currently exercises the codebase entirely through the
  attributes-JSON fallback path — removing it today would make every
  candidate resolve to `pool_id=None` and break `test_scheduler.py`
  outright. `kit/site/tests/unit/test_ledger.py` also has a named test,
  `test_attribute_view_prefers_real_pool_id_over_attributes_json`, whose
  own docstring states this is deliberately supported "during the
  transition before the storefront's attributes-JSON-only push is
  retired" — i.e. the ledger's own test suite documents the fallback as
  an intentionally still-open transitional behavior, not a residual bug.

**Revised decision:** do not remove the fallback as part of Section 4.
Treat it as still load-bearing until proven otherwise. If Section 4's
new session-scoped candidate enumeration (item 1) is a good occasion to
finally retire it, that requires first updating
`kit/fulfillment/tests/unit/test_scheduler.py`'s helpers to pass a real
`pool_id=` column (matching how production resources are actually
registered post-Section-2) and confirming no other caller still depends
on attributes-only registration, as its own explicit task — not a
same-commit incidental deletion while rewriting candidate enumeration
for an unrelated reason.

## Section 5/6/7 resequencing decision (discuss phase, resolved 2026-07-23)

Section 4 is accepted as complete. `tasks.md` Section 4's remaining items
(4.7.4–4.7.6, 4.10.4, 4.11.4–4.11.5, 4.13, 4.15) are executable-validation and
production-composition test gaps, not open design or implementation
questions, and are deferred to the final POOLS-7 review pass rather than
blocking further sections. That deferral is a validation-completeness
decision, not a reopening of any Section 4 design question above.

Inspecting the current codebase for what "Migrate existing hosts and active
leases" (originally Section 5) actually depends on surfaced a genuine
sequencing problem, recorded in full below and now resolved by reordering
the plan.

### The problem

The original order was 5 (migrate hosts/leases) → 6 (fulfillment acceptance)
→ 7 (recovery/lifecycle convergence). Checked against current code:

- `proposal.md`/this file's "Active allocation backfill during cutover" and
  "Active-allocation migration and backfill" sections say the migration
  derives, per reservation, "selected resource, provider identity, and
  **versioned teardown input**." But `AnsibleFulfillmentProvider.create()`/
  `.teardown()` (originally Section 6, task 6.3) still use the pre-split
  shape — no `prepare_create`/`prepare_teardown` distinct from
  `dispatch_create`/`dispatch_teardown` — and `AnsibleFulfillmentMetadata`
  (`vm_host`, `vm_target`, job ids, `operation`) is a plain Pydantic model
  dumped to a dict via `FulfillmentResult(provider_metadata=metadata.model_dump())`,
  not a `VersionedEnvelope`. There is today no concrete `kind`/`schema_version`
  registered for "ansible teardown operation" anywhere in `envelopes.py` or
  the adapter. Task 1.6 deliberately deferred concrete payload kinds to "the
  sections that need them" — that section was originally 6.
- `compute_provisioning_service/services/fulfillment_service.py`'s
  `FulfillmentService` is still the pre-Section-3 in-memory implementation
  (`FulfillmentEntry` in a process-local `dict`; its own docstring says "used
  until durable lifecycle records own retries"). `begin_fulfillment` as a
  durable, callable operation does not exist yet.
- Even if the envelope shape were pulled forward in isolation, a second,
  independent problem remains: a backfilled row sitting in `dispatching` or
  `teardown_dispatch_pending` needs something to converge it to a terminal
  state. That convergence sweep was originally Section 7, also unbuilt.
  Running the migration before it exists would leave real backfilled rows
  frozen indefinitely while the *actual* VM lifecycle keeps progressing
  through today's pre-cutover path (`LeaseLifecycleService`, direct executor
  polling, `VmReleaseExecutor`) — since Sections 9/10 (the storefront/teardown
  cutover that retires that old path) come later regardless of this
  reordering. By the time a recovery sweep eventually exists, it would
  inherit rows already stale relative to reality, turning an ordinary
  crash-recovery sweep into one that also has to handle "this row is old and
  possibly already resolved in the real world" as a normal case.

Two candidate fixes were considered:

  (a) **Full reorder** — implement fulfillment acceptance and recovery first,
      migration last, so the migration only has to reproduce a shape both
      consuming systems already accept and can already converge.
  (b) **Pull forward only the pieces migration strictly needs** — define just
      the versioned envelope kind (and possibly a narrow one-shot poll-and-
      correct step in place of a full watchdog) ahead of the rest of Sections
      6/7, without reordering the sections themselves.

(b) is lighter-weight but concentrates risk on correctly guessing, in
isolation, the interface the real prepare/dispatch split will want, and does
not close the convergence-drift problem unless a second narrow slice of
Section 7 is also pulled forward — at which point it is doing most of the
work of (a) without the clarity of an explicit reorder.

### Resolved: full reorder

`tasks.md`'s implementation order changes to: **Section 4 (done) → fulfillment
acceptance and provider preparation → recovery and lifecycle convergence →
migrate existing hosts and active leases → Section 8 onward (unchanged)**.

Concretely, section numbers and their task-ID prefixes are reassigned:

| Old section | New section | Title |
|---|---|---|
| 6 | 5 | Implement fulfillment acceptance and provider preparation |
| 7 | 6 | Add provisioning-owned recovery and lifecycle convergence |
| 5 | 7 | Migrate existing hosts and active leases |

Sections 1–4 and 8–12 keep their numbers; only the internal ordering of the
three sections above changes. `tasks.md` has been updated to this numbering,
including its own internal cross-references (task 3.5's "task 6.1" →
initially "task 5.1", corrected again during Section 5 planning to "task 5.5"
once that section's detailed task list assigned `begin_fulfillment` to 5.5
rather than 5.1; task 3.11's "Section 7" → "Section 6"; the design-promotion
record row and the "Recovery selection remains provisional" heading above,
both updated the same way).

Rationale for the full reorder over the narrower pull-forward: by the time
migration/backfill runs, the exact envelope shape, `begin_fulfillment`
durability, and the recovery sweep all already exist and are already proven
against freshly-created rows. The backfill's job becomes narrow and
testable — "produce rows indistinguishable from ones the fulfillment-
acceptance path would have created natively, in whatever state matches
reality" — rather than inventing a payload shape in isolation that the later
section might define incompatibly, which would force a second, corrective
migration; that outcome sits poorly against this change's own "comprehensive
breaking migration, no compatibility shims" posture (`proposal.md`,
"Active allocation backfill during cutover"). The drift window between "row
backfilled" and "something can actually converge it" also shrinks to
approximately zero, since the recovery sweep is already running when the
migration executes. Section 8 (pull-based status/result queries) is
independent of this reordering — it only reads whatever is in the aggregate,
backfilled or not — and keeps its position and number.

## Section 7 (migrate existing hosts and active leases) — resolved design decisions (discuss phase, resolved 2026-07-24)

Renumbered from Section 5 per the resequencing decision above. Section 7 is a
pre-release cutover, not a compatibility migration from a previously shipped
resource-pool reservation model. No POOLS capacity reservations or POOLS-only
states such as `unmanaged` exist on production clients before this release.
The safety-critical historical data is the legacy VM lease and its tracked
Ansible create or teardown operation. Losing an unused reservation is an
inconvenience; losing an active lease or provider job can orphan infrastructure,
duplicate provisioning, prevent teardown, breach service-quality commitments,
and create financial exposure.

### Existing host and capacity migration is already complete

Section 2's migrations already create the `default` resource pool and its
`AnsiblePoolConfig`, backfill every existing host into that pool, migrate site
resource capacity into capacity buckets, and create current reservation debits.
Task 7.1 remains closed. Section 7 begins with fulfillment backfill for legacy
VM leases that may be nonterminal when an administrator upgrades.

### Candidate enumeration joins leases and reservations

The migration enumerates nonterminal legacy VM lease rows and joins them to
capacity reservations and migrated resource-pool data. The lease is the
authoritative source for deciding which workloads and provider operations must
survive the cutover. A matching capacity reservation supplies the durable
`capacity_reservation_id` and related capacity context when available. Because
POOLS has not shipped, unmatched new-style reservations need not be preserved
and must never override or obscure a legacy lease. Every relevant legacy lease
must either produce one unambiguous fulfillment aggregate or abort the entire
migration.

### Historical lease-state mapping

Only historical VM lease states that can exist before this release require a
backfill policy:

- `provisioning` maps to `dispatching`. The migrated record continues observing
  the known Ansible create job and never falls back to `dispatch_pending`.
- `leased` maps to `active` and receives a `ProvisionedResource`.
- `releasing` with a teardown job identifier maps to `tearing_down`.
- `releasing` without a teardown job identifier maps to
  `teardown_dispatch_pending`; the current provider contract prepares the
  teardown operation before recovery submits it.
- `release_failed` maps to `teardown_failed`.
- terminal or expired historical leases are skipped.

States introduced only by POOLS do not need migration behavior because they
were never shipped.

### Create-operation replay safety

Retrying a known failed create operation through the provider's normal recovery
behavior is valid. Submitting a new create operation merely because migration
cannot identify or reconstruct the existing Ansible operation is unsafe: the
original operation may still be running or may already have created the VM.
Therefore a historical `provisioning` lease requires a usable existing create
job identifier and maps to `dispatching`; a missing or ambiguous job reference
aborts migration rather than triggering speculative create dispatch.

### Minimal fail-loud validation; no migration repair workflow

Section 7 adds straightforward defense-in-depth assertions, not automated error
recovery. A candidate aborts the migration when it lacks the information needed
to preserve lifecycle ownership safely, including: no selected host; no unique
resource-pool resolution or usable VM Ansible provider configuration; no usable
VM target for an active or releasing lease; disagreement between populated
`vm_target` and `executor_target`; no create job for `provisioning`; no teardown
job for a row represented as already `tearing_down`; or a conflicting existing
settlement/provisioned-resource row. Equivalent target rows are accepted for
idempotent reruns. Conflicting rows are never overwritten. The migration does
not attempt to repair, reconcile, or redispatch ambiguous work.

### Aggregate shape and provider preparation

Migrated and native aggregates have the same runtime meaning. No origin or
`backfilled` field is added, and production code does not branch on migration
provenance. Missing historical create request/prepared-create data is permitted
according to lifecycle state: `dispatching` retains sufficient provider metadata
to observe the known create job, while `active` and teardown states need not
retain an unavailable original create request.

For active and teardown-related leases, the migration derives the canonical
`ProvisionedResource` from the validated VM target. It constructs the
provider-neutral settlement result, resolves the migrated pool configuration,
and calls the current VM provider's `prepare_teardown` contract to persist the
versioned teardown envelope. Existing create and teardown job identifiers are
preserved in their respective provider metadata so convergence observes known
work instead of submitting duplicates.

### Whole-migration atomicity and reruns

The database migration is all-or-nothing. It enumerates, joins, derives, and
validates the complete candidate set before exposing any Section 7 writes, then
inserts the settlement and provisioned-resource rows in one transaction. Any
unsafe candidate or conflict rolls back every Section 7 write. A rerun accepts
missing rows or exactly equivalent rows, rejects conflicting rows, and never
updates an existing aggregate merely to force it to match. No partially migrated
lease population may remain visible after failure.

### Permanent documentation destinations

During implementation, promote the durable current-state rules as follows:

- fulfillment lifecycle continuity, known-job observation, state-based input
  requirements, and idempotent aggregate semantics to
  `openspec/specs/fulfillment/spec.md`;
- the rationale for lease/provider-operation continuity, migration atomicity,
  and no speculative create fallback to
  `openspec/specs/fulfillment/architecture.md`;
- the repository-wide cutover transaction and authority rule (legacy lease
  continuity takes precedence over unused pre-release reservation data) to
  `docs/development/ARCHITECTURE.md`; and
- VM/Ansible-specific target derivation and teardown-envelope preparation to the
  permanent physical-provisioning specification and architecture companion.

### Section 7 code-review follow-up (discuss phase, opened 2026-07-25)

External code review of the implemented Section 7 migration found the
historical-state derivation and provider-preparation logic embedded directly
in `_migrate_legacy_vm_leases_to_fulfillment`'s single SQL transaction, rather
than in the "small, testable derivation layer" task 7.3 called for. The
review also found the task 7.9 scenario matrix under-built: only the
`leased` (active) case is exercised end-to-end; the idempotent-rerun and
conflicting-duplicate branches are unreachable in normal operation because
`apply_schema_migrations` tracks migration IDs and never re-invokes an
applied migration, and the very next migration drops `vm_leases` outright.
Re-running review's own reproduction confirms the existing test suite
passes in full once the repository's internal packages are put on
`PYTHONPATH` (`kit/fulfillment`, `kit/site`, `kit/resource-pools`,
`provisioning/compute/{,service}`, the VM adapter/client, and
`arkhai_bare_metal`) — the tasks.md note that focused execution was
"blocked" and only `py_compile`-checked understated the available
evidence; the code is behaviorally correct for the one scenario it
currently covers, it is the coverage breadth that is short.

**Decision: extract the compiler pattern already sketched as candidate
material.** `dev-branch-migration-notes.md`'s "Candidate material for
Section 7" describes a domain-neutral `LegacyFulfillmentBackfillCompiler`
protocol plus a per-adapter `compile_legacy_vm_fulfillment_backfill`
producing a `LegacyFulfillmentBackfillDraft` (candidate identity, target
state, provider metadata, and an already-frozen
`prepared_teardown_operation`). That shape is adopted, refactored onto this
change's actual accepted contracts (`SettlementResource`/`SettlementResult`
from `market_fulfillment.provider`, the versioned envelope from
`market_fulfillment.envelopes`, and `AnsibleFulfillmentProvider.prepare_teardown`
via `prepare_historical_vm_teardown`) rather than built from that file
directly. The compiler is a pure function: raw historical row fields in,
either a `LegacyFulfillmentBackfillDraft` or a raised validation error out,
with no database session. `_migrate_legacy_vm_leases_to_fulfillment` keeps
owning enumeration (the SQL join), whole-population validation-before-commit
ordering, existing-row conflict/equivalence comparison, and the single
atomic transaction — it stops owning state-derivation and provider-envelope
construction.

**Context, not a scope change: no POOLS-x change has shipped yet.** There
are currently no real capacity reservations or legacy leases in any deployed
environment for this migration to act on. This doesn't relax the
correctness bar — the migration must be correct before any real lease ever
reaches it, and the same compiler shape is the natural extension point for
`domains/bare_metal` if/when that domain needs an equivalent historical
cutover — but it does mean every Section 7 test is necessarily synthetic.
That's the reason to enumerate the task 7.9 matrix deliberately against the
extracted pure compiler (fast, no SQLite needed per case) rather than try to
approximate it from production data that doesn't exist.

**Task 7.10 gap:** no test currently proves a recovery/convergence worker
(Section 6) can observe and act on rows this migration backfills. Closing
this needs a service-level test that runs `run_migrations` against a
populated pre-migration schema, then drives `FulfillmentConvergenceWatchdog`
(or its repository-level claim/dispatch entry points) against the resulting
`dispatching`/`tearing_down`/`teardown_dispatch_pending`/`teardown_failed`
rows and asserts each is claimed and progressed the same way a
natively-created row would be.

**Deferred, not forgotten:**

- The "Section 7 design-promotion record" already exists
  (`tasks.md:405-412`) but lives in `tasks.md` rather than `design.md`,
  unlike the Section 3/5/6 records. Section 7 code review is still open in
  this session; relocating/finalizing the record is deferred until review
  closes rather than done piecemeal now.
- `proposal.md` is missing the `openspec/README.md`-mandated "Permanent
  documentation impact" checklist. This predates this review pass and isn't
  Section-7-specific; it's tracked as a Section 12 cleanup item for the
  final POOLS-7 review rather than fixed here.

#### Follow-up closed (2026-07-25)

7.3.1/7.3.2, 7.9.1–7.9.3, and 7.10 are implemented: `market_fulfillment.backfill`
(`LegacyFulfillmentBackfillDraft`/`LegacyBackfillValidationError`) plus
`vm_provisioning_adapter.legacy_backfill.compile_legacy_vm_fulfillment_backfill`
now own state derivation and provider-envelope preparation as a pure
function; `_migrate_legacy_vm_leases_to_fulfillment`/
`_apply_legacy_vm_lease_backfill` own only enumeration, cross-candidate
dedup, conflict comparison, and the atomic write. The full scenario matrix
from task 7.9 is covered across
`test_legacy_vm_fulfillment_backfill.py` (compiler-level, no engine) and
`test_legacy_vm_lease_migration.py` (DB-level, calling
`_apply_legacy_vm_lease_backfill` directly to reach the equivalent-rerun and
conflicting-duplicate paths that `run_migrations`'s tracked-once gate makes
otherwise unreachable). Task 7.10's gap closes with
`test_fulfillment_convergence_after_legacy_backfill.py`, which runs a real
migration then drives `FulfillmentConvergenceWatchdog` against the
backfilled rows. The full repository test surface reachable from this
session's environment (446 unit tests across `kit/fulfillment` and
`provisioning/compute/service`, 490 including integration) passes with no
regressions from the refactor.

While extracting the compiler, found and closed one real gap task 7.7 had
missed: a candidate reaching `active`/`tearing_down` state with a live
target but no known `create_job_id` previously reached
`AnsibleFulfillmentMetadata.model_validate` (which requires
`create_job_id: str`) and failed with an opaque `ProviderConfigInvalidError`
raised from deep inside the provider stack rather than a clear
migration-level error. The compiler now rejects this explicitly. This
tightens behavior for a case the original inline code did not test, but
does not change the outcome for any currently-passing test — the
transaction still fails loud and rolls back either way, only the error
type and message improve.

Tasks 7.13 (relocate the promotion record into `design.md`) and 7.14
(`proposal.md`'s missing checklist) remain open, deferred to Section 7
review close and the final POOLS-7 review respectively, per the plan
above.

#### Second code-review pass (2026-07-25): production-comment history and `kit/fulfillment` placement

External review of the closed follow-up found `_apply_legacy_vm_lease_backfill`'s
docstring explaining *why* it was split out (test-invocation convenience)
rather than *what* it durably does — a direct `AGENTS.md` violation, since
that rationale is change history, not a present invariant. Fixed by
rewriting the docstring to state the responsibility only ("Enumerate all
historical VM lease candidates, compile them before writing, reject
conflicts, and persist the population atomically") and, since the
parameter list existed only to thread already-imported classes down from
the outer migration function rather than to serve any real caller
diversity, simplifying `_apply_legacy_vm_lease_backfill` back down to a
single `connection` parameter that does its own lazy import — removing the
awkward-looking kwarg-threading pattern along with the docstring problem it
was attached to, not just papering over the wording.

The same review raised a design question, not a mechanical defect:
`market_fulfillment/backfill.py`'s generic naming and its now-removed
`LegacyFulfillmentBackfillCompiler` `Protocol` presented a one-time
historical cutover as a lasting, general-purpose fulfillment extension
point, which reinforced the question of whether this belongs in
`kit/fulfillment` at all. Resolution: the `Protocol` is removed — it had
exactly one implementation (VM), was not referenced by any type annotation
anywhere in the tree, and existed only as speculative interface scaffolding
for a second domain this change does not accept as in scope. What remains
(`LegacyFulfillmentBackfillDraft`, `LegacyBackfillValidationError`) does
belong in `kit/fulfillment` specifically, but not because domain cutover
compilation is itself a durable fulfillment concept — because
`LegacyFulfillmentBackfillDraft` mirrors `SettlementRecord`/
`ProvisionedResource`'s own row shape, which is already defined in this
package, and because both `vm_provisioning_adapter` and
`compute_provisioning_service` already depend on `kit/fulfillment` without
depending on each other, making it the only location both a domain
adapter's compiler and the generic service's migration can share without
crossing the dependency boundary `openspec/specs/fulfillment/spec.md#dependency-boundary`
establishes. The module docstring was rewritten to state this directly
rather than lead with generic "contracts for compiling" framing. If a
second domain later needs an equivalent historical cutover, a shared
extension point can be reconsidered then, against a second real
implementation instead of a speculative one.

Test-file docstrings were also checked against the same rule: task-ID
references (`task 7.10`) are removed from `test_legacy_vm_fulfillment_backfill.py`
and `test_fulfillment_convergence_after_legacy_backfill.py`'s module
docstrings, consistent with `AGENTS.md`'s "task IDs are not durable
documentation" position even where test-strategy prose itself remains
freely descriptive.

#### Third code-review pass (2026-07-25): rerun equivalence was too coarse

External review found the existing-row equivalence check task 7.7/7.8
require ("accept exactly equivalent target rows for idempotent reruns;
never overwrite conflicts") compared only `state`, `settlement_resource_id`,
`pool_id`, and `provider`. A row matching on those four fields could still
carry a different (or missing) tracked create job, a different active
teardown job, a missing prepared teardown envelope, or no corresponding
`ProvisionedResource` row at all — and the rerun would silently `continue`
rather than reject it. That is exactly the provider-operation-identity loss
Section 7 exists to prevent; the coarse check made "equivalent" weaker than
the design decision it was implementing.

Fixed by comparing every field a provider operation depends on:
`resource_attributes`, `provider_metadata` (including the tracked create
job), `teardown_provider_metadata` (including the active teardown job), and
`prepared_teardown_operation`, plus a separate check that the corresponding
`ProvisionedResource` population matches exactly — zero rows for no live
target, exactly one row with the expected `domain_resource_ref` for a live
target. Any mismatch across either check raises the same
`SchemaDriftError` as before; equivalence now means bit-for-bit equivalent,
not merely coarsely similar.

Added to `test_legacy_vm_lease_migration.py`: same coarse fields but a
different `create_job_id`; a different teardown job ID; a missing prepared
teardown operation; a missing `ProvisionedResource` row; a
`ProvisionedResource` row with a different `domain_resource_ref`; and
multiple `ProvisionedResource` rows where exactly one is expected. All six
raise `SchemaDriftError` against otherwise-unmodified legacy lease data,
proving the tightened check — not just the original four-field comparison
— is what rejects them. Full suite re-run: 598 tests, no regressions.

## Section 7 implementation promotion record

| Accepted decision | Permanent location |
|---|---|
| Legacy lease state mapping, known-job observation, state-based required inputs, and no speculative create fallback | `openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover` |
| A live target with no known create job identity is rejected rather than backfilled | `openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover` |
| Idempotent-rerun and conflict-rejection rules for the cutover | `openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover` |
| Whole-population validation-before-commit and atomic-transaction cutover | `openspec/specs/fulfillment/architecture.md#atomic-legacy-lease-cutover` |
| Active lease/provider-operation continuity outranks unused pre-release reservations | `openspec/specs/fulfillment/architecture.md#atomic-legacy-lease-cutover` |
| Per-candidate state derivation and provider-envelope preparation live in a pure, domain-owned compiler; the enumerating migration owns only enumeration, dedup, conflict comparison, and the atomic write | `openspec/specs/fulfillment/architecture.md#atomic-legacy-lease-cutover` |
| Equivalent-rerun/conflict comparison covers every field a provider operation depends on for correctness (resource attributes, provider metadata including the tracked create job, teardown provider metadata including the active teardown job, the prepared teardown envelope) plus the corresponding `ProvisionedResource` population, not only state/resource/pool/provider | `openspec/specs/fulfillment/spec.md#existing-lease-continuity-during-fulfillment-cutover` |
| VM target derivation, provider metadata preservation, and provider-owned teardown preparation | `openspec/specs/physical-provisioning/spec.md#vm-lease-migration-uses-current-provider-contracts` |
| Provider job identifier as the durable correlation point migration cannot safely replace | `openspec/specs/physical-provisioning/architecture.md#preserving-provider-operations-across-schema-cutover` |
| Repository-wide all-or-nothing workload lifecycle cutover rule | `docs/development/ARCHITECTURE.md#atomic-workload-lifecycle-cutovers` |
| Shared cutover row-draft/error types live in `kit/fulfillment` because they mirror `SettlementRecord`/`ProvisionedResource`'s own row shape and because the dependency graph gives a domain adapter and the generic service no other common location to share them, not because domain cutover compilation is itself a durable fulfillment concept | `kit/fulfillment/src/market_fulfillment/backfill.py` module docstring; no separate spec.md entry — this is a code-location rationale, not observable behavior |

Validation evidence: `provisioning/compute/service/tests/unit/services/test_legacy_vm_fulfillment_backfill.py`, `provisioning/compute/service/tests/unit/test_legacy_vm_lease_migration.py`, and `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence_after_legacy_backfill.py` were run directly against the assembled `kit/fulfillment`/`kit/site`/`kit/resource-pools`/`provisioning/compute/{,service}`/VM-adapter/VM-client/`arkhai_bare_metal` source tree, not evaluated by `py_compile` alone. The full reachable suite (`kit/fulfillment/tests` plus `provisioning/compute/service/tests`, unit and integration) passes: 598 tests, no regressions.

## Section 5 (fulfillment acceptance and provider preparation) — resolved design decisions (discuss phase, resolved 2026-07-23)

Discuss phase for the new Section 5 ("Implement fulfillment acceptance and provider preparation," renumbered from 6 per the resequencing decision above) is complete. The decisions below are accepted and bind Section 5 planning.

### Scope boundary: Section 5 is provisioning-service-internal only

Section 5 implements `begin_fulfillment` and provider prepare/dispatch entirely on the provisioning-service side. It does not implement or assume any storefront-side call sequencing. Specifically:

- Capacity reservation itself (`CapacityLedgerService.reserve()`) already exists and needs no new work here.
- The full storefront-side lifecycle — calling `reserve`, then `schedule_resource`, then `begin_fulfillment`, polling status/result, and driving teardown — is **Section 9**'s scope ("Cut over storefront orchestration," task 9.2 explicitly), not Section 5's.
- Canceling a reservation on failed negotiation is already handled by existing `release()` plus the Section 4 `SettlementAbandonmentHook` wiring; no new provisioning-service work is needed. Section 9 only needs to call `release()` at the right point in storefront workflow.
- Teardown dispatch (`begin_fulfillment_teardown`) is **Section 10**'s caller. Section 5 nonetheless builds `prepare_teardown`/`dispatch_teardown` on the provider interface alongside `prepare_create`/`dispatch_create`, ahead of that caller — consistent with the precedent already established by `pools-2`/`pools-3` shipping scheduler/provider capability ahead of a real caller.

### `deal_ref`: excluded from the new fulfillment path now; full removal deferred to Section 11

Investigation found `deal_ref` on five contract classes in `provisioning/compute/src/compute_provisioning/contracts.py`: `ExecutorActionEnvelope`, `JobAccepted`, `ProvisioningJob`, `LeaseRegistration`/`LeaseView`, and `LifecycleEvent`. Only `LifecycleEvent.deal_ref` has a real functional consumer today (`StorefrontLifecycleEventSink.deliver`, wired only for the capacity-released lifecycle push — a `market_site`-owned, reservation-level concern, not a fulfillment concern). The other four are load-bearing for the **currently-active legacy direct-dispatch path** (`ComputeContractService.submit_action`, `BareMetalComputeAdapter.submit`, `register_lease`), which Section 9 has not yet retired and Section 11 has not yet removed.

**Resolved:**

- The new fulfillment-dispatch code (`AnsibleFulfillmentProvider.dispatch_create`/`dispatch_teardown`, Section 5) constructs its own `ExecutorActionEnvelope` with `deal_ref={}`. No commercial or deal identity is read, forwarded, or newly threaded through the fulfillment-acceptance path, satisfying the boundary rule for the code this section actually writes.
- The `deal_ref` field itself is **not** removed from `ExecutorActionEnvelope`, `JobAccepted`, `ProvisioningJob`, `LeaseRegistration`/`LeaseView`, or the `AnsibleJob.deal_ref` column in Section 5. Removing it now would break the still-active legacy path before its callers (`ComputeContractService.submit_action`, `BareMetalComputeAdapter.submit`, `register_lease`'s `body.deal_ref.get("escrow_uid")` read) are retired — the same class of premature-removal mistake this document already caught and reversed once for the `pool_id` attributes fallback (Section 4, item 5).
- **Tracked explicitly for Section 11** ("Remove obsolete schema and compatibility paths," which already scopes "obsolete executor/provider fields"): once Section 9 retires the legacy callers, remove `deal_ref` from all five contract classes and drop `AnsibleJob.deal_ref`. `escrow_uid` already has an independent, non-`deal_ref` source everywhere checked (the reservation's own `escrow_uid` column; bare-metal's adapter already falls back to it), so this removal is mechanically safe once the legacy callers are gone.
- `CapacityReservation.deal_ref` (`kit/site`) and `StorefrontLifecycleEventSink`/`notify_storefront_capacity_released` remain out of scope for POOLS-7 entirely — a pre-existing, separately-flagged transport seam this document already identifies as `provisioning-result-push-delivery`'s territory to properly redesign, not something to touch incidentally here.

### Envelope naming and payload ownership

- Concrete versioned-envelope kinds: `"vm.ansible.create.v1"` / `"vm.ansible.teardown.v1"`. The provider axis is embedded in the kind name (not left implicit) because payload shape is genuinely provider-specific — a hypothetical future GCP provider would mint its own `"vm.gcp.create.v1"` with an unrelated payload (gcloud arguments, not Ansible playbook/inventory), and readers must reject a kind they don't recognize rather than guess. This mirrors `resource.provider` already being a first-class field on `SettlementResource`/`SettlementRecord`.
- `fulfillment_request` (the storefront-supplied payload to `begin_fulfillment`) remains the existing domain-neutral `VmFulfillmentRequirements` shape, unchanged by this section. The storefront never sees, sends, or needs to know about Ansible after this section lands.
- `prepared_create_operation`/`prepared_teardown_operation` are purely provisioning-service-internal artifacts, built by `prepare_create`/`prepare_teardown` by combining the already-known selected resource (from scheduling), `fulfillment_request`, and the pool's Ansible provider configuration (playbook path, extra vars).
- The envelope payload must be a dedicated, validated Pydantic model — not a raw `dataclasses.asdict(AnsibleJobParams)` dump — so it satisfies the existing versioned-envelope requirement ("typed or explicitly validated payload... readers reject unknown `(kind, schema_version)` pairs rather than guessing," task 1.6) on both write and read.

### Provider protocol: prepare/dispatch split, provider stays pure

`FulfillmentProvider` (`kit/fulfillment/src/market_fulfillment/provider.py`) currently declares only `create`/`teardown`/`get_status` — there is no existing prepare/dispatch split to refine; this is a new abstract-base change with one implementer today (`AnsibleFulfillmentProvider`).

- New protocol methods: `prepare_create(request, resource, pool_config) -> VersionedEnvelope`, `dispatch_create(prepared: VersionedEnvelope) -> FulfillmentResult`, and the teardown equivalents. `get_status` is unchanged.
- `prepare_create`/`prepare_teardown` are **pure functions of already-fetched data** — no database access inside the provider. `pool_config` is passed in as an explicit argument by the orchestrator, rather than the provider fetching it itself via a held `ResourcePoolService` reference (today's `AnsibleFulfillmentProvider._pool_config`/`_validate_resource` do the latter, and this is corrected as part of the split). This mirrors `DeterministicRoundRobinPolicy.select` being pure with all DB access owned by the orchestrator/persistence layer, per the Section 4 precedent.

### Closing the session-scoped read gap this split would otherwise reopen

`ResourcePoolService.get_pool()` is self-committing (opens and closes its own session). If `prepare_create`'s pool-config read happened outside the same transaction as `accept_fulfillment`'s row lock and the prepared-operation write, it would reopen the exact "prepared work must be frozen against live pool edits, read within one atomic scope" gap Section 4 closed for scheduling via `list_pools_in_session`/`iter_scheduling_candidates_in_session`.

**Resolved:** add `ResourcePoolService.get_pool_in_session(db, pool_id) -> ResourcePool | None` in `kit/resource-pools`, exposing the class's existing private `_require_pool` session-scoped helper (already used internally by other self-managed-session methods) as a public entry point — the same pattern task 4.2.2 already established for `list_pools_in_session`.

### Transaction shape: follow the Section 4 precedent (`SchedulingUnitOfWork` → `FulfillmentUnitOfWork`)

Per direction received in this session, Section 5 follows the same narrow-persistence-interface pattern Section 4's correction pass established (task 4.10), rather than the orchestrator directly coordinating a raw session plus multiple self-committing services. The surface is smaller than scheduling's: fulfillment acceptance touches one table (`SettlementRecord`), not a transaction spanning `market_site` and `market_fulfillment`.

**Resolved shape:** a `FulfillmentUnitOfWork` protocol in `kit/fulfillment`, exposing exactly: (1) lock/lookup and equivalence-check against the existing aggregate (wrapping `SettlementRepository.accept_fulfillment`), (2) the new session-scoped pool-config read (`get_pool_in_session`), and (3) writing `prepared_create_operation`/`prepared_teardown_operation` alongside the `dispatch_pending`/`teardown_dispatch_pending` transition (wrapping `SettlementRepository.transition`, confirmed to already apply lifecycle updates even when the target state matches the row's current state — no repository signature change needed). The orchestrator opens one `BEGIN IMMEDIATE` transaction through this interface, calls the now-pure `provider.prepare_create(request, resource, pool_config)` before commit, commits, then calls `provider.dispatch_create(prepared)` after commit — matching the "Provider input snapshot: prepare/dispatch split" design already accepted earlier in this file.

### Orchestrator placement: moves into `kit/fulfillment`

Today's in-memory orchestrator (`compute_provisioning_service/services/fulfillment_service.py`'s `FulfillmentService`, with its process-local `FulfillmentEntry` dict) is retired, not adapted in place. Its replacement — the durable `begin_fulfillment` orchestrator driving `FulfillmentUnitOfWork` and `ProviderRegistry` — is implemented in `kit/fulfillment`, not `provisioning/compute/service`. Rationale: it composes only `SettlementRepository` and `ProviderRegistry`, both already owned by `kit/fulfillment`, exactly the same domain-neutral shape as `PhysicalSettlementScheduler`, which already lives there. There is no principled reason for this orchestrator to be the one kit-shaped piece of logic living outside kit.

### Accepted Section 5 lifecycle clarifications

#### Acceptance, dispatch, and acknowledgement are distinct facts

`begin_fulfillment` durably accepts the operation before provider dispatch. Once the acceptance transaction commits, a recoverable provider-dispatch or acknowledgement failure does not make the operation rejected: the aggregate remains accepted in `dispatch_pending`, the caller receives the durable provider-neutral acceptance view, and provisioning-owned recovery may safely retry the persisted prepared operation. Errors that occur before durable acceptance, including an unscheduled reservation, market/request conflict, unknown provider, or invalid preparation input, fail the call without creating an accepted fulfillment.

Successful provider submission is acknowledged in a second short transaction. That transaction stores normalized provider metadata and transitions `dispatch_pending` to `dispatching`. Repeating the acknowledgement with structurally equivalent normalized metadata is idempotent; a conflicting provider job identity is a lifecycle conflict and never overwrites the existing acknowledgement. The crash window between provider submission and this acknowledgement is intentional: deterministic executor idempotency allows recovery to redispatch and rediscover the same provider job.

#### Equivalent retries are state-sensitive

Repository equivalence is necessary but does not by itself authorize dispatch. The acceptance result distinguishes whether the row is newly accepted and whether dispatch remains required. A newly accepted aggregate dispatches. An equivalent retry in `dispatch_pending` without acknowledged provider metadata redispatches the persisted prepared operation. An equivalent retry in `dispatching` or any later lifecycle state returns the existing fulfillment without invoking the provider. Conflicting reuse fails before dispatch.

#### Dry-run mirrors the real acceptance signature and calculable path

The public dry-run operation accepts the same arguments as `begin_fulfillment(capacity_reservation_id, market, fulfillment_request)`. It loads the same already-scheduled aggregate and selected resource, resolves the same provider, reads current pool configuration, and invokes the same request parsing and `prepare_create` validation. It writes no prepared operation or lifecycle state and performs no provider dispatch. Its response is provider-neutral and does not expose the internal Ansible envelope. Because no acceptance snapshot is committed, the result is a non-binding preview of the live configuration at the time of validation. Teardown dry-run is deferred until the teardown endpoint exists.

#### Teardown consumes a provider-neutral durable settlement result

The current process-local caller passes a full `SettlementResource` object, not an identifier. In shared contracts, `resource` therefore denotes that model and a bare identity is named `settlement_resource_id`. The durable teardown preparation contract takes the provider-neutral settlement result rather than a loose resource plus an untyped metadata dictionary. That result carries the selected resource, provisioned-resource outputs, and versioned provider metadata needed by the concrete provider to identify exactly what it created.

Shared fulfillment orchestration does not know Ansible job IDs, targets, playbooks, or VM teardown fields. `AnsibleFulfillmentProvider` owns a typed internal metadata model, validates its own create result, and interprets it during teardown. For newly accepted VM fulfillments, normalized provider metadata must preserve the durable executor job identity and exact teardown identity; missing or contradictory identity causes preparation to fail rather than be reconstructed from storefront state or guessed.

### Cleanup carried into Section 5

`SettlementRepository.select_pending_for_single_worker`'s docstring currently reads "...Section 7's recovery workflow owns duplicate-dispatch prevention..." — this is production code, and per `AGENTS.md` production comments must not reference OpenSpec section/task numbering at all (independent of the fact the number is also now stale post-reorder). This gets corrected as part of Section 5 to describe the concept in stable terms with no section reference, rather than merely renumbered.

## Section 5 design-promotion record

| Accepted decision | Permanent location |
|---|---|
| `begin_fulfillment`, provider prepare/dispatch, and reservation/scheduling remain provisioning-service-internal; storefront sequencing is a separate concern | `openspec/specs/fulfillment/spec.md` |
| The fulfillment-acceptance path carries no commercial/deal identity; `deal_ref` is excluded from new dispatch code | `openspec/specs/fulfillment/spec.md#physical-settlement-request` |
| Versioned envelope kind naming embeds the provider axis (`vm.ansible.create.v1`/`vm.ansible.teardown.v1`) | `openspec/specs/fulfillment/spec.md#versioned-envelopes` |
| `FulfillmentProvider.prepare_*` is pure; pool configuration is read in-session by the orchestrator and passed in, not fetched by the provider | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| `ResourcePoolService.get_pool_in_session` closes the same live-re-read gap `list_pools_in_session` closed for scheduling | `openspec/specs/resource-pool-management/spec.md` |
| Fulfillment acceptance uses a narrow `FulfillmentUnitOfWork`, mirroring `SchedulingUnitOfWork` | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Durable acceptance survives recoverable post-commit dispatch failure; successful submission is acknowledged in a second idempotent transaction | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`; `openspec/specs/fulfillment/architecture.md` |
| Equivalent retries dispatch only while durable state shows acknowledgement is still required | `openspec/specs/fulfillment/spec.md#idempotency-and-retry` |
| Dry run has the same signature and calculable validation path as `begin_fulfillment` but exposes no internal prepared envelope and causes no side effects | `openspec/specs/fulfillment/spec.md#fulfillment-validation` |
| Teardown consumes a provider-neutral durable settlement result; concrete adapters own typed interpretation of provider metadata and exact teardown identity | `openspec/specs/fulfillment/spec.md#fulfillment-results-and-teardown`; `openspec/specs/fulfillment/architecture.md` |
| `resource` names the full `SettlementResource` model; bare identities use `settlement_resource_id` | `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identifiers`; `openspec/specs/fulfillment/spec.md` |
| The durable fulfillment orchestrator lives in `kit/fulfillment`, alongside `PhysicalSettlementScheduler` | `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| `deal_ref` remains on legacy contract classes until Section 9/11 retire their callers | `openspec/changes/pools-7-storefront-fulfillment-cutover/tasks.md` (Section 11 scope; not a permanent-doc statement until removed) |

## Section 5 task 5.10 — integration coverage found and fixed a real transaction bug (2026-07-24)

Writing integration coverage against a real SQLite-backed `FulfillmentUnitOfWork`
(`provisioning/compute/service/tests/integration/test_fulfillment_api.py`) surfaced
that every real call to `begin_fulfillment` failed with
`sqlite3.OperationalError: cannot start a transaction within a transaction`.
`SqlAlchemyFulfillmentUnitOfWork.transaction()` (`fulfillment_persistence.py`) called
`begin_sqlite_write_transaction(db)` itself, and `SettlementRepository.accept_fulfillment`
(called via `tx.accept()`, always the first operation inside every real `transaction()`
usage) also calls it internally — a guaranteed double `BEGIN IMMEDIATE` on one session.
This was invisible in every test that existed before 5.10 because `test_fulfillment.py`
and `test_fulfillment_persistence.py` exercise the orchestrator and transaction logic
exclusively against `FakeTransaction`/`MagicMock` sessions, never a real one.

**Resolved:** the unit of work no longer reserves the writer slot itself; it relies on
`tx.accept()` to do so, since `accept_fulfillment` must keep that guarantee regardless
(it is independently tested and called standalone, without a unit of work, in
`kit/fulfillment/tests/unit/test_repository.py`). This is the opposite division of
responsibility from `SchedulingUnitOfWork` (where the unit of work owns the write-lock
and the wrapped persistence methods do not); the two subsystems settled on this
transaction-ownership boundary at different points, and now that the fulfillment path
has real test coverage exercising it, the difference is intentional and documented in
`fulfillment_persistence.py` rather than a latent inconsistency.

Two supporting gaps in the integration test harness itself were also fixed as
prerequisites, not scope creep: `tests/integration/conftest.py`'s `db_engine` fixture
never created the fulfillment schema at all (no fulfillment-backed integration test
could have run in this suite before), and `client_and_queue` never composed or
overrode `resolved_fulfillment_service`, so `FulfillmentController` had nothing to
resolve. Both now mirror the existing `physical_settlement_scheduler` pattern.

Tasks 5.4 and 5.5's text also had a stale `"submitted"` state name (corrected
everywhere else in this document and in the permanent spec on 2026-07-23, but missed
in two places in `tasks.md` itself); corrected to `"dispatching"`, the actual
`SettlementRecordState` value, to match.

## Section 5 closed (2026-07-24)

All twelve Section 5 tasks (5.1–5.12) are complete. The final review pass closed the
three remaining gaps in 5.8's test checklist (independent-session concurrency proof,
pool-config-frozen-at-acceptance proof, acknowledgement-failure-recovery proof) —
see task 5.8 in `tasks.md` for what each test proves and why it was missing. Full
suite, rebuilt from a clean state: 151 passed across `kit` (alkahest, config, identity,
policy, site, resource-pools, fulfillment), 302 unit + 146 integration passed in
`provisioning/compute/service`. No other domain imports `market_fulfillment`, so this
section's changes are contained; the legacy direct-dispatch path is untouched and
still fully functional. Nothing calls `begin_fulfillment` in production yet — that is
Section 9's job — so this section is safe to merge as dormant, additive code ahead of
Section 6 (recovery/convergence) and Section 9 (storefront cutover).

## Section 6 recovery and lifecycle convergence — resolved (2026-07-24)

Discussed and resolved before planning, per the discuss → plan → implement
workflow. Between the discussion and this write-up, a `dev`-branch merge
into the Section 5 branch was found to have archived this entire change and
introduced an independently-evolved, incompatible implementation of
Sections 6–12 (including a redesigned `FulfillmentProvider` contract that
dropped `pool_config`, and undiscussed scope — a multi-principal storefront
auth boundary and a parallel bare-metal cutover). That merge was reverted
and redone from scratch, resolving every conflict in favor of the design
recorded in this document; none of `dev`'s code survived. The design ideas
worth carrying forward were extracted into
`dev-branch-migration-notes.md` in this change directory, mapped to the
section each would apply to — reference material for future sections'
discuss phases, not accepted decisions, and not reflected in what follows.

**1. What "multi-replica-safe" means against this service's actual
deployment topology.** `docs/development/ARCHITECTURE.md` ("Production and
staging") states the compute provisioner is SQLite-backed single-writer,
deployed with `Recreate` and a `ReadWriteOnce` volume — two replicas never
run against the same database concurrently by construction. Earlier
"multi-replica" language in this document (now corrected in place, above)
overstated the requirement. **Resolved:** "multi-replica-safe" is read as
defense-in-depth under concurrent claim attempts — overlapping asyncio
tasks within one watchdog cycle, a brief overlap during pod replacement, or
an operator running a second instance for diagnosis — not a distributed
multi-replica claim protocol. The claim primitive (item 3) is tested with
the same independent-session, file-backed SQLite technique task 4.11
established, and permanent documentation states the SQLite single-writer
guarantee honestly.

**2. Watchdog shape.** **Resolved:** one asyncio loop, one class,
`FulfillmentConvergenceWatchdog`, composed in `compute_provisioning_service`
alongside `LeaseWatchdog`/`CapacityReservationWatchdog`. It runs an ordered
list of logically separate handler passes per cycle (create
submission/recovery, create status convergence, teardown
submission/recovery, teardown status convergence) rather than five
independent watchdogs. Named for the table it watches (`SettlementRecord`)
and the verb this document already uses for what the handlers do, matching
`LeaseWatchdog`/`CapacityReservationWatchdog`'s naming convention. Not
`SettlementRecoveryWatchdog` — "recovery" overclaims the multi-replica
framing item 1 rejected.

**3. Claim primitive.** **Resolved:** replaces
`SettlementRepository.select_pending_for_single_worker` (task 3.11's
documented placeholder). A new repository method opens its own short,
self-contained `BEGIN IMMEDIATE` write transaction, selects eligible rows
(matching state, unclaimed or claim-expired), writes the claim fields
(`claimed_by`, `claim_expires_at`, increments `attempt_count`), and
commits — releasing the writer slot before any provider call. SQLite has no
`SELECT ... FOR UPDATE SKIP LOCKED`; under SQLite's single-writer contract
it's unnecessary, since the write transaction itself already serializes
against any other claim attempt.

**4. No automatic terminal failure from attempt exhaustion.** **Resolved:**
recovery retries `dispatch_pending`/`teardown_dispatch_pending` indefinitely
with exponential backoff and jitter. `attempt_count` and claim age are
surfaced as operator-facing diagnostics only, never a trigger that forces
`failed`/`teardown_failed`. A row reaches those states only because the
provider explicitly reported failure, or preparation raised a
non-recoverable validation error. Rationale: this service either grants
access to a physical resource a buyer is paying for, or releases one
without stranding it — neither may be silently abandoned by a retry budget.
This is distinct from, and does not change, the existing
`LeaseLifecycleService` capacity-reservation-release path, which already has
its own terminal `release_failed` state and operator-driven retry/force-release
— that mechanism is unaffected by this section.

**5. Status convergence shape.** **Resolved:** claim a batch (short
transaction) → call `provider.get_status(...)` per row outside any open
transaction → apply each row's outcome in its own second short transaction
(`active`/`failed` for create convergence, `torn_down`/`teardown_failed` for
teardown convergence), clearing claim fields on terminal outcomes and
leaving them (or extending the lease) when the provider still reports
`pending`. Mirrors Section 5's prepare/dispatch/acknowledge transaction
shape.

**6. Provisioned-resource identity.** **Resolved:** a new,
pure, synchronous `FulfillmentProvider` method,
`resolve_provisioned_resources(provider_metadata: dict[str, Any]) ->
tuple[str, ...]`, called by create-status convergence exactly once, only
when `get_status` reports `succeeded` — never earlier, so a
`ProvisionedResource` row is never created for a resource whose creation
might still fail. Does not touch `get_status`/`ProviderStatus`, which stay
pure state-polling. For the VM adapter this decodes `vm_target` from the
already-persisted `AnsibleFulfillmentMetadata` — known since dispatch
acknowledgement, not something the provider needs to fetch or the job needs
to have completed to produce. Teardown convergence does not call this
method; it updates the `status` of the `ProvisionedResource` rows already
created at create-convergence time, rather than resolving anything new.

**7. Abandonment reconciliation: not built.** **Resolved:** task 6.2's
originally-planned fifth handler is a no-op, closed rather than
implemented. `SettlementAbandonmentHook` (Section 4, tasks 4.5.1–4.5.4)
already fires synchronously and unconditionally, in the same transaction as
the capacity mutation, from every capacity-reclaiming path
(`_expire_stale_holds`, `release()`, `resize_reservation`'s supersede
step) — there is no commit-ordering gap for a periodic sweep to close.

**8. Package boundary.** Not reopened — `openspec/specs/fulfillment/spec.md`
already states the kit does not own "the periodic multi-replica recovery
sweep" (wording to be corrected during this section's permanent-doc
promotion, per item 1). `kit/fulfillment` gains the claim primitive (item
3) and the domain-neutral convergence functions; `compute_provisioning_service`
composes `FulfillmentConvergenceWatchdog` as the asyncio timer.

### Recovery diagnostics contract — resolved (2026-07-24)

Recovery diagnostics use immutable typed results rather than nested dictionaries.
Oldest-row age and maximum attempt count are calculated independently for each
non-terminal recovery lifecycle state, matching the existing per-state row and
claim counts; there are no global oldest-age or maximum-attempt fields. Every
recovery state is present in each snapshot, including zero-valued states, so the
operator-facing schema remains stable. The repository obtains the snapshot with
one grouped aggregate query for recovery states and one grouped aggregate query
for failure-state counts. The convergence worker emits exactly one structured
diagnostics event after each completed cycle and never one event per row.

### Section 6 permanent-documentation impact (for the design-promotion record)

| Decision | Destination |
| --- | --- |
| SQLite single-writer concurrency contract for recovery claims (item 1) | `openspec/specs/fulfillment/spec.md` — also correct "periodic multi-replica recovery sweep" wording |
| Claim/lease primitive semantics (item 3) | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Unbounded-retry posture for dispatch/teardown recovery (item 4) | `openspec/specs/fulfillment/spec.md` |
| `resolve_provisioned_resources` contract and call timing (item 6) | `openspec/specs/fulfillment/spec.md`; `FulfillmentProvider` protocol docstring |
| Watchdog composition and naming (items 2, 8) | `docs/development/ARCHITECTURE.md` (service composition) |



## Section 6 implementation promotion record

| Accepted decision | Permanent location |
|---|---|
| SQLite recovery claims serialize through short `BEGIN IMMEDIATE` transactions and expire durably | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Provider calls occur outside database transactions and outcomes are applied only by the current claim owner | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Provisioned-resource identities are resolved only after confirmed create success and teardown updates existing rows | `openspec/specs/fulfillment/spec.md#fulfillment-results-and-teardown` |
| The compute provisioning service composes one fulfillment convergence watchdog | `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` (corrected 2026-07-24 from an incorrect `docs/development/ARCHITECTURE.md#runtime-service-map` reference recorded during implementation — this is subsystem-specific behavior, not a repository-wide concern) |
| `(capacity_reservation_id, domain_resource_ref)` is a durable unique constraint, not just an application-level dedup check; a genuine concurrent-insert race is resolved by re-reading and returning the winning row, not raising | `kit/fulfillment/src/market_fulfillment/db.py` (`ProvisionedResource.__table_args__`) and `openspec/specs/fulfillment/spec.md#fulfillment-results-and-teardown` |
| Provider-reported success with unresolvable persisted resource metadata is a non-recoverable `failed` transition, not an indefinite retry | `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` |
| Claim-lease backoff and executor job-resubmission backoff are deliberately separate settings namespaces | `provisioning/compute/service/src/compute_provisioning_service/config/config.yml` (comment); no spec.md change needed, this is operational configuration, not subsystem behavior |
| Abandonment reconciliation was evaluated and intentionally not built as a periodic handler — `SettlementAbandonmentHook` (Section 4) already closes the case synchronously | No new spec.md text needed: Section 4's promotion already documents the hook firing unconditionally from every capacity-reclaiming path. This row exists so the "why isn't there a fifth handler" question has a recorded answer rather than looking like an oversight. |
| No attempt-count ceiling anywhere in recovery; a fresh worker instance resumes purely from durable claim state after a restart | `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` |
| Per-cycle recovery diagnostics use typed stable results; total, active-claim, expired-claim, oldest-row-age, and maximum-attempt metrics are calculated per recovery lifecycle state, with separate failure-state counts, and exactly one structured event is emitted per completed cycle | `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`; `market_fulfillment.recovery_diagnostics`; `SettlementRepository.recovery_diagnostics` |
| **(2026-07-24, external code review)** Outcome-application ownership must be checked under an acquired SQLite write reservation, not a plain read — a plain SELECT does not open a SQLite-level transaction on its own, so the original check-then-write sequence left a real, empirically-confirmed gap where a worker whose lease had already been reclaimed could still commit a stale outcome on top of the new owner's claim | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`; `FulfillmentConvergenceWatchdog._with_owned_record` |
| **(2026-07-24, external code review)** `teardown_failed` needed an actual periodic requeue-to-`teardown_dispatch_pending` step; the state comment and spec text documenting it as retryable predated any handler that actually performed the retry | `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker`; `FulfillmentConvergenceWatchdog.requeue_teardown_failures` |
| **(2026-07-24, external code review)** `openspec/specs/fulfillment/architecture.md` still described scheduler assignments and the fulfillment registry as process-local with no durable Settlement Record — stale since Section 3, never corrected during that section's own promotion pass | `openspec/specs/fulfillment/architecture.md#durable-persistence-and-recovery` |
## Section 8 (pull-based status/result and live credentials) — resolved design decisions (discuss phase, resolved 2026-07-25)

Nine items, resolved in discussion before Section 8 is planned (items 6-9 added
2026-07-25 following implementation review; item 6 replaces an earlier, since-
rejected proposal -- see "Section 8 review corrections accepted for planning"
below):

1. **Live credential fetch is stateless — no claim, lease, or rotation
   bookkeeping.** `dev-branch-migration-notes.md`'s candidate shape
   (`get_live_credentials(..., credential_generation=...)` guarded by a
   claim/lease reused from Section 6, advancing generation via
   `complete_credential_rotation` on `rotated=True`) is rejected. A
   claim/lease exists to protect a mutation under concurrent access; a
   live credential read that is never cached and never coordinates a
   rotation has nothing for a lease to protect. `get_fulfillment_result`
   calls a new stateless `FulfillmentProvider.fetch_credentials` directly.

2. **`credential_generation` is dropped from Section 8 entirely**, not
   shipped as a placeholder constant. See the revised "`SettlementResult`
   delivery" note above for the reasoning: there is no rotation source in
   this codebase for it to track. It was briefly considered whether this
   was actually about API-level (storefront↔provisioning) credentials
   rather than VM tenant credentials, or about the `site_resource_pools`/
   `site_capacity_buckets` capacity-and-hosts projection's own
   revision/digest identity (Section 2) moving toward an eventual
   push/subscription delivery model — neither reading fits the field as
   written in the original result-contract task (a value returned inline
   in `get_fulfillment_result`, not a separate projection or an API-auth
   concept), so both are noted here as considered and set aside rather
   than silently dropped. The projection-push idea itself is real future
   work but belongs with a `site_resource_pools`/`site_capacity_buckets`
   delivery change if one is ever proposed, not with Section 8.

3. **Credential fetch is gated to `active` state only.** Every other
   lifecycle state returns the result envelope with empty/null credential
   and provisioned-resource-output fields and no provider call — a
   fulfillment that hasn't produced a resource yet, or has already torn
   one down, has no credentials a provider call could meaningfully return.

4. **Live credential-fetch failure is its own stable-error-taxonomy
   category** (`credential_fetch_failed`), distinct from create/status/
   teardown failure. This is a different handling loop for the storefront:
   a transient fetch failure on an otherwise-healthy `active` fulfillment
   means "retry the read," not "the workload failed."

5. **The result contract is a real versioned envelope**, `fulfillment.result.v1`,
   per the existing "Versioned envelopes" requirement's own scope statement
   that it applies to "settlement/fulfillment result payloads once those
   values cross a durable or cross-domain boundary." Defining it now, not
   deferred, so `provisioning-result-push-delivery` can reuse the same
   shape unchanged, matching what that change's proposal already assumes.

6. **Credential/resource association is domain-specific and many-to-many.**
   The initial per-`ProvisionedResource` proposal keyed by
   `domain_resource_ref` was rejected during review because it both assumed
   one credential belongs to one output and introduced a second generic
   resource identifier without a present consumer. The generic fulfillment
   envelope owns stable `provisioned_resource_id` values. A versioned domain
   result payload may associate one credential with many provisioned
   resources and one provisioned resource with many credentials by those
   fulfillment-owned IDs. For the VM domain, this association belongs in a
   VM-specific type such as `VmFulfillmentCredential`, not in a universal
   credential model.
7. **`domain_resource_ref` is removed rather than renamed.** Multiple outputs
   from one fulfillment are already distinguished by globally unique
   `provisioned_resource_id` values. Provider-operational identifiers such as
   `vm_host`, `vm_target`, and executor job IDs remain in versioned provider
   metadata or prepared teardown input. Buyer-facing domain attributes remain
   in the versioned domain result payload. A second domain-native identifier
   should be introduced only when a concrete cross-boundary use case requires
   one.
8. **Credential reads are all-or-nothing and fresh.** If any credential fetch
   required to build an active result fails, the whole result request fails as
   `credential_fetch_failed`; Section 8 does not define partial-result error
   entries. Every active result read performs a fresh provider lookup. Durable
   fulfillment state and persisted provisioned-resource outputs are stable
   unless the aggregate changes, but credential equality across reads is not
   guaranteed and the read itself never mutates fulfillment state.
9. **Expected provider failures are classified at the adapter boundary, with a
   defensive orchestration fallback.** Adapters translate known metadata,
   provider, and credential-store failures into `CredentialFetchFailedError`.
   The orchestration layer also wraps unexpected provider exceptions in the
   same public category while recording safe diagnostic context and never
   logging credential material.

### Section 8 review corrections accepted for planning (2026-07-25)

The initial implementation review found that the generic result contract was
still VM-shaped, that the proposed per-resource credential boundary could not
represent credential reuse, and that `domain_resource_ref` duplicated the
fulfillment-owned output identity without a demonstrated consumer. The accepted
correction is to keep the outer `fulfillment.result.v1` transport envelope
provider-neutral while moving credential structure and resource association into
a versioned domain payload. The VM payload will use `VmFulfillmentCredential`
and represent a many-to-many relationship through `provisioned_resource_id`.
`domain_resource_ref` will be removed from the generic durable/result model;
provider-operational VM identity remains in provider metadata and prepared
teardown input.
The review also confirms all-or-nothing credential-fetch failure for v1, fresh
credential lookup on every active read without an equality/idempotency guarantee,
adapter-owned expected exception translation with a defensive orchestration
fallback, and the requirement to prove restart and repeated-read behavior with
dedicated tests rather than inference from one-shot reads.

**Former task 8.5 (per-caller ownership enforcement) is out of scope for
this section.** `StorefrontAuthMiddleware` gates the whole service behind
one shared `admin_api_key` with no per-request caller identity — by its
own docstring, "the provisioning service is an internal dependency of a
single storefront." An ownership check has no second caller identity to
compare against under that model. Real per-caller enforcement is deferred
to a new prerequisite change, `add-storefront-principal-authentication`
(proposed 2026-07-25; see its `proposal.md`/`design.md`), which gives the
provisioning service real per-request principal identity and an
`owner_principal` column on `SettlementRecord`. That change's candidate
starting shape is this file's own "Flagged as new, unscoped, cross-cutting
work: Multi-principal storefront authentication and per-record ownership"
note above (`configured_storefront_principals`, `request.state.
storefront_principal`, `owner_principal` column) — re-evaluated against
its own accepted contracts before being treated as a starting point, per
that note's own caveat. Section 8 ships task 8.5 as an existence-only
check (reject unknown identifiers) structured so the later
`owner_principal` comparison can replace it without reshaping the
endpoint, and `provisioning-result-push-delivery` gains a second, direct
dependency on `add-storefront-principal-authentication` alongside its
existing dependency on this change.

### Section 8 completed design-promotion record

| Decision | Destination |
| --- | --- |
| Provider-neutral `fetch_credentials` contract, no claim/lease/rotation bookkeeping | `openspec/specs/fulfillment/spec.md#requirement-provider-contract`; `FulfillmentProvider` protocol docstring |
| `active`-only credential-fetch gating and non-`active` empty-envelope behavior | `openspec/specs/fulfillment/spec.md` |
| `fulfillment.result.v1` envelope shape | `openspec/specs/fulfillment/spec.md#requirement-versioned-envelopes` |
| `credential_fetch_failed` stable error category | `openspec/specs/fulfillment/spec.md#requirement-stable-error-taxonomy` |
| Many-to-many credential/output association via `provisioned_resource_id`; `VmFulfillmentCredential` VM-domain payload; `domain_resource_ref` removed | `openspec/specs/fulfillment/spec.md`; `openspec/specs/physical-provisioning/spec.md#requirement-vm-fulfillment-result-payload` for the VM payload and credential fields |
| No `credential_generation` field; rationale | `openspec/specs/fulfillment/spec.md` (state explicitly, so a future reader doesn't reintroduce it without re-deriving this reasoning) |
| Ownership-check scope split between this change (existence-only) and `add-storefront-principal-authentication` (real enforcement) | `openspec/specs/fulfillment/spec.md`; `openspec/changes/add-storefront-principal-authentication/proposal.md` |

### Section 8 implementation confirmation (2026-07-25)

All six discuss-phase decisions and the ownership-check split were implemented as recorded; each destination cell above now contains the corresponding promoted text. One correction found during implementation, not a design change: the discuss-phase text assumed `AnsibleFulfillmentProvider.fetch_credentials` would need an async HTTP call through `vm_provisioning_operator.client` to a separate adapter service. In fact `AnsibleFulfillmentProvider` and `AnsibleJobService` (which owns `get_credentials`) run in the same process/service already -- the call is a local, synchronous DB read, wrapped in an `async def` only to satisfy the provider-neutral interface (the same shape `get_status`/`get_job` already has). No design implication beyond the implementation itself; recorded here so a future reader of the discuss-phase note above isn't misled by the superseded assumption.

**Superseded by review, 2026-07-25:** the paragraph above predates the "Section 8 review corrections accepted for planning" section further up this file. Item 6's original credential-per-`ProvisionedResource`/`domain_resource_ref` boundary was implemented as first written, then rejected on review and replaced by the many-to-many `provisioned_resource_id`/`VmFulfillmentCredential` design items 6-9 now describe. "All six discuss-phase decisions... implemented as recorded" is therefore only accurate for items 1-5 and the ownership-check split; item 6 was implemented, reviewed, and reimplemented, not implemented once and left standing. See `tasks.md`'s 8.9/8.10 notes for what the corrected implementation actually shipped.

`get_fulfillment_result` was implemented as `async def` (the discuss-phase note did not specify sync/async for the orchestrator method itself, only for `fetch_credentials`); the read transaction closes before the awaited provider call, per the no-transaction-open-during-provider-I/O principle already established for the convergence worker.


## Section 9 (cut over storefront orchestration) — design review (discuss phase, opened 2026-07-25)

Read against current code, not assumed from `proposal.md`'s "Why" narrative or
`tasks.md`'s 9.1–9.7 task text, both of which predate this review and are
partly stale.

### 1. Task 9.1's premise is partly already satisfied

`proposal.md`'s "Why" says the storefront reserves with
`required_attributes=("vm_host",)`. Current code
(`vm_job_spec_service.compute_capacity_claim_from_order`) already builds a
pool/resource/dimension-shaped claim (`pool_id` or `resource_id`, plus a
`dimensions` map) — the POOLS-4 claim shape 9.1 asks for is implemented.
What 9.1 actually still needs: the reservation response's `vm_host` (a
concrete, feasibility-verified host bound at `reserve()` time — this is
correct, current, "Option A" behavior per this file's "`SiteResource` is
retired" section, not a bug) is today read directly by
`vm_fulfillment_service.py` and handed straight to the executor. Task 9.2,
not 9.1, is where that direct hand-off must be replaced by an explicit
`schedule_resource` call that confirms or fairness-reassigns the settlement
resource before `begin_fulfillment`. 9.1's own text should be corrected to
say this rather than describing the claim-shape work as still to do.

### 2. `schedule_resource` has no HTTP endpoint

`kit/fulfillment/src/market_fulfillment/scheduler.py`'s
`PhysicalSettlementScheduler.schedule_resource` is composed into
`compute_provisioning_service/container.py` but
`fulfillment_controller.py` exposes only `/validate`, `/begin`,
`/{id}/status`, `/{id}/result` — no `/schedule` route. `begin_fulfillment`
requires an already-scheduled `SettlementRecord` (raises `LookupError` /
404 `fulfillment_not_found` otherwise per its own controller mapping), so
the storefront cannot reach the scheduling step at all today, over HTTP,
regardless of what 9.2's storefront-side code does. This blocks 9.2 and is
not called out as its own task anywhere in Sections 1–8.

**Proposed resolution:** add `POST /fulfillment/schedule` to
`fulfillment_controller.py`, wrapping `PhysicalSettlementScheduler.schedule_resource`
the same way `/begin` wraps `FulfillmentOrchestrator.begin_fulfillment` —
same error-mapping conventions (404/409/422 per the existing
`SettlementEntityNotFoundError`/`FulfillmentConflictError`/etc. taxonomy).
The "thin convenience operation" this file already describes (composing
schedule+begin for callers that don't need the placement preview) can be a
second route or a query flag on `/begin`, not a replacement for exposing
`schedule_resource` on its own — 9.2's design explicitly wants the preview
available separately when commercially material.

### 3. No shared client-side contract for the fulfillment HTTP surface

Unlike every other endpoint family this service exposes (`ExecutorActionEnvelope`,
`ProvisioningJob`, `LeaseRegistration`, `LeaseView`, ... all defined once in
`provisioning/compute/src/compute_provisioning/contracts.py` and consumed by
both the server and `ComputeProvisioningClient`), `FulfillmentRequestBody`,
`FulfillmentAcceptanceResponse`, `FulfillmentStatusResponse`, and
`FulfillmentValidationResponse` are defined only inside
`compute_provisioning_service/controllers/fulfillment_controller.py` —
server-only, nothing shared. `ComputeProvisioningClient` has no
`schedule`/`begin`/`get_fulfillment_status`/`get_fulfillment_result` methods
at all today.

**Proposed resolution:** move these four models (plus a new
`FulfillmentScheduleRequest`/`FulfillmentScheduleResponse` pair for the new
route) into `compute_provisioning.contracts`, matching the established
pattern, and have `fulfillment_controller.py` import them from there
instead of declaring local duplicates. Add corresponding methods to
`ComputeProvisioningClient`. Open sub-question: `contracts.py` has its own
`COMPUTE_PROVISIONING_CONTRACT_VERSION`/`VersionedContractModel` scheme,
independent of `market_fulfillment`'s `VersionedEnvelope`/`fulfillment.result.v1`
versioning. The fulfillment response models should carry a
`contract_version` field for consistency with every sibling contract in this
file, without conflating it with the *inner* envelope's own
`schema_version` — two different, deliberately independent version axes,
not one collapsed into the other.

### 4. Site-routing durability is incomplete for the new calls

`core_storefront/aggregation.py`'s `AggregateCapacityClient._reservation_sites`
is an in-memory, process-local cache mapping `capacity_reservation_id` →
site name, explicitly documented as cold after a restart (falls back to
fanning out to every site). `schedule_resource`/`begin_fulfillment`/
`get_fulfillment_status`/`get_fulfillment_result` have no existing home on
`AggregateCapacityClient` (it only implements the six `CapacityClient`
protocol methods) and therefore no routing mechanism of their own yet.

**Proposed resolution:** extend `AggregateCapacityClient` (or a sibling
aggregator reusing its `_reservation_sites` cache and `_route_order` fallback)
with the four new calls, so in-process routing matches `commit`/`release`'s
existing pattern. Separately, amend task 9.3: it currently says to persist
`capacity_reservation_id`, the selected settlement resource, and
`fulfillment_id` for restart recovery, but not which site owns them. Since
the site authority URL and the fulfillment HTTP surface are the same
deployed service (confirmed: `_capacity_settings()`'s `sites` map already is
the provisioning-service base URL), persisting the site name alongside the
other three values in the storefront's own durable workflow row is cheap and
avoids relying on a blind fan-out for a call that mutates state
(`begin_fulfillment`) — fan-out would still be *correct* here given
schedule/begin's idempotent-retry contract, but persisting the site is
simpler and matches 9.3's own restart-safety goal directly.

### 5. Naming collision: `fulfillment_uid` vs. `fulfillment_id`

The storefront's existing schema already uses `fulfillment_uid` for the
on-chain settlement-claim identity (Alkahest escrow arbitration target —
`groups/escrow.py`, `claims_runtime.py`, `listing_service.py`). `kit/fulfillment`'s
`fulfillment_id` (this change's durable physical-provisioning aggregate
identity, `ARCHITECTURE.md`'s "Shared vocabulary and identities" table) is a
different concept that will now be persisted in the same escrow-scoped
workflow row per task 9.3. `ARCHITECTURE.md`'s vocabulary table lists
`fulfillment_id` but has no entry for `fulfillment_uid` at all today.

**Proposed resolution:** when 9.3 adds storage for the new identity, name
the column/field something unambiguous — e.g. `provisioning_fulfillment_id`
— rather than `fulfillment_id` bare, and add `fulfillment_uid` to
`ARCHITECTURE.md`'s vocabulary table alongside `fulfillment_id` with a
one-line disambiguation, since both now legitimately coexist on the same
row and the table's job is exactly to prevent this kind of collision from
being silently discovered later.

### 6. `register_lease` (`/api/v1/contract/leases`) sequencing

`fulfillment_service.py`'s `_register_vm_lease_with_settings` calls the
legacy `POST /api/v1/contract/leases` endpoint via `ComputeProvisioningClient`
today. This is exactly the legacy-lease bookkeeping Section 7's backfill
migrates *from* and Section 11 removes the schema for. Once 9.2 wires a real
`begin_fulfillment` call, the durable `SettlementRecord` it creates
supersedes what `register_lease` records — leaving both call sites active
between 9.2 landing and Section 11's cleanup would write two
partially-overlapping durable records per fulfillment with nothing keeping
them consistent.

**Proposed resolution:** remove the `register_lease` call site as part of
9.2/9.6 (when direct executor dispatch is replaced), not deferred to 11.1's
generic schema removal — 11.1 should drop the now-provably-unused
table/endpoint, not be the first point where the *call site* stops being
exercised.

### 7. Minor, non-blocking observations

- `fulfillment_service.py`'s `_do_shutdown` already unconditionally raises
  `NotImplementedError` in production (the provisioning service was never
  given a `schedule_expiry` endpoint); it's caught and logged by
  `_schedule_shutdown_best_effort`'s own try/except, so this is inert
  log-spam today, not a live bug 9.x introduces or must fix. It is Section
  10's concern (teardown cutover), not Section 9's — noted here only so it
  isn't mistaken for new breakage once 9.x starts touching this file.
- `PhysicalSettlementScheduler`'s `default_resource_kind="compute.gpu"` is
  already composed at the VM composition root
  (`compute_provisioning_service/container.py`), so the storefront does not
  need to supply `resource_kind` explicitly in the ordinary VM path. It does
  need to supply `market`; no canonical value is documented anywhere, but
  `provisioning/compute/service/tests/integration/test_fulfillment_api.py`
  already uses `"vms"`, matching the `domains/vms` package name. Proposed:
  adopt `"vms"` as the VM domain's `market` value for schedule/begin calls,
  and record it once `ARCHITECTURE.md`'s vocabulary section once decided.

### Resolved (2026-07-25)

1. **Contract placement:** fulfillment wire models move into
   `compute_provisioning.contracts`, matching every other endpoint family.
   Confirmed — not the alternative (storefront importing `market_fulfillment`
   types directly).
2. **New tasks vs. folding into 9.2:** the missing `/fulfillment/schedule`
   route and the shared client contracts get their own explicit subtasks in
   `tasks.md`'s Section 9 list, ahead of the existing 9.1–9.7, rather than
   being absorbed silently into 9.2's text. Confirmed.

### Resolved (2026-07-25, continued)

3. **`fulfillment_uid` vs. `fulfillment_id`:** keep `fulfillment_id` bare
   rather than renaming to `provisioning_fulfillment_id`. The existing
   `_uid`/`_id` suffix distinction from `fulfillment_uid` is tried first as
   sufficient disambiguation; add both terms to `ARCHITECTURE.md`'s "Shared
   vocabulary and identities" table with a one-line note distinguishing
   them (on-chain settlement-claim identity vs. physical-provisioning
   aggregate identity). Revisit the name later if this proves confusing in
   practice — not committed permanently, chosen as the first thing to try.

4. **Site-routing for schedule/begin/status/result:** do not add these
   methods to `AggregateCapacityClient`/`RemoteCapacityClient` — those are
   deliberately scoped to the `CapacityClient` protocol's
   `/api/v1/capacity` site-ledger surface only (`RemoteCapacityClient`'s own
   docstring: "speaks one site authority's `/api/v1/capacity` HTTP
   surface"). Instead:
   - Add a new sibling aggregator (name TBD at planning time, e.g.
     `AggregateComputeProvisioningClient`) mapping site name →
     `ComputeProvisioningClient` instance, routing the four new calls the
     same way `AggregateCapacityClient` routes `commit`/`release` — owning
     site first (cache hit), fan-out to the rest on a cold cache.
   - Reuse the *same* `_reservation_sites` mapping instance
     `AggregateCapacityClient` already populates at `reserve()` time, rather
     than maintaining a second, independently-populated cache. This
     requires promoting `_reservation_sites` from `AggregateCapacityClient`-
     private state to a shared object the composition root
     (`market_storefront/services/capacity_client.py`) constructs once and
     passes to both aggregators.
   - `ComputeProvisioningClient` itself is **not** renamed and **not**
     split. Checked directly: every model in
     `compute_provisioning/contracts.py` (`ExecutorActionEnvelope` through
     `LifecycleEvent`) is free of dimension/shape coupling (`ram_gb`,
     `vcpu_count`, `gpu_count`, `dimensions` do not appear anywhere in that
     file; `deal_ref`/`parameters` are opaque dicts, `executor_kind`/
     `action_kind` are plain strings). `openspec/specs/physical-provisioning/spec.md`'s
     "Compute-owned caller contract" requirement already documents
     `fulfillment` as one of the generic, executor-neutral surfaces this
     package is meant to cover, alongside job/lease/capacity — the new
     methods are a documented fit, not scope creep.
   - Non-blocking naming observation, not resolved here: "compute" as a
     package/service boundary name encodes a "has a physical resource"
     commitment (VM, bare-metal, future kube-pod-style executors per
     `ARCHITECTURE.md`'s runtime service map) that is narrower than fully
     domain-agnostic (excludes apicredits, correctly) but the exact
     intended boundary of that commitment (would it fit an electricity
     market? would each unit in a non-physical market like NFTs be a
     "physical_resource"?) has not been reviewed and is out of scope for
     Section 9. Left as a flag for a future change, not a blocker here.

5. **`register_lease` removal timing — corrected, not safe for 9.2/9.6:**
   traced further than the original proposal. `register_lease` does not
   write a separate, superseded table — it attaches `executor_kind`/
   `executor_target`/`executor_ref` directly onto the *same*
   `CapacityReservation` row via `attach_lease_reservation`. Today's legacy
   teardown path reads exactly those fields:
   `LeaseWatchdog` → `LeaseLifecycleService._run_release_delegate` →
   `VmReleaseExecutor.submit_release(reservation)`, which pulls `vm_host`
   and `executor_target` off the row and silently no-ops (leaking the VM)
   if they're missing. Removing the `register_lease` call site in 9.2/9.6 —
   before Section 10 replaces `VmReleaseExecutor` (task 10.5) — would strand
   every VM fulfilled through the new path with no teardown mechanism at
   all. **Decision: `register_lease` stays active through all of Section 9;
   its removal is sequenced with Section 10, specifically task 10.5.** This
   dependency will be noted explicitly on 10.5 when Section 10 is planned.

6. **`market` value:** adopt `"vms"` for the VM domain's schedule/begin
   calls (matching the existing integration test and the `domains/vms`
   package name), pending no objection — not separately contested during
   this review.

This closes the Section 9 discuss-phase design review. Remaining follow-up
work (adding explicit tasks for the `/fulfillment/schedule` endpoint and
shared client contracts, the new sibling aggregator, and the 10.5
dependency note) belongs to the plan phase, not this document.

### Section 9 completed design-promotion record

| Decision | Destination |
| --- | --- |
| `POST /fulfillment/schedule` HTTP contract (request/response shape, 404/409/422 error mapping, schedule-before-begin requirement) | `openspec/specs/fulfillment/spec.md` (new scenarios under "Scheduling and assignment") |
| `schedule_resource`/`begin_fulfillment`/`get_fulfillment_status`/`get_fulfillment_result` as generic `ComputeProvisioningClient` methods, not split into a separate client/class | `openspec/specs/compute-provisioning-contract/spec.md#requirement-fulfillment-scheduling-and-acceptance` |
| Sibling aggregator (`AggregateFulfillmentClient`) pattern and shared `reservation_sites` cache, not an extension of `AggregateCapacityClient`/`RemoteCapacityClient` | `core_storefront/aggregation.py` and `market_storefront/services/capacity_client.py` docstrings — no dedicated subsystem spec exists for storefront-side capacity aggregation at all (checked); recorded as code-owned rationale, not promoted into a new spec file for this one mechanism |
| `fulfillment_id`/`fulfillment_uid` disambiguation | `docs/development/ARCHITECTURE.md`, "Shared vocabulary and identities" |
| `VmConnectivitySettings` (buyer/storefront-configured FRP, request-side) and `VmConnectionInfo` (provider-reported VM metadata, result-side) as separate, direction-specific models rather than one shared shape | `vm_provisioning_adapter/models/fulfillment_model.py` and `vm_provisioning_adapter/fulfillment_results.py` docstrings; no subsystem spec change, since these are VM-domain-adapter-internal shapes the fulfillment kit itself never inspects |
| Three-tier VM sizing precedence (buyer-specified, pool default, Ansible/inventory unset) | `vm_provisioning_adapter/models/fulfillment_model.py`'s `AnsiblePoolConfig` docstring |
| Buyer-specified/negotiated connectivity terms split into a separate change | `openspec/changes/add-buyer-vm-connectivity-terms/proposal.md`; registered in `openspec/changes/README.md` |
| `register_lease` removal sequencing (Section 10 task 10.5, not 9.2/9.6) | Noted on both `tasks.md`'s 9.2 and 10.5 entries |
| `capacity_reservation_id`/`settlement_resource_id`/`fulfillment_id` persisted on the shared `escrows` table, a prerequisite for future restart recovery — **not itself restart recovery**; nothing yet reads these values back to resume an in-progress fulfillment after a crash (see the Section 9 status note below) | `core_storefront/sqlite_client.py` schema/docstrings; no subsystem spec covers storefront-side escrow persistence as its own capability, so this is recorded as code-owned schema documentation, matching the existing `fulfillment_uid`/`provisioning_job_id` precedent on the same table |

### Section 9 implementation confirmation (2026-07-26)

Every decision above was implemented as recorded, with four corrections
found during implementation, not design changes: (1) the legacy VM
provisioning path never sent `vm_ram`/`vm_vcpus`/`vm_disk_size` at all
(relied on Ansible inventory defaults), while the new `VmFulfillmentRequirements`
initially made them required — traced against the actual Ansible role and
made optional with the three-tier precedence above, rather than either
silently breaking every ordinary fulfillment or inventing plausible-looking
required values; (2) `VmFulfillmentCredential` and the new fulfillment
result payload were both missing real data the legacy path carried
(`ssh_key_path_host`/`key_type` on credentials; `vm_name`/`host`/`timestamp`/
`tenant_user`/`vm_ip_internal`/`ssh_port` as connection metadata) — both
gaps traced to their actual source (`job_service.get_credentials`/
`AnsibleJob.result`) and fixed, not assumed acceptable to drop; (3) the
`on_job_submitted` callback in `vm_fulfillment_service.py` was found
persisting a durable `fulfillment_id` value into the `provisioning_job_id`
column (a column whose entire meaning is an ephemeral executor job id) —
renamed the callback and its column target to match what it actually
receives; (4) `domains/vms/storefront/Makefile`'s `reinit` target was
missing `arkhai-kit-fulfillment` (a genuinely new dependency for that
project) and, on a real `make test` run rather than this session's own
sandbox verification, was found also missing `arkhai-kit-site`/
`arkhai-kit-resource-pools` (kit/fulfillment's own transitive dependencies,
never previously forced to refresh in that project's venv) — both fixed.
None of the four change what was decided above; all are places the
implementation would otherwise have silently diverged from, or failed to
apply, an already-correct decision.

### Section 9 reconciled status (2026-07-26, after external code review)

An external review of the completed 9.0–9.8 work found the design-promotion
record above overclaiming one decision ("restart-safe... resumption") and
several documentation-compliance gaps (a too-narrow reference sweep that
missed non-`POOLS-7`-prefixed change-document and section-number references;
a stale `proposal.md`). Those mechanical issues are fixed as of this note.
The review's substantive finding is not mechanical and is not yet resolved:

**Accepted (discuss-phase decisions, still standing):** the sibling
aggregator over `AggregateCapacityClient`/`AggregateFulfillmentClient`
architecture; `schedule_resource` → `begin_fulfillment` → poll
status/result as the fulfillment-cutover shape; `VmConnectivitySettings`/
`VmConnectionInfo` as separate request/result-side models; the three-tier
VM sizing precedence; `register_lease` removal sequenced with Section 10;
`fulfillment_id` kept bare (not renamed) alongside `fulfillment_uid`.

**Implemented and verified:** the HTTP schedule endpoint and shared client
contracts; the storefront cutover itself (`_do_provision`); durable
identifier *persistence* (writes, not resumption — see below); status/
credential delivery parity with the legacy path, including four real data
gaps found and fixed (VM sizing, credential fields, result connection
metadata, an `on_job_submitted`/`provisioning_job_id` naming bug); site
routing with cold-cache fan-out; a real `make test` environment gap
(missing transitive `reinit` dependencies) found and fixed.

**Not implemented, contrary to what "restart-safe... resumption" language
in an earlier version of this record implied:** nothing reads the
persisted `capacity_reservation_id`/`settlement_resource_id`/
`fulfillment_id` back to resume an in-progress fulfillment after a
storefront restart or crash. `_do_provision` always runs
schedule→begin→poll→result from the top; there is no separate resume path
that skips straight to polling an existing `fulfillment_id`. This matters
concretely, not just formally: `capacity.reserve()` is not idempotent by
request content the way `schedule_resource`/`begin_fulfillment` are — it
mints a fresh `capacity_reservation_id` on every call — so a naive
"re-invoke the same call after a crash" retry would reserve a second
capacity allocation rather than resume the first. Persistence-write
failures are currently best-effort (logged, not escalated, not retried),
which is the same class of gap: the identifiers this section added exist
to prevent orphaned work, but a failed write to them is not itself
detected or recovered from.

**Fixed since the review (2026-07-26):** identity-persistence writes now
retry a bounded number of times and escalate loudly (ERROR, not WARNING)
on final failure rather than a single silent attempt (`persist_escrow_fields_with_retry`
in `vm_fulfillment_service.py`). `fulfillment_id` is now exposed on all
three buyer-facing settlement response models. `physical-provisioning/spec.md`'s
VM fulfillment result payload and Ansible fulfillment adapter requirements
now document the sizing precedence, connectivity forwarding, and
credential/connection-metadata field changes made in this section. A
broader documentation-reference sweep (not just the `POOLS-7`/`pools-7`
prefix originally checked) found and fixed several more change-document
and section-number references this section's own comment cleanup had
missed.

**Still not fixed -- the substantive finding stands:** persistence
retrying and escalating on failure is not the same as *implementing
recovery*. Nothing yet reads a persisted `fulfillment_id` back to resume
an in-progress fulfillment after a restart or crash. This remains the
open item below.

**Validation still required before Section 9 is considered closed:**
a real fresh-process/fresh-composition restart test (not just persistence
round-tripping and cold-cache fan-out, which prove prerequisites for
recovery, not recovery itself); a crash-window matrix across the
schedule/begin/poll/result/store/complete sequence; stricter exception
classification in the aggregator's fan-out (a genuine "wrong site" 404
versus auth/validation/timeout/5xx currently route identically).

**Open discuss-phase questions this raises:**

1. **Resolved and implemented (2026-07-26):** `capacity.reserve()`
   (`CapacityLedgerService.reserve` in `kit/site/src/market_site/ledger.py`)
   is now idempotent by `deal_ref["escrow_uid"]`: a repeat call for an
   escrow_uid with an existing reservation in any held state returns that
   reservation instead of admitting a second one, using the existing
   `_find_reservation(db, escrow_uid=...)` lookup (already used by
   `get_reservation_by_escrow` and `commit`/`release`'s own lookups, just
   not previously called from within `reserve()` itself). No new
   caller-supplied identity parameter was needed -- `deal_ref` already
   carried `escrow_uid` on every call site. Promoted into
   `openspec/specs/site-capacity/spec.md`'s "Reservation lifecycle"
   requirement, which already stated reservation "MUST... be idempotent
   for retries" -- `commit`/`release` already satisfied that; `reserve()`
   itself did not, until now. 6 new tests in `kit/site/tests/unit/test_ledger.py`.
2. **Resolved and implemented (2026-07-26):** a failed identity-persistence
   write is now retried a bounded number of times and escalated loudly
   (ERROR, not silently logged) rather than proceeding on a single silent
   attempt. See `persist_escrow_fields_with_retry`.
3. Which component owns scanning for and resuming incomplete escrow
   fulfillments after restart (storefront startup, a dedicated watchdog, or
   the existing settlement-job runner) — under investigation, not yet
   decided.
4. **Resolved and implemented (2026-07-26):** the buyer-facing settlement
   status response now exposes `fulfillment_id` (`SettleResponse`,
   `SettleStatusResponse`, `SettleWaitResponse`), now that
   `provisioning_job_id` is permanently empty for the new path.
5. Which permanent subsystem specification should own storefront
   fulfillment-progress and recovery semantics generally — under
   investigation, not yet decided.

Section 9 is not considered closed pending resolution of questions 3
and 5, and the validation gaps above.



## Section 9 fulfillment-resume design decisions (2026-07-26)

### Accepted commercial-delivery priority

Once a deal has been accepted, commercial delivery takes priority over local
bookkeeping durability. Storefront persistence writes MUST be retried and
exhausted retries MUST be logged loudly with safe lifecycle identifiers, but a
local SQLite persistence failure MUST NOT by itself cause the storefront to
abandon a VM that can still be provisioned and delivered under the accepted
deal. Fail-closed persistence behavior is appropriate only before deal
acceptance. After acceptance, recovery reconciles the local record against the
capacity, fulfillment, credential, chain, and claim authorities using their
available idempotent or queryable boundaries.

This priority is durable VM-storefront behavior and must be promoted into the
VM-domain storefront/adapter specification during Section 9 implementation.

### Accepted recovery model

Section 9 will use a VM-storefront-scoped durable convergence state machine.
The existing foreground settlement job and a new dedicated startup background
worker will call the same convergence implementation. The foreground behavior
remains blocking in Section 9; converting initiation and convergence into the
normal asynchronous product flow is deferred to a separate future OpenSpec
change.

The recovery worker owns full settlement convergence through physical
fulfillment, result and credential persistence, lease registration, on-chain
fulfillment, escrow readiness, and claim creation. It is not part of the claims
engine and does not stop after physical result retrieval.

The storefront will persist a versioned VM fulfillment-context envelope on the
escrow record before physical fulfillment acceptance. The envelope preserves
the immutable inputs required to make an equivalent scheduling/acceptance retry,
including the generated VM target and normalized fulfillment request, without
adding VM-specific columns for every request field to the shared escrow schema.
Unknown envelope kinds or schema versions fail visibly rather than being guessed
into the current model.

A dedicated periodic worker, registered through the existing storefront startup
background-task mechanism, will sweep nonterminal primary escrows. It must also
consider rows lacking persisted lifecycle identifiers because accepted deals can
survive a failed local write. The worker reconciles from the earliest safe
boundary supported by the surviving context and external authorities. Persisted
`fulfillment_id` skips scheduling and acceptance; a missing identifier uses the
persisted request envelope to make equivalent retries.

Aggregate fulfillment routing retains parity with the existing aggregate
capacity-client fallback behavior for this section. Typed fallback/error
classification across both aggregate clients is deferred as one aggregation-wide
concern rather than changed for only one sibling.

`deal_ref` will be removed from the new `_do_provision` fulfillment seam and
`escrow_uid` passed explicitly. The legacy `vm_host` compatibility parameter is
deferred to Section 10.

### On-chain fulfillment idempotency assessment

Repository inspection does not establish `submit_compute_fulfillment` as
idempotent. The helper serializes wallet transactions with `chain_tx_lock` and
then calls `client.string_obligation.do_obligation(connection_details,
escrow_uid)`. It does not provide a deterministic idempotency key, query for an
existing matching fulfillment, persist a transaction intent before submission,
or reconcile a transaction receipt after an ambiguous return. The demo-mode
path also generates a fresh random fulfillment identifier on every call.

No higher storefront layer currently deduplicates this call before submission.
The local `fulfillment_uid` write happens only after `do_obligation` returns, so
a process failure after the chain accepts the transaction but before the local
write leaves an external-commit/local-persistence ambiguity. The Ansible layer
cannot close this chain-side gap.

Therefore Section 9 must not assume that retrying
`submit_compute_fulfillment` is safe. Planning must include chain reconciliation
before resubmission: query authoritative chain state for an existing fulfillment
attestation matching the escrow, seller, obligation schema, and expected
connection-details payload, and reuse its UID when exactly one valid match
exists. If the current Alkahest client does not expose such a query, Section 9
must add a narrow adapter/query surface or retain the escrow in a visible
operator-recovery state rather than blindly create another attestation.

### Permanent documentation disposition

The accepted storefront convergence, versioned recovery-context, aggregate
routing, and delivery-over-bookkeeping decisions belong in VM-domain
storefront/adapter-scoped permanent documentation. A standalone recovery spec or
an aggregation spec folder is not introduced solely for Section 9. The active
change documents retain the design alternatives and migration plan; production
code and permanent documentation must describe only the resulting current
behavior.

## Section 9 recovery design conclusion and planning record (2026-07-26)

The remaining Section 9 recovery design is accepted and ready for implementation planning.

### Delivery priority after deal acceptance

Once a deal has been accepted, commercial delivery takes priority over local bookkeeping durability. Storefront-local persistence writes MUST be retried and failures MUST be logged with sufficient safe identifiers for operator diagnosis, but an exhausted local metadata write MUST NOT by itself cause the storefront to abandon a VM it can still build and deliver. Recovery therefore reconciles durable local evidence with the capacity, fulfillment, credential, chain, listing, and claims authorities rather than assuming every prior local checkpoint succeeded.

This priority is VM storefront settlement behavior and will be promoted to the permanent VM storefront/adapter-scoped specification. It does not weaken pre-acceptance validation or permit accepting a deal when required durable preconditions are unavailable.

### Selected recovery architecture

The selected design is a durable VM storefront convergence state machine with a versioned recovery-context envelope on the escrow row.

The ordinary foreground settlement task remains blocking in this section and continues to attempt the complete fulfillment sequence. Section 9 does not implement the separately deferred initiate/converge product redesign. Instead, the foreground task and a new dedicated startup worker invoke the same idempotent convergence operations so interrupted work can continue after restart.

The worker is registered through `start_storefront_background_task`, owns its own `SQLiteClient`, and periodically sweeps nonterminal primary VM escrows. It is separate from `claims_engine_loop`, because claims processing begins after fulfillment and has a different authority and retry boundary.

Recovery owns full settlement convergence, not physical polling alone. It continues through physical result retrieval, credential delivery, lease registration required by the still-active Section 10 compatibility path, on-chain fulfillment reconciliation/submission, listing update, escrow readiness, and claim creation.

### Versioned VM fulfillment context

Before the first externally visible physical-fulfillment mutation, the storefront persists a versioned VM-domain recovery envelope containing the immutable information needed to reproduce an equivalent request and finish settlement. The envelope uses one shared escrow column rather than adding VM-specific columns to the generic escrow schema.

The envelope includes, at minimum, the accepted listing/order references needed by the VM storefront, the generated `vm_target`, the exact normalized physical `fulfillment_request`, lease timing inputs, the SSH key and connectivity inputs required to reproduce that request, and chain-reconciliation context. Secret response credentials are not placed in this request envelope.

The envelope has a stable kind and positive schema version. Readers reject unknown kinds or unsupported versions visibly instead of guessing. Permanent documentation will define the envelope's ownership, lifecycle, and redaction requirements; the exact Python carrier remains VM-domain-owned.

### Reconciliation from the earliest safe boundary

The convergence operation scans every nonterminal primary VM escrow, including rows where no capacity or fulfillment identity was persisted.

- When no capacity reservation is recorded, it invokes escrow-idempotent reservation recovery.
- When no settlement resource is recorded, it invokes equivalent scheduling.
- When no `fulfillment_id` is recorded, it invokes equivalent `begin_fulfillment` with the exact request preserved in the recovery envelope.
- When `fulfillment_id` exists, it skips schedule/begin work and resumes status/result convergence directly.
- Nonterminal physical state leaves the escrow pending for a later sweep.
- Terminal physical failure applies the existing commercial failure policy.
- Active physical state converges all downstream settlement effects before marking the escrow ready.

Each recovered identifier or checkpoint is persisted with bounded retry. Persistence exhaustion is loud but does not abort a live deliverable operation after deal acceptance.

### Shared convergence implementation

Foreground and recovery execution MUST NOT maintain independent copies of the settlement sequence. Section 9 extracts shared phase operations from the existing storefront fulfillment path and uses them from both callers.

The shared implementation preserves the current blocking storefront behavior. Moving ordinary fulfillment initiation and convergence into separate user-visible phases is deferred to a new future OpenSpec change rather than Section 10 or 11.

`escrow_uid` is passed explicitly through the durable fulfillment path. The opaque `deal_ref` parameter is removed from `_do_provision` and retained only at compatibility or commercial-boundary adapters where required. The existing `vm_host` compatibility parameter is not changed in Section 9; its removal or reshaping is Section 10 work.

### Concurrency and replay

The foreground task and startup worker may observe the same escrow. Correctness therefore relies on durable, cross-process coordination plus replay-safe phase operations, not a process-local lock.

Implementation will first inventory existing escrow update/claim primitives and use the narrowest durable mechanism that prevents simultaneous phase execution. A renewable escrow processing lease is preferred if no suitable compare-and-set primitive already exists. The lease must expire after process death and must not become a permanent ownership record.

External side effects are reconciled against their owning authorities before replay whenever local persistence may have been lost.

### On-chain fulfillment is reconciliation, not blind retry

Repository and available Alkahest surfaces do not establish `string_obligation.do_obligation` as idempotent. `chain_tx_lock` serializes wallet nonce use only. The obligation's `refUID` references the escrow but is not a uniqueness constraint, and a successful transaction followed by loss of its returned UID creates an ambiguous local state.

Before submitting an on-chain compute fulfillment when no local `fulfillment_uid` is available, the VM settlement adapter queries chain truth for existing matching attestations. Raw EAS/RPC event scanning and attestation decoding belong in `kit/alkahest`; matching the VM string-obligation schema, escrow reference, storefront attester, recipient semantics, connection-details payload, and active state belongs in the VM settlement adapter.

RPC/event-based reconciliation is authoritative. A hosted indexer may be added later as an optimization but cannot be the correctness boundary.

Reconciliation outcomes are:

- zero valid matches: submit the fulfillment, then persist the returned UID;
- exactly one valid match: adopt and persist its UID;
- multiple identical valid matches: select the earliest valid attestation deterministically, log the duplicate condition loudly, and continue commercial delivery;
- conflicting matches: do not submit another fulfillment and place the escrow into operator-visible reconciliation failure/pending state.

A failed or timed-out submission returns to reconciliation before any retry. The recovery context records a bounded chain scan origin, preferably a block observed before first submission or another authoritative lower bound already available from the accepted escrow.

### Aggregate routing policy

`AggregateFulfillmentClient` retains the same broad site-fallback policy already used by `AggregateCapacityClient.commit` and `release`. Section 9 does not introduce stricter error classification for only one sibling. Typed retryability and failure classification are deferred as an aggregation-wide concern and must correct both clients together.

Aggregate capacity and fulfillment routing, including cold-cache fan-out and storefront recovery use, are documented together in the VM storefront/adapter-scoped permanent specification. A new aggregation subsystem spec is not created solely for these sibling classes.

### Permanent documentation destinations

| Accepted decision | Permanent documentation destination |
|---|---|
| Commercial delivery takes priority over storefront-local bookkeeping durability after deal acceptance | VM storefront/adapter-scoped specification, storefront fulfillment recovery requirement |
| Versioned VM fulfillment-context envelope and redaction/version rules | VM storefront/adapter-scoped specification; generic envelope principles remain in `openspec/specs/fulfillment/spec.md` |
| Dedicated storefront startup recovery worker and full settlement convergence ownership | VM storefront/adapter-scoped specification; `docs/development/ARCHITECTURE.md` only for repository-wide worker/service-flow updates |
| Shared foreground/recovery convergence implementation and explicit `escrow_uid` | VM storefront/adapter-scoped specification and current code docstrings |
| Duplicate-safe ambiguous on-chain submission handling | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-ambiguous-on-chain-submission-safety`; a supported generic bounded attestation query is deferred to `alkahest-py` or `kit/alkahest` |
| Aggregate capacity/fulfillment routing parity and cold-cache fallback | VM storefront/adapter-scoped specification |
| `vm_host` compatibility seam retained until teardown cutover | Section 10 plan and the permanent VM teardown documentation updated by that section |
| Two-phase ordinary initiate/converge redesign deferred | New future OpenSpec change; no production comment or permanent current-state claim until implemented |

The implementation planning tasks below must resolve the exact existing permanent-spec file or create the broader VM storefront/adapter specification before implementation begins. A recovery-only specification is not created.


## Section 9 final implementation and promotion record (2026-07-26)

Section 9 is complete. The implementation uses a versioned VM fulfillment context, durable escrow processing claims, a dedicated storefront startup worker, shared foreground/restart convergence operations, exact replay before fulfillment acceptance, direct resumption after a durable fulfillment ID, and replay-safe downstream convergence through credentials, lease registration, on-chain fulfillment, listing update, escrow readiness, and claim creation.

The accepted operational priority is permanently documented in `openspec/specs/vm-storefront-fulfillment/spec.md`: once a deal is accepted, commercial delivery takes priority over storefront-local bookkeeping durability. Failed checkpoint writes are retried and loudly reported but do not cause abandonment of an otherwise deliverable VM.

The Alkahest investigation established that `alkahest-py==1.1.2` contains internal log-scanning machinery but exposes neither its provider nor a bounded `refUID` attestation query. Section 9 therefore implements the strongest supported safety boundary: adopt a matching attestation when an exposed query is available; otherwise never blindly resubmit after an ambiguous transaction outcome, keep the escrow pending, and surface operator reconciliation. Raw repository-owned RPC/EAS scanning is deferred because it would depend on external ABI, address, and network assumptions that belong behind a supported Alkahest abstraction.

Validation completed through the supplied offline wheelhouse and the repository owner's root `make test`. The final local run included 627 VM storefront unit tests (1 skipped), 145 VM storefront integration tests, both Alkahest integration tests, and all other repository suites. Strict OpenSpec validation was unavailable in both environments because the CLI was not installed; this was explicitly accepted and is not an open Section 9 defect. Section 10 may begin.

| Material decision | Permanent destination |
|---|---|
| Accepted-deal commercial delivery priority | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-accepted-deal-delivery-priority` |
| Versioned fulfillment context and restart convergence | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-versioned-fulfillment-context` and `#requirement-foreground-and-restart-convergence` |
| Full storefront settlement convergence ownership | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-full-settlement-convergence-ownership` |
| Physical fulfillment replay and direct resumption | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-physical-fulfillment-resumption` |
| Aggregate routing parity during recovery | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-aggregate-site-routing` |
| Duplicate-safe ambiguous on-chain handling and upstream query deferral | `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-ambiguous-on-chain-submission-safety` |
| `vm_host` compatibility seam removal | Section 10 task 10.5 and its permanent teardown documentation |


## Section 9 post-completion correction and promotion record (2026-07-26)

The correction pass restores the generated VM target as a single caller-owned identity and proves that the exact value survives context persistence, production-model validation, physical fulfillment submission, and lease registration. The permanent contract and its scenarios are in `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-versioned-fulfillment-context`.

The VM settlement adapter no longer probes guessed Alkahest methods. Unknown-attestation discovery is unavailable in `alkahest-py==1.1.2`; ambiguous outcomes remain pending without resubmission. A supported future query capability can be injected explicitly. This limitation and its falsifiable scenarios are in `openspec/specs/vm-storefront-fulfillment/spec.md#requirement-ambiguous-on-chain-submission-safety`.

All requirements in the permanent VM storefront fulfillment specification now include repository-convention `#### Scenario:` blocks. Focused correction tests passed against installed review artifacts. Strict OpenSpec CLI validation remains waived because the executable is unavailable.

## Section 10 design review (2026-07-27)

### Current-state findings

Repository inspection (not assumption) establishes the actual starting point for teardown cutover:

- `FulfillmentProvider.prepare_teardown`/`dispatch_teardown` already exist on the provider interface and are implemented by `AnsibleFulfillmentProvider`.
- The full durable teardown state machine already exists and already runs every cycle: `transitions.py` defines `teardown_dispatch_pending → tearing_down → torn_down/teardown_failed`, and `FulfillmentConvergenceWatchdog` (`provisioning/compute/service`) already implements `dispatch_pending_teardowns`, `converge_teardowns`, and `requeue_teardown_failures`, domain-neutral, alongside its create-side passes.
- Nothing calls any of it. No `begin_fulfillment_teardown` (or equivalent) exists anywhere in the repository. This is the actual gap task 10.1 closes, not a formality.
- Section 7's backfill compiler (`legacy_backfill.py`) already produces backfilled rows in these same teardown states with `prepared_teardown_operation`/`teardown_provider_metadata` pre-populated where a live target exists, so backfilled and native rows are already uniform once a native-row preparation path exists (10.2 is materially smaller than the proposal implied).
- VM release today is driven entirely by `LeaseLifecycleService`/`LeaseWatchdog` (`provisioning/compute/src/compute_provisioning`), a generic, domain-neutral component shared with bare-metal through `ExecutorReleaseDispatcher`, keyed by `executor_kind`. It performs expiry detection (`list_time_bounded_reservations_due` against the site reservation ledger's `lease_end_utc`), submits one job through `ExecutorReleasePort.submit_release` (VM's implementation is `VmReleaseExecutor`, submitting an Ansible `vm_remove` job directly), polls that job through a single shared `ReleaseJobPort` (`job_service`/`AsyncJobQueue`, also genuinely exercised by bare-metal's `reclaim_access_for_reservation`, not just a `"direct-release"` sentinel), and on confirmed completion calls `_finish_release` → `record_release_success` (→ `CapacityLedgerService.release`, which is itself the authoritative capacity-table update — releasing a reservation from `HELD_RESERVATION_STATES` is what excludes it from committed pool capacity going forward) plus a best-effort, non-durable push (`StorefrontLifecycleEventSink.notify_capacity_released`) that cannot currently authenticate to the storefront.
- `POST /api/v1/contract/leases/{capacity_reservation_id}/terminate` already exists on `ComputeContractController` and is already client-wrapped on `ComputeProvisioningClient.terminate_lease` — the exact client `_register_vm_lease_with_settings` already uses for `register_lease` today. (A second, VM-domain-branded surface, `POST /leases/{lease_id}/terminate` on `LeasesController`, also exists and calls the identical `LeaseLifecycleService.terminate_lease`; the storefront is not currently wired to that client, so the generic contract surface is the one this section uses.) Both already validate the reservation is `leased`, already call the same `submit_release` seam as the expiry sweep, and already document "capacity is released only after the delegated release job succeeds." Nothing in the VM storefront calls either yet.

### Accepted decision: keep `LeaseLifecycleService` as the sole trigger and capacity-release owner

An earlier draft of this design considered moving VM off `LeaseLifecycleService` entirely (a new fulfillment-aggregate-native expiry sweep, and/or moving capacity release into `kit/fulfillment` or the convergence watchdog). This is rejected. `LeaseLifecycleService` is already generic across the compute domain family (VM and bare-metal share one instance), already owns expiry detection, admin recovery endpoints (`retry_release`, `force_release`, `release_oversight`), and the only call site that performs the authoritative capacity-table release. There is no reason to duplicate any of that for VM specifically.

What changes is narrow, confined to the release-submission/completion seam:

1. **Submission.** `VmReleaseExecutor.submit_release` stops submitting an Ansible `vm_remove` job directly. It resolves the durable `fulfillment_id` for the reservation's `capacity_reservation_id` and calls the new `begin_fulfillment_teardown(fulfillment_id)`, which durably prepares the teardown envelope and transitions `active → teardown_dispatch_pending` — no provider I/O inline, mirroring how `begin_fulfillment` separates durable acceptance from dispatch. It returns `fulfillment_id` as the tracked "job id." `FulfillmentConvergenceWatchdog` — already implemented, already running — owns dispatch, retry, and status convergence through to `torn_down`/`teardown_failed`, entirely independently of `LeaseLifecycleService`'s own polling cadence. This is what "entirely from provisioning-owned watchdog handlers" (task 10.3, as originally drafted) actually refers to: the convergence watchdog already is that owner; it needed a caller, not new mechanics.
2. **Completion.** `LeaseLifecycleService`'s `_process_releasing_reservation` calls one shared `ReleaseJobPort.get_job(job_id)`. Bare-metal genuinely needs this to keep resolving real, polled Ansible job status (confirmed: `reclaim_access_for_reservation` submits a real job, not only a `"direct-release"` sentinel), so the shared port cannot simply be repointed at fulfillment state. Instead, `release_jobs` becomes a small kind-routed dispatcher — the same shape as the existing `ExecutorReleaseDispatcher` for submission — routing `get_job` by the reservation's `executor_kind`: bare-metal's route is byte-for-byte unchanged (`job_service`/`AsyncJobQueue`); VM's route answers by reading the `SettlementRecord`'s teardown state for the given `fulfillment_id` (`torn_down` → `succeeded`, `teardown_failed` → `failed`, anything else → `pending`), via a thin adapter over `FulfillmentOrchestrator.get_fulfillment_status` or the settlement repository directly.
3. **Capacity release.** `_finish_release` is unchanged. It already performs the authoritative capacity-table update (`record_release_success` → `CapacityLedgerService.release`). The only actual gap it had was a trustworthy completion signal for the VM case, which (2) now supplies. The non-durable `notify_storefront_capacity_released` push stays as a best-effort nicety, unchanged — it already fails safe (logs and returns `False`) when it cannot reach or authenticate to the storefront, which is the expected outcome until `provisioning-result-push-delivery` lands. The storefront's authoritative view of freed capacity remains its own projection poll (POOLS-8), not this push.

### Accepted decision: no new API for early termination

Storefront-initiated early lease termination reuses the existing `POST /api/v1/contract/leases/{capacity_reservation_id}/terminate` endpoint (`ComputeProvisioningClient.terminate_lease`) — the same client the storefront already uses for `register_lease`. No new provisioning-service surface is added. Two alternatives were considered and rejected:

- Setting `lease_end_utc` to now/past and waiting for the next `LeaseLifecycleService` sweep — adds up to a full poll-interval of latency for what should be an immediate operator/buyer action, and repurposes a field whose meaning is "when this naturally expires" rather than "end this now." Reconstructing immediacy would mean also forcing a `check_leases` cycle, which only rebuilds what `terminate_lease` already does atomically.
- The VM storefront calling `begin_fulfillment_teardown` directly — wrong layer. It would bypass the reservation ledger's `releasing` state entirely, which is what `_finish_release`, capacity release, and the admin recovery endpoints are keyed off; the storefront would end up duplicating `terminate_lease`'s bookkeeping to stay consistent.

The only new work is VM-domain storefront-side: call `terminate_lease` from whatever business logic decides a lease should end before its natural expiry. The provisioning-service endpoint, its state validation, and its client wrapper are unchanged by this section.

### `register_lease` field scope (resolves task 9.2's/10.5's deferred note)

Fully traced, not assumed. `_register_vm_lease_with_settings` keeps writing `executor_kind` and `lease_end_utc` — both remain load-bearing: `LeaseLifecycleService` needs `executor_kind` to route submission/completion through the correct dispatcher entry, and `lease_end_utc` to find reservations due for release (`CapacityLedgerService.list_lease_due` filters on `state == leased` and `lease_end_utc IS NOT NULL`). Calling `register_lease`/`attach_lease` at all also remains mandatory regardless of which fields it carries, since `attach_lease` is what transitions the reservation into `leased` state in the first place — the state `list_lease_due` filters on.

`executor_target` and `executor_ref` do not behave the same way and were investigated separately:

- **`executor_target` (backs `CapacityReservation.vm_target`) is retained.** `vm_target` has exactly one write path in `kit/site/src/market_site/ledger.py`: `attach_lease`/`update_lease_fields`, both only from an explicitly supplied `vm_target`/`executor_target` argument. Nothing else ever populates it — unlike `vm_host`, there is no independent commit-time write. `LeasesController._lease_view` (the VM-domain lease API's list/get/terminate response shape) reads `reservation.get("vm_target")` directly with no fallback; dropping the write would silently empty that field for every future VM lease. The generic, bare-metal-shared `compute_contract_controller._lease_view` also depends on it indirectly: its `executor_target` resolution checks `vm_target` before falling back to `vm_host`, and since `vm_host` identifies the physical KVM host (which can run multiple VMs) rather than the specific VM, an empty `vm_target` would make that view silently report the wrong, host-level identity rather than merely a less specific one.
- **`executor_ref` (backs `CapacityReservation.executor_ref`, `{"vm_host": ...}`) is dropped.** `reservation.vm_host` is already written independently of `register_lease`, at capacity-commit/rebind time, from the scheduled resource's own attributes (`ledger.py`'s `commit`/`rebind_capacity`: `reservation.vm_host = (resource.attributes or {}).get("vm_host")`) — this happens at `schedule_resource` time, before `register_lease` is ever called. `_sync_executor_fields`, already invoked by both `attach_lease` and `update_lease_fields`, already self-heals `executor_ref` from that independently-set `vm_host` whenever the explicit argument is omitted (`elif reservation.vm_host and not reservation.executor_ref: reservation.executor_ref = {"vm_host": reservation.vm_host}`). No reader observes any difference between an explicitly-passed and a self-healed `executor_ref`.

Task 10.7 is therefore not a "confirm before dropping" placeholder: `_register_vm_lease_with_settings` stops passing `executor_ref` to `register_lease`, and continues passing `executor_target=vm_target`, `executor_kind`, and `lease_end_utc` exactly as today.

### Permanent documentation destinations

| Accepted decision | Permanent documentation destination |
|---|---|
| `begin_fulfillment_teardown` as the whole-fulfillment teardown entrypoint, and its idempotent treatment of already-prepared (backfilled) rows | `openspec/specs/fulfillment/spec.md` |
| `LeaseLifecycleService` retained as sole VM/bare-metal release trigger and capacity-release owner; `ExecutorReleasePort`/`ReleaseJobPort` become the seam fulfillment-backed teardown crosses, not a replaced mechanism | `openspec/specs/physical-provisioning/spec.md`; `docs/development/ARCHITECTURE.md` only if the repository-wide service/worker map changes |
| Kind-routed `ReleaseJobPort` dispatch (bare-metal via job queue, VM via fulfillment aggregate state) | `openspec/specs/physical-provisioning/spec.md` |
| `POST /api/v1/contract/leases/{capacity_reservation_id}/terminate` (`ComputeProvisioningClient.terminate_lease`) as the storefront-facing early-termination call; no new endpoint | `openspec/specs/physical-provisioning/spec.md`; `openspec/specs/vm-storefront-fulfillment/spec.md` for the storefront-side call site |
| Authoritative capacity release remains `CapacityLedgerService.release`, gated on confirmed fulfillment teardown for VM; storefront-facing notification remains poll-based (POOLS-8) until `provisioning-result-push-delivery` | `openspec/specs/physical-provisioning/spec.md`; `openspec/specs/site-capacity/spec.md` if reservation-ledger release semantics need a stated precondition update |
| `register_lease` field scope: `executor_kind`/`executor_target`/`lease_end_utc` retained (no independent write path exists for `vm_target`); `executor_ref` dropped (self-heals from the independently-written `vm_host`) | `openspec/specs/physical-provisioning/spec.md` |

Implementation must confirm or correct each destination above against the actual accepted code shape before promotion; this table records intent, not a substitute for the design-promotion record task 12 requires at closure.

### Addendum: pre-existing `LeaseState` serialization bug found and fixed during 10.7

Not a design decision from this review — a defect in already-existing code, found incidentally while adding 10.7's regression test and fixed in the same pass (by agreement, rather than filed as a separate change) because it sat directly on the call path this section's design depends on. `compute_contract_controller._lease_view` passed the raw `market_site.ReservationState` value straight into `LeaseView.status: LeaseState` with no translation. `LeaseState` never had a `"leased"` member, and `attach_lease` always sets that literal raw state, so `ComputeProvisioningClient.register_lease` — the client `_register_vm_lease_with_settings` actually uses — failed its own response validation on every real call. No prior integration test caught it: existing lease-registration coverage used either the other client (`vm_provisioning_operator.ProvisioningClient`, whose controller already translates correctly) or mocked the client entirely.

Fixed by giving `_lease_view` the same `reserved→pending, provisioning→pending, leased→active, ...` translation `leases_controller._LEASE_STATUS` already used, and adding `LeaseState.PROVISIONING_FAILED`/`LeaseState.FORCE_RELEASED` so the full nine-member `ReservationState` vocabulary is representable. `openspec/specs/compute-provisioning-contract/spec.md` should be checked for whether it documents `LeaseView`/`LeaseState`'s member set, and updated to describe the corrected (complete) vocabulary if so — this is a correctness fix to already-promoted behavior, not new design, so it belongs in that spec's existing description rather than a new requirement.

## Section 10 completed design-promotion record

| Decision | Destination |
| --- | --- |
| `begin_fulfillment_teardown` as the whole-fulfillment teardown entrypoint: valid only from `active`, idempotent across every already-tearing-down state including terminal `torn_down` and retryable `teardown_failed`, no inline dispatch, reuses an already-prepared operation (backfilled or retried) rather than re-preparing | `openspec/specs/fulfillment/spec.md` — new paragraph and two scenarios in "Durable settlement persistence", plus its `POST /fulfillment/{fulfillment_id}/begin-teardown` HTTP exposure |
| `LeaseLifecycleService` retained, unchanged, as the sole release trigger and capacity-release owner for both VM and bare-metal; only the submission leaf (`VmReleaseExecutor`) and a new kind-routed completion-read seam (`ReleaseJobDispatcher`) cross into the fulfillment aggregate | `openspec/specs/physical-provisioning/spec.md` — new paragraph and three scenarios after "Site-backed release lifecycle" |
| Explicit early lease termination reuses the existing `terminate_lease` release mechanism rather than adding a second termination code path; no lease-management migration to the storefront | `openspec/specs/physical-provisioning/spec.md` — new "Explicit early lease termination" requirement; `openspec/specs/vm-storefront-fulfillment/spec.md` — plumbing note on "Full settlement convergence ownership", explicit that no caller exists yet |
| `register_lease` field scope: `executor_ref` was never sent on the storefront's actual call path in the first place (traced, not assumed); `executor_target`/`vm_target` has no independent write path and is retained; `executor_kind`/`lease_end_utc` remain load-bearing | `openspec/specs/physical-provisioning/spec.md` — new "Lease registration tolerates omitted identity hints" requirement, stated generically (not VM/`executor_ref`-specific) since the property — registration need not resupply what committed resource attributes already carry — is domain-neutral |
| Kind-routed `ReleaseJobPort`/`ReleaseJobDispatcher`, mirroring the existing submission-side `ExecutorReleaseDispatcher` pattern; the `"direct-release"` sentinel is a per-executor "nothing to poll" signal, not a global on/off switch | `openspec/specs/physical-provisioning/spec.md` — same new paragraph/scenarios as the `LeaseLifecycleService` row above |
| Circular-dependency break for `VmReleaseExecutor`/`VmFulfillmentReleaseJobPort` (`FulfillmentOrchestrator` needs `provider_registry` → `composed_adapters` → the VM adapter bundle these two classes live inside): a lazy module-level accessor (`_resolved_fulfillment_service()`) mirroring the container's existing `_resolved_job_queue()` pattern, passed via `providers.Object` rather than a DI dependency | `compute_provisioning_service/container.py` docstring on `_resolved_fulfillment_service`; not promoted to a subsystem spec — this is a composition-root wiring technique already established by precedent in the same file, not new cross-cutting design |
| Pre-existing `LeaseState` serialization bug (missing `"leased"`, `"provisioning_failed"`, `"force_released"` members) found and fixed in the same pass, by agreement, rather than filed separately | `compute_provisioning/contracts.py` (`LeaseState` enum, now complete); `compute_contract_controller.py` (`_lease_view`'s translation table) — checked `openspec/specs/compute-provisioning-contract/spec.md` for existing `LeaseState` documentation to correct; found none, so no spec text needed updating |

### Section 10 implementation confirmation (2026-07-27)

Every decision above was implemented as recorded. Full test suite green throughout, run together at the end rather than only per-package: kit/fulfillment 148/148 (16 new), `compute_provisioning` kit 32/32 (7 new `ReleaseJobDispatcher` tests, 2 new teardown-path restart/worker-death tests), compute-provisioning-service unit+integration 515/515 (12 new/rewritten across `test_ledger_lease_lifecycle.py`, `test_compute_contract_api.py`, `test_provisioning_client_endpoint_coverage.py`, `test_leases_api.py`), VM storefront unit 629/629 (1 new). Two corrections found during implementation, not design changes: (1) the `"direct-release"` sentinel bug described in task 10.3's entry — a real production regression the new kind-routed dispatcher would have introduced, caught by an integration test rather than assumed safe; (2) the `LeaseState` bug described above — a genuine pre-existing defect on the call path this section's design depends on, found incidentally while adding 10.7's regression test, fixed with explicit sign-off rather than either silently patched or silently left. Neither changes what was decided in the design review; both are places implementation would otherwise have diverged from, or exposed a latent defect in, already-correct or already-existing behavior.

Two design-review citations were themselves corrected during implementation and are recorded on their own task entries rather than repeated here: task 10.6's early-termination endpoint (the design review cited `vm_provisioning_operator.ProvisioningClient`'s `/leases/...` surface; the storefront actually uses `compute_provisioning.ComputeProvisioningClient`'s `/api/v1/contract/leases/...` surface — both call the identical underlying service, so no behavioral correction, only a citation correction), and task 10.7 (the design review assumed `executor_ref` needed to be dropped from an existing write; tracing found it was never written on this path at all, so 10.7 required no code change, only confirmation and a regression test).

## Section 10 post-implementation review corrections (2026-07-27)

This section supersedes the earlier statement that Section 10 was complete and
ready for Section 11. The implemented direction remains accepted, but review
found architectural, client-contract, end-to-end validation, and documentation
promotion work that must be completed before the Section 10 gate can close.

### Accepted correction: replace the module-global fulfillment-service bridge

The lazy `resolved_fulfillment_service` bridge is not retained as an accepted
composition technique. The import cycle is architectural evidence that the VM
release adapter depends on a service that itself depends on the composed VM
adapter registry. A module-global initialized later by the application container
hides that dependency behind process initialization order and makes the adapter
harder to compose or test independently.

Planning will introduce a narrow fulfillment-teardown port owned by the shared
compute-provisioning boundary. The VM release adapter depends only on operations
needed at the release seam, such as beginning teardown and reading teardown
status. The application composition root supplies an implementation after the
fulfillment orchestrator and provider registry have been constructed, without a
module-global service locator or lazy import. The exact carrier may be one port
or two focused ports, but it must not expose the whole orchestrator merely to
avoid naming the dependency.

This correction invalidates the earlier Section 10 promotion-record row that
classified `_resolved_fulfillment_service()` as an accepted implementation
technique. That row remains historical evidence of what was implemented, but it
is superseded by this decision and must not survive in the final promotion
record.

### Accepted correction: preserve teardown-submission failure taxonomy

`VmReleaseExecutor.submit_release` must not collapse every exception into a
`None` return. `LeaseLifecycleService` already distinguishes a delegate that
intentionally reports no pollable job from a delegate that raises while trying
to submit release. Unexpected persistence, composition, or programming failures
must propagate to that existing `release_submit_error` path so the reservation
records a useful failure reason and logs retain the originating traceback.

Known domain outcomes may be translated deliberately. For example, a missing
fulfillment aggregate may become a specific release-submission failure with a
stable message, while an already-started teardown should return the existing
`fulfillment_id` idempotently. The implementation plan must enumerate the known
exceptions it translates and leave unexpected exceptions visible.

### Accepted correction: complete the HTTP client contract

`ComputeProvisioningClient` and `ComputeProvisioningClientProtocol` will expose
`begin_fulfillment_teardown(fulfillment_id)`. An integration test must invoke
`POST /fulfillment/{fulfillment_id}/begin-teardown` through that client rather
than calling the controller or ASGI transport directly. The earlier task 10.2
completion note, which deferred the client wrapper despite naming it in the
accepted task, is inaccurate and is superseded.

### Lease-state projection duplication: current finding and alternatives

The implementation did not introduce a duplicate *diff*. It introduced a second
copy of the same reservation-state-to-lease-state translation table:

- `compute_provisioning_service.controllers.compute_contract_controller._LEASE_STATUS`
- `vm_provisioning_adapter.controllers.leases_controller._LEASE_STATUS`

The e2e `DealLease` helper also contains a third, partial projection
(`{"leased": "active"}`) while reading raw capacity-reservation rows. The first
two copies are currently identical; the problem is future drift, not an existing
behavioral difference. The added regression test proves one copy accepts every
reachable state but does not make the other copy authoritative.

Two alternatives remain open for planning:

1. Move the translation into the shared `compute_provisioning` contract package
   as a pure projection helper consumed by both controllers. This removes the
   duplicate and makes `LeaseState` translation part of the shared HTTP contract.
2. Keep controller-owned projections separate because the response models differ,
   but add one shared mapping constant or contract test that both controllers
   consume. This preserves controller-local construction while eliminating
   duplicated vocabulary.

The first alternative is preferred unless package-boundary inspection reveals a
real dependency violation. The VM adapter already depends on
`compute_provisioning`, so current evidence does not show such a violation.
Planning must decide the exact owner and update the e2e helper to consume a
contract endpoint or the shared projection rather than maintaining a partial
third mapping.

### Accepted documentation invariant: retry ownership across two state machines

The permanent physical-provisioning documentation must state this invariant:

> Lease release and fulfillment teardown are separate durable state machines.
> `LeaseLifecycleService` owns the reservation's `releasing`/`released` decision
> and final capacity return. Fulfillment convergence owns dispatch, retry, and
> recovery of `teardown_dispatch_pending`, `tearing_down`, and
> `teardown_failed`. Retrying a lease release resumes or re-observes the same
> fulfillment aggregate; it does not create a second teardown operation or make
> the lease lifecycle responsible for resetting fulfillment teardown state.

Capacity remains held while either state machine lacks confirmed teardown
success, including while fulfillment is retryable after `teardown_failed`.

### Static analysis of `e2e-tests/.../vms/test_full_deal.py`

The current phases 10 and 11 are not compatible with the Section 10 cutover.
They were written for the old direct-Ansible release path and still encode that
path in names, control flow, and assertions.

The important mismatches are:

1. `DealLease.refresh()` reads `vm_remove_job_id` from the raw reservation. After
   Section 10 this field aliases the generic release tracking identifier and, for
   VM release, contains a `fulfillment_id`, not an Ansible queue job id.
2. Stage 11a calls `SyncProvisioningClient.get_job(remove_job_id)`. That client
   calls the VM job endpoint backed by `JobService`/`AsyncJobQueue`; a
   `fulfillment_id` is not present there, so the assertion will fail with a
   not-found response rather than report teardown progress.
3. Stages 10a and 11b arm and resume a programmable mock rule for
   `vm_action=vm_remove`, then call `wait_for_job(remove_job_id)`. The actual
   Ansible teardown job is now created later by `FulfillmentConvergenceWatchdog`,
   and its queue job id is provider metadata internal to the fulfillment
   aggregate. The lease-facing identifier no longer gives the test direct access
   to that job.
4. `check_leases()` advances only `LeaseLifecycleService`. It initiates teardown
   and later polls aggregate status, but it does not synchronously run the
   fulfillment convergence watchdog. Pausing only the lease watchdog therefore
   does not provide deterministic control over dispatch/convergence; the
   independent fulfillment watchdog may advance between assertions.
5. Stage comments still describe the new design as a future `vm_destroy` rework
   and assert structural identity with the old direct job path. That statement is
   now false: the observable lease invariant remains, but the execution and
   status APIs are intentionally different.
6. The scenario uses the legacy VM-branded `SyncProvisioningClient`, while the
   new teardown endpoint is added to the shared `compute_provisioning` client.
   This is not necessarily wrong for host/test controls, but teardown assertions
   must use the client that owns the fulfillment contract or an explicit e2e
   wrapper over it.

The e2e scenario should be rewritten around public durable states rather than an
internal Ansible job identifier. A deterministic composed path needs controls to
pause or manually cycle fulfillment convergence independently of the lease
watchdog. The preferred observable sequence is:

1. expire or explicitly terminate the lease;
2. run one lease lifecycle cycle and assert reservation `releasing`, fulfillment
   `teardown_dispatch_pending`, and capacity held;
3. run or release one fulfillment-convergence dispatch step and assert
   `tearing_down`, with capacity still held;
4. complete the provider mock operation and run convergence to `torn_down`;
5. run one lease lifecycle cycle and assert reservation `released`, capacity
   available, and the storefront release observation eventually converges.

Planning must inventory the existing e2e test-control endpoints before adding a
new one. If no deterministic fulfillment-convergence control exists, add a
mock-profile/admin test control rather than sleeping against the 30-second
background interval.

### Teardown-submission error taxonomy example

The desired distinction is illustrated by the following behavior, not a required
exact API shape:

```python
async def submit_release(self, reservation: dict[str, Any]) -> str:
    try:
        fulfillment_id = self._settlements.require_fulfillment_id(
            reservation["capacity_reservation_id"]
        )
        await self._teardown.begin_teardown(fulfillment_id)
        return fulfillment_id
    except SettlementEntityNotFoundError as exc:
        raise ReleaseSubmissionError(
            "no fulfillment aggregate exists for the reservation"
        ) from exc
    except FulfillmentStateConflictError:
        # Preserve a deliberate domain conflict for LeaseLifecycleService's
        # release_submit_error handling and operator diagnosis.
        raise
```

An unavailable port, database exception, or programming error is not converted
into `None`; it propagates and is recorded by `LeaseLifecycleService` as
`release_submit_error`. `None` remains reserved for an executor contract that
intentionally has no pollable release operation, if that behavior is still
needed at all.

### Documentation discrepancies found in review

- Task 10.2 marks controller/client exposure complete while its own note says the
  client is absent. The task must be reopened until the wrapper and client-based
  integration test exist.
- Task 10.4 and the completed promotion record present the module-global lazy
  accessor as an accepted design. This is superseded by the narrow-port decision.
- The completed promotion record is not final because retry ownership and the
  fulfillment-id-as-release-tracking-id invariant are not yet mapped precisely
  into permanent documentation.
- The implementation confirmation says every decision was implemented and
  Section 10 is complete. This review supersedes that conclusion.
- Production comments and e2e stage documentation still use historical
  direct-`vm_remove` wording and must be rewritten to describe current intent.

Section 11 must not begin until the correction tasks appended to `tasks.md` are
implemented, validated, and promoted into permanent documentation.

## Section 10 rebuilt design-promotion record (2026-07-27)

Supersedes the "Section 10 completed design-promotion record" above and the
review findings immediately preceding this entry. Written after tasks
10.9–10.13 and 10.15 were independently verified against the actual code and
test suite (the prior "implemented" note for 10.9–10.13 was written without
running tests at all, blocked by an unavailable dependency in that review
environment) — three of the five were found not to meet their own stated
acceptance criteria and were completed properly rather than left as
inaccurate `[x]` marks. See `tasks.md`'s "Section 10 correction
implementation, verified and completed" entry for what was found wrong and
fixed in each case.

| Decision | Destination | Status |
| --- | --- | --- |
| `begin_fulfillment_teardown` whole-fulfillment entrypoint, idempotent across already-tearing-down states, HTTP exposure | `openspec/specs/fulfillment/spec.md` | Unchanged from the original promotion; verified still accurate |
| Narrow `FulfillmentTeardownPort`/`DeferredFulfillmentTeardownPort` composition-root-bound port replacing the module-global lazy accessor | `openspec/specs/physical-provisioning/spec.md`, "VM release delegates to durable fulfillment teardown" | Supersedes the original promotion's row calling the module-global lazy accessor an accepted technique — that row is retracted, not merely amended |
| Kind-routed `ReleaseJobPort`/`ReleaseJobDispatcher`; `"direct-release"` sentinel is per-executor, not global | `openspec/specs/physical-provisioning/spec.md`, "Site-backed release lifecycle" | Unchanged from the original promotion; verified still accurate |
| Unexpected teardown-submission failures propagate to `release_submit_error` undiminished; known idempotent outcomes (already-tearing-down) never reach an exception at all | `openspec/specs/physical-provisioning/spec.md`, "VM release delegates to durable fulfillment teardown" scenario | Verified with the four tests task 10.10 required (missing aggregate, invalid aggregate state, unavailable teardown port, unexpected repository failure); the existing bare-propagation code needed no change, only the tests proving it |
| `begin_fulfillment_teardown` client method on `ComputeProvisioningClient`/`ComputeProvisioningClientProtocol` | `openspec/specs/fulfillment/spec.md` | The client method itself was already correct; its test rebuilt (task 10.11) to exercise the real endpoint and real aggregate rather than a monkeypatched orchestrator, plus 404/409 error-mapping coverage that hadn't existed |
| One authoritative `lease_state_for_reservation_state` projection, consumed by both lease-facing controllers | Code contract (`compute_provisioning.contracts`); no `compute-provisioning-contract/spec.md` prose needed — confirmed that spec doesn't document `LeaseState`'s member set | Actually completed (task 10.12) — `compute_contract_controller.py` had imported the shared function but kept its own separate, un-migrated dict; removed. The e2e `DealLease` helper's own partial mapping is explicitly deferred with task 10.14, not folded into this row |
| Lease release and fulfillment teardown as separate retry-owning state machines; operator lease retry re-observes rather than duplicates teardown | `openspec/specs/physical-provisioning/spec.md`, "Lease release and fulfillment teardown have separate retry ownership" | Verified accurate as written (task 10.13) |
| Migration-produced backfill reaches the current teardown path through the real entrypoint, not a substituted row | `openspec/specs/fulfillment/spec.md`'s existing backfilled/native equivalence language ("VM lease migration uses current provider contracts") | New (task 10.15); no additional spec prose needed — the existing requirement already describes the invariant the new test proves |
| `LeaseState` enum completeness (`"leased"`, `"provisioning_failed"`, `"force_released"`) and the URL-prefix fix on `ComputeProvisioningClient`'s pre-existing fulfillment methods | Code-level fixes from the original Section 10 pass, confirmed still correct on re-verification | Unchanged from the original promotion |
| VM full-deal e2e teardown phases (stale Ansible-job/`vm_remove` assumptions, no deterministic convergence control) | No permanent-spec impact — e2e implementation detail | Explicitly deferred (task 10.14, repository-owner direction, 2026-07-27): Section 10 completes without executing the full e2e suite; this work, and the `DealLease` helper cleanup that rides with it, resume in the final POOLS-7 review loop after Section 11 |

Two lightweight consolidations made while rebuilding this record, neither a
design change: (1) the "Site-backed release lifecycle" paragraph added in the
original Section 10 promotion overlapped with task 10.13's newer, more
formal "VM release delegates to durable fulfillment teardown" requirement —
trimmed the one duplicated sentence and cross-referenced rather than
restructuring either; (2) confirmed no other permanent-documentation
destination in this table needs a corresponding correction beyond what's
listed — the discrepancies the review found were implementation/test gaps,
not documentation-vs-code mismatches, except where noted above.

**Section 10 is complete under this record.** Section 11 may begin. The one
carried-forward obligation is task 10.14, tracked explicitly rather than
folded into "done" — deferred by direction, not discovered to be
unnecessary. (Task 10.14 was subsequently completed by
`refactor-e2e-fulfillment-lifecycle`, a separate change — see that change's
`proposal.md`/`design.md`. Not Section 11 scope; noted here only so the
"carried-forward obligation" language above isn't read as still open.)

## Section 11 design review (discuss phase, opened 2026-07-28, continued 2026-07-30)

Read against current code, not assumed from `tasks.md`'s 11.1–11.6 text or
earlier sections' forward-looking notes about what Section 11 would need to
do — several of those notes turn out to be stale once checked against what
Sections 5–10, and adjacent concurrent changes, actually shipped. Nothing in
this entry is an implementation task list; it exists to settle scope before
11.1–11.6 are planned in detail.

### 1. `allocation_id`/`SiteAllocation`: already fully retired, nothing to remove

Repository-wide search finds zero production references to `SiteAllocation`
and zero non-migration references to `allocation_id` outside two narrow,
unrelated cases:

- The historical rename migrations themselves (`core_storefront/sqlite_migrations.py`,
  `compute_provisioning_service/db/migrations.py`) — these *are* the record
  of the `allocation_id` → `capacity_reservation_id` cutover (`RENAME COLUMN
  allocation_id TO capacity_reservation_id`, plus the `vm_leases`/`ansible_jobs`
  backfill migrations that read the old column to populate the new one).
  These must stay exactly as they are: they run against real pre-cutover
  databases and are the mechanism by which the rename actually took effect,
  not leftover naming to clean up.
- `market_storefront/utils/sqlite_client.py`'s `compute_allocations` table
  and its own `allocation_id` primary key. Traced and confirmed this is an
  unrelated, pre-existing storefront concept — a local execution-hold ledger
  against advertised listing capacity — not the POOLS `SiteAllocation`
  entity this task's wording refers to. Same name, different schema, no
  connection to this change's rename.

**Finding: task 11.1's `allocation_id`/`SiteAllocation` clause is already
satisfied by Sections 2–9's work. There is nothing to do here**, beyond not
mistakenly touching the two cases above when 11.1 is executed.

### 2. "Direct-host storefront placement" and "process-local settlement maps/locks": already retired

- The pre-cutover in-memory `FulfillmentService`/`FulfillmentEntry` dict
  (`compute_provisioning_service/services/fulfillment_service.py`) no longer
  exists as a file — confirmed retired in Section 5 ("Orchestrator placement:
  moves into `kit/fulfillment`"). Section 5's durable `kit/fulfillment`
  orchestrator plus Section 6's durable claim/lease fields on the aggregate
  row are what deal with the state a process-local map/lock used to hold.
  Nothing remaining under `market_fulfillment`/`compute_provisioning_service`
  uses a bare in-process dict or lock keyed by settlement identity.
- The VM storefront's own direct executor dispatch (`create_vm_and_wait_with_credentials`,
  raw `ExecutorActionEnvelope` submission from `domains/vms/storefront`) has
  no remaining call sites — confirmed by search; `_do_provision` (Section 9)
  is the only fulfillment entry point now, and it calls
  `schedule_resource`/`begin_fulfillment` exclusively.

**Finding: also already satisfied.** The one adjacent surface that might be
mistaken for "direct-host storefront placement" and must explicitly **not**
be touched is `vm_provisioning_adapter/controllers/vms_controller.py`
(`/api/v1/hosts/{host}/vms/...`). Its own module docstring already scopes it
as a permanent admin/operator API ("Direct VM operations are admin/operator
APIs"), it has no storefront caller (`domains/vms/storefront` imports
neither this router nor the `vm_provisioning_operator` client that would
reach it), and it was never part of the storefront fulfillment path this
change cuts over. It predates POOLS-7 and is out of this change's scope
entirely, not a leftover of it.

### 3. `most_available`'s claim-blindness bug — design reviewed again; the 2026-07-17 sketch is stale and must not be implemented as written

`core_storefront/aggregation.py`'s `_site_available_units` still takes only
`snapshot` and ignores `claim` today — the underlying bug this file's
2026-07-17 "`fill_first`/`most_available`: resolved" section diagnosed is
still present and task 11.2 is still real. But the fix sketched there
(`_resource_matches_claim` matching arbitrary flat `claim` keys against
`row.get(key)`/`attrs.get(key, row.get(key))`, skipping only
`"units"`/`"gpu_count"`) predates two things that later actually shipped and
changed both sides of the comparison it performs:

- **The claim shape.** `reserve()`/`probe()` claims are no longer an
  arbitrary flat attribute bag. Per the "Final planning decisions"/`pools-4`
  claim shape actually in use today (`vm_job_spec_service.compute_capacity_claim_from_order`,
  `kit/site/ledger._requested_dimensions`), a claim is `{"pool_id": ...,
  "resource_id": ...}` (either or both, optional pinning) plus, when a
  buyer's shape has more than one governed dimension, a nested
  `{"dimensions": {<dimension>: <quantity>, ...}}` map — `dimensions` is
  authoritative *when present*, and its absence falls back to a legacy
  single-quantity claim (`units`/`gpu_count`) that apicredits still uses
  today (confirmed: apicredits never sends `dimensions`, only the legacy
  shape — it has no per-dimension governed capacity). The original sketch's
  `for key, expected in claim.items(): ... != expected` would treat
  `"dimensions"` as one opaque key to compare by equality against
  `row.get("dimensions")` — which doesn't exist on a row at all (see next
  point) — rather than checking per-dimension sufficiency the way admission
  and scheduling actually do.
- **The row shape.** A snapshot row (`kit/site/ledger.py`'s
  `_resource_payload`) carries `resource_id`, `pool_id` (a real top-level
  field, not `attributes["pool_id"]` — the attributes-JSON `pool_id`
  fallback this document's Section 4 item 5 once found load-bearing has
  since been fully removed from the codebase, confirmed by search: zero
  remaining `attributes.get("pool_id")` call sites anywhere, and
  `kit/fulfillment/tests/unit/test_scheduler.py`'s own resource-construction
  helpers now pass a real `pool_id=` argument, not `attributes={"pool_id":
  ...}` as this document previously described them), `available_units` (the
  primary/GPU-count dimension only), and, since POOLS-6, multidimensional
  `capacity`/`available` maps (`{<dimension>: <quantity>, ...}`). There is
  no `row["dimensions"]` key for the original sketch's generic `attrs.get(key,
  row.get(key))` fallback to have found even if the claim-side problem above
  were fixed.

**Corrected design**, matching today's actual claim/row vocabulary rather
than the pre-POOLS-4/6 one, while preserving every other principle the
2026-07-17 section already established (best-effort ranking hint only, not
an enforcement point; no import of `kit/site`; operates on the plain-dict
`snapshot()` payload):

```python
# core/storefront/aggregation.py

def _resource_matches_claim(
    row: Mapping[str, Any], claim: Mapping[str, Any] | None,
) -> bool:
    """Best-effort client-side ranking hint only — NOT an enforcement
    point. Deliberately does not import kit/site (the aggregator is a
    storefront-process concept and must not depend on
    provisioning-service-internal packages); operates on the plain-dict
    snapshot() payload that crosses the HTTP boundary, using the claim
    vocabulary reserve()/probe() actually accept today: an optional
    pool_id/resource_id pin, plus either a multidimensional
    ``dimensions`` map or a legacy single-quantity claim.
    """
    if not claim:
        return True
    pool_id = claim.get("pool_id")
    if pool_id is not None and row.get("pool_id") != pool_id:
        return False
    resource_id = claim.get("resource_id")
    if resource_id is not None and row.get("resource_id") != resource_id:
        return False
    requested = claim.get("dimensions")
    if isinstance(requested, Mapping) and requested:
        available = row.get("available") or {}
        for dimension, quantity in requested.items():
            try:
                if float(available.get(dimension, 0) or 0) < float(quantity):
                    return False
            except (TypeError, ValueError):
                return False
        return True
    # Legacy, non-dimensional claim (apicredits' current shape): compare
    # against the row's single reported available_units value.
    requested_units = claim.get("units", claim.get("gpu_count"))
    if requested_units is None:
        return True
    try:
        return float(row.get("available_units") or 0) >= float(requested_units)
    except (TypeError, ValueError):
        return False


def _site_available_units(
    snapshot: list[dict[str, Any]], claim: Mapping[str, Any] | None,
) -> int:
    return sum(
        max(int(row.get("available_units") or 0), 0)
        for row in snapshot
        if _resource_matches_claim(row, claim)
    )
```

`most_available` changes only to pass `claim` through to
`_site_available_units` (it already receives `claim` itself — only the
inner helper was claim-blind). The ranking signal remains coarse by
design — summing `available_units` (the primary GPU dimension) rather than
scoring a full multidimensional fit — since this is a *try-order* hint, not
an admission decision; `probe()`/`reserve()` on the chosen site remain the
real, authoritative check per the existing "layered ownership model"
section. `fill_first`/`most_available` otherwise remain pure
pre-reservation site-selection policy exactly as designed — this file's
"Site fallback after POOLS-4" open question about whether ranked fallback is
now vestigial does not need to be resolved to fix this bug; task 11.2
already scopes the work to the claim-filter fix only, not a restructuring.

### 4. `deal_ref` removal: dropped from Section 11 scope (accepted)

Section 5's design note ("`deal_ref`: excluded from the new fulfillment path
now; full removal deferred to Section 11") anticipated removing `deal_ref`
from all five contract classes (`ExecutorActionEnvelope`, `JobAccepted`,
`ProvisioningJob`, `LeaseRegistration`/`LeaseView`, `LifecycleEvent`) and
from `AnsibleJob.deal_ref` once Section 9 retired the legacy callers.
Checked against what Sections 9–10 actually settled, none of the five have
an actual removal condition this change satisfies:

- `LeaseRegistration`/`LeaseView.deal_ref` is permanent, not retired —
  Section 10 established `register_lease`/`attach_lease` as durable,
  ongoing infrastructure (it's what transitions a `CapacityReservation` into
  `leased` state), and `fulfillment_service.py`'s
  `_register_vm_lease_with_settings` still constructs
  `LeaseRegistration(deal_ref={"escrow_uid": escrow_uid}, ...)` on every VM
  lease registration today. This field was miscategorized alongside the
  other four in Section 5's note.
- `ExecutorActionEnvelope`/`JobAccepted`/`ProvisioningJob.deal_ref` are
  VM-retired but not repository-retired — `submit_action`/`ExecutorActionEnvelope`
  remains the live, generic, `executor_kind`-routed contract
  `BareMetalComputeAdapter.submit` still depends on, and bare-metal's own
  fulfillment cutover is explicit non-goal scope for this change.
- `LifecycleEvent.deal_ref` was already flagged as out of scope by Section
  5's own note (a real, independent consumer, `market_site`-owned, not a
  fulfillment concern) — it was nonetheless swept into the same note's
  five-class removal list, an internal inconsistency rather than a
  considered inclusion.
- `AnsibleJob.deal_ref` is written from `contract.deal_ref` on every
  `job_service.submit()` call and cannot be dropped while bare-metal keeps
  using the shared job-submission contract.

**Accepted (2026-07-30):** this was a design decision made after Section 11
was originally drafted, and the item is dropped from Section 11's scope
entirely — not deferred, not re-evaluated per-class, dropped. Task 11.1's
"obsolete executor/provider fields" clause should be read without a
`deal_ref` component when Section 11 is planned. Revisiting `deal_ref`
removal belongs to whichever future change performs bare-metal's own
fulfillment cutover, since that is the actual precondition none of the
three shared classes currently meet.

### 5. `register_resource` compatibility endpoint: re-investigated, found live — not safe to remove

The prior pass of this review found no `domains/vms/storefront` caller of
`kit/site`'s `PUT /capacity/resources/{resource_id}` (`register_resource`)
and proposed it as an in-scope Section 11 removal pending confirmation the
callsite is actually dead. Re-checked against the current codebase with a
repository-wide search, not scoped to the VM domain this time — the
callsite is **not** dead:

`domains/apicredits/storefront/src/apicredits_storefront/startup.py`'s
`_register_seed_quota` calls this exact endpoint (`PUT
/api/v1/capacity/resources/{resource_id}`) directly via `httpx` on every
storefront startup, to seed/re-assert the apicredits domain's quota
resource in its credits-service ledger. This is load-bearing, not
vestigial: apicredits has no host/pool inventory of its own the way the VM
domain now derives `site_resource_pools` from a provisioning service's
`hosts`/`resource_pools` tables (this file's "`SiteResource` is retired"
section already notes apicredits "calls `CapacityLedgerService` directly
with no pool concept at all" and has not yet adopted the
pooled-capacity-view shape VM has). `register_resource` is currently
apicredits' only mechanism for advertising capacity at all — removing it
would break apicredits domain startup, not clean up a retired VM-only path.

**Finding, applying the "safe to remove only if the callsite is actually
dead" standard directly: it is not safe to remove `register_resource` (the
endpoint) in Section 11.** This corrects the previous pass's proposed
default. The narrower piece that *is* independently resolved: the
`pool_id`-attributes-JSON fallback this endpoint's caller-side dead code
was originally coupled to (Section 4 item 5's "verified, proposal reversed"
finding) has since been removed from the codebase entirely on its own
merits (see item 3 above) — `test_scheduler.py`'s helpers already register
resources with a real `pool_id=` column, so that specific precondition no
longer blocks anything. But the fallback's removal and the endpoint's
removal were always two different questions, and only the first is settled.
`register_resource`/`CapacityLedgerService.register_resource` stay, and
task 11.1 should not name them as an obsolete compatibility path pending
apicredits either adopting a pooled-capacity-view shape of its own (per
this file's already-stated, unscoped intent) or gaining some other
registration mechanism — neither is this change's scope.

### 6. New: task 11.6, `CapacityReservation.vm_host` schema question

Added since this review's first pass, surfaced by `fix-vm-fulfillment-capacity-boundary`'s
audit (2026-07-29) while that change was deciding to strip `vm_host` from
the reservation HTTP response (done, in that change) — the response-level
fix doesn't address the underlying schema. Confirmed by reading that
change's `design.md` and `proposal.md`: `kit/site/src/market_site/db.py`'s
`CapacityReservation.vm_host` is a VM-domain-specific column name on the
otherwise domain-neutral reservation table, unlike bare-metal's equivalent
concept, which correctly lives in the generic `executor_ref` JSON column
rather than its own dedicated column. Task 11.6 itself states the candidate
direction (migrate `vm_host` into `executor_ref`/`attributes`, matching
bare-metal's pattern) without committing to it, and exists so Section 11
doesn't close without at least an explicit decision to do this or defer it
further. Not otherwise re-litigated here — `fix-vm-fulfillment-capacity-boundary`'s
own design.md is the fuller record of how this was found.

No second new item was found beyond 11.6 itself. Task 10.14 (VM full-deal
e2e teardown rewrite), previously carried forward alongside this review as
"not Section 11 scope," was itself completed by the separate
`refactor-e2e-fulfillment-lifecycle` change (2026-07-29) — not a Section 11
addition, but worth noting since earlier passes of this document still
described it as outstanding.

### 7. Task 11.6 resolved: migrate `vm_host` into `executor_ref`, scoped narrowly

Full call-site inventory of `CapacityReservation.vm_host`
(`kit/site/src/market_site/db.py`), traced end to end rather than assumed
from the task's own candidate sketch:

- **Write sites**, all in `ledger.py`: `reserve()` (sets `vm_host` from the
  matched resource's `attributes.get("vm_host")` at reservation time, and
  separately re-derives `executor_kind` from the same attribute lookup — two
  copies of the same check), the settlement-resource reassignment/rebind
  path (same attribute-derived write against the *new* resource), and
  `attach_lease`/`update_lease_fields` (accept an explicit `vm_host`
  parameter).
- **One real query dependency**: `find_active_lease_by_vm_target(vm_host,
  vm_target)` filters `CapacityReservation.vm_host == vm_host` directly at
  the SQL layer. It backs `POST /vms/{vm_name}/remove` (the permanent
  admin/operator endpoint from item 2 above) cancelling a watchdog-managed
  lease before submitting an explicit removal job. This is the one place
  bare-metal has no equivalent need for its own `physical_host_id` — there
  is no bare-metal analogue of this lookup anywhere in `kit/site`, which is
  presumably why `vm_host` alone grew a dedicated column while bare-metal's
  concept never did.
- **Read/output site**: `_reservation_payload` includes `"vm_host":
  reservation.vm_host` in the generic dict every reservation-returning call
  produces.
- **The self-heal direction is already backwards from what the column
  implies.** `_sync_executor_fields` treats `vm_host` as the *source* the
  generic `executor_kind`/`executor_ref` fields heal from
  (`elif reservation.vm_host and not reservation.executor_ref:
  reservation.executor_ref = {"vm_host": reservation.vm_host}`) — but
  `kit/site/authority.py`'s `SiteAuthorityAdapter` (the domain-neutral port
  `LeaseLifecycleService` actually calls) does the *opposite* one layer up:
  its `_legacy_vm_fields` static method takes an already-generic
  `executor_ref` (the real value every caller above `kit/site` already
  passes) and manufactures a `vm_host` string from
  `executor_ref.get("vm_host")` purely to satisfy `ledger.attach_lease`'s/
  `update_lease_fields`'s legacy `vm_host=` parameter — a compatibility
  shim synthesizing the deprecated shape from the generic one, immediately
  before the generic value passed in gets the deprecated shape re-derived
  from it inside `ledger.py`. `executor_ref["vm_host"]` is already the
  value in hand at every one of these call sites; the dedicated column
  never carries information the generic field doesn't already have or
  can't already receive directly.

**Decision: migrate, scoped strictly to `vm_host`.** Concretely, when
Section 11 is planned:

- `reserve()` and the reassignment/rebind path stop writing
  `reservation.vm_host`; they write `executor_ref={"vm_host": ...}`
  directly (mirroring how `executor_kind` is already derived from the same
  resource attribute at the same call sites).
- `attach_lease`/`update_lease_fields` drop their `vm_host=` parameter.
  `authority.py`'s `_legacy_vm_fields` and its two call sites
  (`attach_lease_reservation`, `update_reservation_fields`) are deleted
  outright, not adapted — they exist only to synthesize the column-shaped
  value `ledger.py` no longer needs, and every caller already has
  `executor_ref` in hand.
- `find_active_lease_by_vm_target`'s filter becomes
  `func.json_extract(CapacityReservation.executor_ref, '$.vm_host') ==
  vm_host` — an ORM-level use of SQLite's JSON1 extension with no ORM-level
  precedent yet in this codebase, but the extension itself is already
  relied on at the raw-SQL migration layer
  (`compute_provisioning_service/db/migrations.py`'s `json_extract`-based
  `pool_id` backfill), so this isn't a new dependency, just a new call
  site for an existing one.
- `_reservation_payload`'s `"vm_host"` output key stays and keeps producing
  the same value for every existing consumer — it's computed from
  `reservation.executor_ref.get("vm_host")` instead of a dedicated column.
  This is a schema-internal change; no consumer outside `kit/site` needs to
  change.
- **Migration** (`compute_provisioning_service/db/migrations.py`, which
  already owns `capacity_reservations`' concrete migrations): backfill
  `executor_ref` via `json_set`/`json_patch` (merge, not overwrite — a
  reservation may already carry other `executor_ref` keys) for every row
  where `vm_host IS NOT NULL` and `executor_ref` doesn't already carry it,
  then `ALTER TABLE capacity_reservations DROP COLUMN vm_host` — precedented
  verbatim by `core_storefront/sqlite_migrations.py`'s existing
  `DROP COLUMN` migration.
- **apicredits' own database is a secondary, lower-stakes consideration,
  not a blocker.** `domains/apicredits/service/src/db/database.py`'s
  `init_db` calls `Base.metadata.create_all()` with no migration runner at
  all — apicredits composes the same `kit/site` `CapacityLedgerService`
  (confirmed: `container.py`'s own comment says apicredits resources "carry
  no host"), so its database also has a `capacity_reservations.vm_host`
  column today, always NULL, never read or written by apicredits code.
  `create_all()` won't retroactively drop the column from an
  already-created apicredits table (SQLAlchemy's `create_all` never alters
  existing tables), so an already-deployed apicredits database keeps a
  harmless, permanently-empty leftover column after this change — noted for
  planning, not a reason to change the decision or scope.
- **Explicitly out of scope, per the task's own wording:** `vm_target`,
  `create_job_id`, and `vm_remove_job_id` remain dedicated columns.
  `vm_target` in particular was already evaluated and deliberately retained
  during Section 10's design review ("no independent write path exists...
  read directly with no fallback") — migrating it would be a strictly
  larger, riskier change than what 11.6 asks for, and the task names only
  `vm_host`.

### 8. Task 11.3 investigated: already substantially satisfied

Checked every sub-claim in 11.3's text against current composition,
build, and deployment config rather than assuming it's still a gap:

- **Wheel/dist/test chains**: `kit/Makefile` already wires
  `test-fulfillment`/`dist-fulfillment` into its aggregate `test`/`dist`
  targets, and the root `Makefile`'s `dist`/`test-kits` targets already
  delegate to `kit/Makefile` — `arkhai-kit-fulfillment` was never missing
  from the build graph.
- **Reinit targets**: both real consumers —
  `provisioning/compute/service/Makefile` and
  `domains/vms/provisioning/adapter/Makefile` — already explicitly
  `--upgrade-package`/`--reinstall-package arkhai-kit-fulfillment` in their
  `reinit` targets.
- **Docker image**: `provisioning/compute/service/Dockerfile` installs the
  extracted service package entirely from `.dist` wheels
  (`arkhai-compute-provisioning-service[adapters]`); `arkhai-kit-fulfillment`
  comes in transitively through that package's own declared dependency, so
  there's no separate image-level wiring step missing.
- **Watchdog worker composition**: `FulfillmentConvergenceWatchdog` is
  already composed and started as an in-process background task in
  `app_runtime.py`, config-gated
  (`fulfillment_convergence_watchdog_enabled`, default `true`) exactly like
  `LeaseWatchdog`/`CapacityReservationWatchdog` — it is not a separate
  deployable process, so there is no additional Kubernetes/Helm resource
  (Deployment, CronJob) to add for it.
- **Deployment configuration**: `helm/charts/provisioning/templates/deployment.yaml`
  already uses `Recreate` strategy against a `ReadWriteOnce`-shaped PVC,
  matching `ARCHITECTURE.md`'s documented production topology (predates
  this change; not something POOLS-7 needed to add). Watchdog poll
  intervals/enablement already have sane defaults in the service's own
  `config.yml`, with no Helm-level exposure — a nice-to-have, not a
  functional gap.
- **VM/Ansible registration through `domains/vms/provisioning/adapter`**:
  `container.py`'s `provider_registry` is already sourced from
  `composed_adapters.provider_registry`, i.e. the adapter package's own
  composition — already wired, not new work.
- **Adjacent, already-fixed by a concurrent change**: `fix-vm-fulfillment-capacity-boundary`
  already removed the VM adapter's stale `[tool.uv.sources]` editable-path
  block (confirmed: `domains/vms/provisioning/adapter/pyproject.toml` has
  no `[tool.uv.sources]` section at all now) and consolidated root/domain
  distribution ownership. That change's own design.md separately flags an
  **unresolved, out-of-scope CI-matrix gap** (missing packages in
  `.github/workflows/tests.yml`'s matrix, staging-only trigger) — real, but
  not assigned to this change by anything in `proposal.md`; noted here so
  Section 11 doesn't silently absorb it.

**Finding: 11.3 has no remaining implementation work found by this
investigation.** Planning should treat it as a confirmation/verification
task (re-check the above holds at implementation time, since this was
inspected, not executed against a live build) rather than assume there is
undone composition work waiting.

### 9. Task 11.5 investigated: suite inventory, and a real typing-coverage gap

11.5 ("run repository-wide import, typing, migration, unit, integration,
and end-to-end suites and fix all renamed-contract consumers") is
fundamentally a validation task, not a design question, but inventorying
what it actually runs against surfaces two things worth recording before
planning:

- **Suite inventory**: root `make test` chains through `test-core`,
  `test-kits` (includes `kit/fulfillment`), `test-provisioning`,
  `test-provisioning-iac`, `test-registry`, `test-storefront`,
  `test-vms-buyer`, `test-apicredits`/`test-apicredits-middleware`.
  `e2e-tests` is a fully separate root with its own `Makefile`/`reinit` —
  confirmed genuinely decoupled from `compute_provisioning`/`kit/fulfillment`
  (it wraps the provisioning HTTP surface with its own hand-written
  `e2e-tests/src/provisioning_test_client.py`, not the `ComputeProvisioningClient`
  package), so its `reinit` not refreshing those wheels is correct, not a
  gap. `openspec validate --all --strict` has been recorded as unavailable
  in every validation environment used since Section 8 — 11.5 should
  disclose this again rather than silently re-attempt it as if it were new.
- **No stale renamed-contract call sites found by static search**: no
  remaining `.select_resource(` (the pre-Section-4 name) or direct
  `provider.create(`/`provider.teardown(` (the pre-Section-5
  prepare/dispatch-split name) call sites anywhere in production code.
  Encouraging, but not a substitute for actually running the suites, which
  needs an environment with every internal wheel installed — not available
  in this review pass.
- **Real gap: "typing" barely exists as a repository-wide lever.** Only
  three packages have a `mypy` Makefile target at all —
  `core`, `core/registry`, `core/registry-client` — none of them touched by
  this change. `kit/fulfillment`, `kit/site`, `kit/resource-pools`,
  `provisioning/compute`(`/service`), and every `domains/*` package this
  change actually modified have no typing check configured anywhere.
  **Open question, not resolved here:** does 11.5's "typing" clause mean
  "run whatever typing checks exist" (in which case it covers none of this
  change's own code and the clause is close to vacuous for this change), or
  does it implicitly expect typing checks to exist for the touched
  packages first? Adding `mypy` configuration to every kit/provisioning/domain
  package this change touched would be materially larger, unscoped work —
  not something to absorb into 11.5 silently. Proposed default: 11.5 runs
  the typing checks that exist today (i.e., effectively a no-op for this
  change's own code) and this gap is flagged, not fixed, unless told
  otherwise.
- **"Migration" suites**: no single top-level "run all migrations" target
  exists; the closest equivalent is each service's own migration test
  coverage (already exercised section-by-section — Sections 2, 3, and 7 in
  particular) plus the `compute-provisioning-migrate` command used as the
  Helm init container. 11.5 should run a fresh-database migration pass per
  touched service plus existing migration test suites, not assume a
  dedicated repository-wide command exists.

### 10. Task 11.4 investigated: real credential-leak gap found in Ansible stdout streaming, not in application-level HTTP/log code

11.4 ("ensure logs, traces, exception payloads, and request logging redact
credentials and prepared secret material") got no discuss-phase pass before
planning (only 11.3/11.5/11.6 did). Investigated now, before implementation,
per direction. The application-level HTTP/log surfaces checked out clean;
the real gap is at the Ansible execution layer, one level below where 11.4's
own wording points.

**Checked and found already safe:**

- `StorefrontAuthMiddleware`/`AdminKeyAuthMiddleware` (the two admin-key
  gates) log only method/path on rejection
  (`logger.warning("Rejected %s %s: missing/invalid X-Admin-Key", ...)`),
  never the presented header value.
- `CredentialFetchFailedError` never reaches an HTTP response body as
  `str(exc)`: `fulfillment_controller.py`'s `result()` endpoint maps it to a
  fixed, generic detail (`"Credentials could not be fetched right now;
  retry the read."`) — the exception's actual message, which could in
  principle wrap an inner exception's text via
  `AnsibleFulfillmentProvider.fetch_credentials`'s `raise
  CredentialFetchFailedError(str(exc)) from exc`, never crosses the
  controller boundary.
- `_extract_and_store_credentials` (`job_service.py`) pops the
  `authentication` block out of a job's `result_payload` before it's stored
  as `job.result` or used anywhere else (confirmed:
  `AnsibleFulfillmentProvider.fetch_credentials`'s `VmConnectionInfo`
  construction reads only non-secret fields — `vm_name`, `host`,
  `timestamp`, `tenant_user`, `vm_ip_internal`, `ssh_port` — from that
  already-sanitized payload). Credentials live only in the dedicated
  `Credential` table, read back only through `get_credentials`.
- `job_service.py`'s three places that persist `job.logs`
  (`_redact_logs`'s call sites: the periodic streaming callback, the
  success path, the `AnsibleError` failure path) all redact consistently —
  a regex-based scrubber for `"password": "..."`/`password: ...`-shaped
  lines (which also matches `tenant_password:`/`root_password:` as
  substrings, confirmed by reading the regex, not assumed), `-i <ssh key
  path>` flags, and `sshpass -p <value>`.
- No SQLAlchemy `echo=True`/SQL-statement logging anywhere in the
  repository; no middleware found that logs full request bodies.

**Real gap, confirmed by tracing the actual data flow, not assumed:**

`ansible_service.py`'s subprocess-output reader calls `logger.debug("ansible
stdout: %s", line.rstrip())`/`logger.debug("ansible stderr: %s", ...)` on
every line read from the Ansible subprocess, immediately and
unconditionally — this is a separate code path from, and runs before,
`job_service.py`'s periodic `log_callback` (which is what `_redact_logs`
actually protects). The per-line debug logging goes straight to Python's
own `logging` module with no redaction applied at all.

This becomes a real credential leak, not just a theoretical one, because of
a second, compounding gap: `domains/vms/provisioning/iac/ansible/roles/vm-management/tasks/vm-create.yml`'s
two password-generating tasks —

```yaml
- name: Generate random password for tenant user
  set_fact:
    tenant_password: "{{ lookup('password', '/dev/null chars=ascii_letters,digits length=32') }}"
  when: vm_action == "create"
...
- name: Generate random password for root user
  set_fact:
    root_password: "{{ lookup('password', '/dev/null chars=ascii_letters,digits length=32') }}"
  when:
    - vm_action == "create" and vm_image_type == "scratch"
```

— have no `no_log: true`, unlike the equivalent tasks in
`vm-management/tasks/vm-reset-password.yml` (`grep -n no_log` finds exactly
two hits, both there, none in `vm-create.yml`). Ansible's default behavior
echoes a `set_fact` task's resulting value in its own "ok" result output;
without `no_log: true`, the raw `tenant_password`/`root_password` value
appears in Ansible's stdout stream during a normal `create` run. Combined
with the first gap, that raw value reaches `logger.debug` unredacted the
moment this module's log level is `DEBUG` — and `ansible.cfg`'s `log_path =
./ansible.log` means Ansible's own run log also captures it to disk,
independent of the application's logger entirely.

**Confirmed not actively firing under default configuration, but real and
latent:** no `log_level` override exists in
`compute_provisioning_service/config/config.yml`, and `main.py` defaults to
`logging.INFO` when unset — so `logger.debug(...)` doesn't emit today under
default settings. This is a latent gap, not an active leak, but it's latent
in exactly the way that matters: `DEBUG` is what an operator reaches for
first when a provisioning job is stuck, which is precisely the moment this
would start leaking a tenant's root password into whatever aggregates the
application's Python logs.

**Secondary, lower-priority finding:** `vm_fulfillment_service.py`'s
`fulfill_vm_obligation` logs `logger.info("[ALKAHEST] Order for fulfillment:
%s", order)` — the entire order/deal-terms object, at `INFO` (not
`DEBUG`-gated), with no field allowlist. Traced what `order` contains today:
it does not appear to carry the buyer's SSH public key or other credential
material directly — `ssh_public_key` is threaded through this function as
its own separate parameter, not read out of `order` — so this isn't an
active leak either. But it's the same class of risk as the Ansible one:
logging a whole, structurally-evolving object wholesale rather than an
explicit allowlist of fields. Worth fixing on its own terms, and especially
before `add-buyer-vm-connectivity-terms` (already noted elsewhere in this
file as split-out, not-yet-built work) has a chance to add SSH-related
fields into the negotiated order shape without anyone revisiting this log
line.

**Proposed fixes, for planning:**

1. Add `no_log: true` to `vm-create.yml`'s two password-generating
   `set_fact` tasks, matching `vm-reset-password.yml`'s existing pattern.
2. Route `ansible_service.py`'s per-line `logger.debug("ansible
   stdout/stderr: %s", ...)` through the same `_redact_logs` scrubber
   `job_service.py` already has — either by having `ansible_service.py`
   import and apply it directly, or by moving the scrubber to a location
   both modules can share without creating an unwanted dependency
   direction (`ansible_service.py`/`job_service.py`'s existing relationship
   should decide which; not resolved here).
3. Change `vm_fulfillment_service.py`'s order-logging line to log an
   explicit, small allowlist of fields (or drop it to `DEBUG`) rather than
   the whole object.
4. Add a regression test proving a `vm-create` run's captured Ansible
   output (both the per-line debug stream and the persisted `job.logs`)
   never contains the raw generated password, using the existing
   `no_log`-protected `vm-reset-password.yml` tasks as the pattern to
   match, not just asserting `_redact_logs`'s regex catches a hand-written
   test string.

**Permanent documentation:** none of this is new normative behavior — it's
a correctness fix restoring the "credentials must not leak into logs"
posture the codebase already partially implements (Section 8's "raw
credentials MUST NOT be persisted" principle, `openspec/specs/fulfillment/spec.md`).
If planning decides the redaction scrubber should move to a shared
location, that's a code-location decision, not a new requirement, per the
same distinction this document has already drawn for
`market_fulfillment.backfill`'s placement (Section 7's implementation
promotion record).

### Section 11 discuss-phase summary

Of `tasks.md`'s six Section 11 items: 11.1's `allocation_id`/`SiteAllocation`
clause and its "direct-host storefront placement"/"process-local settlement
maps or locks" clause are already satisfied and need no new code. 11.1's
`deal_ref` component is dropped from scope entirely (accepted, item 4).
11.1's `register_resource`/compatibility-path component is **not** safe to
remove — apicredits actively depends on it (item 5); task 11.1's wording
should not include it. 11.2 (`most_available` claim-blindness) is real,
current, and now has a corrected design matching today's claim/row
vocabulary, ready to plan directly against item 3 above rather than the
stale 2026-07-17 sketch. 11.3 (composition/wheel/reinit/deployment updates
for `kit/fulfillment`) is investigated and found already satisfied — no
implementation work identified (item 8). 11.4 (credential/secret redaction)
is investigated and found to have one real, concrete gap — unredacted
per-line Ansible stdout debug logging, compounded by two missing `no_log`
directives in `vm-create.yml` — plus one lower-priority object-logging
smell, both with proposed fixes (item 10). 11.5 (repository-wide suite run)
is investigated: suite inventory recorded, no stale renamed-contract call
sites found statically, and a real typing-coverage gap is flagged as an
open scope question rather than resolved (item 9). 11.6 (`vm_host` schema
question) is decided: migrate now, scoped strictly to `vm_host`, with a
concrete write/read/query/migration plan recorded above (item 7).
## Section 11 code-review amendment and planning decisions (2026-07-30)

This entry supersedes the implementation direction in Section 11 design-review
item 3 where it proposed hardcoding complete claim interpretation inside
`core/storefront/aggregation.py`. The original diagnosis remains valid —
`most_available` must rank only capacity relevant to the request — but review
established that duplicating the site authority's requirement semantics in core
storefront would create a second, diverging implementation.

### Accepted matcher composition

- `core/storefront` owns placement orchestration over bounded plain-dict
  projections and remains independent of `kit/site`.
- `most_available` accepts an injected `ClaimMatcher`; its default is an
  intentionally coarse matcher covering pool/resource identity and quantitative
  dimensions so existing generic callers preserve their behavior.
- `kit/site` exposes a public plain-dict adapter,
  `dict_resource_satisfies_claim`, that reconstructs the existing
  `ResourceFeasibilityView`, uses the existing claim parser, and delegates to
  `resource_satisfies_requirement`. It must not implement a second parser or
  matcher.
- A domain composition root may combine these layers. The VM storefront injects
  the exact kit/site adapter under the same placement gate already used for
  `most_available`; domains that do not want site-exact semantics are not forced
  to adopt them.
- VM composition must bind the exact legacy quantity vocabulary used by its
  authoritative ledger: `unit_claim_keys=("units", "gpu_count")`. A bare
  adapter reference uses kit/site's default `("units",)` and is therefore not
  equivalent for legacy VM claims.
- Missing projected categorical fields fail closed for ranking. Site admission
  remains authoritative; stale or incomplete projections may produce a less
  useful order, but identical projected and authoritative data must be
  interpreted identically.

### Projection and authority boundary

The accepted design does not permit storefront to fetch unrestricted provider
inventory. The domain-owned projection still decides which resource fields are
advertised and grouped. Shared matching semantics operate over two different
views: the site authority's current inventory and storefront's bounded, possibly
stale projection. The matcher is shared; data authority and disclosure are not.

### Current `resource_type` decision

The VM claim's current `resource_type="compute.gpu"` is accepted in Section 11
only as the existing site-inventory adapter discriminator consumed by
`resource_satisfies_requirement`. It is not a buyer-facing statement that the
market offering is "VM GPU" and does not replace a future market/offering type.
VM storefront capacity wiring is domain-scoped today, so buyer-facing
cross-domain routing vocabulary is not introduced in this section.

### Deferred cross-domain requirement vocabulary

The following are one coupled future OpenSpec change, not Section 11 cleanup:

- a buyer-facing nested `requirements` shape (for example
  `gpu.{count, model}`);
- domain parsing of that shape into the existing generic quantitative
  `dimensions` and categorical `attributes` split;
- canonical `ResourceRequirement`/`CapacityClaim` vocabulary;
- compatibility migration of the persisted and external
  `required_attributes` field;
- whether a buyer-facing `offering_type` is needed in addition to the
  site-inventory `resource_type`.

A nested domain shape does not change the generic matcher invariant. Domain
parsers decide that `gpu.count` is quantitative and `gpu.model` is categorical,
then feed the existing flat feasibility contract. The generic matcher must not
learn VM-specific component schemas.

The local `required_attributes` variable inside VM job-spec construction may be
renamed to `capacity_claim` now because it is function-local. The serialized
`required_attributes` key is a real admin API, durable-resume, and external
storefront-client compatibility surface and remains unchanged until the future
cross-domain change supplies an explicit migration strategy.

### SQLite rebuild correction

The deterministic table-rebuild direction remains accepted, but code review
proved that dropping the referenced `capacity_reservations` table with
`PRAGMA foreign_keys=ON` triggers `ON DELETE CASCADE` and silently deletes
`capacity_reservation_debits`. The implementation must use a foreign-key-safe
offline rebuild on one connection, preserve child rows, run
`PRAGMA foreign_key_check`, and restore the prior foreign-key setting. Tests
must assert child-row survival, not only referential consistency.

### Section 11 scope expansion: API-credits modernization

The broader audit found API credits is current at the market protocol level but
still uses older repository packaging, persistence-evolution, and direct-HTTP
composition patterns. The following are accepted Section 11 implementation
work:

- replace relative editable sibling sources and repository-root import assembly
  with repository-built wheels installed through reinit targets;
- add service-owned ordered SQLite migrations, deployment init wiring, and
  startup schema-version validation, without adding a migration CLI;
- add a typed capacity-administration client for resource registration/update;
- add an API-credits-domain client so settlement callers do not construct
  service URLs directly.

Background-task supervision, core watchdog/persistence changes, generic remote
capacity assembly, durable issuance/compensation design, quota-release
compensation, and exact API-credit matcher adoption remain deferred for further
design review.

### Permanent documentation destinations after review acceptance

Promotion is intentionally deferred until the implementation stabilizes, but
planning identifies these exact destinations:

| Accepted durable decision | Permanent destination |
|---|---|
| Core placement accepts domain-composed matching without depending on site authority packages | `openspec/specs/market-composition/architecture.md`, `Composition from above and below`; `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| Projected ranking and authoritative admission share requirement semantics while retaining different data authority | `openspec/specs/site-capacity/architecture.md`, add/update projected-feasibility matching section; `docs/development/ARCHITECTURE.md#storefront-capacity-boundary` |
| Site-inventory `resource_type` is distinct from any future buyer-facing offering vocabulary | `openspec/specs/site-capacity/spec.md`, resource feasibility/claim vocabulary; `docs/development/ARCHITECTURE.md#shared-vocabulary-and-identities` |
| API-credit service uses ordered SQLite migrations and deployment-time initialization | `openspec/specs/deployment-state/spec.md`, service schema initialization; API-credit subsystem specification if one exists or is added |
| Operator capacity mutation uses a typed administration client, separate from buyer reservation use | `openspec/specs/site-capacity/spec.md`, capacity administration surface; `docs/development/ARCHITECTURE.md#site-authority` |
| API-credit callers use a domain-owned client instead of constructing service URLs | API-credit subsystem spec/architecture; `docs/development/ARCHITECTURE.md#package-and-dependency-layers` only if the repository-wide client ownership rule needs clarification |

## Section 11 second code-review decisions (2026-07-31)

The second implementation review accepted a narrow correction pass and rejected
expanding this section into deployment-topology or core-lifecycle redesign. The
completed implementation history remains intact; the decisions below govern the
new planning tasks 11.14–11.18.

### API-credit migrations remain in-process for the current topology

The API-credit service currently has no deployment topology that can own a
separate migration job. Section 11 therefore does not add a migration CLI, Helm
init container, or a startup process split. The current service may apply its
owned migrations before constructing request-serving dependencies. Production
documentation must describe that current behavior without comparing it to a
hypothetical future deployment.

The existing empty migration registry is insufficient evidence of ordered schema
evolution or drift detection. The accepted correction is to register a durable
baseline/adoption migration, or explicitly name the mechanism as registry
bootstrap, and to test a non-empty ordered sequence. Tests must prove execution
order, durable recording, rerun idempotency, failure non-recording, preservation
of earlier successes, and incomplete-version detection.

### API-credit clients are composed and reused, without a new protocol

The domain-owned HTTP client remains the accepted boundary. Concrete
`CreditsServiceClient` instances should be constructed in API-credit composition
and injected or reused by settlement and key-lookup services. This avoids
operation-local URL/client construction and permits connection reuse. A separate
client `Protocol` is deliberately not introduced in this correction.

Client validation must exercise the HTTP contract directly rather than only
monkeypatching concrete methods at callers: paths, headers, payloads, successful
responses, not-found semantics, HTTP/transport failures, and rollback sequencing.
The existing typed capacity-administration caller is not expanded further in this
pass.

### Production helpers expose current invariants only

`VM_UNIT_CLAIM_KEYS` remains necessary and must match the legacy aliases composed
by the authoritative VM capacity ledger. Production commentary should state that
invariant concisely; dependency alternatives and review chronology remain here.

The SQLite table-rebuild helper may remain generic only if every interpolated
identifier is validated as a safe SQLite identifier. Otherwise it should be
narrowed to fixed reservation-table identifiers. Its accepted foreign-key-safe
offline rebuild and refusal to silently discard unsupported schema features
remain unchanged.

### Wheel isolation remains an architectural requirement

API-credit packages must install internal dependencies from built distributions,
not repository-relative editable sources or root-level import fallbacks. Remaining
`pythonpath`, `dev-mode-dirs`, or equivalent source-tree shortcuts must be removed
where unnecessary and any retained package-local exception documented. Isolated
wheel import and Docker/build-context validation are required evidence.

### Documentation accuracy is part of completion

Task 11.10's record currently conflates migration-registry bootstrap with
deployment-init and startup-drift work that was not implemented. The record must
be amended rather than preserving a checked acceptance criterion and explaining
away its absence. Production migration modules must remove future-oriented and
changelog-style prose. Completed task notes should retain final behavior, material
validation, deferred work, and permanent destinations; detailed review history
belongs in this design record.

Permanent promotion is complete as of 2026-08-01 — see `tasks.md`'s "Section
11 design promotion record" for the destinations and what was deliberately
not promoted.

## Task 11.2 alternatives: where the exact claim matcher lives (2026-07-30)

The coarse `most_available` fix (task 11.2's original scope) ignores
categorical claim attributes the VM claim builder already emits
(`region`, `gpu_model`) that the authoritative site admission path
already checks. This does not cause incorrect admission — the site
remains authoritative — but causes avoidable failed probe/reserve
attempts. Three placements for the fix were considered.

**Rejected: duplicate more site-matching logic into `core/storefront`.**
`docs/development/ARCHITECTURE.md`'s package-and-dependency-layers rule
is direct: `core/storefront` is a core-layer package, `kit/site` is a
kit-layer package, and dependencies only point downward (kit may depend
on core; core must never depend on kit).
`core/storefront/aggregation.py`'s own docstring ("deliberately does not
import kit/site") is that rule in effect, not a style choice.

**Rejected: promote `ResourceFeasibilityView`-style matching into `core`
itself.** `ResourceFeasibilityView` is `kit/site`'s own way of modeling a
resource (`resource_kind`, per-dimension `available`, exact-match
`attributes`), not a concept every domain needs — `apicredits` runs
through the same aggregator with none of it meaning anything (a single
resource type, no dimensions beyond `units`). Moving it into `core` would
make `core/storefront` stop being backend-agnostic (every `CapacityClient`
implementation would be assumed `kit/site`-shaped) — a regression in the
abstraction `CapacityClient` exists to provide, not a generalization of
it.

**Accepted: dependency injection**, matching a pattern already in use one
parameter over — `AggregateCapacityClient.__init__` already takes a
pluggable `placement: PlacementPolicy | None`, and
`capacity_client.py`'s `build_capacity_client` is already the composition
point that resolves a placement policy by config string. Adding an
injected `claim_matcher` is the same shape as something already there,
not a new seam. `kit/site` gained `dict_resource_satisfies_claim` (a thin
adapter delegating entirely to its own existing pure functions, so there
remains exactly one implementation of claim parsing and matching); VM's
`capacity_client.py` injects it specifically when the resolved placement
is `most_available`, leaving the shared `PLACEMENT_POLICIES` dict — and
what `apicredits`/bare-metal get when they select `"most_available"` —
untouched.

`Callable` type alias vs. `Protocol` for `ClaimMatcher`: went with the
type alias for a single-signature callable; no behavior difference either
way, open to `Protocol` if preferred later.

## Suite-run failure root causes (task 11.5, 2026-07-30)

Two of the four suite-run failures were sandbox dependency-version drift,
diagnosed rather than assumed: re-pointed editable installs at a
byte-for-byte clean copy of the branch point and confirmed the identical
failures reproduced there too, then traced further instead of stopping
at "reproduces on clean, therefore unrelated."

`domains/vms/storefront`'s `test_server_app_composition.py` failed
because the validation sandbox had `fastapi==0.141.0`/`uvicorn==0.52.0`
installed instead of the repository's actual pins (`fastapi~=0.115.8`,
`uvicorn~=0.34.0` — confirmed by `pip`'s own conflict warnings once the
correct versions were installed).

`test_negotiate_controller.py::test_amountless_exact_escrow_can_start_and_accept`
failed because `dynaconf==3.3.4` was installed instead of the pinned
`dynaconf==3.2.13`: with `merge_enabled=True`, `settings_overrides`'
`settings.set(dotted, value)` call merges a list-valued override with the
existing config value instead of replacing it, so the test's
`negotiation.policies` override was silently concatenated with the
config's own default policy list, producing a duplicated middleware chain
(`bisection_middleware` spliced in) that never reached the configured
`accept_exact_listing` terminal policy. Traced by instrumenting every
middleware in the chain and printing the actually-resolved chain.
Installing the pinned dependency versions fixed both.

## Task 11.6 implementation notes: vm_host/vm_target retirement (2026-07-30)

**vm_target was also fully retired, not just vm_host, on the same
finding that corrected this task's own original scoping.** `_legacy_vm_target`
(the helper 11.6.2 introduced to replace `_legacy_vm_fields`) derived
`vm_target` by returning `executor_target` unchanged for VM-kind
reservations — proof by construction that the two columns were always
written to the identical value at the same call sites, making
`vm_target` fully redundant with the pre-existing generic
`executor_target` column. This contradicted the task's original framing
("`vm_target` has no independent write path... stays a dedicated column
while `vm_host` did not") — wrong, and corrected in the same pass.
`attach_lease`/`update_lease_fields` drop `vm_target=` entirely;
`find_active_lease_by_vm_target` filters on `executor_target`;
`_legacy_vm_target` is deleted outright; the migration backfills
`executor_target = COALESCE(executor_target, vm_target)` before dropping
the column. One real behavioral fix this surfaced: the `"vm_target"`
payload key can't simply alias `executor_target` the way `"vm_host"`
aliases a JSON key inside `executor_ref` — `executor_target` is a flat
column shared by every domain (bare-metal populates it too), so an
unscoped alias would leak a bare-metal reservation's target under a
VM-flavored key where it used to correctly read `None`. Caught by
`test_register_bare_metal_lease_attaches_executor_metadata` failing;
fixed by scoping the payload key to `executor_kind == "vm"`.

**Migration consolidation:** `_migrate_remove_provisioned_resource_domain_ref`,
`_migrate_ansible_pool_requirement_delegate`, the `vm_host` migration, and
the new `vm_target` migration were all folded into the single
`_migrate_capacity_model_cutover` function instead of registering four
separate dated migrations — nothing built on any of them has been
deployed anywhere, so there is no intermediate, partially-migrated
database whose compatibility needs preserving across separate migration
IDs. Verified no ordering dependency exists between the folded-in logic
and the migrations that sit between the cutover and where these used to
be registered (they operate on entirely different tables).

**Column-drop determinism:** the original implementation caught
`OperationalError` from `ALTER TABLE ... DROP COLUMN` and continued —
review flagged this as both conflicting with Section 11's own purpose
(an obsolete column could silently survive migration while marked
applied) and too broad a catch. Since this repository supports only
SQLite, "does this SQLite support `DROP COLUMN`" isn't ambiguous enough
to justify a runtime fallback — replaced with
`_drop_columns_via_table_rebuild`, a full create/copy/drop/rename cycle
introspecting columns via `PRAGMA table_info`. A test written
specifically to check index preservation caught a real bug in the first
implementation: it queried `sqlite_master` for the table's indexes
*after* the rename, by which point the query matched the newly renamed
(index-less) table instead of the original's — fixed by capturing the
index list before the rename.

## AGENTS.md comment compliance sweep (2026-07-30)

A repository-wide sweep (`grep` for `POOLS-7`, `Section 11`, `§10`,
`task 11.` across every `.py`/`.yml` file outside `openspec/`) found
Section 11's own new tests violating AGENTS.md's "no OpenSpec change IDs
or task numbers in code comments" rule repeatedly, plus five pre-existing
Section 10-era violations in files this section never otherwise touched.
All twelve occurrences rewritten to state the invariant or behavior
being tested directly, with no change-history reference; re-verified
against every affected suite afterward — all green, text-only changes.

## Task 11.8 debugging note: a false lead while writing the FK-cascade fixture

Writing the FK-cascade regression test (11.8.3) surfaced a real debugging
detour worth recording: the first version of the test failed with a
`FOREIGN KEY constraint failed` on the child insert even though the
parent row was demonstrably present and visible in the same transaction.
Extensive isolation (raw `sqlite3` vs SQLAlchemy, `exec_driver_sql` vs
`text().execute()`, pragma state checks mid-transaction) turned out to
be chasing a red herring: `capacity_reservation_debits.capacity_bucket_id`
has its own separate foreign key to `capacity_buckets`, which the test
simply never populated. Not a SQLAlchemy/pysqlite quirk at all — fixed
by inserting a valid bucket row.

## Section 8 correction tasks — fix-loop debugging record (2026-07-25)

A code review of the diff that had marked 8.9/8.10/8.12/8.13 done found it did not
actually run against the real service composition. Re-applying it to a clean
checkout and running the affected suites (not inspection alone) surfaced four
independent real bugs, all fixed in the same pass:

1. **`vm_provisioning_adapter/fulfillment_results.py` was missing from the reviewed
   diff** (present in the author's working tree, apparently lost to `make
   review-diff` not picking up an untracked new file). Without it,
   `AnsibleFulfillmentProvider` — and the whole `compute_provisioning_service`
   composition root — failed to import, silently invalidating every 8.10/8.13
   claim that depended on a real adapter or app instance (the full 13-test
   integration suite, 16 of 17 `test_legacy_vm_lease_migration.py` tests, and two
   convergence test files could not even collect). Only `kit/fulfillment`'s own
   suite passed, because it mocks the provider — almost certainly why the break
   went unnoticed. Fixed by adding the file.
2. Two integration-test assertions were stale against the new nested
   `domain_result` envelope shape (still reading a since-removed top-level
   `payload["credentials"]`). Fixed to read
   `payload["domain_result"]["payload"]["credentials"]`.
3. **The legacy backfill conflict check was weakened, not preserved**:
   `_existing_provisioned_resources_conflict` had changed from comparing actual
   stored identity to comparing row count only, with the test that asserted a
   mismatched identity is rejected flipped to assert it's accepted — a real loss
   of the safety property the function's own docstring describes. Restored value
   comparison and the original test assertion.
4. `legacy_backfill.py` passed the raw VM target straight through as
   `provisioned_resource_id`, contradicting the fulfillment-owned-opaque-identity
   principle this same diff added to `architecture.md`. Replaced with a
   deterministic derivation — first keyed on `fulfillment_id` (wrong: the
   compiler generates a fresh random `fulfillment_id` per invocation, so this
   isn't stable across a backfill re-run, caught by
   `test_equivalent_rerun_is_idempotent_and_writes_nothing_new` failing),
   re-keyed on `capacity_reservation_id`, which is genuinely stable across
   re-runs of the same lease. Re-running the rerun scenario then surfaced a
   fifth, independent bug: `_apply_legacy_vm_lease_backfill`'s `INSERT` never
   used `draft.provisioned_resource_ref` at all — it inserted a fresh
   `uuid.uuid4()` every time, disconnected from whatever the compiler derived.
   Fixed the `INSERT` to use the derived value.

Also restored `fetch_credentials`' docstring invariants (thinned to two sentences
by the reviewed diff), fixed an incomplete-edit broken sentence in `spec.md`, and
documented `VmFulfillmentCredential`/`vm.fulfillment.result.v1` in
`openspec/specs/physical-provisioning/spec.md#requirement-vm-fulfillment-result-payload`
— including that `provisioned_resource_ids` is not yet genuinely many-to-many
(every credential today names the fulfillment's one and only output).

**Root cause pattern common to bugs 1 and 3-5**: every one was invisible to the
suite that had been run because that suite mocked the exact boundary the bug
lived in (the real adapter import, the real backfill INSERT). This is why
`tasks.md`'s validation notes for this and adjacent sections distinguish "runs
against a real composition" from "passes with the boundary mocked" as different
strength claims, not interchangeable ones.
