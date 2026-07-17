## Context

Captured during the `pools-3-fulfillment-provider` design-review session
(2026-07-15), before any implementation of `pools-3` existed. This file is
reference material for whoever picks this change up — it is not a design
this change has committed to; it records what was verified true at the
time so a future session doesn't have to re-derive it, and can verify it's
still true before proceeding.

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

## Remaining open questions for whoever picks this up

- **RESOLVED, see "`fill_first`/`most_available`: resolved" below.**
  ~~Does `AggregateCapacityClient`'s `fill_first`/`most_available`
  placement logic get deleted outright...~~ — kept, bug-fixed, not
  bundled with the listing-mode hint. That same section also surfaced a
  new, still-open question: whether the site-fallback behavior itself is
  now vestigial for pool/resource-pinned claims post-POOLS-4.
- **RESOLVED, see "Scope decision: retrofit, not compute-30 extraction"
  below.** ~~Whether `market-platform-compute-30-extract-service`'s
  absorbed package-boundary decision... should be forced by this
  change...~~ — forced, for `PhysicalSettlementScheduler`/
  `DeterministicRoundRobinPolicy` specifically (moved to
  `compute_provisioning`); `compute-30`'s own proposal has been updated
  to match.
- **Operator listing-mode hints via `ResourcePool.policy_tags`** —
  **designed, then SPLIT OUT to `pools-8-capacity-projection-and-listing-hints`
  along with `CapacityProjection`** (see "Scope split: `CapacityProjection`
  and hints move to `pools-8`" below) — not resolved in this change. The
  channel question this bullet originally left open (how a storefront
  learns a pool's `policy_tags` across the service boundary) was answered
  during this review by `CapacityProjection`: the pull-based pool mirror
  carries `policy_tags` along for free, no new channel needed — but the
  design itself now lives in `pools-8`, not here. The
  `_eligible_candidates`/`SiteResource.attributes.pool_id` sync gap this
  bullet also raised IS resolved in this change (unaffected by the scope
  split) — see "`SiteResource` is retired," below: `site_resource_pools`
  is now derived from `hosts`/`resource_pools`, not storefront-pushed.

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
set for policy selection. Exact home for this predicate (alongside
`PhysicalSettlementScheduler` in `compute_provisioning`, or in
`kit/site` where the resource rows themselves live) is not decided;
resolve during planning.

### `PhysicalSettlementScheduler` and `DeterministicRoundRobinPolicy` move to `compute_provisioning`, not `kit/resource-pools`

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
scheduler operates on already live there (`pools-2`). **Resolved:**
`PhysicalSettlementScheduler` and `DeterministicRoundRobinPolicy` move
into `compute_provisioning`.

This incidentally resolves part of the open, unresolved question
`market-platform-compute-30-extract-service` inherited from the closed
`pools-5-shared-provisioning-package` ("should `PhysicalSettlementScheduler`
... consolidate into `compute_provisioning`") — without POOLS-7 taking on
compute-30's actual service-extraction scope. This is the same kind of
narrow, deliberate override `pools-3` already made once for
`FulfillmentProvider`/`ProviderRegistry`; see that change's `design.md`,
"Domain-neutral contracts vs. domain-specific payloads." `compute-30`'s
proposal has been updated to reflect this as resolved rather than open.

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

### Open question surfaced by writing this table down: is the second layer's fallback still meaningful post-POOLS-4?

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

## Storefront orchestrates scheduling and dispatch as separate calls (design review continued, 2026-07-17)

**Resolved: confirms POOLS-3's design was already correct as written —
no correction needed there.** `pools-3`'s `design.md` diagram names "the
storefront" as the orchestrator calling `select_resource(...)` then
`FulfillmentService.create(...)` in sequence. An earlier pass of this
review flagged apparent tension between that and this change's atomic,
single-transaction `select_resource` design — there isn't one, once the
reason for the split is understood: **`select_resource`'s result can be
commercially material to the negotiation before a deal is finalized**
(e.g. a larger node's price for the same requested capacity may differ
from a smaller one, and the buyer/agent may need to know which node was
selected before price is finalized). Scheduling capacity and finalizing
a deal are genuinely separate decisions the storefront needs to make at
separate times, not an implementation detail to hide behind one call.

Resolved shape: two required storefront-facing operations, plus one
optional convenience operation:

1. **Schedule** — invokes `select_resource`. Returns the selected
   `SettlementResource` (so it can inform pricing/negotiation). Does not
   dispatch anything.
2. **Dispatch** — invokes `FulfillmentService.create` against an
   already-scheduled allocation. This is where `dispatch_pending` and
   everything downstream in the state machine begins.
3. **(Optional) Atomic convenience operation** — calls (1) then (2) in
   one request, for callers that don't need the pricing-preview behavior
   and just want to fulfill immediately. Not required; a thin
   composition of the two required operations, not a third code path.

Each of (1) and (2) remains its own atomic transaction internally (this
file's earlier transaction-boundary decisions are unaffected) — "the
storefront calls them separately" describes the *external* API shape,
not the internal transaction boundary of either call. Exact route/wire
shapes (the concrete API contract `create_vm_and_wait_with_credentials`
gets replaced by — request/response bodies, status representation,
credentials retrieval, teardown request/response) are not decided here;
left for planning.

## Transaction boundary and repository ownership, stated explicitly (design review continued, 2026-07-17)

Two things that were implicit in this file's code sketches rather than
stated as requirements, made explicit here:

- **`assign_settlement_resource` (capacity rebind) and `SettlementRecord`
  creation/transition MUST share one database transaction.** Achievable
  because `CapacityLedgerService`, `ResourcePoolService`, and (per the
  `compute_provisioning` migration decision above) `PhysicalSettlementScheduler`
  all already live in the same provisioning-service process/database — this
  isn't a cross-service transaction, it's an ordinary single-database one.
  A sequence that moves capacity, commits, and only then inserts the
  settlement record as a second commit is NOT acceptable — a crash between
  those two commits leaves a moved reservation with no durable scheduling
  identity, silently reintroducing the exact failure window point 2 exists
  to close.
- **`SettlementRecord`'s model/repository interface lives in
  `compute_provisioning`, alongside `PhysicalSettlementScheduler` and the
  request/resource dataclasses it already owns — not in `kit/resource-pools`
  alongside `ResourcePool`.** It is physical-settlement lifecycle state,
  not pool-administration state; it belongs with the scheduler that writes
  it, for the same reasons the scheduler itself moved there. The concrete
  SQLAlchemy table is still composed into whichever service's actual
  database (the VM provisioning service's, today).

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

## Legacy allocations during cutover (design review continued, 2026-07-17)

Real gap, not addressed by "no allocation without a `SettlementRecord`"
alone — that describes the target *steady state*, not what happens to
allocations already in flight, created under the old direct-dispatch
path, at the moment this change deploys. **Resolved: two acceptable
strategies, choice deferred to planning, but whichever is chosen MUST be
stated explicitly rather than silently assumed:**

1. **Fabricate a `SettlementRecord` for each pre-existing allocation
   during migration** — backfill a row (state reflecting whatever's
   inferable about the allocation's actual status, e.g. `active` for a
   running VM) so every allocation uniformly has one going forward, and
   the release path never needs a "no settlement record" branch at all.
2. **Explicitly accept a compatibility break** — allocations created
   before the cutover marker are not migrated; release for them continues
   through the pre-existing direct-dispatch-aware path (or an equivalent
   documented fallback) rather than being forced through
   `PhysicalSettlementScheduler`/`FulfillmentService`. This is acceptable
   for this codebase's maturity level ("that's OK from time to time," not
   a production migration with an SLA) but MUST be written down as a
   deliberate decision in whatever change implements the cutover, not
   discovered by a future reader as an unstated gap.

Either way, this needs a concrete plan before implementation — not
resolved further here.
