## ADDED Requirements

### Requirement: Shape-resolvable commercial rates

Commercial resolution MUST produce a rate structure that yields a price for any
admissible capacity shape, rather than a single price bound to one shape. Each priced
capacity dimension MUST carry its rate alongside the capability it prices, in the same
structure that describes that capability. Rates MUST resolve through the same
per-field precedence used for other commercial values, independently per dimension. A
dimension the shape requests with no rate resolvable at any tier MUST render the shape
unpriceable rather than free.

#### Scenario: Price is requested for a shape other than the advertised one

- **WHEN** a price is resolved for an admissible shape differing from the listing's
  advertised shape
- **THEN** the rate structure yields a price for it without republishing the listing

#### Scenario: A dimension has no rate at any tier

- **WHEN** a requested shape includes a capacity dimension for which no rate resolves
  at any precedence tier
- **THEN** the shape is reported unpriceable, and no price is produced that omits or
  zero-values that dimension

#### Scenario: Rates resolve from different tiers per dimension

- **WHEN** one dimension's rate is set by a storefront override and another's is
  available only as a default
- **THEN** each resolves independently from its own highest available tier

#### Scenario: A listing advertises a single rate from before rate structures existed

- **WHEN** commercial resolution reads a listing carrying one advertised rate
- **THEN** it is interpreted as a rate structure pricing the primary dimension only,
  and the price produced for that listing's own shape is unchanged

### Requirement: Price aggregation is replaceable

Deriving a price from a shape and a resolved rate structure MUST occur behind a
replaceable aggregation interface selected by domain configuration. No consumer of a
price MAY reconstruct or assume a total by combining individual dimension rates and
quantities directly.

#### Scenario: A domain selects a different aggregation

- **WHEN** a domain is configured with a different price aggregation
- **THEN** prices change accordingly with no change to negotiation, publication, or
  settlement code paths

#### Scenario: A consumer needs a shape's price

- **WHEN** any component needs the price of a shape
- **THEN** it obtains it through the aggregation interface rather than by multiplying a
  dimension's rate by its quantity
