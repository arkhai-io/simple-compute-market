## ADDED Requirements

### Requirement: Production rate servicing requires a qualified hosted revision

Production compositions MUST NOT declare rate-part servicing until the intended hosted deployment implements the vendored payments revision with per-part authorities and hold extensions. Qualification MUST verify authority-hosted stop notice, afterStop holds, partial reverse after stop and case extend/lift through real authority responses. No billing horizon, payee vouch, minimum-spend primitive or backdated payee stop is a prerequisite.

#### Scenario: Schema is published but target is older

- **WHEN** the schema and vectors include the required revision but the selected hosted deployment does not implement it
- **THEN** production publication, acceptance and materialization of rate deals remain disabled

#### Scenario: Hosted revision qualifies

- **WHEN** hosted behavior and consumer conformance pass for the required revision
- **THEN** VM and bare-metal production compositions may declare published-contract rate servicing and enforce the declaration at all three doors

### Requirement: Rate activation preserves existing commitment servicing

Enabling or withdrawing new rate-deal publication MUST NOT reinterpret accepted terms, redirect an existing commitment to another authority, or remove its lifecycle loops. Deployment preparation MUST confirm target selectors and readiness before seeding and live execution, and credential values MUST remain outside public configuration and evidence.

#### Scenario: Operator withdraws the declaration

- **WHEN** new per-period deals are disabled after activation
- **THEN** accepted commitments continue watching authority records, executing end effects and retaining evidence under their original Agreement

#### Scenario: Target readiness fails

- **WHEN** the intended hosted target is not ready
- **THEN** live deal scenarios do not run, the failed setup is recorded and activation remains blocked
