## ADDED Requirements

### Requirement: A listing may publish the seller's asking rate

A compute listing MAY publish the rate its seller is asking for the listing's
advertised shape. A published rate MUST carry three parts together — an amount,
the asset it is quoted in, and the period it is quoted per — and publication MUST
be refused when any one of them is absent, because an amount alone cannot be read
and a bound cannot be evaluated against it.

The period MUST be drawn from the same canonical time-unit vocabulary settlement
rates use, so a published period and a settlement period cannot diverge. The asset
MUST be an opaque, non-empty identifier of the same kind a settlement option's
published asset already carries; it MUST NOT require an on-chain contract address,
token decimals, or a chain identity, so that a rate quoted in an off-chain
currency is expressible. No surface may interpret the identifier beyond comparing
it for equality.

The amount MUST be carried as decimal text rather than as a number or as
base units. Base units cannot be interpreted without a companion decimals field,
and amounts in this domain routinely exceed what a 64-bit integer or an IEEE-754
double holds, so a numeric encoding would be lossy at ordinary values.

One rate is published per listing. A listing's advertised shape does not vary, so
the rate MUST NOT be decomposed per capacity dimension; pricing a shape a buyer
proposes is negotiation-side work and is not this field.

The published rate is a listing attribute and not a settlement option rate. No
settlement option, escrow term, or accepted obligation may be constructed from it,
and an agreed amount remains absent rather than zero until one is negotiated. This
constrains what the system builds from the number, not how far a buyer should trust
it: like every published field, an asking rate is a seller assertion, and nothing in
the marketplace verifies any of them.

#### Scenario: A listing publishes an asking rate

- **WHEN** a seller publishes a listing carrying an asking rate with its asset and period
- **THEN** the amount, asset, and period appear in the published listing shape
- **AND** the amount appears as decimal text
- **AND** no settlement option or obligation carries a value derived from them

#### Scenario: A rate omits its asset or its period

- **WHEN** a listing publishes a rate amount without an asset, or without a period
- **THEN** publication is refused rather than publishing an amount that cannot be read

#### Scenario: A rate is quoted in an unsupported period

- **WHEN** a listing publishes a rate whose period is outside the canonical time-unit vocabulary
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

Neither may be derived from the other. A storefront MUST NOT populate the asking
rate from a mechanism rate, and MUST NOT write a published asking rate into a
settlement option, escrow term, or obligation. Deriving either direction would make
the field's provenance unreadable, and it is undefinable for a listing advertising
escrows in several assets at several rates.

A listing that settles through a mechanism declining scalar participation carries
no mechanism rate at all. Such a listing MUST still be able to publish an asking
rate, since comparison before contact is the whole value the marketplace offers
for supply agreed out of band.

#### Scenario: A listing carries both an asking rate and an escrow rate

- **WHEN** a listing publishes an asking rate and also advertises escrow rate slots
- **THEN** both appear in the published shape
- **AND** the asking rate is not derived from the escrow rate
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

A rate-bounded query MUST name the asset and the period it asks about, and MUST be
refused rather than evaluated when either is absent: a bare bound has no
interpretation, since it states neither what is being counted nor per what.

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
