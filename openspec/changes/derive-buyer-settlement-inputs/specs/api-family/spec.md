## ADDED Requirements

### Requirement: A buyer stage adds no mechanism override to a normal command

A buyer stage of the api family MUST NOT contribute an option that overrides a mechanism input — wallet, signing key, chain, token, decimals, or settlement identity — to the buying library's `buy`, `negotiate`, or `settle` command. The buying library MUST hand a stage the selected matches when it scales explicit prices, so a stage derives the price scale from what was selected.

#### Scenario: The Alkahest buyer stage is composed

- **WHEN** a buyer plugin composes the buyer-side Alkahest stage
- **THEN** the stage contributes no option to any command

#### Scenario: A stage scales explicit prices

- **WHEN** a buy has explicit prices and has selected its matches
- **THEN** each stage scales them from the selected matches it proposed for
