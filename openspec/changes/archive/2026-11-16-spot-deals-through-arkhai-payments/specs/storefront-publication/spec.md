## ADDED Requirements

### Requirement: Compute rate preset helpers disclose setup pricing
The hosted preset helper for both compute domains MUST construct presets from parts and lifecycle terms, not runtime classes. A setup amount MUST be the seller's explicit choice in both domains, with no minimum-spend gate and no domain-specific default. Both compute compositions MUST install the payments preset helper and its timing projection through one payments-kit function, dark until the composition declares rate servicing. The helper MUST return its clause's own delivery deadline for the composition to override with the pool's, and MUST convert the clause's rate to minor units through one conversion that refuses a rate finer than the asset's precision.

#### Scenario: The compute publication adapter consumes presets
- **WHEN** either compute publication adapter requests on-demand and spot preset parts
- **THEN** the helper supplies setup/rate and the corresponding accepted terms without emitting listings or creating a second publication path

#### Scenario: A setup price is incomplete
- **WHEN** a seller configures a setup-bearing preset without a setup price
- **THEN** the builder refuses the incomplete preset rather than inventing a charge
- **AND** omitting setup permits a valid rate-only option in either domain

#### Scenario: The helper is installed but dark
- **GIVEN** a VM or bare-metal composition with no rate servicing declared
- **WHEN** a recurring clause is published
- **THEN** the installed helper is reached only after the declaration check, which refuses the clause as undeclared
- **AND** both compositions take the helper and timing projection from the same payments-kit function

#### Scenario: A clause's rate is finer than its asset
- **WHEN** an hourly clause rate has more decimal places than the asset's precision
- **THEN** pricing and encoding both refuse it rather than round

#### Scenario: Setup is disclosed
- **WHEN** a declared setup-bearing preset is built
- **THEN** the helper discloses that the setup charge is owed from approval, kept when delivered=true and returned in full when delivered=false for either cause under the delivery_end ruling
- **AND** it does not spread setup over the maximum compute term

#### Scenario: Accepted pricing survives publication changes
- **GIVEN** an accepted spot option and its signed-acceptance-bound rate structure
- **WHEN** its pool is repriced or removes the payee entitlement before materialization or recovery
- **THEN** derivation and buyer checking use the bound rate structure, and notice admission uses the accepted entitlement
- **AND** an unavailable bound structure refuses instead of falling back to the current listing

#### Scenario: Another domain uses a once option
- **WHEN** a reserved compute or API-credit option uses only once parts
- **THEN** the helper does not convert it to rate servicing
