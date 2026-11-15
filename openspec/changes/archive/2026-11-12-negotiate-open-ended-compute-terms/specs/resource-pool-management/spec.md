## ADDED Requirements

### Requirement: Capacity bounds are validated publication hints

Pool contracts MUST support optional `max_duration_seconds` and
`available_until_utc` hints per offering mode without making the site the authority
for commercial entitlements. A stated absolute bound MUST be timezone-aware UTC;
unset or nonpositive relative bounds MUST mean no relative limit. Malformed values
MUST be refused rather than converted into guessed defaults.

#### Scenario: Absolute capacity date

- **WHEN** a valid pool document states a UTC availability date
- **THEN** the pool wire model preserves it for storefront resolution without adding a site commercial-policy check

#### Scenario: Invalid date

- **WHEN** a pool hint supplies a malformed or timezone-naive availability date
- **THEN** validation refuses it with an actionable diagnostic
