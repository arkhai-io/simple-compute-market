## ADDED Requirements

### Requirement: Buyers approve explicit compute price and end terms

Both compute buyers MUST display the derived product class, quote with unit,
separate setup once charge, initial reserve, maximum term/end, selected horizon,
the delivery deadline as seconds after approval within which the resource is active,
payer/payee entitlements, notices, per-stopper and term-end `settles_through`, premature-stop penalty amount/asset/cap, and adjudication/retention terms
before approval.

#### Scenario: On-demand approval

- **WHEN** a buyer approves a payer-only recurring option with a setup once part
- **THEN** the display says on-demand, separately shows setup and recurring charge, and states payer notice and started-period treatment without granting the payee an entitled reclaim right; the display does not claim the mandate enforces that the seller will not preempt, since on-demand gives the seller no stop entry and the buyer's remedy is the penalty and a case over held money
- **AND** it explains stop-then-hint with service through the effective stop, receipt-only immediate surrender, that the storefront cannot stop billing and the buyer's journaled, retried authority stop does, and the optional buyer_end case for human triage

#### Scenario: Payee treatment is displayed faithfully

- **WHEN** a buyer selects an interim spot option with `settles_through: started_period` for both parties
- **THEN** the display says both stops charge the started period, not that seller preemption returns it
- **AND** the display states that the setup charge is owed from approval, kept if the buyer stops, and returned only if the seller never delivers

### Requirement: Buyer display separates billing guarantees from cooperation

Both compute buyers MUST distinguish reserve from spend, billing start from observed delivery, and authority guarantees from cooperative seller behavior. They MUST NOT present reserve-ahead as a dishonest-seller billing cap.

#### Scenario: Reserve is displayed

- **WHEN** a buyer views the selected option's initial reserve
- **THEN** display identifies reserved funds, not a spend floor or a cap on dishonest-seller billing

### Requirement: The buyer refuses seller ends that keep the started period

The buyer's acceptance policy MUST by default refuse an option whose payee entitlement or term end has a `settles_through` other than `last_boundary`, and MUST let the buyer configure the treatments it accepts. The refusal MUST name the term.

#### Scenario: A spot option charges the started period on a seller stop

- **WHEN** a buyer with the default policy is offered a spot option whose payee entitlement settles through `started_period`
- **THEN** the buyer refuses the option, naming the payee entitlement's `settles_through`

#### Scenario: A buyer accepts charged seller stops

- **WHEN** a buyer configures its policy to accept `started_period` on payee stops
- **THEN** the same option is acceptable

### Requirement: Default acceptance requires an on-demand seller penalty

Buyer acceptance policy SHOULD refuse an on-demand option without positive early_termination.premature_stop_penalty and a compute option without `delivery_deadline_seconds`, and SHOULD expose explicit buyer opt-out for each. It MUST display the selected value as a ceiling and explain that an unentitled seller end forfeits at most earned amounts still held after unearned-money refunds — at the start of a deal the setup charge, and nothing when nothing is earned and held; it MUST NOT present the penalty as an assured amount; an entitled notice stop pays none. In a buyer case a person applies the remedy.

#### Scenario: An on-demand option has no penalty

- **WHEN** the buyer uses the recommended default acceptance policy and the on-demand penalty is absent or zero
- **THEN** selection refuses it by name rather than claiming the mandate prevents preemption

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
