## Context

This content previously lived in `docs/development/ARCHITECTURE.md`'s
"Physical Settlement Scheduler and FulfillmentProvider Architecture"
section, recovered the same way as `pools-2`'s design.md (see that
document's Context for the provenance note — the migration ledger pointed
at a change directory that was never created).

`pools-3` builds directly on `pools-2`: the scheduler answers "which
resource," the provider answers "what do I do with it." Verified against
current code before writing this down: `AnsibleJobService`,
`AnsibleService`, and `ProgrammableMockAnsibleService` still exist as
described in `domains/vms/provisioning/service/src/services/`, and the
storefront's `settlement_claims`/`mechanism_state`/`ClaimsEngine` still
exist in `core/storefront/src/core_storefront/`.

## Goals / Non-Goals

See `proposal.md`.

## Decisions

### 1. Provider owns operations, not placement

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

@dataclass
class FulfillmentResult:
    """Provider result persisted on the settlement record.

    ``create()`` is dispatch-only (see Decision 1a) — for Ansible this
    result is returned the moment the job is *submitted*, not when it
    finishes. ``provider_metadata`` therefore always carries enough to
    resume tracking (e.g. a job id) and a ``state`` the caller can read
    without needing provider-specific knowledge: "pending" until
    get_status confirms otherwise.
    """
    provider_metadata: dict[str, Any]
    credentials: dict[str, Any]

@dataclass
class ProviderStatus:
    state: str           # "pending" | "running" | "stopped" | "gone" | "unknown"
    detail: str | None = None

