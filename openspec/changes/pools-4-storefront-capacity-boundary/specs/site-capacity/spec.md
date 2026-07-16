## MODIFIED Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a
storefront MUST reach capacity only through the CapacityClient boundary,
MUST treat its own view as a projection, and MUST NOT require or select a
`vm_host` when building an ordinary reservation claim. A listing MUST
carry at least one of `pool_id` or `resource_id`; a `resource_id`-only
listing (no `pool_id`) is a specific-resource listing and its reservation
claim carries the explicit `resource_id`, while a listing published from a
multi-member pool carries `pool_id` and no `resource_id`. There is no
separate opt-in flag — which shape a listing's claim takes follows
directly from which identity the listing was published with.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

#### Scenario: Ordinary reservation omits a specific host
- **WHEN** a buyer reserves through a listing published from a multi-member resource pool
- **THEN** the reservation claim carries `pool_id` and capacity/shape attributes, and the storefront does not require or select a `vm_host` or `resource_id`

#### Scenario: Specific-resource listing reserves a named resource
- **WHEN** a buyer reserves through a listing whose `offer_resource` carries `resource_id` with no `pool_id`
- **THEN** the reservation claim carries the explicit `resource_id` and pool-scoped matching is not required

#### Scenario: Listing carries neither identity
- **WHEN** a compute listing is created with neither `pool_id` nor `resource_id` on its offer
- **THEN** the storefront rejects the listing creation rather than publishing a listing whose reservations cannot be reliably matched to inventory
