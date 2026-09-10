## ADDED Requirements

### Requirement: A listing may publish the seller's asking rate

A compute listing MAY publish the rate its seller is asking for the listing's
advertised shape. The published rate MUST carry the period it is quoted per, drawn
from the same canonical time-unit vocabulary settlement rates use, so a published
period and a settlement period cannot diverge.

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

- **WHEN** a seller publishes a listing carrying an asking rate and its period
- **THEN** the rate and period appear in the published listing shape
- **AND** no settlement option or obligation carries a value derived from them

#### Scenario: A rate is quoted in an unsupported period

- **WHEN** a listing publishes a rate whose period is outside the canonical time-unit vocabulary
- **THEN** publication is refused rather than storing an uninterpretable period

#### Scenario: A deal is agreed against a listing carrying an asking rate

- **WHEN** a negotiation concludes against a listing publishing an asking rate
- **THEN** the agreed amount comes from the negotiation
- **AND** the published asking rate does not constrain or supply it

### Requirement: Rate filters match the period rather than normalizing across it

A rate-bounded query MUST name the period it asks about and MUST match only
listings quoting that period. A listing quoting a different period MUST be excluded
rather than converted, because a period signals the commitment a seller expects: a
buyer shopping hourly is not asking for supply quoted monthly, and converting one to
the other returns terms the buyer did not request dressed as a price match.

A listing publishing no rate MUST be excluded from a rate-bounded query rather than
matching it, consistent with every other filter over the published listing shape. An
unstated rate has not been shown to satisfy a stated bound.

#### Scenario: A buyer bounds a query by rate

- **WHEN** a buyer queries for listings at or below a rate in a named period
- **THEN** only listings quoting that period and satisfying the bound are returned

#### Scenario: A listing quotes a different period

- **WHEN** a listing quotes its rate in a period the query did not name
- **THEN** it is excluded rather than converted into the queried period

#### Scenario: A listing publishes no rate

- **WHEN** a buyer bounds a query by rate and a listing publishes none
- **THEN** that listing is excluded from the result
