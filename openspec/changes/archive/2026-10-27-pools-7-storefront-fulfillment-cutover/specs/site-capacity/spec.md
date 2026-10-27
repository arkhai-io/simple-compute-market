## ADDED Requirements

### Requirement: Unambiguous capacity reservation identity

Cross-domain contracts and schemas MUST use `capacity_reservation_id` instead
of the ambiguous `allocation_id`. Capacity reservations, pools, physical
resources, fulfillments, and provisioned resources MUST use globally unique
opaque identifiers, while ownership remains explicit through `site_id` or an
equivalent authority field rather than being inferred by parsing identifiers.

#### Scenario: Reservation routed to owning site
- **WHEN** the storefront invokes scheduling or fulfillment for a capacity
  reservation
- **THEN** it sends the request only to the provisioning authority that owns
  that reservation

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

### Requirement: Capacity schema separation

The site-capacity schema MUST name a reservation `CapacityReservation`,
keyed by `capacity_reservation_id`, with explicit site ownership and
globally unique identifiers. It MUST keep host identity, pool membership,
reservable capacity, and settlement-resource assignment separate.

#### Scenario: Existing host migration
- **WHEN** the schema migration runs
- **THEN** every existing host is represented in the default resource pool
  before active fulfillment records are backfilled
