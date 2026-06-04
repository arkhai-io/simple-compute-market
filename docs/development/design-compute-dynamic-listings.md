# Compute dynamic listings from inventory and leases

This is the compute-specific implementation plan for deriving storefront
listings from GPU VM inventory and lease state. It intentionally does not try
to extract a generic core abstraction yet. The current useful boundary is:

- **Storefront state** covers market-facing facts and policy inputs:
  inventory pools, allocations, listing derivation, negotiation, settlement
  policy, refund/dispute policy, and registry sync.
- **Provisioning state** covers execution facts: provider jobs, concrete VM
  targets, host checks, leases, and release execution.
- **Provisioning callbacks** report execution facts to the storefront. The
  storefront applies seller policy and reconciles listings.

## Goals

- Support partial GPU capacity allocation. A 4x GPU machine must be able to
  lease 1, 2, 3, or 4 GPUs without treating the whole machine as consumed for
  every request.
- Derive registry listings from current pool capacity. For a 4x pool, publish
  1x, 2x, 3x, and 4x listings while all 4 GPUs are available; after a 2x lease,
  keep 1x and 2x listings available and close/unpublish 3x and 4x listings.
- Keep provisioning execution separate from market policy. Provisioning failure
  is a fact; retry, alert, refund, hold, or release is storefront policy.
- Keep listings fungible. A listing can represent a pool backed by multiple
  machines or multiple provisioning providers without exposing the concrete
  backend choice to buyers.

## Non-goals

- Do not introduce a `market-core` lifecycle abstraction yet. This should be
  implemented as a compute storefront/provisioning subsystem first.
- Do not make the provisioning service decide listing status or seller policy.
- Do not make listing derivation depend on direct provisioning DB reads. The
  storefront should maintain a local market-state projection.

## Storefront data model

The current implementation uses existing `resources` rows as single-resource
pools: `compute_allocations.resource_id`, `derived_compute_listings.resource_id`,
and listing `offer_resource.resource_id` all point to the same concrete resource
row. This supports partial allocation for one machine and multiple independent
machines, but it does not yet support one fungible market-facing pool backed by
multiple concrete machines or provisioning providers.

The planned follow-up is to add the explicit pool/member model below and change
listing derivation from per-resource to per-pool.

### `compute_inventory_pools`

Market-facing capacity buckets. A pool is what listings are derived from.

```python
class ComputeInventoryPool:
    pool_id: str
    seller_id: str
    resource_type: Literal["compute.gpu"]
    gpu_model: str
    region: str
    sla: float
    total_gpu_count: int
    status: Literal["active", "paused", "deleted"]
    pricing_policy_id: str | None
    escrow_policy_id: str | None
    allocation_policy: Literal["first_fit", "least_fragmenting", "round_robin"]
    created_at: datetime
    updated_at: datetime
```

### `compute_pool_members`

Concrete backing capacity for a pool. Members may come from different
provisioning providers when the storefront wants fungible listings.

```python
class ComputePoolMember:
    member_id: str
    pool_id: str
    provider_id: str
    provider_resource_id: str
    provider_host_id: str | None
    gpu_count: int
    status: Literal["active", "draining", "disabled", "deleted"]
    attributes: dict
```

### `compute_allocations`

Storefront-side market allocation projection. Allocations exist before a
provisioning lease exists, so this table cannot be replaced by provisioning
`vm_leases`.

```python
class ComputeAllocation:
    allocation_id: str
    pool_id: str
    member_id: str | None
    resource_id: str | None
    listing_id: str | None
    escrow_uid: str | None
    negotiation_id: str | None
    gpu_count: int
    status: Literal[
        "reserved",
        "provisioning",
        "leased",
        "releasing",
        "released",
        "failed",
        "held",
    ]
    provider_id: str | None
    provider_job_id: str | None
    provider_lease_id: str | None
    lease_end_utc: datetime | None
    failure_reason: str | None
    created_at: datetime
    updated_at: datetime
```

Statuses that consume capacity for listing derivation:

```python
CAPACITY_HELD_STATUSES = {
    "reserved",
    "provisioning",
    "leased",
    "releasing",
    "held",
}
```

### `derived_compute_listings`

Storefront-owned record of listings generated from a pool. The existing
`listings` table can remain the canonical local listing row; this table links
derived listing identity back to the pool and derivation parameters.

```python
class DerivedComputeListing:
    listing_id: str
    pool_id: str
    gpu_count: int
    status: Literal["open", "closed", "paused"]
    derivation_key: str
    last_reconciled_at: datetime
```

The `derivation_key` should be deterministic, for example
`pool:{pool_id}:gpus:{gpu_count}:policy:{pricing_policy_id}`. This lets the
reconciler update existing rows instead of creating churn.

## Provisioning data model

Provisioning keeps execution facts. Existing `jobs` and `vm_leases` should be
extended only with correlation fields needed by callbacks and lookups.

