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
  **RESOLVED, see "Listing-mode hint consumption" below.** The channel
  question this bullet originally left open (how a storefront learns a
  pool's `policy_tags` across the service boundary) is answered by
  `CapacityProjection` (this file's "`SiteResource` is retired" section):
  the pull-based pool mirror carries `policy_tags` along for free, no new
  channel needed. The `_eligible_candidates`/`SiteResource.attributes.pool_id`
  sync gap this bullet also raised is separately resolved by the same
  section — `site_resource_pools` is now derived from `hosts`/
  `resource_pools`, not storefront-pushed.

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
- **`CapacityProjection`** (storefront-side, new) — the storefront's
  read-only, pull-based mirror of every connected provisioning service's
  pool/capacity state (`GET /api/v1/pools`, which already exists and is
  already reachable — the storefront already holds the admin key for
  each configured site). This is the only place aggregation across hosts
  happens, and it is explicitly advisory/display-only (pricing, listing
  publication) — never the thing admission control checks against. Keyed
  by `(site, pool_id)`, since pool IDs are only unique per provisioning
  service.
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
                                            # no dispatch yet — the ONLY
                                            # state in which the row may
                                            # still be re-selected/mutated
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
    tearing_down     = "tearing_down"
    torn_down        = "torn_down"
    teardown_failed  = "teardown_failed"
    abandoned        = "abandoned"         # reservation expired/released/
                                            # changed while still
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
                                                    # mutable while state=="assigned"
                                                    # (negotiation may still change
                                                    # requirements before dispatch)
    provider_metadata = Column(JSON, nullable=False, default=dict)
    teardown_provider_metadata = Column(JSON, nullable=True)
    state = Column(String, nullable=False, default=SettlementRecordState.assigned.value)
    created_at = Column(DateTime, ...)
    updated_at = Column(DateTime, ...)
```

### Two different idempotency rules depending on `state`

`select_resource`'s existing-record handling is NOT a single uniform
"record exists -> return it" rule. The dividing line is whether `state`
has left `assigned`:

- **`state == "assigned"` (including no record at all):** the row is
  still a mutable scheduling decision. `select_resource` is free to
  re-run eligibility/selection and overwrite `pool_id`,
  `settlement_resource_id`, `provider`, and `requirements` — needed for
  the case where negotiation changes the deal's requirements (or the
  buyer's requested capacity) after an initial schedule but before
  dispatch. `assign_settlement_resource` already handles the capacity
  side of a genuine re-pick atomically (no-op if the resource is
  unchanged; moves held units correctly if it's a real reassignment) —
  `select_resource` now also calls it on re-selection, not only on first
  selection.
- **`state != "assigned"` (dispatch has started or finished):** the row
  is the immutable, equivalence-checked record `pools-3` already
  specified. `select_resource` returns it as-is; an explicit-resource
  request that disagrees with `settlement_resource_id` fails with
  `SettlementRequestMismatchError`. No expiry check applies on this path
  — the `CapacityReservation`'s TTL hold is irrelevant once real physical
  work exists; only equivalence/conflict rules apply from here.

`CapacityReservation` expiry (`CapacityReservationExpiredError`) is
therefore checked **only** on the "still assigned, may re-schedule"
path, never on the "already dispatched" fast-return path — an allocation
whose TTL lapsed after dispatch already succeeded must not have its
retries start failing.

**If an operator requests scheduling against an already-expired
`CapacityReservation`, `select_resource` MUST reject it.** The storefront
handles that failure by requesting a fresh `CapacityReservation` (which
may itself fail if the physical picture changed in the interim) — this
is an existing, already-designed failure path in `pools-2`'s error
taxonomy, not new work. It is deliberately the storefront's
responsibility how long a hold it asks for; see "Pool-level reservation
TTL hint" below for an operator-side lever on that.

### `abandoned` state and the lease-lifecycle watchdog

A `CapacityReservation` can expire, release, or have its requirements
change while its `SettlementRecord` is still sitting in `assigned`
(nothing dispatched yet) — this is expected to be the common case for
delay between scheduling and dispatch, not the exception; see below. The
existing watchdog that already sweeps expired/released
`CapacityReservation` rows (`LeaseLifecycleService.check_leases`) should
also transition any `assigned`-state `SettlementRecord` for that
allocation to `abandoned` — reusing the existing sweep rather than adding
a second, parallel watchdog. No capacity cleanup is needed as part of
that specific transition: `assign_settlement_resource` only ever moves
*which* resource the reservation's already-held units point at, and the
reservation's own release path already frees whatever resource it
currently points to, independent of whether a `SettlementRecord` was
ever created. `abandoned` exists purely for audit clarity, so a
`settlement_records` row never sits at `assigned` forever with no
explanation of why it stalled.

### Expected time between scheduling and dispatch

Normally short — scheduling shouldn't happen until fulfillment is about
to occur, at which point there is little reason for delay between
`select_resource` and `FulfillmentService.create`. The gap that matters
in practice is between **reservation and scheduling**, not between
scheduling and dispatch — a `CapacityReservation` may sit unscheduled for
a long time and can expire before it's ever scheduled. A real (if
uncommon) case for delay between scheduling and dispatch specifically:
scheduling happening as part of agent lease negotiation itself (e.g. a
delayed lease start time, or a late-stage negotiation change), most
plausibly triggered by the buyer's requested capacity/requirements
changing mid-negotiation after an earlier schedule. The
still-`assigned`/mutable-until-dispatch design above is what accommodates
this without treating it as an error case.

### Pool-level reservation TTL hint (flagged, not designed here)

An operator may want a pool-level limit on how long a
`CapacityReservation` against their resources can sit unscheduled/held —
raised during this review as a real, well-motivated use case, not
designed here. Same shape and posture as the listing-mode hint above:
an additive `ResourcePool.policy_tags` entry
(`{"max_reservation_hold_seconds": 900}`), read and voluntarily respected
by a cooperating storefront when it chooses the `ttl_seconds` it passes
to `reserve()` — never enforced by the provisioning service itself
(`reserve()` already accepts a caller-supplied `ttl_seconds`; no new
ledger capability is needed, only a place for the operator to express a
preference and a storefront willing to read it). Left for planning to
schedule, not required by POOLS-7's first pass.

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

## Listing-mode hint consumption: resolved (design review continued, 2026-07-17)

Resolves the channel question the original "Operator listing-mode hints"
entry above left open. No new channel is needed: `CapacityProjection`
(this file's "`SiteResource` is retired" section) already pulls pool
metadata from `GET /api/v1/pools`, so `policy_tags` rides along once the
sync carries it:

```python
class CachedResourcePool(Base):
    __tablename__ = "capacity_projection_pools"

    site = Column(String, primary_key=True)
    pool_id = Column(String, primary_key=True)
    label = Column(String, nullable=False)
    provider = Column(String, nullable=False)
    enabled = Column(Boolean, nullable=False)
    policy_tags = Column(JSON, nullable=False, default=dict)
    synced_at = Column(DateTime, nullable=False)
```

The reconciler-driven publish path (`domains/vms/listings/reconciler.py`,
`cli_publish.py`) already has a structural default, confirmed during
`pools-4`'s design review: a listing derived from a single-resource pool
is resource-pinned; one derived from a real multi-member pool is
pool-scoped. This change's scope is narrower than originally framed: let
an explicit hint override that default, don't replace it.

```python
# kit/resource-pools — domain-neutral: the key name only.
LISTING_MODE_TAG = "listing_mode"

# domains/vms — VM-domain interpretation + default.
class VmListingMode(str, Enum):
    pooled = "pooled"
    specific_resource = "specific_resource"

def resolve_vm_listing_mode(pool: CachedResourcePool, member_count: int) -> VmListingMode:
    declared = pool.policy_tags.get(LISTING_MODE_TAG)
    if declared in (VmListingMode.pooled.value, VmListingMode.specific_resource.value):
        return VmListingMode(declared)
    return (VmListingMode.specific_resource if member_count == 1
            else VmListingMode.pooled)   # unchanged pools-4 structural default
```

**Extensibility confirmed against `apicredits`**, not just asserted: since
`apicredits` is explicitly in scope for this session's broader
`kit`/`CapacityReservation` reshape, the shape only counts as
domain-neutral if `apicredits` can express something VM doesn't need
without touching `kit/resource-pools`. It can — same `LISTING_MODE_TAG`
key, a wholly different enum and default rule, zero kit changes:

```python
class ApiCreditsListingMode(str, Enum):
    shared_quota = "shared_quota"     # listing draws from a pooled quota bucket
    dedicated_key = "dedicated_key"   # listing is pinned to one provider API key

def resolve_apicredits_listing_mode(pool: CachedResourcePool) -> ApiCreditsListingMode:
    declared = pool.policy_tags.get(LISTING_MODE_TAG)
    if declared in (ApiCreditsListingMode.shared_quota.value, ApiCreditsListingMode.dedicated_key.value):
        return ApiCreditsListingMode(declared)
    return ApiCreditsListingMode.shared_quota
```

`kit/resource-pools` owns one string key; each domain owns its own enum
and default rule; no cross-domain coupling.

**Enforcement posture unchanged, restated for the record:**
`PhysicalSettlementScheduler`'s explicit-`resource_id` eligibility path
(`pools-2`) is unaffected by a pool's `listing_mode` regardless — a
buyer's explicit resource request is honored even against a pool tagged
`pooled`. A storefront that never reads the tag, or one running against a
provisioning service that predates this feature, falls through to the
unchanged structural default. Purely additive.
