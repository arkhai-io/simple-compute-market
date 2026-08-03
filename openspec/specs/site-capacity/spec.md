# Site Capacity Specification

## Purpose

Define authoritative site ledgers, storefront capacity projections, reservations, aggregation, and event delivery.

## Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a storefront MUST reach capacity only through the CapacityClient boundary and MUST treat its own view as a projection.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

### Requirement: Storefront capacity-claim identity
VM compute listings MUST normalize surrounding whitespace and carry at least one valid `pool_id` or `resource_id`. Every supplied identity MUST begin with an alphanumeric character, contain only letters, digits, `.`, `_`, `:`, or `-`, and contain at most 128 characters. A pool-only listing produces a pool-scoped reservation claim. A listing carrying `resource_id`, whether alone or with `pool_id`, produces a resource-specific claim and excludes `pool_id`. Ordinary pool-scoped claims MUST NOT require or select a `vm_host` or `resource_id`.

Claim construction MUST reject a missing, empty, or malformed settlement order and any extracted claim lacking both identities before probing or reserving capacity. Stored listings that violate the identity invariant MUST fail closed on publication or republication. Resuming such a listing MUST return an actionable conflict before changing pause state or contacting a registry; the seller-authenticated close operation MUST remain available without implicit identity backfill or automatic unpublication.

#### Scenario: Pool-only listing creates an ordinary reservation
- **WHEN** a buyer reserves through a listing carrying `pool_id` without `resource_id`
- **THEN** the claim carries `pool_id` and capacity/shape attributes without requiring or selecting a specific host or resource

#### Scenario: Resource-only listing creates a specific reservation
- **WHEN** a buyer reserves through a listing carrying `resource_id` without `pool_id`
- **THEN** the claim carries the explicit `resource_id` and does not require pool-scoped matching

#### Scenario: Listing carries both capacity identities
- **WHEN** a listing carries both `pool_id` and `resource_id`
- **THEN** the claim carries `resource_id` and drops `pool_id`

#### Scenario: Listing carries neither capacity identity
- **WHEN** a compute listing is created without `pool_id` or `resource_id`
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Listing carries a malformed capacity identity
- **WHEN** a supplied identity is empty, whitespace-only, malformed, or too long
- **THEN** model validation rejects it before persistence or publication

#### Scenario: Settlement order is absent or malformed
- **WHEN** VM fulfillment receives no valid non-empty settlement order
- **THEN** fulfillment fails before probing or reserving capacity rather than constructing an unscoped claim

#### Scenario: Legacy-invalid listing is resumed
- **WHEN** an operator resumes a stored listing that lacks a valid capacity identity
- **THEN** the storefront returns an actionable conflict without changing pause state or contacting a registry

#### Scenario: Legacy-invalid listing is explicitly closed
- **WHEN** the operator invokes the seller-authenticated close operation after the validation conflict
- **THEN** the storefront removes it from active registry discovery without inventing a capacity identity

### Requirement: Reservation scheduling view
A capacity reservation MUST expose its identity, lifecycle state, hold expiry, reserved dimensions, resource kind, and generic scheduling constraints through the site-authority boundary. Scheduling MUST reject a missing or expired reservation and any request that conflicts with the reservation's generic physical requirements. Commercial agreement identity and terms remain at the storefront and MUST NOT be required by generic scheduling.

#### Scenario: Reservation is missing
- **WHEN** scheduling references a `capacity_reservation_id` that the site authority does not know
- **THEN** scheduling reports a missing-reservation error before policy selection

#### Scenario: Reservation hold expired
- **WHEN** scheduling references an uncommitted hold whose expiry has passed
- **THEN** scheduling reports reservation expiry before policy selection

#### Scenario: Request exceeds reserved dimensions
- **WHEN** a scheduling request asks for more of a dimension than the reservation holds
- **THEN** scheduling reports a request mismatch before assignment or provider execution

### Requirement: Reservation lifecycle
Capacity reservation MUST use a hold/commit/release lifecycle keyed by durable allocation identity, support expiry of uncommitted holds, and be idempotent for retries.

