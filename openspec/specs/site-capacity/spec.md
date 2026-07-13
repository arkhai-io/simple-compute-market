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

<!-- Provenance: ARCHITECTURE.md “Capacity and the Site Authority”, API-credits domain capacity notes; evidence: kit/site ledger and core_storefront capacity/aggregation tests -->
