## ADDED Requirements

### Requirement: An Alkahest obligation uses exactly the release condition its listing authorizes

Every published Alkahest settlement option MUST carry an authorized release condition — an
arbiter and its demand data — for the chain it publishes on. Where a buyer's proposal selects a
release condition, the seller MUST reject the round unless the selected arbiter and demand data
equal a condition the listing authorizes for that chain, including when the listing authorizes
none. Independently of any seller policy, the plan a seller materializes MUST use exactly the
authorized condition the proposal selected, or the listing's authorized condition where the
proposal selected none, and a listing whose authorized condition is missing or cannot be read
MUST fail closed before any obligation is accepted.

#### Scenario: A proposal substitutes the recipient

- **WHEN** a buyer proposes an Alkahest escrow naming the listing's advertised arbiter with a
  recipient other than the one its demand data authorizes
- **THEN** the seller rejects the round and no plan is materialized

#### Scenario: A listing authorizes no release condition

- **WHEN** a buyer proposes an Alkahest escrow naming a release condition against a listing that
  authorizes none
- **THEN** the seller rejects the round rather than accepting the buyer's condition

#### Scenario: A proposal names no escrow address

- **WHEN** a buyer's Alkahest proposal names no escrow address, so a seller policy that compares
  escrow fields finds nothing to compare
- **THEN** the plan the seller materializes still uses exactly the listing's authorized release
  condition, or materialization is refused

#### Scenario: The seller configures no escrow-shape policy

- **WHEN** a seller's negotiation policies omit the escrow-shape guard and a buyer selects an
  unauthorized release condition
- **THEN** plan materialization refuses it and no obligation is accepted