`reserve()` itself is idempotent by `deal_ref`'s `escrow_uid` when present: a repeat call for an escrow_uid with an existing reservation in any held state (`reserved`, `provisioning`, `leased`, `releasing`, `release_failed`, `unmanaged`) returns that reservation rather than admitting a second one. This closes the retry gap `commit`/`release` already closed for their own calls: a caller retrying `reserve()` itself after a crash — before it durably recorded the first reservation's identity elsewhere — does not double-reserve capacity for the same deal. An escrow_uid whose prior reservation already expired or was released is not matched (it has moved out of the held states), so a genuinely new attempt after expiry still admits fresh.

#### Scenario: Two buyers reserve the same final unit
- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

#### Scenario: Reserve is retried for the same deal before its identity is durably recorded elsewhere
- **WHEN** `reserve()` is called again with the same `deal_ref.escrow_uid` while the first reservation is still in a held state
- **THEN** the existing reservation is returned and no additional capacity is admitted

#### Scenario: Reserve is retried after the prior hold expired
- **WHEN** `reserve()` is called again with an `escrow_uid` whose only prior reservation has already expired or been released
- **THEN** a new reservation is admitted, exactly as if no prior attempt had occurred

### Requirement: Multi-site aggregation
A storefront MAY aggregate multiple site clients as soft state but MUST route each reserve to one authority and MUST NOT create cross-site hard-state capacity of its own.

#### Scenario: One site cannot satisfy a request
- **WHEN** another configured site can satisfy it
- **THEN** the aggregator may reserve at the eligible site and records which site owns the allocation

### Requirement: Capacity and deal events
Site authorities MUST publish anonymous versioned capacity deltas for projection subscribers and MUST route deal-scoped execution events to the owning storefront. Capacity deltas for multidimensional resources MUST report the per-dimension availability change so consumers do not infer one dimension from another.

#### Scenario: Capacity is released
- **WHEN** an allocation release commits in the site ledger
- **THEN** subscribers can observe a capacity version advance and reconcile listings idempotently

### Requirement: Cross-mode physical accounting
Shareable VM slices and exclusive bare-metal allocations referring to the same physical host MUST conflict according to allocation mode before executor work starts.

#### Scenario: VM slice is held
- **WHEN** an exclusive bare-metal reservation targets the same physical host
- **THEN** the site ledger rejects the exclusive reservation

### Requirement: Multidimensional capacity accounting
A site resource MAY declare total capacity across more than one named quantity dimension (for example `gpu_count`, `vcpu_count`, `ram_gb`, `disk_gb`); a claim's requested quantities MUST be checked and held against every declared dimension, not only a single default quantity, with held/available accounting kept exact under concurrent holds. A dimension a resource does not declare MUST NOT be assumed to have room. This accounting is per resource row: it does not aggregate or cross-check declared or held capacity across multiple resource rows that happen to share a physical host (see "Cross-mode physical accounting" above for the one cross-row check that does exist, which is scoped to exclusive/shareable mode conflicts, not capacity sums).

#### Scenario: A reservation would exceed a secondary dimension
- **WHEN** a claim requests more of a declared dimension (for example memory) than the resource has available, even though another dimension (for example GPU count) would fit
- **THEN** the reservation is rejected rather than admitted for a shape the resource cannot serve

#### Scenario: Concurrent holds accumulate per dimension
- **WHEN** two separate holds are placed on one shareable resource
- **THEN** each declared dimension's available quantity reflects the sum of both holds, not just the dimension the first hold happened to request

#### Scenario: Legacy single-quantity claims are unaffected
- **WHEN** a claim requests a quantity using the legacy `units`/`gpu_count` key instead of a dimensions map
- **THEN** it is checked and held exactly as it was before multidimensional capacity existed, translated internally to the primary dimension

### Requirement: Executor-neutral site authority
The site authority MUST own Physical Resources, settlement-relevant Resource Pool identities, Capacity Reservations, committed allocations, deal ownership references, capacity versions, and capacity events without depending on lease watchdogs, job runners, or concrete executor teardown states. A provisioner MAY stage administrative pool membership and provider configuration, but those records MUST NOT alter settlement selection until integrated through the site-authority boundary.

#### Scenario: Allocation is committed
- **WHEN** a valid Capacity Reservation is committed for executor work
- **THEN** the site authority records its allocation identity, physical accounting mode, executor kind, and deal ownership while leaving execution policy to the compute lifecycle