```python
class ProvisioningProvider:
    provider_id: str
    base_url: str
    status: Literal["active", "disabled"]
    auth_profile: str
```

```python
class ProvisioningJob:
    job_id: str
    provider_id: str
    action: Literal["create", "check", "destroy", "expiry"]
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    allocation_id: str | None
    escrow_uid: str | None
    resource_id: str | None
    error: str | None
    result: dict | None
```

```python
class VmLease:
    lease_id: str
    provider_id: str
    allocation_id: str
    escrow_uid: str
    resource_id: str
    vm_host: str
    vm_target: str
    gpu_count: int
    status: Literal["pending", "active", "releasing", "released", "failed"]
    lease_end_utc: datetime
    create_job_id: str | None
    check_job_id: str | None
```

## Storefront service interfaces

### Repository

```python
class ComputeInventoryRepository:
    def load_pool(self, pool_id: str) -> ComputeInventoryPool: ...
    def list_active_pools(self) -> list[ComputeInventoryPool]: ...
    def list_pool_members(self, pool_id: str) -> list[ComputePoolMember]: ...
    def list_active_allocations(self, pool_id: str) -> list[ComputeAllocation]: ...
```

### Allocator

```python
class ComputeAllocator:
    def reserve_capacity(
        self,
        terms: ComputeTerms,
        *,
        listing_id: str,
        negotiation_id: str | None,
        escrow_uid: str | None,
    ) -> ComputeAllocation: ...

    def mark_provisioning_started(
        self,
        allocation_id: str,
        *,
        provider_id: str,
        provider_job_id: str,
    ) -> None: ...

    def mark_lease_started(
        self,
        allocation_id: str,
        *,
        provider_lease_id: str,
        lease_end_utc: datetime,
    ) -> None: ...

    def mark_releasing(self, allocation_id: str) -> None: ...
    def mark_released(self, allocation_id: str) -> None: ...

    def apply_failure_policy(
        self,
        allocation_id: str,
        failure: FulfillmentFailedEvent,
    ) -> FailurePolicyResult: ...
```

### Listing reconciler

```python
class ComputeListingReconciler:
    def derive_listing_intents(
        self,
        pool: ComputeInventoryPool,
        members: list[ComputePoolMember],
        allocations: list[ComputeAllocation],
    ) -> list[ComputeListingIntent]: ...

    def reconcile_pool(self, pool_id: str) -> ReconcileResult: ...
    def reconcile_all(self) -> ReconcileResult: ...
```

For the first implementation, `ComputeListingIntent` can be concrete and
storefront-specific: upsert local listing, publish/update registry listing, or
close/unpublish registry listing. Do not abstract this until another resource
domain exists.

## Listing derivation rule

```python
held_gpu_count = sum(
    allocation.gpu_count
    for allocation in allocations
    if allocation.status in CAPACITY_HELD_STATUSES
)
available_gpu_count = pool.total_gpu_count - held_gpu_count

for gpu_count in range(1, pool.total_gpu_count + 1):
    should_be_open = pool.status == "active" and available_gpu_count >= gpu_count
```

In the full fungible-pool model, `pool.total_gpu_count` is the sum of active
member capacity and held capacity is grouped by `compute_allocations.pool_id`.
The selected concrete member is stored on the allocation for provisioning, but
derived listings use `pool_id` so duplicate equivalent machines do not create
duplicate market listings.

The listing offer payload is derived from the pool and the requested slice:

```python
offer_resource = {
    "resource_type": "compute.gpu",
    "gpu_model": pool.gpu_model,
    "gpu_count": gpu_count,
    "region": pool.region,
    "sla": pool.sla,
}
```

Pricing, `accepted_escrows`, and `max_duration_seconds` come from pool policies
or defaults. The listing should not expose `provider_id`, `provider_resource_id`,
or `provider_host_id` unless a seller explicitly chooses a non-fungible schema.

## Provisioning callback API

Provisioning callbacks report facts. They do not instruct the storefront to
close listings, refund, retry, or release capacity. The storefront applies
policy and runs reconciliation after any capacity-state change.

```python
class FulfillmentStartedEvent:
    allocation_id: str
    escrow_uid: str
    provider_id: str
    provider_job_id: str
    resource_id: str
    gpu_count: int
```

```python
class FulfillmentFailedEvent:
    allocation_id: str
    escrow_uid: str
    provider_id: str
    provider_job_id: str
    resource_id: str | None
    reason: str
    message: str
    logs_ref: str | None
```

```python
class UsageStartedEvent:
    allocation_id: str
    escrow_uid: str
    provider_id: str
    provider_lease_id: str
    resource_id: str
    vm_host: str
    vm_target: str
    gpu_count: int
    lease_end_utc: datetime
```

```python
class ReleaseStartedEvent:
    allocation_id: str
    provider_lease_id: str
    check_job_id: str | None
```

```python
class CapacityReleasedEvent:
    allocation_id: str
    provider_lease_id: str
    resource_id: str
    released_at: datetime
```

