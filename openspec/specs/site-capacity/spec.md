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

Job-kind dispatch and deal-event routing across multiple storefront domains are not established by this capacity baseline; they remain proposed in `prove-multi-domain-capacity`.

## Capacity settlement lifecycle

A **Capacity Reservation** records accepted capacity, the agreement/deal relationship, requested shape or units, lifecycle state, and any hold expiry. A reservation is not itself a concrete provisioning decision.

A **Capacity Settlement Assignment** is the idempotent scheduling decision that maps one unchanged Capacity Reservation to one concrete pooled Settlement Resource. Retrying assignment for the same unchanged reservation returns the existing decision rather than rerunning scheduling policy. An assignment alone does not imply that physical settlement succeeded or that a workload is active.
