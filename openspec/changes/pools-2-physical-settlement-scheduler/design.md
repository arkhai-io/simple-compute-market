## Context

POOLS-1 gave operators durable, provider-neutral pool identity and
administrative host membership, but deliberately stopped short of
settlement selection: existing capacity reservation and allocation
selection behavior was explicitly left unchanged, and the site ledger
still hardcodes `pool_id: None` on allocation payloads. Today, physical
placement is not a decision at all — it is either a caller-supplied
`vm_target` or a static `default_vm_host` configuration fallback
(`job_service.py`). There is no formal boundary that owns "which physical
resource satisfies this allocation," which is exactly the conflation this
change resolves.

This content — the scheduler/provider split, the request and resource
shapes, the naming decision, and the pool-selection algorithm — previously
lived in `docs/development/ARCHITECTURE.md` under "Physical Settlement
Scheduler and FulfillmentProvider Architecture." That section was dropped
during the migration to OpenSpec: the migration ledger recorded a
destination change directory (`migrate-compute-provisioning`) that was
never actually created, so the content had nowhere to land and was deleted
along with the source. This design.md is that content's recovered and
updated home.

## Goals / Non-Goals

**Goals:**
- Give the system one durable, idempotent answer to "which physical
  resource satisfies this allocation," keyed by `allocation_id`.
