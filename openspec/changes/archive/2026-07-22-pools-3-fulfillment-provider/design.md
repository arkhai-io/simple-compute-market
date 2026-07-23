## Context

`pools-3` builds directly on `pools-2`: the scheduler answers "which
resource," the fulfillment layer answers "how is work executed against that
selected resource." The storefront will eventually own the business workflow
that obtains a Capacity Reservation, negotiates a Market Agreement, starts
physical fulfillment, observes completion, and lets the lease lifecycle request
teardown. That production cutover remains scoped to
`pools-7-storefront-fulfillment-cutover`.

The provisioning service remains authoritative for physical-fulfillment
consistency. The storefront decides when a workflow command should occur; the
provisioning service validates and executes that command idempotently against
the selected physical resource.

## Goals / Non-Goals

See `proposal.md`.

## Decisions

### 1. `FulfillmentService` owns physical-fulfillment consistency, not placement

A provisioning-side `FulfillmentService` sits above `ProviderRegistry` and is
the entry point future storefront-facing code calls. It owns:

- validation that the allocation and *already-selected* resource may be
  fulfilled (including a side-effect-free `validate_create(...)` dry-run
  path, shared with `create()` itself, so a future API can validate
  request/allocation/pool/provider/resource-attribute consistency before
  committing anything);
- atomically rebinding the allocation's held capacity to the selected
  resource via `CapacityLedgerService.assign_settlement_resource(...)`
  before dispatch — this is real, durable, transactional capacity-transfer
  logic (not the scheduler, and not a stub): it re-checks the destination
  has capacity, releases the source, and is idempotent on repeat calls
  with the same resource;
- the allocation-to-fulfillment identity;
- equivalent-retry detection and conflicting-request rejection, for both
  `create` and `teardown`;
- provider resolution and dispatch;
- normalization of provider operation state; and
- persistence updates once durable settlement storage is introduced.

The storefront owns business-workflow progression, but it MUST NOT directly
write settlement records or decide whether a physical dispatch is a duplicate.

**`FulfillmentService` does not call `PhysicalSettlementScheduler` and never
will.** Placement and execution stay separate services, called in sequence by
whatever orchestrates the workflow (the storefront, from `pools-7`):

```text
storefront (or other orchestrator) fulfillment workflow
        |
        |-- 1. select_resource(...) -> PhysicalSettlementScheduler   (placement)
        |
        v
        2. FulfillmentService.create(request, selected_resource)     (execution)
                |-- capacity_ledger.assign_settlement_resource(...)   (durable rebind)
                |-- settlement/fulfillment identity (in-memory this round; see Decision 4)
                |-- ProviderRegistry
                        |-- AnsibleFulfillmentProvider
                                |-- AnsibleJobService
```

The capacity-ledger rebind is a distinct concern from the in-memory
create/teardown identity map in Decision 4: the ledger call makes *which
physical resource the allocation is bound to* durable and safe against a
storefront-supplied resource that doesn't match what was actually reserved
(the "misallocated capacity" concern from this session's implementation
review). It does **not** make the `create`/`teardown` dispatch record
itself durable — that remains an in-memory `FulfillmentEntry` map, and
Decision 4's "not durable, not a concurrency guarantee, POOLS-7 replaces
it" framing still applies to that part.

POOLS-3 introduces the service boundary and provider behavior, tested with a
test caller that plays the orchestrator role — no storefront or scheduler
wiring is added this round. POOLS-7 wires the real storefront workflow to
call the scheduler and then this service in sequence, and completes the
durable transaction design for the create/teardown identity map.

### 2. Provider owns operations, not placement

`FulfillmentProvider`, `FulfillmentResult`, `ProviderStatus`,
`ProviderOperationState`, `ProviderRegistry`, and the error taxonomy live in
`kit/resource-pools` (`market_resource_pools.fulfillment`) — see "Domain-neutral
contracts vs. domain-specific payloads" below for why. `AnsibleFulfillmentProvider`
and the concrete `FulfillmentService` remain in the VM provisioning service.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any


class ProviderOperationState(str, Enum):
    pending = "pending"
    succeeded = "succeeded"
    failed = "failed"
    unknown = "unknown"


@dataclass(frozen=True)
class FulfillmentResult:
    """Result of accepting an asynchronous provider dispatch."""

    provider_metadata: dict[str, Any]


