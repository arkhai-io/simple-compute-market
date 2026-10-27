## MODIFIED Requirements

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. A payment scenario MUST report itself blocked only when no payments target is configured or the configured target is not ready; once a target is configured, a missing setting the scenario itself supplies — its parties' accounts and credentials, or the service policy it pins — MUST fail the scenario rather than block it. Payment-service ledger, hold release, fees, disputes, top-ups, payouts, and provider recovery remain the payments service's evidence.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: A configured payments run lacks a buyer credential

- **WHEN** a payments target is configured but the buyer's marketplace credential is not
- **THEN** the payment scenario fails naming the missing setting, rather than reporting itself blocked
