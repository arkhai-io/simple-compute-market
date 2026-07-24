## Approved legacy-cutover decisions — 2026-07-24

The active-VM migration normalizes historical hosts and capacity records into the operator-created default pool before fulfillment backfill. Generic compute migration code receives a VM-owned pure backfill compiler through composition; it does not import VM adapter models. Native provider metadata remains strict, while a separate validated backfilled metadata shape permits an absent historical create-job identity. A releasing reservation is migrated only when its teardown coordinates and referenced provider job are pollable and unambiguous; otherwise the entire migration, including its completion marker, fails atomically.

The VM storefront persists only the trusted configured `site_id` alongside reservation and fulfillment correlation. URLs and credentials remain operator configuration. Scheduling, acceptance, status, result, and teardown resolve that persisted site directly and never broadcast after reservation. The chain `fulfillment_uid` remains distinct from provisioning's `fulfillment_id`. Storefront workflow persistence retains canonical request/result state needed for restart reconciliation but no provisioning credential payload; buyer-facing credential retention continues under the storefront's existing security boundary and must remain buyer-authorized.

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
  provider-configuration envelope).
- `resource_kind` is the **provider-routing domain**. The canonical bare-metal
  resource kind is `"bare_metal"`; it remains distinct from the identically
  spelled executor kind and from `virtualization_type`. `ProviderRegistry`
  dispatches on exact `(provider, resource_kind)` pairs.
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
provisioning service may have multiple replicas and may restart between steps.

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

## Public fulfillment transport and caller ownership (2026-07-23 amendment)

The generic compute contract owns one versioned HTTP/client boundary; storefronts do not import service implementations or `market_fulfillment` persistence models. The v1 routes are:

- `POST /api/v1/fulfillment/schedules` for `schedule_resource`;
- `POST /api/v1/fulfillments` for `begin_fulfillment`;
- `POST /api/v1/fulfillments/dry-run` for side-effect-free provider preparation validation;
- `GET /api/v1/fulfillments/{fulfillment_id}/status`;
- `GET /api/v1/fulfillments/{fulfillment_id}/result`; and
- `POST /api/v1/fulfillments/{fulfillment_id}/teardown`.

Wire carriers live in `compute_provisioning.contracts` and carry the compute-contract version. Scheduling requires `capacity_reservation_id`, immutable `market`, normalized requirements, and an optional exact resource constraint. Fulfillment acceptance requires `capacity_reservation_id`, the same market, and a versioned domain fulfillment-request envelope; it never accepts a selected physical resource. Responses expose only neutral settlement, fulfillment, provisioned-resource, failure, and credential carriers. Typed not-found failures map to 404, identity/idempotency conflicts to 409, invalid requirements or prepared input to 422, and temporarily unavailable lifecycle operations to 503.

Authorization is bound to credentials, not to the caller-controlled `X-Agent-ID` header. Production configuration maps opaque storefront principal IDs to distinct admin secrets; constant-time key lookup places the authenticated principal on request state. The legacy single `admin_api_key` is represented as one configured principal for compatible single-seller deployments. Local development may retain the existing open mode, but ownership checks remain structurally present using a local-development principal.

Capacity reservation creation records that authenticated principal as an opaque `owner_principal`; the site authority does not interpret it as commercial or buyer identity. Scheduling verifies the reservation owner before assignment and copies the same immutable principal onto the fulfillment aggregate. Status, result, and teardown require that persisted principal. A different valid storefront credential receives 404, rather than an ownership-revealing 403, and cannot claim an existing reservation merely by knowing its opaque ID. Operator-only pool/resource administration remains governed by the existing administrative role and is not made storefront-owned by this change.

Raw credentials are not accepted into the generic fulfillment aggregate or prepared-operation payloads. Domain providers expose a live credential accessor. For VM password access, completion discards provider-job credential rows after extracting non-secret output; a result read obtains a fresh credential by the adapter's reset/rotation path, returns it once, deletes the transient provider-job credential material, and advances a persisted non-secret generation counter. Bare-metal SSH-key fulfillment returns connectivity/access references without persisting buyer private material. This design makes restart recovery independent of stored raw credentials while retaining on-demand access recovery.

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

