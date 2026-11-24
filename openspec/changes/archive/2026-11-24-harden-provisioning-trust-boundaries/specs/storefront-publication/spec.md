## ADDED Requirements

### Requirement: A storefront never authorizes its administrator as a party

A storefront — VM, bare metal, or API credits — MUST refuse a request signed under the `admin` role on every route whose authorization binds the caller to a deal as a party: a buyer's negotiation, settlement, heartbeat and delivery routes, a route the storefront's own seller principal calls as counterparty, and a service peer's callback. Its administrator MUST act on a negotiation or deal only through administrator operations, which record it as the administrator. Every storefront MUST serve a listing's negotiation list and a negotiation's detail, `GET /api/v1/listings/{listing_id}/negotiations` and `GET /api/v1/listings/{listing_id}/negotiations/{neg_id}`, to its administrator alone, through the signed request and response its other administrator routes use, and MUST refuse an unsigned request to either. A storefront's own records of its deals, such as bare-metal lease-ready evidence, MAY admit its administrator as a reader.

#### Scenario: The administrator opens a negotiation as a buyer

- **WHEN** a request signed under the `admin` role by an active administrator principal calls a storefront's negotiation-opening route
- **THEN** it is refused, and no negotiation is opened

#### Scenario: The administrator advances a negotiation

- **WHEN** the administrator advances a negotiation through the advance route
- **THEN** the round is recorded as the administrator's, not the buyer's

#### Scenario: The API-credits storefront's negotiations are read unsigned

- **WHEN** a caller requests the API-credits storefront's negotiation list or a negotiation's detail without the administrator's signature
- **THEN** the request is refused as unauthenticated and nothing is returned

#### Scenario: The administrator reads a listing's negotiations

- **WHEN** the administrator reads a listing's negotiations on any storefront through the canonical storefront client
- **THEN** the signed response lists them
