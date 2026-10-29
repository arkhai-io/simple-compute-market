## ADDED Requirements

### Requirement: Buyers approve explicit compute price and end terms

Both compute buyers MUST display the derived product class, quote with unit,
separate setup once charge, initial reserve, maximum term/end, selected horizon,
payer/payee entitlements and notices, exposure and adjudication/retention terms
before approval. They MUST distinguish reserve from spend, start from observed
delivery, and authority guarantees from cooperative seller behavior. They MUST NOT
present reserve-ahead as a dishonest-seller billing cap.

#### Scenario: On-demand approval

- **WHEN** a buyer approves a payer-only recurring option with a setup once part
- **THEN** the display says on-demand, separately shows setup and recurring charge, and states payer notice/exposure without granting the payee a stop right
- **AND** it explains the buyer's authority stop/case and kept-evidence backstop

### Requirement: Recurring purchase may omit a horizon

Compute buyers MUST permit omitted duration for recurring selections and use the
seller-bound horizon returned in the final accepted terms. Reserved selections
MUST require duration. Both domains MUST permit recurring purchases without a
protocol minimum-spend term; setup fees and churn refusal MUST be represented as
seller pricing/policy.

#### Scenario: Unnamed bare-metal horizon

- **WHEN** a buyer selects a bounded bare-metal recurring option without naming duration
- **THEN** the buyer can proceed using its finite bound without a minimum-spend gate

#### Scenario: Missing reserved duration

- **WHEN** a fresh reserved selection omits duration
- **THEN** the buyer refuses rather than substituting an hour or listing maximum
