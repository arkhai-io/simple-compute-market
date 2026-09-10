## ADDED Requirements

### Requirement: The asking rate is declared at the listing's origin site

A listing's published asking rate MUST originate from a declaration on the
Resource Pool the listing derives from, carried in that pool's projected
domain-owned pricing policy metadata and read from the projection at publication.
The declaration MUST sit alongside the domain's per-capability pricing structure
rather than inside it: the asking rate prices the whole listing, so nesting it
under a capability family or an individual capability value would contradict what
it means.

A storefront-local per-pool override and a storefront-wide pricing default MAY
participate in resolution **only** for pools at the storefront's own home site.
Neither MUST reach a pool at another origin. A storefront may publish listings for
several seller sites, and a storefront-wide default reaching another origin's
listings would advertise the aggregator's price as that seller's asking price —
a false assertion about another party's commercial position rather than a degraded
result.

A pool with no declaration, and no default that applies to it, MUST publish no
asking rate. Its listings MUST publish normally and are absent from rate-bounded
discovery, which is the intended semantics rather than a failure.

A malformed or partial asking-rate declaration MUST fail its pool closed rather
than resolving to a lower tier or to no rate. An absent declaration and a
malformed one are different: falling through would either silently drop a price
the seller believes they advertised, or publish a storefront default in place of a
seller's broken declaration.

#### Scenario: A pool declares an asking rate

- **WHEN** publication reads a projected pool declaring a complete asking rate
- **THEN** each listing derived from that pool publishes it unchanged

#### Scenario: A remote origin declares no asking rate

- **WHEN** a storefront publishes for a pool at another origin that declares no
  asking rate, and the storefront configures a pricing default
- **THEN** the listing publishes with no asking rate
- **AND** the storefront's default is not applied to it

#### Scenario: The storefront's own pool declares no asking rate

- **WHEN** a pool at the storefront's own home site declares no asking rate and the
  storefront configures an applicable default or per-pool override
- **THEN** that value resolves for the listing

#### Scenario: A declaration is malformed

- **WHEN** a pool declares an asking rate that is malformed or missing one of its
  amount, asset, or period
- **THEN** that pool fails closed rather than publishing a lower-tier value or no
  rate

### Requirement: The asking rate is seller-stated and never derived from settlement

A storefront MUST NOT populate a listing's asking rate from a rate advertised in
that listing's settlement carriers, and MUST NOT write a published asking rate into
a settlement option, escrow term, or accepted obligation. The asking rate is
publication input the seller states.

Deriving it in either direction would make the field's provenance unreadable — a
buyer could not tell whether the seller asked for that number or the storefront
computed it — and it is undefinable for a listing advertising escrows in several
assets at several rates.

A storefront MAY derive the asking rate from a seller's negotiation-side rate
structure where the seller's declared policy says so, once such a structure exists.
That is a seller-chosen derivation from the seller's own declaration, not a
storefront reading a settlement carrier, and the structure does not replace,
subsume, or reinterpret the published asking rate.

#### Scenario: A listing advertises both an escrow rate and an asking rate

- **WHEN** publication builds a candidate for a listing whose pool declares an
  asking rate and whose settlement configuration advertises escrow rates
- **THEN** the published asking rate is the declared one
- **AND** it is not populated from, reconciled against, or written into any
  settlement carrier

#### Scenario: A rateless mechanism carries a declared asking rate

- **WHEN** a listing's only settlement option is under a mechanism declining scalar
  participation and its pool declares an asking rate
- **THEN** the candidate publishes the asking rate and the option remains rateless

### Requirement: An asking-rate change republishes the listing in place

Changing a pool's declared asking rate — its amount, asset, or period — MUST
republish the listings derived from that pool under their existing durable
identity. This is a published-shape change flowing from a source declaration, and
it reconciles through source publication rather than capacity availability.

Removing the declaration MUST republish those listings without an asking rate. Each
remains discoverable and becomes absent from rate-bounded queries.

A rate change MUST NOT close a listing and republish it under a new identity. Only
a backing change does that, and an asking rate is not backing.

#### Scenario: A seller changes a declared asking rate

- **WHEN** a pool's declared asking rate amount, asset, or period changes
- **THEN** each derived listing is republished carrying the new rate under its
  existing durable identity

#### Scenario: A seller removes a declared asking rate

- **WHEN** a pool's asking-rate declaration is removed
- **THEN** each derived listing is republished without one
- **AND** each remains discoverable while absent from rate-bounded queries
