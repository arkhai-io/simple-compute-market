## ADDED Requirements

### Requirement: The filter grammar can compare exact decimal values

The filter specification MUST support a declared value type whose wire and stored
representation is a decimal-text string and whose comparison domain is exact
decimal. Range bounds declared under it MUST be parsed as exact decimals, resolved
listing values MUST be accepted when they are decimal text, and comparison MUST
NOT pass through a binary floating-point representation at any point.

The existing JSON-number value type MUST be left unchanged. Retyping its
comparison domain would alter the meaning of filters that other deployments'
specifications already declare, so exact decimal comparison MUST be a distinct
declared type that a specification opts into.

A registry MUST refuse to load a filter specification declaring a value type it
does not implement, rather than ignoring the declaration. A specification whose
comparison semantics the engine cannot honour MUST NOT be served, because a
silently-ignored type would evaluate every query under semantics the operator did
not declare.

A buyer resource-query compiler MUST render a bound of this type without loss and
MUST resolve its type from the specification like any other.

#### Scenario: A bound compares against a high-precision listing value

- **WHEN** a buyer bounds a query against a decimal-text field and a listing's
  value carries more significant digits than a binary double represents exactly
- **THEN** the comparison is exact and the listing matches or is excluded on its
  true value

#### Scenario: A decimal-text value is compared at the bound

- **WHEN** a listing's decimal-text value equals an inclusive bound exactly
- **THEN** it matches, and it does not match an exclusive bound of the same value

#### Scenario: A registry is given a specification it cannot honour

- **WHEN** a registry configured with an engine that does not implement a declared
  value type loads that filter specification
- **THEN** it refuses the specification rather than serving queries under
  substituted semantics

#### Scenario: The existing number type is unaffected

- **WHEN** a filter declared under the JSON-number value type is evaluated
- **THEN** its behaviour is unchanged by the presence of the decimal type

### Requirement: A filter may declare co-required filters

A filter declaration MAY name other declared filters that MUST be supplied
alongside it. A query supplying a filter without every filter it co-requires MUST
be refused rather than evaluated, because a constraint missing a dimension it
depends on has no interpretation.

The dependency MUST be one-directional: a co-required filter supplied on its own
remains a valid constraint in its own right.

Both the registry and the buyer resource-query compiler MUST resolve
co-requirements from the active filter specification. Neither MUST encode a
specific field's dependency in code, consistent with the requirement that every
field, operator, type, alias, and missing-value rule is resolved from the
specification and that no domain field is added.

Specification validation MUST reject a co-requirement naming an undeclared filter,
naming its own declaration, or participating in a cycle. Each is a specification
defect that would otherwise surface as a query that can never be satisfied.

#### Scenario: A co-required filter is missing from a query

- **WHEN** a buyer supplies a filter whose declaration co-requires another and
  omits it
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A co-required filter is supplied alone

- **WHEN** a buyer supplies only a filter that others co-require
- **THEN** the query is evaluated normally as a constraint on that field

#### Scenario: A client bypasses compiler validation

- **WHEN** a request reaches the registry supplying a filter without its
  co-requirements, without having been compiled by the buyer client
- **THEN** the registry refuses it

#### Scenario: A specification declares a cyclic co-requirement

- **WHEN** a filter specification declares co-requirements that form a cycle, name
  an undeclared filter, or name their own declaration
- **THEN** specification validation fails rather than the registry serving it

### Requirement: A listing may publish the seller's asking rate

A compute listing MAY publish the rate its seller is asking for the listing's
advertised shape, as an `asking_rate` object on the published listing resource
carrying `amount`, `asset`, and `period`. All three MUST be present together, and
publication MUST be refused when any is absent: an amount alone cannot be read and
a bound cannot be evaluated against it.

`amount` MUST be exact decimal text. A binary floating-point encoding cannot
represent ordinary decimal prices, and a base-unit integer encoding cannot
represent a fraction and needs a companion decimals field to be interpreted.

`asset` MUST be an opaque, non-empty identifier of the same kind a settlement
option's published asset already carries. It MUST NOT require an on-chain contract
address, token decimals, or a chain identity, so a rate quoted in an off-chain
currency is expressible. No surface may interpret it beyond comparing it for
equality.

`period` MUST be the currently supported time-rate unit, `hour`. A period outside
that MUST be refused at publication. Accepting a further period is a decision for
a later version rather than a consequence of a settlement-side change.

One rate is published per listing, as a single catalogue price for a shape that
does not vary. It MUST NOT be decomposed per capacity dimension, and it MUST NOT be
nested under a capability family: it prices the whole listing.

The published rate is a listing attribute and not a settlement option rate. No
settlement option, escrow term, or accepted obligation may be constructed from it,
and an agreed amount remains absent rather than zero until one is negotiated. This
constrains what the system builds from the number, not how far a buyer should trust
it: like every published field, an asking rate is a seller assertion, and nothing in
the marketplace verifies any of them.

#### Scenario: A listing publishes an asking rate

