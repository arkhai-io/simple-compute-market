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
  fulfilled;
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
                |-- settlement/fulfillment identity (in-memory this round; see Decision 4)
                |-- ProviderRegistry
                        |-- AnsibleFulfillmentProvider
                                |-- AnsibleJobService
```

This keeps `FulfillmentService` from becoming a combined placement-and-
execution service, and preserves the rule that providers (and, transitively,
`FulfillmentService`) act only on the resource they were explicitly handed —
never selecting or substituting one themselves. `FulfillmentService.create`
and `FulfillmentService.teardown` both take a `SettlementResource` as an
input parameter, exactly as `FulfillmentProvider.create`/`teardown` do; there
is no scheduler dependency anywhere in this call chain.

POOLS-3 introduces the service boundary and provider behavior, tested with a
test caller that plays the orchestrator role (see Decision 4 for how — no
storefront or scheduler wiring is added this round). POOLS-7 wires the real
storefront workflow to call the scheduler and then this service in sequence,
and completes the durable transaction design when settlement persistence is
added.

### 2. Provider owns operations, not placement

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

For the same `allocation_id`:

- an equivalent retry returns the existing fulfillment result;
- a request that conflicts on agreement, selected resource, provider, or other
  fulfillment identity fails with a conflict before another provider operation
  is dispatched.

POOLS-3 specifies this behavior at the service boundary and backs it with a
simple in-memory dict inside `FulfillmentService`, keyed on `allocation_id` —
enough to make this change's own spec scenarios (equivalent retry, conflicting
reuse) true and testable, mirroring the pattern `PhysicalSettlementScheduler`
already uses for its own in-memory assignment map. **This is not a concurrency
guarantee.** It does not attempt to close the race between two concurrent
callers for the same `allocation_id`, and it is explicitly not durable across
restarts. POOLS-7 MUST replace it with durable database uniqueness and
transactions, and MUST NOT treat this dict (or any process-local/asynchronous
lock) as a substitute for that — closing the concurrent-request race and
surviving restarts are POOLS-7 concerns, not solved here.

The executor job may additionally retain a deterministic command identity as a
last defensive layer around the dispatch/persistence failure window, but that
does not replace higher-level eligibility and duplicate validation.

### 5. `ProviderRegistry` maps provider strings to instances

```python
class ProviderRegistry:
    def __init__(self, providers: dict[str, FulfillmentProvider]) -> None:
        self._providers = providers

    def require(self, provider: str) -> FulfillmentProvider:
        if provider not in self._providers:
            raise KeyError(f"No provider registered for '{provider}'")
        return self._providers[provider]
```

The VM provisioning service initially registers only
`"ansible" -> AnsibleFulfillmentProvider`. New mechanisms extend the registry
without provider-specific branching in fulfillment or lifecycle code.

### 6. Ansible configuration is pool metadata snapshotted at dispatch

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

`inventory_group` is dropped from this provider-facing dataclass — it is not
operationally used: scheduling already selects one concrete
`SettlementResource`, and Ansible execution is limited to that selected host.
Allowing an inventory group to influence placement would create a second,
conflicting scheduler.

Scoped to this dataclass only: `AnsiblePoolConfigHandler`'s DB-facing
validation, `db/models.py`'s `AnsiblePoolConfig` ORM column, and
`db/migrations.py` are untouched this round (no DB work in POOLS-3 — see
`proposal.md` Impact). The column stays required and populated exactly as
today; `AnsibleFulfillmentProvider` simply doesn't read it into its own typed
config. Relaxing the handler/schema is a later decision, not part of this
change.

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
  a substitute in the interim.
