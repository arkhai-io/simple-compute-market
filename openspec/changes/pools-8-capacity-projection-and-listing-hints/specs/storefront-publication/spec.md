## ADDED Requirements

### Requirement: Projection-to-commercial inventory mapping

A storefront MUST explicitly map provisioning-owned projected site, pool, and optional resource identity to storefront-owned commercial publication state. Projection refresh MAY update physical facts and close unsupported derived listings, but MUST NOT overwrite pricing, settlement policy, agreement history, or other seller-owned state.

#### Scenario: Projected resource disappears

- **WHEN** a complete authoritative generation no longer contains the physical identity supporting an open derived listing
- **THEN** reconciliation closes or suppresses that listing while retaining its commercial and agreement history

#### Scenario: Projection mapping is ambiguous

- **WHEN** a projected identity cannot be mapped unambiguously to commercial inventory
- **THEN** the storefront quarantines or reports it and does not publish or construct a claim from guessed identity

### Requirement: Projection-owned claim identity

Listings derived from a projection MUST retain an internal trusted mapping to the producing site and projected pool/resource identity. Reservation claim construction MUST use that mapping and route directly to the producing authority rather than broadcasting a pinned state-changing request.

#### Scenario: Buyer accepts a projected listing

- **WHEN** the storefront constructs a Capacity Reservation claim for a listing mapped to one site
- **THEN** it uses the projected pool/resource identity and sends the claim only through that site's trusted binding

### Requirement: Domain-owned publication and hold hints

A storefront domain MAY interpret projected `listing_mode` and `max_reservation_hold_seconds` policy tags. Each domain MUST own accepted listing-mode values and fallback behavior; unknown values MUST NOT change admission authority. A cooperating storefront MUST treat the hold value as an advisory upper bound on its requested reservation TTL.

#### Scenario: Listing mode is absent or invalid

- **WHEN** a projected pool omits `listing_mode` or supplies a value unsupported by the selected domain
- **THEN** publication uses the domain's structural default and exposes an operator-visible explanation without failing projection ingestion

#### Scenario: Hold preference is shorter than storefront policy

- **WHEN** a valid positive `max_reservation_hold_seconds` is lower than the storefront's configured acceptance-hold TTL
- **THEN** the storefront requests no more than the projected preference while live site admission remains authoritative
