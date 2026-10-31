## ADDED Requirements

### Requirement: Agreed compute prices carry their unit

Compute price consumers MUST use one core accessor returning the agreed quote and
its unit, `total` or `per_period`, with the selected period available for display.
It MUST preserve negotiated rate-multiplier semantics, upward rounding and asset
amount limits. Prepaid quotes use Agreement duration; recurring quotes use one
selected option period. Direct reads of `Agreement.amount` outside the accessor and
explicit raw negotiation hooks MUST fail the repository check.

#### Scenario: Sub-hour recurring quote

- **WHEN** a 10,000-bps Agreement selects PT1M at 2,500,000 USD/6 per hour
- **THEN** the accessor returns 41,667 per period rather than the full maximum-term price

#### Scenario: Prepaid recovery

- **WHEN** an accepted two-hour prepaid Agreement at that rate is recovered
- **THEN** the accessor returns 5,000,000 total from the accepted option

#### Scenario: Publication is repriced before materialization

- **WHEN** the pool rate changes after signed acceptance but before mandate derivation or restart recovery
- **THEN** the accessor and buyer check use the acceptance-bound rate structure and selected option, and the agreed price does not change

#### Scenario: A consumer bypasses the accessor

- **WHEN** a price consumer directly reads Agreement amount outside a declared raw negotiation hook
- **THEN** the repository check fails rather than accepting an unclassified reader

### Requirement: Compute horizons bind both seller bounds

Reserved duration MUST be positive and fit both bounds. Recurring horizons MAY be omitted; default is the least stated relative bound or absolute availability minus resolved start. Accepted duration/max term MUST equal that default or a shorter selection without rounding, and MUST include at least one whole period. Acceptance MUST refuse expired, excessive or sub-period selections.

#### Scenario: Absolute bound is earlier

- **WHEN** max duration is 48 hours, availability is 20 hours after resolved start and a recurring buyer names no horizon
- **THEN** the signed selection binds duration and max term to 20 hours

#### Scenario: Maximum term is not a whole period

- **WHEN** the effective seller bound or shorter buyer horizon is 125 seconds for a 60-second period
- **THEN** duration and max term bind 125 seconds before signature, without rounding
- **AND** the term end carries its own `settles_through` under the foundation codec: compute presets use `last_boundary` mapped to `end.partialPeriod: returned`, and fail closed until vendored

#### Scenario: Reserved term exceeds availability

- **WHEN** a reserved duration fits the relative maximum but ends after absolute availability
- **THEN** acceptance is refused

#### Scenario: Buyer chooses a shorter horizon

- **WHEN** a buyer chooses 10 hours under a 20-hour seller bound
- **THEN** the final identity-bound option and Agreement both bind 10 hours before acceptance
- **AND** no cached or accepted option is silently mutated

### Requirement: Final recurring options only narrow advertised horizons

The seller's signed acceptance MUST carry the final recurring option and its canonical ID. The buyer MUST verify the ID and equality to an advertised option except for max_term_seconds and the resulting ID; Agreement duration_seconds MUST equal that max term, which MUST NOT exceed the advertised bound. Every other option field MUST remain equal. Cached options and accepted bytes MUST NOT be mutated.

#### Scenario: Final horizon is within the advertised bound

- **WHEN** signed acceptance carries a canonical final option with a 10-hour max term under an advertised 20-hour bound and no other option field changed
- **THEN** the buyer accepts the refinement if Agreement duration is also 10 hours and both listing bounds hold
- **AND** selection retains the advertised-to-final option correlation

#### Scenario: Final horizon exceeds the advertised bound

- **WHEN** signed acceptance carries a 21-hour max term under an advertised 20-hour bound
- **THEN** the buyer refuses even if the final option has a valid canonical ID

#### Scenario: Another option field changes

- **WHEN** signed acceptance narrows the max term but changes any other option field, such as price, asset, notice or adjudication
- **THEN** the buyer refuses even if duration equals max term and the canonical ID is valid

### Requirement: Recurring starts resolve before signature

The terms runtime MUST resolve recurring start_utc to whole-second precision before the final signature, with bound/horizon and canonical option identity fixed. It MUST reject a fractional rate start rather than round accepted bytes. Once-only timestamp handling MUST remain unchanged.

#### Scenario: A recurring start is fractional

- **WHEN** the final recurring proposal carries a fractional-second start
- **THEN** acceptance refuses before signature rather than silently shifting the window

### Requirement: Acceptance checks current rate servicing

Seller acceptance MUST refuse recurring selections if the composition no longer
declares compatible servicing, even if a cached advertised option carries recurring
terms. The refusal MUST precede persistence and use the withdrawn-option/refetch
outcome. The listing MUST NOT be treated as the servicing declaration.

#### Scenario: Cached recurring option after servicing is disabled

- **WHEN** a buyer selects a cached recurring option and composition no longer declares servicing
- **THEN** the seller refuses before persisting acceptance and asks the buyer to refetch
