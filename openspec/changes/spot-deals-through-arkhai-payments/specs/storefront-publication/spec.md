## ADDED Requirements

### Requirement: Both compute domains publish rate presets per option
VM and bare-metal storefronts MUST support independently priced on-demand and spot rate options from one pool through the same hosted option builder. Presets MUST be combinations of parts and lifecycle terms, not class-specific servicing branches. Default presets MUST disclose an explicitly priced setup once part, with seller opt-out, and MUST NOT require minimum spend.

#### Scenario: One pool offers spot beside on-demand
- **GIVEN** a servicing-capable VM or bare-metal storefront and valid lifecycle terms
- **WHEN** a pool offers both presets at different rates
- **THEN** publication emits distinct options with their own prices and option IDs
- **AND** only the spot option grants the payee a stop entitlement

#### Scenario: A default setup price is missing
- **WHEN** a seller selects the default setup-bearing preset without a setup price
- **THEN** the builder refuses the incomplete preset rather than inventing a charge
- **AND** explicit setup opt-out permits a valid rate-only option

#### Scenario: Accepted pricing survives publication changes
- **GIVEN** a committed spot option
- **WHEN** its pool changes the spot rate or removes the payee entitlement
- **THEN** mandate derivation and notice admission still use the accepted option

#### Scenario: Another domain uses a once option
- **WHEN** a reserved compute or API-credit option uses only once parts
- **THEN** this change does not convert it to rate servicing
