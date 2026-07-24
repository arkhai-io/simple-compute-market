## ADDED Requirements

### Requirement: Unambiguous capacity reservation identity

Cross-domain contracts and schemas MUST use `capacity_reservation_id` instead
of the ambiguous `allocation_id`. Capacity reservations, pools, physical
resources, fulfillments, and provisioned resources MUST use globally unique
opaque identifiers, while ownership remains explicit through `site_id` or an
equivalent authority field rather than being inferred by parsing identifiers.

Planning MUST review whether site-plus-pool composite identity is additionally
required for routing or integrity.

#### Scenario: Reservation routed to owning site
- **WHEN** the storefront invokes scheduling or fulfillment for a capacity
  reservation
- **THEN** it sends the request only to the provisioning authority that owns
  that reservation

#### Scenario: Another authenticated storefront presents the reservation ID
- **WHEN** a valid non-owning storefront credential attempts to schedule or mutate the reservation
- **THEN** the provisioning authority rejects the call without revealing reservation state

### Requirement: Scheduling requirements remain within reserved capacity

Scheduling requirements MAY be smaller than the admitted reservation but MUST
NOT exceed it in any governed dimension. Reservation admission and scheduling
eligibility MUST use the same shared feasibility predicate.

#### Scenario: Smaller scheduled shape
- **WHEN** a reservation contains more capacity than the requested scheduling
  shape
- **THEN** scheduling may select an eligible resource without increasing the
  reservation

#### Scenario: Scheduling exceeds reservation
- **WHEN** any requested scheduling dimension exceeds the capacity reservation
- **THEN** scheduling is rejected before resource assignment

### Requirement: Broad capacity schema cleanup

POOLS-7 MUST perform the approved breaking rename and schema cleanup,
including `SiteAllocation` to `CapacityReservation`, `allocation_id` to
`capacity_reservation_id`, explicit site ownership, globally unique
identifiers, and the final separation of host identity, pool membership,
reservable capacity, and settlement-resource assignment.

#### Scenario: Existing host migration
- **WHEN** the schema migration runs
- **THEN** every existing host is represented in the default resource pool
  before active fulfillment records are backfilled
