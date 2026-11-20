## MODIFIED Requirements

### Requirement: Reconciliation reads every listing once

The core storefront's listing pages MUST be ordered by `created_at` and, among
listings created at one instant, by the order they were first written, newest
first; no write changes either. They MUST accept a keyset cursor, the last row's
`(created_at, listing_id)`, from which the next page continues. A reconciliation pass
that pages through listings MUST page by that cursor rather than by offset, so that a
listing it closes, reopens, or publishes during the pass neither shifts another listing
out of the pass nor brings one into it twice.

#### Scenario: A reconciliation pass writes while it pages

- **WHEN** a reconciliation pass pages through listings by the keyset cursor and changes listings on an earlier page, or publishes a new listing, before reading the next page
- **THEN** every listing that existed when the pass began is visited exactly once

#### Scenario: Listings created at one instant are paged

- **WHEN** several listings share one `created_at`, as every listing written between two settings of injected time does, and are read in pages smaller than their number
- **THEN** each is returned exactly once, the last written first