- **WHEN** a seller publishes a listing carrying an asking rate
- **THEN** the published listing resource carries an `asking_rate` object with its
  amount, asset, and period
- **AND** the amount appears as decimal text
- **AND** no settlement option or obligation carries a value derived from them

#### Scenario: A rate omits its asset or its period

- **WHEN** a listing publishes a rate amount without an asset, or without a period
- **THEN** publication is refused rather than publishing an amount that cannot be read

#### Scenario: A rate is quoted in an unsupported period

- **WHEN** a listing publishes a rate whose period is not the supported time-rate unit
- **THEN** publication is refused rather than storing an uninterpretable period

#### Scenario: A rate is quoted in an off-chain asset

- **WHEN** a seller publishes an asking rate in an asset that has no contract address, decimals, or chain identity
- **THEN** the rate publishes with that asset identifier carried opaquely

#### Scenario: A deal is agreed against a listing carrying an asking rate

- **WHEN** a negotiation concludes against a listing publishing an asking rate
- **THEN** the agreed amount comes from the negotiation
- **AND** the published asking rate does not constrain or supply it

### Requirement: The asking rate and a mechanism rate are independent carriers

A listing MAY publish an asking rate and also advertise a rate inside a
settlement carrier — an accepted escrow's rate slots or a settlement option's
rates. The two MUST be treated as different carriers with different meanings: a
mechanism rate governs what the runtime constructs for that mechanism, and the
asking rate governs nothing.

The two MUST NOT be required to agree, and where they disagree neither corrects
the other. A buyer comparing on the asking rate while negotiating against a
mechanism rate is the ordinary relationship between a published field and its
negotiated outcome, and no surface may present one as authoritative for the other.

Neither may be derived from the other, in either direction. A published asking
rate MUST NOT be written into a settlement option, escrow term, or obligation.

A listing that settles through a mechanism declining scalar participation carries
no mechanism rate at all. Such a listing MUST still be able to publish an asking
rate, since comparison before contact is the whole value the marketplace offers
for supply agreed out of band.

#### Scenario: A listing carries both an asking rate and an escrow rate

- **WHEN** a listing publishes an asking rate and also advertises escrow rate slots
- **THEN** both appear in the published shape
- **AND** no settlement option, escrow term, or obligation carries a value derived from the asking rate

#### Scenario: The two published rates disagree

- **WHEN** a listing's published asking rate differs from the rate advertised in its settlement carrier
- **THEN** publication is not refused on that ground
- **AND** the mechanism rate remains the only one from which anything is constructed

#### Scenario: A rateless mechanism carries an asking rate

- **WHEN** a listing's only settlement option is under a mechanism that declines scalar participation
- **THEN** the listing may still publish an asking rate
- **AND** the option remains rateless

### Requirement: Rate filters match the period and asset rather than normalizing across them

The compute filter specification MUST declare exact, fail-on-missing filters over
the asking rate's amount, asset, and period. The amount filters MUST use the exact
decimal comparison type and MUST co-require the asset and period filters, so the
refusal below is declared in the specification rather than encoded in the registry
or the buyer client.

A rate-bounded query MUST name the asset and the period it asks about, and MUST be
refused rather than evaluated when either is absent: a bare bound states neither
what is being counted nor per what.

A listing quoting a different period MUST be excluded rather than converted,
because a period signals the commitment a seller expects: a buyer shopping hourly
is not asking for supply quoted monthly, and converting one to the other returns
terms the buyer did not request dressed as a price match.

A listing quoting a different asset MUST likewise be excluded rather than
converted. Converting between assets requires an external exchange rate that moves
continuously, which would make one query's result depend on when it ran and would
make the registry an authority on relative asset value. Asset comparison MUST
remain equality only, consistent with every other published asset field.

A listing publishing no rate MUST be excluded from a rate-bounded query rather than
matching it, consistent with every other filter over the published listing shape. An
unstated rate has not been shown to satisfy a stated bound.

#### Scenario: A buyer bounds a query by rate

- **WHEN** a buyer queries for listings at or below a rate in a named asset and period
- **THEN** only listings quoting that asset and period and satisfying the bound are returned

#### Scenario: A rate bound names no asset or no period

- **WHEN** a buyer submits a rate bound without an asset, or without a period
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A listing quotes a different period

- **WHEN** a listing quotes its rate in a period the query did not name
- **THEN** it is excluded rather than converted into the queried period

#### Scenario: A listing quotes a different asset

- **WHEN** a listing quotes its rate in an asset the query did not name
- **THEN** it is excluded rather than converted into the queried asset

#### Scenario: A listing publishes no rate

- **WHEN** a buyer bounds a query by rate and a listing publishes none
- **THEN** that listing is excluded from the result

#### Scenario: A rate bound compares exactly

- **WHEN** a listing's asking amount carries more significant digits than a binary
  double represents exactly and a buyer bounds a query near it
- **THEN** the listing is matched or excluded on its exact value
