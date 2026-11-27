## MODIFIED Requirements

### Requirement: Delivery commits the Agreement window

Every commit and recovery MUST use the Agreement's `start_utc` and `start_utc + duration_seconds` under the same reservation identity. Delivery MUST NOT substitute the current time for a start or a default for a duration; missing or conflicting timing MUST be repair-required without replacing an existing resource. Late settlement MUST shorten service and MUST NOT move the end. Every commit MUST also carry the deal's accepted `delivery_deadline_seconds` and its commitment instant as end service's delivery record holds them, in both domains through the one commit step, and MUST omit whichever of the two the record does not hold.

#### Scenario: Settlement completes late

- **GIVEN** an Agreement from 12:00 through 14:00
- **WHEN** settlement completes at 12:30
- **THEN** both domains commit 12:00 through 14:00, on the first attempt and on every retry

#### Scenario: Recovery lacks timing

- **WHEN** an unfinished delivery has no valid accepted start or duration
- **THEN** it is repair-required with its recorded resource, not a replacement or a guessed hour

#### Scenario: A deal accepted a delivery deadline

- **WHEN** delivery commits a deal whose delivery record holds an accepted deadline of 1800 seconds and a commitment instant
- **THEN** the commit carries both, on the first attempt and on every retry

#### Scenario: A deal accepted no delivery deadline

- **WHEN** delivery commits a deal whose option carries no lifecycle terms
- **THEN** the commit carries no accepted deadline