- Balance load across pools without a static priority column (rejected in
  POOLS-1: can't express live balance, duplicate priorities too common).
- Support both the fungible (pool/capacity-attribute) path and the
  specific-resource (explicit `resource_id`) path in the same request
  shape.
- Resolve the previously-blocking capacity-reservation-expiry question by
  reusing the existing lease expiry model rather than inventing a new one.
- Close the `disable_pool` guardrail gap now that there is something for it
  to check.

**Non-Goals:** see `proposal.md` — persistence, `FulfillmentProvider`
execution, specific-resource opt-in configuration, full DRF, and
storefront-side reservation cleanup are all out of scope for this change.

## Decisions

### 1. Scheduler is a separate step from fulfillment, called after capacity reserve

```python
PhysicalSettlementScheduler.select_resource(...)
    -> atomically binds the agreement/allocation to a settlement resource

FulfillmentProvider.create(...)   # pools-3
    -> performs provider-specific operations against the selected resource
```

The scheduler owns placement; it does not execute anything. A provider
(added in `pools-3`) receives an already-selected `SettlementResource` and
must not independently substitute a different one. This keeps the boundary
usable by future non-VM markets (bare metal, Kubernetes, power, storage,
bandwidth) without teaching the generic path any one provider's vocabulary.

```python
from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class PhysicalSettlementRequest:
    allocation_id: str
    agreement_id: str
    market: str
    terms: dict[str, Any]
    pool_id: str | None = None
    resource_id: str | None = None

@dataclass(frozen=True)
class SettlementResource:
    settlement_resource_id: str
    pool_id: str
    resource_kind: str
    provider: str
    attributes: dict[str, Any]

class PhysicalSettlementScheduler:
    async def select_resource(
        self,
        request: PhysicalSettlementRequest,
    ) -> SettlementResource:
        """Atomically bind request.allocation_id to a settlement resource.

        Repeated calls for the same allocation_id return the existing
        binding.
        """
        ...
```

An alternative considered was folding selection into
`ExecutorLeaseService.register_lease` directly. Rejected: it blurs
"registering a lease" with "making a scheduling decision" and denies
scheduling its own idempotency/testing seam (scheduler idempotency,
disabled/exhausted-pool exclusion, and no-match errors need to be testable
in isolation from lease registration).

### 2. Naming: `Settlement Resource`, not `SettlementTarget`

`select_resource(...)` is the primary name; `select_target_resource(...)`
is also acceptable where a call site benefits from emphasizing that the
selected resource is the fulfillment target. The noun `SettlementTarget`
is avoided throughout code and docs — the canonical domain noun is
**Settlement Resource**, per the repository's official vocabulary
(`openspec/config.yaml`).

### 3. Pool selection: bottleneck-normalized least-loaded

```text
for each eligible pool:
    utilization = max(
        used_cpu / total_cpu,
        used_ram / total_ram,
        used_gpu / total_gpu,
        used_disk / total_disk,
    )   # the bottleneck dimension, not an average
select the pool with the lowest utilization
```

Taking the `max` across dimensions rather than an average matters: a pool
at 90% GPU utilization and 10% everywhere else is effectively full for
GPU-bound requests even though its average looks healthy. This is a
lightweight slice of Dominant Resource Fairness (Ghodsi et al.); full DRF
also weights by each *request's* resource shape, not just each pool's
current load — that fuller treatment is deliberately deferred. The
approach requires no new schema or persistent state (no cursor, no
counters) and degenerates to plain round-robin when fed only
single-resource, equal-sized pools, so it is not a regression for the
simple case.

### 4. Specific-resource path is honored, not configured

`PhysicalSettlementRequest.resource_id` is part of the shape from day one:
if supplied, the scheduler binds exactly that resource and does not
substitute another one. What remains unresolved — deliberately, not as an
oversight — is *how* a seller opts a listing into exposing specific
resources, and at what layer that authority lives (resource, pool,
provisioning-service, or storefront level). Encoding an answer now would
be premature; this stays open for a future change once real specific
-resource listings exist to design against.

### 5. Reservation expiry reuses the lease model; watchdog lives at the site authority, not the storefront

Decided this session. Capacity reservations gain the same `start`/`end`
lease-window shape executor leases already use
(`kit/site/src/market_site/ledger.py` already has `hold_expires_at` TTL and
lazy `_expire_stale_holds()` invoked on every `reserve`/`commit`/`release`).
What's added is a periodic sweep, mirroring the existing `LeaseWatchdog`
thin-timer pattern (`domains/vms/provisioning/service/src/services/lease_watchdog.py`):
an asyncio interval timer whose only job is scheduling, delegating all
logic to the ledger's own expiry check, so uncommitted holds are reclaimed
even without another request touching them.

This lives on the site-authority side, not the storefront: a storefront
only ever holds a cached capacity projection and unions multiple sites'
projections for an approximate view (`site-capacity`'s multi-site
aggregation requirement). It has no independent capacity ledger to run a
watchdog against; it only needs to request reservations and receive
change notifications. `kit/site` cannot depend on domain composition roots
(market-composition's from-below dependency rule), so the watchdog itself
is composed at the same place `LeaseWatchdog` already is today — a
provisioning service's composition root — pointed at the ledger's expiry
check instead of VM lease lifecycle. Exact file placement is a `tasks.md`
concern for the implementation plan, not a design decision.

### 6. No persistence this change; binding lives only for this change's own test/process scope

`pools-3` introduces `FulfillmentProvider` and is expected to extend the
same binding identity with `provider_metadata` / `credentials_ref` /
`state` rather than create a second, competing record:

```python
@dataclass
class SettlementRecord:
    allocation_id: str
    agreement_id: str
    market: str
    pool_id: str
    provider: str
    resource: SettlementResource
    provider_metadata: dict[str, Any]
    credentials_ref: str | None
    state: str
```

This change is not deployed to production ahead of `pools-3`, so shipping
without durable storage is acceptable as long as scheduler idempotency is
fully exercised within this change's own test doubles.

### 7. `disable_pool` guardrail

Once the scheduler can create a binding, `ResourcePoolService.disable_pool`
must reject disabling (via DELETE, PUT, or PATCH) a pool with at least one
active settlement-resource binding. Previously a documented no-op — "the
check will be added once the scheduler creates something to check" — this
change is what creates that something.

### 8. The default pool can be disabled; it cannot stop being the fallback

Corrected this session. POOLS-1 implemented `_ensure_default_pool_enabled`
in `resource_pool_service.py`, which rejects `enabled=false` for `default`
on create, replace, patch, and YAML import (`default_pool_disabled`). That
invariant is wrong and this change relaxes it: `default` MUST remain
present under its configured ID — it can never be hard-deleted, and hosts
or create requests that omit a pool ID always resolve to it — but its
`enabled` flag is otherwise ordinary. Disabling it only excludes it from
new scheduler selection (decision 7's guardrail still applies: a disabled
pool with an active binding cannot be disabled further, same as any pool).

This matters operationally: there is currently no mechanism to change
*which* pool ID is `default` other than reconfiguring and restarting the
service. Allowing `default` to be disabled gives operators a real lever
without that restart — e.g., to roll out updated Ansible playbooks pool by
pool: stand up a new pool with the updated `AnsiblePoolConfig`, disable
`default` so the scheduler stops placing new settlement onto it, reassign
existing hosts to the new pool via ordinary host `PATCH`, and only update
the `default` pool ID configuration once the old pool is empty. None of
that requires blocking `default` from being disabled; it only requires
`default` to keep existing and keep catching omitted pool IDs.

### 9. `disable_pool` guardrail applies uniformly, including to `default`

Once decision 8 removes the default-specific block, the active-binding
guardrail from decision 7 becomes the *only* thing that can reject
disabling `default` — there is no longer a default-specific special case
in the disable path.

## Error surface (carried forward, not newly decided)

The planned failure taxonomy is broader than the initial VM path so future
markets can reuse it. Names may be refined during implementation; each
failure classifies as retryable, terminal, or operator-action-required:

`pool_not_found`, `pool_disabled`, `pool_exhausted`, `resource_unavailable`,
`target_resource_missing` / `settlement_resource_missing`,
`provider_not_found`, `provider_unavailable`, `provider_config_invalid`,
`settlement_already_bound`, `fulfillment_create_failed`,
`fulfillment_status_failed`, `fulfillment_teardown_failed`,
`credentials_publish_failed`, `capacity_projection_stale`.

Only the selection-relevant subset (`pool_not_found`, `pool_disabled`,
`pool_exhausted`, `resource_unavailable`, `settlement_already_bound`) is
exercised by this change; the fulfillment-side errors apply once `pools-3`
lands.

## Risks / Trade-offs

- **No persistence yet.** A process crash between selection and (future)
  provider execution loses the binding. Acceptable only because nothing
  consumes bindings for real provisioning before `pools-3`, and this change
  is explicitly not for production deployment ahead of it.
- **Listing-authority question stays open.** The specific-resource path is
  mechanically correct but has no operator-facing configuration surface;
  it can only be exercised by directly supplying `resource_id` today.
- **DRF-lite, not full DRF.** Bottleneck-normalized selection can still
  make a suboptimal placement under heterogeneous request shapes relative
  to full DRF. Deliberately deferred rather than under-designed.
- **Watchdog composition location.** Reusing `LeaseWatchdog`'s pattern
  instead of its code means some duplication until a shared thin-timer
  utility is justified; not worth extracting for one additional caller.

## Migration Plan

None. No schema or wire change in this change; nothing to roll back beyond
reverting the added scheduler module, request/response shapes, watchdog
wiring, and `disable_pool` guardrail.

## Carried-forward note for the plan step

Drafting `pools-5-shared-provisioning-package` surfaced a placement
question worth deciding during `pools-2`'s own plan step rather than
building VM-service-local and reconsidering later: `compute_provisioning`
(`provisioning/compute/src/compute_provisioning`) already owns the pool
wire models and generic lease/contract shapes this scheduler is adjacent
to. Building `PhysicalSettlementScheduler` directly there — rather than in
`domains/vms/provisioning/service` and extracting afterward — may avoid
`pools-5`'s residual-extraction step outright. Worth an explicit
file-placement decision when we move to planning.
