## ADDED Requirements

### Requirement: Unfunded exclusivity is not a shipped default

A storefront MUST NOT hold capacity before settlement under its shipped default
configuration while holding capacity is uncompensated. Where holding is uncompensated,
exclusive claim on capacity MUST arise only from settlement. A configuration value that
enables uncompensated pre-settlement holds MUST document, where the value is set, that
enabling it permits an unfunded counterparty to exclude others, and MUST name the
condition under which enabling it becomes safe.

#### Scenario: Counterparty accepts terms without settling

- **WHEN** a counterparty accepts terms and does not settle
- **THEN** no capacity is held on their behalf under default configuration, and other
  buyers may still reserve it

#### Scenario: Deal settles

- **WHEN** a deal settles
- **THEN** capacity is reserved at settlement and becomes exclusive from that point

#### Scenario: Operator reads the hold-duration setting

- **WHEN** an operator inspects the configuration value controlling pre-settlement holds
- **THEN** the exposure enabling it creates, and the condition under which enabling it
  is safe, are stated where the value is set

#### Scenario: Holding capacity becomes compensated

- **WHEN** held capacity is charged to the party holding it
- **THEN** a non-zero default may be restored, since exclusivity is no longer unfunded
