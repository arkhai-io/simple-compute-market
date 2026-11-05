## ADDED Requirements

### Requirement: Class discovery uses public billing and release projections

Mechanism registrations used for compute class discovery MUST expose the public
billing-kind and release-condition eligibility needed to distinguish prepaid,
recurring and legacy prepaid-interruptible options. The shared class compiler MUST
consume those projections and codec-owned entitlements, not inspect opaque params
or infer unsupported entitlements from an arbiter tree. Approval expiry MUST use
`arkhai_payments.approval_window`, not a dispute-hold or billing-period field.

#### Scenario: Legacy release model without lifecycle adapter

- **WHEN** an Alkahest splitter option is evaluated for reserved class
- **THEN** its public release eligibility excludes it without inventing an early-termination entitlement

#### Scenario: Setup fee beside rate

- **WHEN** an option contains setup once pricing and recurring rate pricing
- **THEN** its public billing projection identifies it as recurring