#### Scenario: Generic site package is installed alone
- **WHEN** site authority modules are imported without VM or bare-metal provisioning packages
- **THEN** resource, reservation, allocation, and event behavior remains available without concrete executor imports

### Requirement: Idempotent release recording
The site authority MUST record release exactly once for an allocation and advance capacity version only when the authoritative allocation transition commits.

#### Scenario: Release command is repeated
- **WHEN** the compute lifecycle repeats a successful release command with the same allocation identity
- **THEN** the site authority returns the released state without duplicating capacity or event transitions

### Requirement: Separate capacity and deal event semantics
Capacity projection events MUST remain anonymous and versioned, while deal-scoped lifecycle events MUST retain the owning deal/storefront reference recorded on the allocation.

#### Scenario: Allocation changes capacity and deal state
- **WHEN** an executor lifecycle transition releases an allocation
- **THEN** projection subscribers can reconcile from the capacity version and the owning storefront can correlate its deal event without either channel exposing the other's private payload

**Evidence**

- Reserve/commit/release, hold TTL, versioned anonymous events, and cross-mode conflicts: `kit/site/tests/unit/test_ledger.py`.
- Multidimensional capacity, including declared-dimension fit, concurrent per-dimension holds, legacy-claim compatibility, and per-dimension event deltas: `kit/site/tests/unit/test_ledger.py`.
- Site-tagged soft-state aggregation and failure isolation: `core/storefront/tests/unit/test_aggregation.py`.
- Storefront-to-site HTTP contract: `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`.
- “Do not close on ignorance” reconciliation: `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py`.
- Shared feasibility predicate: `kit/site/tests/unit/test_resource_satisfies_requirement.py`.
- Session-scoped settlement assignment, locked reservation reads, and in-session backing-resource lookup: `kit/site/tests/unit/test_settlement_assignment.py`.
- Reservation supersede (`resize_reservation`) and unconditional settlement-abandonment hook invocation across TTL lapse, release, and resize: `kit/site/tests/unit/test_ledger.py`.
- Listing identity normalization and validation: `domains/vms/storefront/tests/unit/test_listing_model_capacity_identity.py`.
- Claim identity precedence and fail-closed construction: `domains/vms/storefront/tests/unit/test_two_phase_reserve.py`, `domains/vms/storefront/tests/unit/test_vm_fulfillment_planner.py`, and `domains/vms/storefront/tests/unit/test_fulfill_vm_obligation_error_handling.py`.
- Listing publication and legacy-invalid remediation: `domains/vms/storefront/tests/integration/test_listings_api.py`.
- Per-site/family projection load-state reporting, including partial multi-site failure isolation, never-loaded retry, and `fetched_at` tracking: `core/storefront/tests/unit/test_site_projections.py`, `domains/vms/storefront/tests/unit/services/test_site_projection_cache.py`, and `domains/vms/storefront/tests/unit/services/test_system_service.py`.
- The real HTTP contract (`HealthResponse` server model through the actual `/api/v1/system/status` route to the real `StorefrontClient`) surfacing this state intact: `domains/vms/storefront/tests/integration/test_admin_api.py`.

Job-kind dispatch and deal-event routing across multiple storefront domains are not established by this capacity baseline.

**Capacity settlement lifecycle**

A **Capacity Reservation** records accepted capacity, the agreement/deal relationship, requested shape or units, lifecycle state, and any hold expiry. A reservation is not itself a concrete provisioning decision.

A **Capacity Settlement Assignment** is the idempotent scheduling decision that maps one unchanged Capacity Reservation to one concrete pooled Settlement Resource. Retrying assignment for the same unchanged reservation returns the existing decision rather than rerunning scheduling policy. An assignment alone does not imply that physical settlement succeeded or that a workload is active.

**Relationship to fulfillment scheduling**

The site authority admits and persists capacity reservations. The higher-layer [fulfillment capability](../fulfillment/spec.md) binds an admitted reservation to a Settlement Resource and records that assignment through the site boundary before provider dispatch.

A reservation is scoped to the one provisioning authority (database) that admitted it; scheduling does not fall back to another site after admission. Cross-site ranking and any durable record of which site owns what is storefront aggregation policy applied before reservation — not a field this database carries, since one provisioning-service deployment is one site and every row in it already implicitly belongs to that site. Type-only imports from the site authority into fulfillment are prohibited because they would invert the kit dependency hierarchy.

