## MODIFIED Requirements

### Requirement: Storefront capacity-claim identity

VM compute listings MUST normalize surrounding whitespace and carry at least one valid `pool_id` or `resource_id`. Every supplied identity MUST begin with an alphanumeric character, contain only letters, digits, `.`, `_`, `:`, or `-`, and contain at most 128 characters. Where a reservation claim is constructed, a listing carrying `resource_id`, whether alone or with `pool_id`, produces a resource-specific claim and excludes `pool_id`. Ordinary pool-scoped claims MUST NOT require or select a `vm_host` or `resource_id`. Which listings construct a claim at all is stated below; carrying a valid identity is an invariant of every listing, including one no claim is ever constructed for.

Claim construction MUST reject a missing, empty, or malformed settlement order and any extracted claim lacking both identities before probing or reserving capacity. Stored listings that violate the identity invariant MUST fail closed on publication or republication. Resuming such a listing MUST return an actionable conflict before changing pause state or contacting a registry; the seller-authenticated close operation MUST remain available without implicit identity backfill or automatic unpublication.

Where capacity admission is requested for such a listing, a pool-only listing produces a pool-scoped reservation claim and a listing carrying Physical Resource identity produces a resource-scoped claim. A listing with no admission authority behind it constructs no reservation claim at all, so this construction does not apply to it; its identity requirements are unchanged.

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

#### Scenario: A listing with no admission authority is not reserved against

- **WHEN** capacity admission is attempted for a listing with no admission authority behind it
- **THEN** no reservation claim is constructed and the attempt is refused
