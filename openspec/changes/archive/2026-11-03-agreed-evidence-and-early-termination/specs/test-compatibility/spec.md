## MODIFIED Requirements

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision and check readiness before mutations. Unavailable external prerequisites MUST report blocked/unrun; a configured lane missing required settings or failing readiness MUST fail setup by name before scenarios. Neither MUST substitute another mechanism. Reports MUST follow "Lane qualification identifies readiness and evidence class".

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: A configured payments run lacks a buyer credential

- **WHEN** a payments target is configured but the buyer's marketplace credential is not
- **THEN** the payment scenario fails naming the missing setting, before mutations rather than disguising a configured-target setup failure as an unavailable external prerequisite

## ADDED Requirements

### Requirement: External authority effects retain their evidence owner

Payment-service ledger, hold release/extensions, fees, top-ups, payouts and provider recovery MUST remain the payments service's evidence; cases and outcomes MUST remain the dispute authority's. Deterministic local evidence MUST NOT claim physical hardware effects.

#### Scenario: A deterministic lane passes

- **WHEN** contract qualification passes against local doubles
- **THEN** the report claims no external ledger, adjudication or hardware outcome
