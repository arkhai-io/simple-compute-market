# Site Capacity Specification

## Purpose

Define authoritative site ledgers, storefront capacity projections, reservations, aggregation, and event delivery.

## Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a storefront MUST reach capacity only through the CapacityClient boundary and MUST treat its own view as a projection.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

### Requirement: Reservation lifecycle
Capacity reservation MUST use a hold/commit/release lifecycle keyed by durable allocation identity, support expiry of uncommitted holds, and be idempotent for retries.

#### Scenario: Two buyers reserve the same final unit
- **WHEN** concurrent requests race at one site
- **THEN** the authoritative ledger commits at most one reservation

### Requirement: Multi-site aggregation
A storefront MAY aggregate multiple site clients as soft state but MUST route each reserve to one authority and MUST NOT create cross-site hard-state capacity of its own.

#### Scenario: One site cannot satisfy a request
- **WHEN** another configured site can satisfy it
- **THEN** the aggregator may reserve at the eligible site and records which site owns the allocation

### Requirement: Capacity and deal events
Site authorities MUST publish anonymous versioned capacity deltas for projection subscribers and MUST route deal-scoped execution events to the owning storefront.

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

#### Scenario: Administrative pool is created before settlement integration
- **WHEN** an operator creates or assigns hosts to a provisioning resource pool during POOLS-1
- **THEN** existing site-capacity reservation and allocation selection behavior remains unchanged

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

## Evidence

- Reserve/commit/release, hold TTL, versioned anonymous events, and cross-mode conflicts: `kit/site/tests/unit/test_ledger.py`.
- Multidimensional capacity (declared-dimension fit, concurrent per-dimension holds, legacy-claim compatibility, per-dimension event deltas): `kit/site/tests/unit/test_ledger.py` (POOLS-6 pass 1 tests).
- Site-tagged soft-state aggregation and failure isolation: `core/storefront/tests/unit/test_aggregation.py`.
- Storefront-to-site HTTP contract: `domains/vms/storefront/tests/unit/test_remote_capacity_client.py`.
- “Do not close on ignorance” reconciliation: `domains/vms/storefront/tests/unit/test_cli_publish_helpers.py`.
- Shared feasibility predicate: `kit/site/tests/unit/test_resource_satisfies_requirement.py`.
- Session-scoped settlement assignment, locked reservation reads, and in-session backing-resource lookup: `kit/site/tests/unit/test_settlement_assignment.py`.

Job-kind dispatch and deal-event routing across multiple storefront domains are not established by this capacity baseline; they remain proposed in `prove-multi-domain-capacity`.

## Capacity settlement lifecycle

A **Capacity Reservation** records accepted capacity, the agreement/deal relationship, requested shape or units, lifecycle state, and any hold expiry. A reservation is not itself a concrete provisioning decision.

A **Capacity Settlement Assignment** is the idempotent scheduling decision that maps one unchanged Capacity Reservation to one concrete pooled Settlement Resource. Retrying assignment for the same unchanged reservation returns the existing decision rather than rerunning scheduling policy. An assignment alone does not imply that physical settlement succeeded or that a workload is active.

## Relationship to fulfillment scheduling

The site authority admits and persists capacity reservations. The higher-layer [fulfillment capability](../fulfillment/spec.md) binds an admitted reservation to a Settlement Resource and records that assignment through the site boundary before provider dispatch.

A reservation is scoped to the one provisioning authority (database) that admitted it; scheduling does not fall back to another site after admission. Cross-site ranking and any durable record of which site owns what is storefront aggregation policy applied before reservation — not a field this database carries, since one provisioning-service deployment is one site and every row in it already implicitly belongs to that site. Type-only imports from the site authority into fulfillment are prohibited because they would invert the kit dependency hierarchy.

`market_site` exports `resource_satisfies_requirement(resource_kind, available, attributes, required_resource_kind, required_dimensions, required_attributes) -> bool`, the one feasibility check both reservation-time admission and fulfillment's scheduling-time eligibility evaluate against. `required_resource_kind=None` accepts any resource kind, matching reservation admission's claim, where a resource-kind constraint is optional; scheduling always supplies a concrete one.

`CapacityLedgerService` exposes session-accepting entry points (`lock_reservation`, `assign_settlement_resource_in_session`, `backing_resource_id_in_session`) alongside its self-managed-transaction public methods (`get_reservation`, `assign_settlement_resource`, `get_reservation_backing_resource_id`), so a higher-layer caller composing one transaction across reservation state and another authority's write — for example, fulfillment scheduling's settlement assignment — can open one session, drive both, and commit once. `market_site` remains unaware of what that other write is; the composition happens at the caller, which is why these are the only surface fulfillment scheduling needs from this package to keep the rebind and the settlement assignment atomic.

### Requirement: Site identity ownership boundary
Provisioning-owned site-capacity persistence MUST NOT redundantly store storefront-owned `site_id` on pools, resources, or reservations. The storefront aggregation boundary assigns the trusted site identity associated with a configured provisioning connection. A remote counterparty MUST NOT self-assert that identity in capacity payloads.

#### Scenario: Capacity payload attempts to assert site identity
- **WHEN** a provisioning endpoint returns or accepts a payload containing a caller-selected `site_id`
- **THEN** the storefront ignores that assertion and uses the identity bound to the configured connection
- **AND** provisioning capacity rows remain scoped by the local database authority rather than a redundant site column


## Internal capacity accounting

A storefront-facing capacity reservation identifies the durable hold by `capacity_reservation_id` and exposes lifecycle metadata, expiry, and reserved dimensions. It does not expose the provisioning authority's initial accounting choice.

Within the site authority, a `CapacityBucket` is the host-level multidimensional accounting boundary. For the VM domain there is one current bucket per host. `backing_resource_id` links the bucket to its physical inventory record, while `CapacityReservationDebit` records the reservation's current bucket and debited dimensions. Scheduling may atomically replace that debit when it rebinds a reservation to another eligible host and then records `settlement_resource_id`.

## Storefront projection families

The site authority publishes two independent pull projections:

- `site_resource_pools` preserves resource-pool membership and the allowlisted per-resource inventory facts needed for individual-resource listings.
- `site_capacity_buckets` vertically groups resources with identical canonical grouping criteria and currently available dimensions. Each group exposes a deterministic digest-derived `capacity_group_key` and `resource_count`, but no internal capacity-bucket identifiers or duplicated physical-resource identifier list.

Each projection family has its own monotonic revision and canonical snapshot digest. Storefront caches replace complete generations atomically and retain the last complete generation when a refresh fails; unavailable projection state is distinct from an authoritative empty projection.

### Requirement: Capacity accounting is private to the site authority
The site authority SHALL account reservable capacity with `CapacityBucket` rows and SHALL store each active reservation's current backing in `CapacityReservationDebit`. A storefront-facing capacity reservation SHALL NOT expose a bucket identifier or backing physical-resource identifier. Scheduling MAY atomically replace the current debit when it selects a different eligible bucket.

### Requirement: Physical inventory and grouped capacity are separate projections
A site authority SHALL expose `site_resource_pools` from authoritative domain inventory and `site_capacity_buckets` from current bucket availability. Each projection SHALL have an independent monotonic revision and canonical digest. Grouped capacity SHALL contain deterministic grouping criteria and `resource_count`, SHALL NOT contain physical-resource identifiers, and SHALL NOT be used as an allocation target.