class FulfillmentProvider(ABC):
    """Minimum contract for any physical settlement provider.

    The identity key is allocation_id. Infra-specific identifiers are
    provider metadata, not generic lifecycle identity.

    create() is idempotent on allocation_id: re-delivery must detect-or-create,
    not double-provision. teardown() is idempotent: no-op if already gone.
    status() and teardown() operate from the persisted settlement record.
    """

    @abstractmethod
    async def create(
        self,
        request: "PhysicalSettlementRequest",   # from pools-2
        resource: "SettlementResource",          # from pools-2
    ) -> FulfillmentResult: ...

    @abstractmethod
    async def teardown(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> None: ...

    @abstractmethod
    async def get_status(
        self,
        allocation_id: str,
        resource: "SettlementResource",
        provider_metadata: dict[str, Any],
    ) -> ProviderStatus: ...
```

A provider may validate that the selected resource is usable, but must not
independently select or substitute a different resource without returning
to the scheduler boundary.

### 1a. `create()` is dispatch-only; the caller polls

Ansible execution is not synchronous. `AnsibleJobService.submit()` enqueues
onto the existing `AsyncJobQueue` and returns immediately; the actual
playbook run happens later in `_process_job` and can take minutes. A
`create()` signature that returns a finished `FulfillmentResult` cannot be
satisfied without either (a) blocking the async call until the job reaches
a terminal state — effectively re-implementing polling one layer down and
tying up the caller for the same duration anyway — or (b) making `create()`
itself return once dispatched and letting the caller poll `get_status()`.
Decision: **(b)**. This is not a new pattern in this codebase — it's the
same shape as `LeaseRegistration.create_job_id`, and matches how the
storefront's `create_vm_and_wait_with_credentials` already polls
`ComputeProvisioningClient` today.

```python
class AnsibleFulfillmentProvider(FulfillmentProvider):
    async def create(self, request, resource) -> FulfillmentResult:
        pool_config = self._pool_config(resource.pool_id)   # see Decision 3
        params = self._build_params(request, resource, pool_config)
        job_id = await self._job_service.submit(params, self._job_queue)
        return FulfillmentResult(
            provider_metadata={"job_id": job_id, "state": "pending"},
            credentials={},
        )

    async def get_status(self, allocation_id, resource, provider_metadata):
        job = self._job_service.get_job(provider_metadata["job_id"])
        if job.status == "succeeded":
            return ProviderStatus(state="running")
        if job.status in ("failed", "cancelled"):
            return ProviderStatus(state="unknown", detail=job.error)
        return ProviderStatus(state="pending")
```

Whatever eventually calls `create()` (unscoped by this change — see
`pools-7-storefront-fulfillment-cutover`) is responsible for the poll loop
and for updating `SettlementRecord.state`/`credentials_ref` once
`get_status` reports completion and credentials become available via the
job service.

### 2. `ProviderRegistry` maps provider strings to instances

```python
class ProviderRegistry:
    def __init__(self, providers: dict[str, FulfillmentProvider]) -> None:
        self._providers = providers

    def require(self, provider: str) -> FulfillmentProvider:
        if provider not in self._providers:
            raise KeyError(f"No provider registered for '{provider}'")
        return self._providers[provider]
```

The VM service starts as a degenerate singleton
(`"ansible" -> AnsibleFulfillmentProvider`), constructed in the DI
container at startup. New provider implementations extend the registry
without adding provider branches to lifecycle code.

### 3. Ansible provider owns variable construction and pool-level variation

```python
@dataclass
class AnsiblePoolConfig:
    playbook_path: str
    inventory_group: str
    extra_vars: dict[str, Any]
```

Pool-level variation in data-center infrastructure (different FRP servers,
network bridges, firewall topologies, available utilities) is expressed via
`AnsiblePoolConfig`. **This storage already exists** —
`AnsiblePoolConfigHandler` (`services/ansible_pool_config_handler.py`)
persists `playbook_path`/`inventory_group`/`extra_vars` per pool today, and
`ResourcePoolService.get_pool(pool_id).provider_config` already resolves it
(`_attach_provider_config` in `market_resource_pools/service.py`). This
change adds no new pool-config storage; `AnsibleFulfillmentProvider` simply
calls `resource_pool_service.get_pool(resource.pool_id).provider_config` at
execution time. Different pools get different playbooks and extra vars
without a new provider type. The mock seam stays at this layer:
`ProgrammableMockAnsibleService` is selected by the `mockMode` profile flag
inside the Ansible provider, not promoted to `FulfillmentProvider`. The
`/test/*` controller and e2e gate pattern are unchanged.

### 4. `SettlementRecord` extends the `pools-2` binding identity

```python
@dataclass
class SettlementRecord:
    allocation_id: str
    agreement_id: str
    market: str
    pool_id: str
    provider: str
    resource: "SettlementResource"   # from pools-2
    provider_metadata: dict[str, Any]
    credentials_ref: str | None
    state: str   # "pending" | "active" | "failed"
```

`resource` records what the scheduler selected; `provider_metadata` records
what the provider learned or created while executing settlement. Sensitive
access material should be referenced (`credentials_ref`) rather than stored
inline. This is the same `allocation_id`-keyed identity `pools-2`
establishes non-durably — `pools-3` is what makes it durable, not a second
parallel record.

`state` starts `pending` on `create()` dispatch (Decision 1a), moves to
`active` once `get_status` reports the resource is up and credentials are
available, or `failed` on a terminal job failure. There is no `released`
state here: `teardown()` removes the record from the live set rather than
holding a tombstone (mirrors the scheduler's own non-durable design —
nothing downstream needs a torn-down settlement record to exist).

**Confirmed independent of `ClaimsEngine`**: `SettlementRecord` is
provisioning-side physical-settlement state keyed on `allocation_id`. The
storefront's `settlement_claims`/`mechanism_state` (`ClaimsEngine`,
`core/storefront/settlement_lifecycle.py`) is seller-side on-chain claim
collection keyed on `claim_ref`, with no notion of `allocation_id`, pools,
or physical resources. `SettlementRecord` MUST NOT reference either. See
`proposal.md`'s "Settlement Record / Claims Boundary" section.

### 5. Release-path rewiring is explicitly deferred, not decided here

Earlier drafts of this document assumed a `release_delegate` parameter on
`LeaseLifecycleService` that would become a thin adapter over the
registry-resolved provider's `teardown(...)`. That parameter doesn't exist
in the current codebase — the real injection point is `executor_release:
ExecutorReleasePort`, routed by `ExecutorReleaseDispatcher` on
`allocation["executor_kind"]` (`"vm"` / `"bare_metal"`) to
`VmReleaseExecutor` / `BareMetalReleaseExecutor`
(`services/release_executors.py`).

`executor_kind` and `provider` are different, orthogonal axes:
`executor_kind` is a domain-allocation-semantics distinction (VM allocations
are shareable across many VMs per host; bare-metal allocations are
exclusive to one host — see `market-platform-compute-40-multi-domain-proof`,
which explicitly proves VM-shareable and bare-metal-exclusive allocations
coexisting against the same physical host, in the same provisioning
process). `provider` is an infrastructure-mechanism distinction (how to
reach a resource — Ansible today). Neither subsumes the other, and
`ExecutorReleaseDispatcher` doesn't select physical resources or
mechanisms at all — it's a pure lookup on a value already stamped on the
allocation at lease-registration time; resource/mechanism selection is
entirely `PhysicalSettlementScheduler`'s and `ProviderRegistry`'s job.

`VmReleaseExecutor` today is a narrow, VM-specific Ansible caller
(`vm_action="vm_remove"`) with no `SettlementResource`/`pool_id`/`provider`
awareness — it is not the same abstraction as `FulfillmentProvider`, which
is meant to own the full create/status/teardown lifecycle for one
mechanism, addressable by any executor kind that uses that mechanism.

This change does **not** wire them together. Because nothing yet calls
`select_resource` + `create` (see Non-Goals / "Explicitly Deferred This
Round" in `proposal.md`), no `SettlementRecord` rows will exist for
`VmReleaseExecutor` to release through the registry — that wiring is
deferred to whichever change first gives `SettlementRecord` a real caller
(`pools-7-storefront-fulfillment-cutover`), so it can be designed against
an actual call shape rather than guessed at now.

## Error surface

Shared with `pools-2`'s design.md (same taxonomy, this change exercises
the fulfillment-side subset): `provider_not_found`,
`provider_unavailable`, `provider_config_invalid`,
`fulfillment_create_failed`, `fulfillment_status_failed`,
`fulfillment_teardown_failed`, `credentials_publish_failed`.

## Risks / Trade-offs

- **Ansible-only.** The `FulfillmentProvider` boundary is designed to be
  provider-neutral, but only one implementation exists until a second
  domain needs a different provider.
- **No production caller yet.** `FulfillmentProvider`/`ProviderRegistry`/
  `SettlementRecord` are built and tested in isolation this round with
  nothing invoking `select_resource` + `create` end to end. Correctness
  under real dispatch (concurrent creates, retries mid-flight, the
  release-path wiring in Decision 5) won't be exercised until
  `pools-7-storefront-fulfillment-cutover` gives it a caller. Keep the unit
  and integration tests for this change resource-pool/provider-focused
  rather than assuming a caller shape that doesn't exist yet.
- **`PhysicalSettlementScheduler` stays non-durable.** `select_resource()`
  has no production caller today either (only tests call it —
  `app_runtime.py` just resolves the singleton at startup), so this isn't
  urgent, but it means `pools-2`'s "persist Capacity Settlement Assignments
  ... transactionally" follow-on item is **not** picked up by this change.
  Considered and rejected for this round: having `select_resource()` write
  through a `SettlementRecord` row itself (state `pending`, no provider
  execution yet) would close that gap as a side effect, but it means
  `pools-3` reaching into `PhysicalSettlementScheduler`'s internals, which
  is scope beyond the fulfillment-provider boundary this change is for.
  Explicitly deferred to `pools-7-storefront-fulfillment-cutover`, which is
  the change most likely to need it (a real caller makes both scheduling
  and fulfillment durability matter at the same time).

## Migration Plan

Adds a new `SettlementRecord` table, keyed on `allocation_id` — `pools-2`'s
`_capacity_settlement_assignments` map stays process-local/in-memory (per
its own `tasks.md`, "Persist Capacity Settlement Assignments... " remains
separately-listed follow-on work, not something this change silently
folds in). No wire break: `AnsibleJobService`/`AnsibleService`'s existing
callers are wrapped, not replaced.
