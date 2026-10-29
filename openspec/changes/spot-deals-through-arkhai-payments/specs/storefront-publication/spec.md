## ADDED Requirements

### Requirement: Compute rate preset helpers disclose setup pricing
The hosted preset helper consumed by both compute domains MUST construct presets from parts and lifecycle terms, not runtime classes. Default presets MUST disclose an explicitly priced setup once part with seller opt-out, and MUST NOT require minimum spend. The helper MUST disclose setup's activation end and the authority's standard self-penalty treatment: all returned for undelivered setup, none once delivered.

#### Scenario: The terms-owned publication adapter consumes presets
- **WHEN** either compute publication adapter requests on-demand and spot preset parts
- **THEN** the helper supplies setup/rate and the corresponding accepted terms without emitting listings or creating a second publication path

#### Scenario: A default setup price is missing
- **WHEN** a seller selects the default setup-bearing preset without a setup price
- **THEN** the builder refuses the incomplete preset rather than inventing a charge
- **AND** explicit setup opt-out permits a valid rate-only option

#### Scenario: Accepted pricing survives publication changes
- **GIVEN** an accepted spot option and its signed-acceptance-bound rate structure
- **WHEN** its pool is repriced or removes the payee entitlement before materialization or recovery
- **THEN** derivation and buyer checking use the bound rate structure, and notice admission uses the accepted entitlement
- **AND** an unavailable bound structure refuses instead of falling back to the current listing

#### Scenario: Another domain uses a once option
- **WHEN** a reserved compute or API-credit option uses only once parts
- **THEN** this change does not convert it to rate servicing