## Resource-kind-aware provider routing (2026-07-23 amendment)

Provider identity names an infrastructure mechanism, not a domain. VM and
bare-metal pools may therefore both name `ansible` while requiring different
domain-owned request validation and execution adapters. `ProviderRegistry`
resolves the exact `(provider, resource_kind)` pair from the persisted selected
resource. Duplicate exact pairs fail startup, but the same provider identity may
be registered for distinct resource kinds. Legacy provider-only registrations
remain explicit compatibility fallbacks; a scoped registration is never
inferred for another resource kind or a provider-only lookup. The canonical
registrations are `("ansible", "compute.gpu")` for VM fulfillment and
`("ansible", "bare_metal")` for bare-metal fulfillment. This preserves domain
ownership without requiring provider-name migrations in resource pools.

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
sweep; just scheduled periodically instead of once. Multi-replica safety
(claiming rows so multiple replicas don't double-process the same record
— `SELECT ... FOR UPDATE SKIP LOCKED` or an equivalent claim/lease
pattern) is required regardless of whether the sweep is startup-only or
periodic, and is left for planning to specify concretely.

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
multi-replica-safe claim/lease pattern. Database locks are released before any
long-running external provider call. Recovery uses bounded batches,
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
- **`credential_generation` still matters, for a different reason.**
  Originally it prevented a stale push retry from clobbering a newer
  credential set the storefront already received. In a pull model there's
  no retry race to prevent, but a client that cached an earlier response
  still benefits from knowing whether its cached credentials are stale
  relative to a later rotation — `credential_generation` in the response
  serves that purpose instead.
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
| Credential-bound storefront principals own reservation and fulfillment access; caller-controlled headers and deal data do not grant authority | `openspec/specs/site-capacity/spec.md#requirement-storefront-owned-reservation-authority`, `openspec/specs/fulfillment/spec.md#requirement-credential-bound-fulfillment-ownership`, and `docs/development/ARCHITECTURE.md#site-authority` |
| One settlement/fulfillment aggregate keyed by `capacity_reservation_id`; `fulfillment_id` is a generated column, not a second key | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Scheduling equivalence and fulfillment equivalence are two independent, separately-persisted checks | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| No persisted `SettlementResult`; results are a read-time projection over the aggregate and its provisioned resources | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Recovery-claim fields live on the aggregate row, not a separate claims table | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| The scheduled market is immutable and every fulfillment acceptance must match it | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Settlement persistence documents and tests SQLite transaction guarantees rather than portable row-lock claims | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Recovery selection in Section 3 is provisional; Section 7 owns the final operational claim protocol | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Generic lifecycle updates are limited to the shared mutable lifecycle payload and cannot alter aggregate invariants | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Repository callers provide validated canonical models; persistence performs structural JSON equality rather than arbitrary-input canonicalization | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| `CapacityLedgerService` session-accepting entry points let a higher-layer caller compose one transaction across reservation state and settlement assignment | `openspec/specs/site-capacity/spec.md#relationship-to-fulfillment-scheduling` |
| `schedule_resource` is one atomic transaction (lock, enumerate, select, rebind, persist, commit/rollback together), replacing separate self-committing calls | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Round-robin fairness state is durable and scoped per `resource_kind`, read/written in the same transaction as the settlement record; the scheduling policy itself stays a pure function with no database access | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Scheduling's SQLite concurrency contract (single-writer `BEGIN IMMEDIATE`, not portable row locks) matches fulfillment acceptance's existing contract | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment` |
| Scheduling uses a narrow transaction-scoped persistence boundary over the existing repositories; deterministic database-concurrency tests instrument that semantic boundary with independent sessions and explicit barriers | `openspec/specs/fulfillment/spec.md#requirement-scheduling-and-assignment`; `docs/development/ARCHITECTURE.md#deterministic-database-concurrency-tests` |
| `resize_reservation` supersedes a reservation via one self-managed-session transaction (release-then-reserve, never two independently committed calls); no `_in_session` twin is built without a real co-transactional caller | `openspec/specs/site-capacity/spec.md#requirement-reservation-supersede-and-settlement-abandonment` |
| `SettlementAbandonmentHook` is called unconditionally from every capacity-reclaiming path (TTL lapse, release, resize); `market_site` never imports `market_fulfillment` to implement it | `openspec/specs/site-capacity/spec.md#requirement-reservation-supersede-and-settlement-abandonment` |
| Fulfillment providers resolve by exact `(provider, resource_kind)` with only explicit provider-only compatibility fallback; canonical Ansible routes are `compute.gpu` for VM and `bare_metal` for bare metal | `openspec/specs/fulfillment/spec.md#provider-contract`; `openspec/specs/physical-provisioning/spec.md#validated-executor-registration`; `openspec/specs/physical-provisioning/architecture.md#registration-boundary` |
| Provider preparation is synchronous and side-effect-free; accepted versioned commands commit before claimed recovery dispatch, which reads no mutable pool/host configuration | `openspec/specs/fulfillment/spec.md#provider-contract`; `openspec/specs/fulfillment/spec.md#durable-settlement-persistence` |
| Periodic SQLite recovery workers claim bounded non-overlapping batches under the single-writer boundary, release locks before provider calls, reclaim expired leases, and back off failed work | `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`; `docs/development/ARCHITECTURE.md#fulfillment` |
| Pull-based results project durable state at read time; active credential issuance uses a durable non-overlapping claim, provider-owned live rotation, transient private job material, deletion after consumption, and generation advancement only after success | `openspec/specs/fulfillment/spec.md#requirement-pull-based-fulfillment-result-and-live-credentials`; `docs/development/ARCHITECTURE.md#fulfillment` |
| Whole-fulfillment teardown persists immutable pending input at the authenticated command boundary; recovery exclusively dispatches/converges it and releases capacity only after provider success | `openspec/specs/fulfillment/spec.md#requirement-provisioning-owned-whole-fulfillment-teardown`; `docs/development/ARCHITECTURE.md#release` |
| Historical VM leases normalize into the default pool and are compiled by the VM adapter into teardown-capable explicitly backfilled aggregates in one fail-fast migration transaction | `openspec/specs/fulfillment/spec.md#requirement-historical-vm-fulfillment-backfill`; `openspec/specs/resource-pool-management/spec.md#requirement-explicit-valid-host-membership` |
| VM storefront orchestration persists trusted site routing, immutable remote requests, lifecycle correlation, and non-secret result progress; restart recovery never broadcasts after reservation and keeps provisioning and chain fulfillment identities separate | `openspec/specs/fulfillment/spec.md#requirement-durable-storefront-fulfillment-orchestration`; `openspec/specs/site-capacity/spec.md#requirement-site-identity-trust-boundary`; `docs/development/ARCHITECTURE.md#fulfillment` |
| Public route, migration, worker-health, adapter, storefront, and operator procedures describe the current pull/recovery lifecycle without callback-based release instructions | `openspec/specs/compute-provisioning-contract/spec.md#requirement-authenticated-fulfillment-lifecycle`; `provisioning/compute/README.md`; `domains/vms/provisioning/adapter/README.md`; `domains/vms/storefront/README.md`; `docs/development/VALIDATION_RUNBOOK.md`; `docs/seller-quickstart.md` |

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

### Recovery selection remains provisional until Section 7

The recovery columns belong on the aggregate row, but the Section 3 helper is not the final multi-worker claim protocol. It must be named and documented as a single-worker SQLite persistence primitive. Section 7 owns the operational worker model, acquisition/lease semantics, duplicate-dispatch prevention, and the tests that prove those guarantees. Permanent Section 3 documentation may describe the durable claim fields and lease intent, but must not present the provisional helper as the completed recovery algorithm.

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
