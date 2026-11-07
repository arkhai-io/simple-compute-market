## ADDED Requirements

### Requirement: The seller's reference amount is the selected option's rate

A seller's reference amount for a scalar negotiation MUST be derived from the amount rate of the
option the buyer's proposal selects: the matched accepted escrow for an escrow proposal, or the
settlement option matched by its identity for a settlement selection. A configured negotiation floor
MUST apply only when the selected option advertises no rate. A reference amount MUST NOT be derived
from an option the buyer did not select or from a rate in another asset. The negotiation runtime
MUST give the domain the buyer's pinned proposal when it asks for the reference amount.

#### Scenario: A hosted option is selected on a two-mechanism listing

- **WHEN** a listing offers an Alkahest option and a hosted option, and the buyer selects the hosted
  option
- **THEN** the seller's reference amount is derived from the hosted option's rate in its own minor
  units, not from the Alkahest rate

#### Scenario: A hosted-only listing is negotiated

- **WHEN** a listing offers only hosted options with rates and the storefront configures a
  negotiation floor
- **THEN** the seller's reference amount is derived from the selected option's rate, and the floor
  is not used

#### Scenario: The selected option is a hidden reserve

- **WHEN** the buyer selects an option that advertises no rate
- **THEN** the seller's reference amount is derived from the configured negotiation floor

## MODIFIED Requirements

### Requirement: Uint256-safe negotiation values

Negotiated scalar payment amounts in proposals, rates, accepted obligations, and persisted agreed state MUST remain non-negative integers without precision loss. A seller's reference amount derived from an option's rate or from its configured negotiation floor MUST be computed with integer arithmetic on exact values, never through binary floating point or a fixed-precision decimal context; truncation to whole base units is the only permitted rounding. Canonical JSON wire representations MUST encode uint256-domain values as decimal-digit strings, and persistence MUST round-trip values larger than JSON's safe-integer range and SQLite's signed 64-bit range without rounding or truncation.

#### Scenario: Negotiation uses an 18-decimal token amount

- **WHEN** a proposal contains an amount greater than SQLite's signed 64-bit maximum as a decimal-digit wire value
- **THEN** the seller authenticates and evaluates that exact integer, persists it losslessly, and returns accepted or counterproposal artifacts with the same precision

#### Scenario: Proposal amount is not an unsigned decimal integer

- **WHEN** an amount is negative, fractional, boolean, or otherwise not a non-negative decimal integer
- **THEN** the negotiation rejects it instead of rounding, truncating, or interpreting it through a floating-point value

#### Scenario: A long-duration reference amount exceeds a fixed-precision context

- **WHEN** the selected option advertises a base-unit rate with 21 significant digits and a buyer
  requests a one-year duration
- **THEN** the seller's reference amount equals the rate multiplied by the duration in seconds,
  divided by 3600 and truncated to whole base units, exactly

#### Scenario: The negotiation floor is configured as decimal text

- **WHEN** the selected option advertises no rate and the storefront's negotiation floor is configured
- **THEN** the floor is parsed exactly from its decimal text and never through a floating-point value

