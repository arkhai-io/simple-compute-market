## ADDED Requirements

### Requirement: Seller feasibility precedes pricing

Before pricing a requested capacity shape, a seller policy MUST evaluate that shape
against every dimension it constrains, quantitatively as well as categorically. A
policy MUST NOT price a shape it has already determined it will not serve.

#### Scenario: Requested shape exceeds a quantitative constraint

- **WHEN** a requested shape exceeds a seller constraint on a quantitative dimension
- **THEN** the seller declines on that basis rather than quoting a price for it

#### Scenario: Requested shape fails a categorical constraint

- **WHEN** a requested shape names a categorical attribute the seller does not offer
- **THEN** the seller declines without pricing, as it does today

## MODIFIED Requirements

### Requirement: Uint256-safe negotiation values

Negotiated scalar payment amounts in proposals, rates, accepted obligations, and persisted agreed state MUST remain non-negative integers without precision loss. A seller's reference amount derived from an advertised rate or from its configured negotiation floor MUST be computed with integer arithmetic on exact values, never through binary floating point or a fixed-precision decimal context; truncation to whole base units is the only permitted rounding. Canonical JSON wire representations MUST encode uint256-domain values as decimal-digit strings, and persistence MUST round-trip values larger than JSON's safe-integer range and SQLite's signed 64-bit range without rounding or truncation.

#### Scenario: Negotiation uses an 18-decimal token amount

- **WHEN** a proposal contains an amount greater than SQLite's signed 64-bit maximum as a decimal-digit wire value
- **THEN** the seller authenticates and evaluates that exact integer, persists it losslessly, and returns accepted or counterproposal artifacts with the same precision

#### Scenario: Proposal amount is not an unsigned decimal integer

- **WHEN** an amount is negative, fractional, boolean, or otherwise not a non-negative decimal integer
- **THEN** the negotiation rejects it instead of rounding, truncating, or interpreting it through a floating-point value

#### Scenario: A long-duration reference amount exceeds a fixed-precision context

- **WHEN** a listing advertises a base-unit rate with 21 significant digits and a buyer requests a
  one-year duration
- **THEN** the seller's reference amount equals the rate multiplied by the duration in seconds,
  divided by 3600 and truncated to whole base units, exactly

#### Scenario: The negotiation floor is configured as decimal text

- **WHEN** a listing advertises no rate and the storefront's negotiation floor is configured
- **THEN** the floor is parsed exactly from its decimal text and never through a floating-point value

