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

#### Scenario: A consumer bypasses the accessor

- **WHEN** a price consumer directly reads Agreement amount outside a declared raw negotiation hook
- **THEN** the repository check fails rather than accepting an unclassified reader

### Requirement: Compute horizons bind both seller bounds

Reserved selections MUST name a positive duration satisfying both listing bounds.
Recurring selections MAY omit a horizon; their default MUST be the minimum of the
positive relative bound and absolute availability minus resolved start, considering
only stated bounds. Accepted `duration_seconds` and `early_termination.max_term_seconds`
MUST be equal, positive and finite. An explicit shorter horizon MUST bind both;
expired or excessive selections MUST be refused before acceptance.

#### Scenario: Absolute bound is earlier

- **WHEN** max duration is 48 hours, availability is 20 hours after resolved start and a recurring buyer names no horizon
- **THEN** the signed selection binds duration and max term to 20 hours

#### Scenario: Reserved term exceeds availability

- **WHEN** a reserved duration fits the relative maximum but ends after absolute availability
- **THEN** acceptance is refused

#### Scenario: Buyer chooses a shorter horizon

- **WHEN** a buyer chooses 10 hours under a 20-hour seller bound
- **THEN** the final identity-bound option and Agreement both bind 10 hours before acceptance
- **AND** no cached or accepted option is silently mutated

### Requirement: Acceptance checks current rate servicing

Seller acceptance MUST refuse recurring selections if the composition no longer
declares compatible servicing, even if a cached advertised option carries recurring
terms. The refusal MUST precede persistence and use the withdrawn-option/refetch
outcome. The listing MUST NOT be treated as the servicing declaration.

#### Scenario: Cached recurring option after servicing is disabled

- **WHEN** a buyer selects a cached recurring option and composition no longer declares servicing
- **THEN** the seller refuses before persisting acceptance and asks the buyer to refetch
