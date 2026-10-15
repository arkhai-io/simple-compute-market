## ADDED Requirements

### Requirement: A selected release condition must be one the listing advertises

When a buyer's Alkahest proposal names a release condition, the seller MUST reject the
round unless that condition is one the listing advertises for the proposal's chain,
including when the listing advertises none. A materialized escrow plan MUST name the
arbiter of the release condition the proposal selected, or, where the proposal selected
none, the default the listing's advertised condition names.

#### Scenario: A proposal names an arbiter the listing does not advertise

- **WHEN** a buyer proposes an Alkahest escrow whose release condition names an arbiter
  absent from the listing's advertised conditions
- **THEN** the seller rejects the round and no plan is materialized

#### Scenario: A listing advertises no release condition

- **WHEN** a buyer proposes an Alkahest escrow naming a release condition against a listing
  that advertises none
- **THEN** the seller rejects the round rather than accepting the buyer's condition