`market_site` exports `resource_satisfies_requirement(resource_kind, available, attributes, required_resource_kind, required_dimensions, required_attributes) -> bool`, the one feasibility check both reservation-time admission and fulfillment's scheduling-time eligibility evaluate against. `required_resource_kind=None` accepts any resource kind, matching reservation admission's claim, where a resource-kind constraint is optional; scheduling always supplies a concrete one.

`CapacityLedgerService` exposes session-accepting entry points (`lock_reservation`, `assign_settlement_resource_in_session`, `backing_resource_id_in_session`, `iter_scheduling_candidates_in_session`) alongside its self-managed-transaction public methods (`get_reservation`, `assign_settlement_resource`, `get_reservation_backing_resource_id`, `reservation_payload_in_session`), so a higher-layer caller composing one transaction across reservation state and another authority's write — for example, fulfillment scheduling's settlement assignment — can open one session, drive both, and commit once. `market_site` remains unaware of what that other write is; the composition happens at the caller, which is why these are the only surface fulfillment scheduling needs from this package to keep the rebind and the settlement assignment atomic.

### Requirement: Reservation supersede and settlement abandonment

A negotiated shape change to an already-reserved capacity hold MUST NOT mutate the existing `CapacityReservation` or any settlement assignment already bound to it in place. `CapacityLedgerService.resize_reservation` supersedes it instead: one atomic transaction releases the old reservation, evaluates the new shape's candidacy as if the old hold had already cleared, reserves the new shape under a new `capacity_reservation_id`, and commits or rolls back all of it together. A new shape with no eligible candidate leaves the old reservation exactly as it was — still held, never released — rather than losing it. `resize_reservation` is a single self-managed-session method; it is not composed into a larger caller transaction.

The site authority reclaims capacity from a reservation in exactly three internal paths: a lapsed TTL hold, a terminal release, and a resize's supersede step. Each of these unconditionally invokes an optional `SettlementAbandonmentHook`, a `Protocol` this package defines without referencing fulfillment types, in the same transaction as the reclaim. `market_site` MUST NOT import `market_fulfillment` to implement this hook, including under `TYPE_CHECKING`; the concrete implementation is supplied by the fulfillment capability at composition time and alone decides whether there is a not-yet-dispatched settlement assignment to mark abandoned. The site authority calls the hook regardless of whether one exists for the reservation in question.

#### Scenario: Resize evaluates the new shape as if the old hold already cleared

- **WHEN** a reservation is resized to a new shape that only fits once the old reservation's own held capacity is released
- **THEN** the resize succeeds, because release and re-evaluation happen inside the same transaction rather than as two independently committed steps

#### Scenario: Resize rolls back when the new shape is unavailable

- **WHEN** no candidate satisfies the new shape
- **THEN** the whole transaction rolls back and the old reservation remains held, unmodified, with no abandonment hook invoked

#### Scenario: Capacity reclaim always offers the abandonment hook a chance to react

- **WHEN** a TTL hold lapses, a reservation is released, or a resize supersedes a reservation
- **THEN** the configured `SettlementAbandonmentHook`, if any, is called for the affected `capacity_reservation_id` regardless of whether a settlement assignment exists for it

### Requirement: Site identity ownership boundary
Provisioning-owned site-capacity persistence MUST NOT redundantly store storefront-owned `site_id` on pools, resources, or reservations. The storefront aggregation boundary assigns the trusted site identity associated with a configured provisioning connection. A remote counterparty MUST NOT self-assert that identity in capacity payloads.

#### Scenario: Capacity payload attempts to assert site identity
- **WHEN** a provisioning endpoint returns or accepts a payload containing a caller-selected `site_id`
- **THEN** the storefront ignores that assertion and uses the identity bound to the configured connection
- **AND** provisioning capacity rows remain scoped by the local database authority rather than a redundant site column


**Internal capacity accounting**

A storefront-facing capacity reservation identifies the durable hold by `capacity_reservation_id` and exposes lifecycle metadata, expiry, and reserved dimensions. It does not expose the provisioning authority's initial accounting choice.

Within the site authority, a `CapacityBucket` is the host-level multidimensional accounting boundary. For the VM domain there is one current bucket per host. `backing_resource_id` links the bucket to its physical inventory record, while `CapacityReservationDebit` records the reservation's current bucket and debited dimensions. Scheduling may atomically replace that debit when it rebinds a reservation to another eligible host and then records `settlement_resource_id`.

