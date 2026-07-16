## MODIFIED Requirements

### Requirement: Site-authoritative capacity
A site authority MUST own physical resource capacity and allocations; a
storefront MUST reach capacity only through the CapacityClient boundary,
MUST treat its own view as a projection, and MUST NOT require or select a
`vm_host` when building an ordinary reservation claim. A compute listing
MUST normalize and validate its capacity identities at model construction
and MUST carry at least one valid `pool_id` or `resource_id`. A valid
capacity identity starts with an alphanumeric character, contains only
letters, digits, `.`, `_`, `:`, or `-`, and is at most 128 characters. A
listing whose offer carries `resource_id` (whether or not `pool_id` is also present) is a
specific-resource listing, and its reservation claim carries the explicit
`resource_id` with `pool_id` excluded; a listing whose offer carries
`pool_id` with no `resource_id` is pool-scoped. There is no separate
opt-in flag — which shape a listing's claim takes follows directly from
which identity/identities the listing was published with, with
`resource_id` taking priority when both are present.

#### Scenario: Site authority is unavailable
- **WHEN** listing reconciliation cannot obtain an authoritative snapshot
- **THEN** it skips capacity-driven close/reopen actions rather than treating ignorance as zero capacity

#### Scenario: Ordinary reservation omits a specific host
- **WHEN** a buyer reserves through a listing published from a multi-member resource pool
- **THEN** the reservation claim carries `pool_id` and capacity/shape attributes, and the storefront does not require or select a `vm_host` or `resource_id`

#### Scenario: Specific-resource listing reserves a named resource
- **WHEN** a buyer reserves through a listing whose `offer_resource` carries `resource_id` with no `pool_id`
- **THEN** the reservation claim carries the explicit `resource_id` and pool-scoped matching is not required

#### Scenario: Listing carries both a pool and a specific resource
- **WHEN** a buyer reserves through a listing whose `offer_resource` carries both `pool_id` and `resource_id`
- **THEN** the reservation claim carries the explicit `resource_id` and `pool_id` is dropped from the claim, matching this listing as specific-resource rather than requiring both to match

#### Scenario: Listing carries neither identity
- **WHEN** a compute listing is created with neither `pool_id` nor `resource_id` on its offer
- **THEN** the storefront rejects the listing creation rather than publishing a listing whose reservations cannot be reliably matched to inventory

#### Scenario: Listing carries a blank or malformed identity
- **WHEN** a compute listing is created with an empty, whitespace-only, or malformed `pool_id` or `resource_id`
- **THEN** storefront listing-model validation rejects it before persistence or publication

#### Scenario: Settlement order is absent or malformed
- **WHEN** VM fulfillment receives no valid non-empty settlement order
- **THEN** fulfillment fails before probing or reserving capacity and does not convert the missing order into an unscoped claim

#### Scenario: Legacy-invalid listing is resumed
- **WHEN** an operator attempts to resume a stored compute listing that lacks a valid `pool_id` or `resource_id`
- **THEN** the storefront returns an actionable conflict before changing pause state or publishing to a registry

#### Scenario: Operator explicitly removes a legacy-invalid listing
- **WHEN** the operator invokes the seller-authenticated close operation after the validation conflict
- **THEN** the storefront permits the invalid listing to be closed and removed from active registry discovery without silently inventing a capacity identity