Endpoint shape:

```text
POST /api/v1/admin/fulfillment/events
```

or explicit endpoints:

```text
POST /api/v1/admin/fulfillment/events/started
POST /api/v1/admin/fulfillment/events/failed
POST /api/v1/admin/fulfillment/events/usage-started
POST /api/v1/admin/fulfillment/events/release-started
POST /api/v1/admin/fulfillment/events/capacity-released
```

Use the storefront admin auth boundary initially. A later implementation can
replace this with signed provider callbacks.

## Lifecycle hooks

### 1. Inventory import or startup

Storefront:

1. Upsert pools and members.
2. Reconcile affected pools.
3. Publish/update/close derived listings.

### 2. Buyer settlement terms accepted

Storefront:

1. Reserve capacity from the relevant pool.
2. Reconcile the pool immediately so oversized listings disappear before the
   provisioning job finishes.
3. Start provisioning through the selected provider.

### 3. Provisioning job starts

Provisioning -> storefront: `FulfillmentStartedEvent`.

Storefront:

1. Mark allocation `provisioning`.
2. Reconcile pool.

### 4. Provisioning succeeds and usage starts

Provisioning -> storefront: `UsageStartedEvent`.

Storefront:

1. Mark allocation `leased`.
2. Store provider lease correlation fields.
3. Reconcile pool.

### 5. Provisioning fails

Provisioning -> storefront: `FulfillmentFailedEvent`.

Storefront:

1. Apply seller failure policy: release, retry, alert, refund, hold, or mark
   failed.
2. Reconcile pool only after policy changes capacity state.

### 6. Lease release begins

Provisioning -> storefront: `ReleaseStartedEvent`.

Storefront:

1. Mark allocation `releasing`.
2. Reconcile pool. Capacity is still held until release is confirmed.

### 7. Capacity released

Provisioning -> storefront: `CapacityReleasedEvent`.

Storefront:

1. Mark allocation `released`.
2. Reconcile pool so listings for larger slices can reopen.

## First implementation sequence

Current status: steps 1, 3, 4, 5, 6, 7, and 8 are implemented for the
single-resource-as-pool shape. Step 2 remains as the full fungible-pool
follow-up.

1. Add storefront compute allocation tables and repository methods.
2. Add compute pool/member tables, or adapt existing `resources` rows into a
   pool/member projection if a smaller first step is needed.
3. Change settlement reservation from whole-resource state flip to partial
   capacity allocation.
4. Add deterministic derived listing rows and a pool reconciler.
5. Trigger reconciliation on inventory import, capacity reserve, lease start,
   release start, and capacity release.
6. Add provisioning callback endpoint(s) for usage/release events.
7. Add provisioning failure callback and seller failure policy hooks.
8. Add e2e coverage for a 4x pool:
   - initial listings: 1x, 2x, 3x, 4x open
   - settle 2x
   - listings: 1x and 2x open, 3x and 4x closed/unpublished
   - release lease
   - listings: 1x, 2x, 3x, 4x open again

## Fungible pool follow-up

To support two equivalent machines as one market-facing capacity pool, implement
the explicit `compute_inventory_pools` and `compute_pool_members` tables instead
of treating each `resources.resource_id` as its own pool.

Required changes:

1. Add `compute_inventory_pools` and `compute_pool_members` startup migrations.
2. Backfill one pool/member pair for each existing compute resource so current
   installations preserve behavior.
3. Add `pool_id` and `member_id` columns to `compute_allocations`; keep
   `resource_id` as the selected concrete resource/member correlation.
4. Change `derived_compute_listings` from `resource_id`-keyed derivation to
   `pool_id`-keyed derivation, with deterministic keys such as
   `pool:{pool_id}:gpus:{gpu_count}`.
5. Change listing offer payloads to carry `pool_id` for fungible listings and
   omit concrete `resource_id` unless the seller intentionally publishes a
   non-fungible resource listing.
6. Change reservation to resolve listing terms to a pool, then choose a concrete
   active member inside that pool according to the pool allocation policy.
7. Reconcile listings from aggregate pool availability, not per-resource
   availability, while only opening slice sizes that at least one active member
   can satisfy after its own held capacity is subtracted.
8. Add e2e coverage for two equivalent machines in one pool:
   - one set of 1x/2x/3x/4x listings is published for the pool
   - reserving 2x on one 4x member leaves 3x/4x listings open if another 4x
     member can satisfy them
   - reserving enough capacity across members closes only slices no remaining
     member can satisfy
   - release reopens affected pool listings

## Relationship to market core extraction

This subsystem lives in the compute instantiation, not in `market-core`.
The generic filing rule still applies: core owns the invariant
discover/negotiate/settle skeleton; compute owns GPU pool math, provider
routing, allocation, listing derivation, and provisioning callbacks.

If another resource domain later needs the same lifecycle shape, extract the
generic hook surface then. Until then, keep the implementation concrete.
