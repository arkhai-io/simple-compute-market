## ADDED Requirements

### Requirement: Delivery is available wherever the mechanism composes

Introduction delivery MUST be available in every domain that composes the
contact-exchange mechanism, not in one domain alone. A domain gaining the mechanism
MUST gain delivery through the same injected dispatch seam, sink discovery, and
configuration shape, and MUST NOT carry a domain-local delivery implementation.

Delivery MUST remain non-authoritative in every domain that gains it. That property
is what makes best-effort delivery safe: the durable, idempotently re-readable
reveal is what both parties can always fall back to. Re-delivery MUST read that
durable reveal rather than reconstructing one, so a re-send cannot invent contact
data that was never exchanged.

#### Scenario: A newly composing domain delivers

- **WHEN** a compute-family storefront composes the mechanism and configures a sink
- **THEN** revealed introductions in that domain reach the configured sink through
  the same dispatch seam bare metal uses
- **AND** the domain carries no delivery implementation of its own

#### Scenario: Re-delivery in a newly composing domain

- **WHEN** an operator re-delivers an already-revealed introduction in a newly
  composing domain
- **THEN** the sinks receive the material read from the durable reveal
- **AND** no contact data absent from that reveal is delivered

## MODIFIED Requirements

### Requirement: Delivery is local, self-addressed, and recipient-side

Each side of an introduction deal MUST deliver only to destinations configured by
that side's own operator, and MUST carry only the revealed material that side
already holds. The buyer's delivery MUST carry the seller's revealed contact
entries; the seller's delivery MUST carry the buyer's. Neither side MUST use a
counterparty-supplied contact entry as a delivery destination, and neither side
MUST deliver anything to the counterparty.

Where one storefront publishes listings originating at several seller sites,
seller-side destinations MUST resolve from the origin of the listing the deal was
negotiated against. The seller's delivery carries the buyer's contact entries, so
dispatching to another origin's destinations would disclose the buyer's personal
details to a seller who was not party to the deal. A storefront with one origin
MUST resolve to the destinations it configures today, and an origin with no
configured destinations MUST deliver nothing rather than fall back to another
origin's.

#### Scenario: Each side receives the counterparty's contact

- **WHEN** an introduction is revealed and both parties have configured sinks
- **THEN** the buyer's sinks receive the seller's contact entries and the seller's
  sinks receive the buyer's, each from its own process

#### Scenario: A counterparty address is not a destination

- **WHEN** a revealed contact payload contains an address that a configured sink
  could technically reach
- **THEN** delivery targets only the operator's configured destinations and never
  the counterparty's address

#### Scenario: Two origins publish through one storefront

- **WHEN** an introduction is revealed for a listing originating at one of several
  seller sites behind one storefront
- **THEN** the seller-side delivery reaches only that origin's configured
  destinations
- **AND** no other origin's destinations receive the buyer's contact entries

#### Scenario: An origin configures no destinations

- **WHEN** an introduction is revealed for a listing whose origin has no configured
  destinations
- **THEN** nothing is delivered seller-side and the reveal, its obligation, and the
  counterparty's request are unaffected