**Storefront projection families**

The site authority publishes two independent pull projections:

- `site_resource_pools` preserves resource-pool membership and the allowlisted per-resource inventory facts needed for individual-resource listings.
- `site_capacity_buckets` vertically groups resources with identical canonical grouping criteria and currently available dimensions. Each group exposes a deterministic digest-derived `capacity_group_key` and `resource_count`, but no internal capacity-bucket identifiers or duplicated physical-resource identifier list.

Each projection family has its own monotonic revision and canonical snapshot digest. Storefront caches replace complete generations atomically and retain the last complete generation when a refresh fails; unavailable projection state is distinct from an authoritative empty projection.

### Requirement: Per-site projection load-state visibility
A storefront MUST report, per configured site and per independent projection family (resource-pool, capacity-bucket), whether that projection has never loaded, is currently loaded, is stale, or is unavailable. This state MUST be visible on the storefront's operator status surface, scoped per site and family — one site's load failure MUST NOT present as broad storefront degradation while other configured sites are healthy. A storefront MUST NOT persist projection generations durably across restart; retry-until-success plus this observable status is the accepted mechanism for a site being unreachable at storefront startup. Any future reader of these caches MUST treat a never-loaded or unavailable state as unknown, not as authoritative zero capacity — the same principle "Site authority is unavailable" already states for the legacy reconciliation path applies equally here.

#### Scenario: A configured site is unreachable at storefront startup
- **WHEN** the storefront starts and one configured site's projection load has not yet succeeded
- **THEN** operator status reports that site/family as not-yet-loaded rather than presenting an empty projection as authoritative, and the storefront continues retrying without blocking readiness for other configured sites

#### Scenario: One projection family fails to refresh after a successful load
- **WHEN** a resource-pool refresh fails while the capacity-bucket family advances
- **THEN** the storefront retains the previous resource-pool generation in memory as stale, reports that state on the status surface, and commits the capacity-bucket replacement independently

### Requirement: Capacity accounting is private to the site authority
The site authority SHALL account reservable capacity with `CapacityBucket` rows and SHALL store each active reservation's current backing in `CapacityReservationDebit`. A storefront-facing capacity reservation SHALL NOT expose a bucket identifier or backing physical-resource identifier. This extends to domain-specific physical-placement fields carried on the reservation (for example the VM domain's `vm_host`), not only the site authority's own generic accounting identifiers -- any field that identifies which concrete physical resource is serving a reservation is a backing physical-resource identifier for the purposes of this requirement, regardless of which domain named it. Scheduling MAY atomically replace the current debit when it selects a different eligible bucket.

#### Scenario: Storefront reads a capacity reservation
- **WHEN** a storefront reads an admitted reservation
- **THEN** it receives lifecycle state and reserved dimensions without private bucket or backing-resource identity

### Requirement: Physical inventory and grouped capacity are separate projections
A site authority SHALL expose `site_resource_pools` from authoritative domain inventory and `site_capacity_buckets` from current bucket availability. Each projection SHALL have an independent monotonic revision and canonical digest. Grouped capacity SHALL contain deterministic grouping criteria and `resource_count`, SHALL NOT contain physical-resource identifiers, and SHALL NOT be used as an allocation target.

#### Scenario: Storefront refreshes grouped capacity
- **WHEN** the capacity-bucket projection revision changes
- **THEN** the storefront can replace that projection independently without receiving physical-resource identifiers or using a group as an allocation target

### Requirement: Committed dimensions remain authoritative through scheduling

Scheduling MUST NOT admit a dimension shape exceeding what the capacity reservation declares. Within that bound, a scheduling request MAY be narrower than the reservation — reflecting, for example, a negotiated shape change not yet expressed as a reservation resize, or a placement/pricing check against a candidate shape. The dimensions actually scheduled — not the reservation's own dimensions unconditionally — are the authoritative admitted resource shape carried with the selected settlement resource, so the domain fulfillment provider can interpret them without the caller retransmitting an independently computed shape. A negotiated shape change that is meant to persist resizes the reservation itself (supersede, never mutate) rather than relying on an implicit narrower scheduling request to represent it.
