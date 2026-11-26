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

### Requirement: A storefront never authorizes its administrator as a party

A storefront — VM, bare metal, API credits, or inference — MUST refuse a request signed under the `admin` role on every route whose authorization binds the caller to a deal as a party: a buyer's negotiation, settlement, heartbeat and delivery routes, a route the storefront's own seller principal calls as counterparty, and a service peer's callback. Its administrator MUST act on a negotiation or deal only through administrator operations, which record it as the administrator. Every storefront MUST serve a listing's negotiation list and a negotiation's detail, `GET /api/v1/listings/{listing_id}/negotiations` and `GET /api/v1/listings/{listing_id}/negotiations/{neg_id}`, to its administrator alone, through the signed request and response its other administrator routes use, and MUST refuse an unsigned request to either. A storefront's own records of its deals, such as bare-metal lease-ready evidence, MAY admit its administrator as a reader.

#### Scenario: The administrator opens a negotiation as a buyer

- **WHEN** a request signed under the `admin` role by an active administrator principal calls a storefront's negotiation-opening route
- **THEN** it is refused, and no negotiation is opened

#### Scenario: The administrator advances a negotiation

- **WHEN** the administrator advances a negotiation through the advance route
- **THEN** the round is recorded as the administrator's, not the buyer's

#### Scenario: The API-credits storefront's negotiations are read unsigned

- **WHEN** a caller requests the API-credits storefront's negotiation list or a negotiation's detail without the administrator's signature
- **THEN** the request is refused as unauthenticated and nothing is returned

#### Scenario: The inference storefront's negotiations are read unsigned

- **WHEN** a caller requests the inference storefront's negotiation list or a negotiation's detail without the administrator's signature
- **THEN** the request is refused as unauthenticated and nothing is returned

#### Scenario: The administrator reads a listing's negotiations

- **WHEN** the administrator reads a listing's negotiations on any storefront through the canonical storefront client
- **THEN** the signed response lists them
