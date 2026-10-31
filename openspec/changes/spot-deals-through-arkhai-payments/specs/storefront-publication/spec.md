## ADDED Requirements

### Requirement: Compute rate preset helpers disclose setup pricing
The hosted preset helper for both compute domains MUST construct presets from parts and lifecycle terms, not runtime classes. Setup MUST be explicitly priced with seller opt-out and no minimum-spend gate. Setup-bearing presets MUST refuse until the activation trigger and bounded no-activation full-return fallback are qualified. Rate-only interim presets MUST require explicit setup opt-out.

#### Scenario: The compute publication adapter consumes presets
- **WHEN** either compute publication adapter requests on-demand and spot preset parts
- **THEN** the helper supplies setup/rate and the corresponding accepted terms without emitting listings or creating a second publication path

#### Scenario: A default setup price is missing
- **WHEN** a seller selects the default setup-bearing preset without a setup price
- **THEN** the builder refuses the incomplete preset rather than inventing a charge
- **AND** explicit setup opt-out permits a valid rate-only option

#### Scenario: Setup contract support is missing
- **WHEN** the authority cannot express the linked activation trigger and bounded no-activation fallback
- **THEN** publication and acceptance refuse setup-bearing presets
- **AND** explicit seller setup opt-out permits the rate-only interim

#### Scenario: Setup is disclosed
- **WHEN** a qualified setup-bearing preset is built
- **THEN** the helper discloses its activation end, no-payout reservation before activation and full return if lawfully cancelled first
- **AND** it does not spread setup over the maximum compute term

#### Scenario: Accepted pricing survives publication changes
- **GIVEN** an accepted spot option and its signed-acceptance-bound rate structure
- **WHEN** its pool is repriced or removes the payee entitlement before materialization or recovery
- **THEN** derivation and buyer checking use the bound rate structure, and notice admission uses the accepted entitlement
- **AND** an unavailable bound structure refuses instead of falling back to the current listing

#### Scenario: Another domain uses a once option
- **WHEN** a reserved compute or API-credit option uses only once parts
- **THEN** the helper does not convert it to rate servicing