@dataclass(frozen=True)
class ProviderStatus:
    state: ProviderOperationState
    detail: str | None = None


class FulfillmentProvider(ABC):
    @abstractmethod
    async def create(
        self,
        request: "PhysicalSettlementRequest",
        resource: "SettlementResource",
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def teardown(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def get_status(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus: ...
```

`FulfillmentResult` is intentionally the accepted-dispatch result. A separate
`FulfillmentDispatch` type would describe the same contract and is not added.
Credentials are not part of the dispatch result; POOLS-3 introduces no new
secret-distribution system. Existing provisioning credential behavior remains
unchanged and credentials become available only after successful execution.

A provider may validate that the selected resource is usable, but it MUST NOT
select or substitute a different resource. Placement remains solely the
scheduler's responsibility.

### 3. Create and teardown are dispatch-only

Ansible create and teardown operations can take minutes. Both provider methods
therefore submit work and return once the operation is durably accepted by the
job machinery. Callers observe progress through `get_status(...)` rather than
holding a REST request open until completion.

The normalized provider operation states are:

```text
queued/running/retrying -> pending
succeeded               -> succeeded
failed/cancelled        -> failed
missing/unreadable      -> unknown
```

The fulfillment lifecycle maps them as follows:

```text
pending   -> pending
succeeded -> active for create
failed    -> failed
unknown   -> observation failure; do not invent a successful transition
```

Teardown-specific terminal settlement transitions and retention are finalized
in POOLS-7. POOLS-3 guarantees only that teardown mirrors create's asynchronous
semantics and is idempotent.

### 4. Idempotency belongs above `AnsibleJobService`

`AnsibleJobService` remains a narrowly scoped Ansible runner. It is not the
primary authority for whether a Capacity Reservation may begin fulfillment or
whether the allocation already has an accepted fulfillment.

`FulfillmentService` owns the logical identity:

```text
allocation_id -> fulfillment / settlement record -> provider operation metadata
```

**Equivalent-request definition.** Comparison is scoped to the fields that
identify *what* is being fulfilled, not to `PhysicalSettlementRequest.resource_id`
(an optional selection constraint on the *request* — the resolved
`SettlementResource` the scheduler actually picked is the authoritative
resource identity, and `resource_id` may legitimately be absent even though
a concrete resource was still selected). For the same `allocation_id`, a
retry is equivalent if all of the following match the stored fulfillment:
`agreement_id`, `market`, `requirements` (from the request — renamed from
`terms`; see "Domain-neutral contracts vs. domain-specific payloads" below)
and the entire selected `SettlementResource` (`settlement_resource_id`,
`pool_id`, `resource_kind`, `provider`, `attributes`). Both
`PhysicalSettlementRequest` and `SettlementResource` are pydantic models
with structural equality, so this is plain field comparison (excluding
`resource_id`) — no canonical serialization or hashing needed for the
in-memory POOLS-3 implementation.

- an equivalent retry returns the existing fulfillment result;
- a request that reuses `allocation_id` with any of those fields differing
  fails with `FulfillmentConflictError` before another provider operation
  is dispatched.

POOLS-3 specifies this behavior at the service boundary and backs it with a
simple in-memory dict inside `FulfillmentService` (the `FulfillmentEntry` map
— see Decision 4a), keyed on `allocation_id` — enough to make this change's
own spec scenarios (equivalent retry, conflicting reuse) true and testable,
mirroring the pattern `PhysicalSettlementScheduler` already uses for its own
in-memory assignment map. **This is not a concurrency guarantee.** It does
not attempt to close the race between two concurrent callers for the same
`allocation_id`, and it is explicitly not durable across restarts. POOLS-7
MUST replace it with durable database uniqueness and transactions, and MUST
NOT treat this dict (or any process-local/asynchronous lock) as a substitute
for that — closing the concurrent-request race and surviving restarts are
POOLS-7 concerns, not solved here.

This is distinct from — and does not substitute for — the capacity-ledger
rebind in Decision 1: `assign_settlement_resource` durably and atomically
locks in *which physical resource* an allocation is bound to (closing the
"misallocated capacity" gap) and is safe under concurrency by construction
(a session-scoped SQL transaction). It says nothing about whether a second,
concurrent `create()` call for the same `allocation_id` would race past this
in-memory equivalence check before either finishes — that race is still
open and still POOLS-7's job to close.

The executor job may additionally retain a deterministic command identity as a
last defensive layer around the dispatch/persistence failure window, but that
does not replace higher-level eligibility and duplicate validation.

### 4a. `FulfillmentService` owns provider metadata after `create` — callers don't pass it back in

`teardown`/`get_status` do **not** take `resource`/`provider_metadata` as
caller-supplied parameters. A caller supplying its own copy of that data
after `create` has already registered the fulfillment weakens the identity
map Decision 4 establishes — the value could belong to a different
allocation, name a different job, or simply be stale. `FulfillmentService`
stores what it needs at `create` time and looks it up by `allocation_id`
alone thereafter:

```python
@dataclass(frozen=True)
class FulfillmentEntry:
    request: "PhysicalSettlementRequest"
    resource: "SettlementResource"
    create_result: FulfillmentResult
    teardown_result: FulfillmentResult | None = None


class FulfillmentService:
    async def create(
        self,
        request: "PhysicalSettlementRequest",
        resource: "SettlementResource",
    ) -> FulfillmentResult: ...

    async def teardown(self, allocation_id: str) -> FulfillmentResult: ...

    async def get_status(
        self, allocation_id: str, operation: Literal["create", "teardown"] = "create",
    ) -> "ProviderStatus": ...
```

`teardown` idempotency falls out of this directly: no stored
`teardown_result` → resolve the provider from the stored `resource`, dispatch,
and save the result; an existing `teardown_result` → return it without
redispatching. `get_status`'s `operation` argument selects which stored
`FulfillmentResult`'s `provider_metadata` to check status against, since
`create`'s and `teardown`'s dispatches are tracked separately (e.g. two
different Ansible job ids).

`FulfillmentProvider`'s own contract (Decision 2) is unchanged and stays at
the lower, stateless layer — it still takes `resource`/`provider_metadata`
explicitly, since a provider has no identity map of its own and shouldn't
need one. The signature simplification is specific to `FulfillmentService`,
which does own that map.

### 5. `ProviderRegistry` maps provider strings to instances

Lives in `kit/resource-pools` alongside the rest of the domain-neutral
contract (Decision 2).

```python
class ProviderRegistry:
    def __init__(self, providers: dict[str, FulfillmentProvider]) -> None:
        self._providers = dict(providers)

    def require(self, provider: str) -> FulfillmentProvider:
        try:
            return self._providers[provider]
        except KeyError:
            raise ProviderNotFoundError(
                f"No FulfillmentProvider registered for provider={provider!r}"
            ) from None
```

The VM provisioning service initially registers only
`"ansible" -> AnsibleFulfillmentProvider`. New mechanisms extend the registry
without provider-specific branching in fulfillment or lifecycle code.

### 6. Ansible configuration is pool metadata snapshotted at dispatch, validated eagerly

```python
@dataclass(frozen=True)
class AnsiblePoolConfig:
    playbook_path: str
    extra_vars: dict[str, Any]
```

Pool-level infrastructure variation is stored in the resource pool's generic
provider-configuration envelope. `AnsibleFulfillmentProvider` resolves that
envelope through `ResourcePoolService`, validates it, translates it into
Ansible executor inputs, and snapshots those inputs into the submitted job.

Snapshotting occurs when fulfillment is dispatched, not when the background
worker later starts. Editing a pool therefore cannot silently change an
already-accepted operation or make a retry non-deterministic.

Before dispatch, `_validate_resource` rejects: a pool that no longer exists,
a disabled pool (`ResourcePool.enabled`), and a resource whose `.provider`
doesn't match its pool's current `.provider`. `_vm_host` requires a
non-empty `resource.attributes["vm_host"]` and raises
`ProviderConfigInvalidError` rather than guessing — an earlier draft of this
provider fell back to `resource.settlement_resource_id` when `vm_host` was
absent from `attributes`, which was flagged during implementation review as
an unverified assumption about resource-registration shape; failing loudly
is the correct replacement regardless of how that assumption resolves.
`validate_create` additionally parses `request.requirements` into a typed
`VmFulfillmentRequirements` (`models/fulfillment_model.py`, VM-domain-local
— see "Domain-neutral contracts vs. domain-specific payloads" below),
rejecting malformed requests before any dispatch.

`_validate_extra_vars` rejects pool `extra_vars` that collide with a
reserved set of built-in job-identity keys. **Resolved during this session**
(originally shipped as a hardcoded, incomplete list — confirmed during
implementation review to miss real built-in fields such as `executor_kind`,
letting a collision on those pass this check and only surface later, inside
the background job worker, when `_build_vm_vars` ran its own complete but
asynchronous check). Fixed by extracting `AnsibleService`'s built-in-field
construction into a shared `_build_builtin_var_lines` helper, used both by
`_build_vm_vars` (rendering) and a new `reserved_var_keys(params)` method
(synchronous validation) — the two can no longer disagree about what's
reserved, because they're the same code. `AnsibleFulfillmentProvider` calls
this (via `AnsibleJobService.reserved_var_keys`, preserving the existing
"no direct `AnsibleService` dependency" boundary) with the fully-built
`AnsibleJobParams` *before* attaching `provider_extra_vars`, so the reserved
set reflects exactly what this specific create/teardown would emit
(conditional fields like `image_setup_type`'s golden-image branch included),
not a static approximation.

`inventory_group` is removed from `AnsiblePoolConfig`. The current execution
path does not use it operationally: scheduling already selects one concrete
`SettlementResource`, and Ansible execution is limited to that selected host.
Allowing an inventory group to influence placement would create a second,
conflicting scheduler.

Provider metadata (`AnsibleFulfillmentMetadata`) retains `vm_host`,
`vm_target`, `create_job_id`, `teardown_job_id`, and `current_job_id` from
create through teardown, rather than re-deriving `vm_host` from the resource
at teardown time. This closes a real bug found during implementation review:
an earlier draft never set `vm_target` on the teardown job's params at all,
so `vm_remove` on a shared host had no way to know which VM to remove.

The `ProgrammableMockAnsibleService` seam remains inside the Ansible provider
and existing test-controller gating remains unchanged.

### 7. Settlement record contract

The durable record introduced with the storefront cutover extends the scheduler
binding identity rather than creating a competing physical-fulfillment identity:

```python
@dataclass
class SettlementRecord:
    allocation_id: str
    agreement_id: str
    market: str
    pool_id: str
    provider: str
    resource: "SettlementResource"
    provider_metadata: dict[str, Any]
    credentials_ref: str | None
    state: str  # "pending" | "active" | "failed"
```

The final ORM layout and migration are deferred until POOLS-7's persistence
work. The contract decisions fixed now are:

- `allocation_id` is the idempotency and lookup identity;
- the scheduler-selected resource and provider are retained durably;
- provider metadata MUST contain enough information to resume status checks and
  later dispatch teardown after process restart;
- credentials remain references to the existing provisioning credential flow,
  not a new secret-distribution system; and
- the record remains available until asynchronous teardown has completed.

Final teardown state transitions, live-set behavior, and record retention are
specified by POOLS-7 rather than guessed here.

`SettlementRecord` remains independent of the storefront's
`settlement_claims` / `mechanism_state` and `ClaimsEngine`. Physical
fulfillment is keyed by `allocation_id`; financial claim collection is keyed by
`claim_ref`.

### 8. Release-path wiring is deferred to POOLS-7

`executor_kind` and `provider` are orthogonal:

- `executor_kind` selects domain allocation semantics and valid executor actions
  (`vm`, `bare_metal`);
- `provider` selects the infrastructure mechanism (`ansible` today).

POOLS-3 does not rewire `LeaseLifecycleService`, `ExecutorReleaseDispatcher`,
or the current release executors because there is no production caller or live
settlement record yet. POOLS-7 will connect lease teardown to the persisted
record, resolve the provider, dispatch asynchronous teardown idempotently, and
notify the storefront/capacity workflow as appropriate.

## Error surface

The fulfillment-side error taxonomy is:

- `provider_not_found`
- `provider_unavailable`
- `provider_config_invalid`
- `fulfillment_conflict`
- `fulfillment_create_failed`
- `fulfillment_status_failed`
- `fulfillment_teardown_failed`

`credentials_publish_failed` is removed because POOLS-3 defines no credential
publication operation that could raise it.

## Risks / Trade-offs

- Only the Ansible provider is implemented initially.
- POOLS-3 establishes the service and provider contracts before the storefront
  has a production caller. POOLS-7 must validate the cross-service retry and
  restart behavior against the real call path.
- Database-backed idempotency and the final persistence schema are deliberately
  deferred together to POOLS-7; process-local locking MUST NOT be introduced as
  a substitute in the interim. The capacity-ledger rebind (Decision 1) is a
  partial, real exception to this — it makes resource *binding* durable now —
  but the create/teardown dispatch identity map is not, and is not intended
  to be until POOLS-7.
- `FulfillmentService.create()`'s `capacity_ledger` integration has no test
  coverage at the `FulfillmentService` level (only in isolation, directly
  against `CapacityLedgerService`) as of this document. `assign_settlement_resource`
  itself is also only tested for the happy path and idempotent re-assignment —
  not insufficient-capacity rejection, wrong-allocation-state rejection, a
  missing allocation, or that the source resource's capacity is actually freed.

## Domain-neutral contracts vs. domain-specific payloads

This split (and the `terms` → `requirements` rename) came out of team
design review, not solely this document. Two positions were in tension:
`PhysicalSettlementRequest` living in the VM domain could be VM-specific and
strongly typed (better tests, less accidental generality); but it was
already clear other domains (bare-metal, eventually others) would need the
same request/scheduling/fulfillment shape soon, arguing for a generic
contract now rather than a painful generalization later.

Resolution: `PhysicalSettlementRequest.requirements` stays a generic
`dict[str, Any]` — the storefront translates negotiated commercial/deal
terms into both capacity-reservation demand and fulfillment requirements;
provisioning validates the supplied requirements against the allocation, but
neither derives fulfillment inputs from the Capacity Reservation nor reads
workload sizing from pool provider configuration. Domain-specific typing
happens one layer down: `VmFulfillmentRequirements`
(`models/fulfillment_model.py`) is VM-domain-local, not part of the shared
contract, and is where the earlier VM-specific-typed-command proposal's
intent (deterministic `vm_target`, explicit image/CPU/memory/disk/SSH-key
fields) actually lives.

This also settles where `FulfillmentProvider`/`ProviderRegistry`
(Decision 2/5) belong: once the request/resource types those classes
operate on are domain-neutral (`PhysicalSettlementRequest`/
`SettlementResource` already live in `compute_provisioning`, per `pools-2`),
keeping the classes themselves VM-service-local was an awkward split either
way. The final package boundary places them with provider-neutral scheduling
contracts in `kit/fulfillment`.

## Closure ownership reconciliation

The authoritative implementation locations at archive time are:

- provider-neutral requests, resources, provider protocols, status, errors, and registry: `kit/fulfillment/src/market_fulfillment/`;
- generic process-local coordination: `provisioning/compute/service/src/compute_provisioning_service/services/fulfillment_service.py`;
- VM requirements and the Ansible provider: `domains/vms/provisioning/adapter/src/vm_provisioning_adapter/`.

Earlier `kit/resource-pools`, VM-service, `allocation_id`, and generic
`agreement_id` placement is superseded. Generic fulfillment uses
`capacity_reservation_id`; the storefront retains commercial identity.

## Design promotion record

| Accepted decision | Permanent location or disposition |
|---|---|
| Fulfillment scheduling and provider-neutral execution contracts share the higher-level fulfillment kit | `openspec/specs/fulfillment/spec.md#ownership`; `docs/development/ARCHITECTURE.md#package-and-dependency-layers` |
| Providers execute against a selected resource and cannot perform replacement placement | `openspec/specs/fulfillment/spec.md#provider-contract` |
| Provider and executor registration are independent namespaces | `openspec/specs/fulfillment/spec.md#provider-contract`; `openspec/specs/physical-provisioning/spec.md#requirement-validated-executor-registration` |
| Ansible validates pool/resource inputs, snapshots resolved configuration, normalizes status, and preserves exact teardown identity | `openspec/specs/physical-provisioning/spec.md#requirement-ansible-fulfillment-adapter` |
| Capacity assignment transfers an existing debit rather than subtracting capacity twice | `openspec/specs/site-capacity/spec.md#internal-capacity-accounting` |
| Process-local fulfillment identity is not durable concurrent idempotency | `openspec/specs/fulfillment/spec.md#scheduling-and-assignment` |
| Durable persistence, recovery, public dry-run wiring, and persisted prepared-operation evidence | Transferred to `pools-7-storefront-fulfillment-cutover` sections 3, 6–8, and 10 |
