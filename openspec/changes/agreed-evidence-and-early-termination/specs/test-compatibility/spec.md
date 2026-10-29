## MODIFIED Requirements

### Requirement: External payment qualification names its target

External qualification MUST identify the actual payments target and consumer revision, check readiness before mutations, and report unavailable prerequisites rather than substitute another mechanism. Payment-service ledger, hold release and hold extensions, fees, top-ups, payouts, and provider recovery remain the payments service's evidence; cases and outcomes remain the dispute authority's.

#### Scenario: Bare-metal qualification lacks hardware

- **WHEN** a disposable selected-site host is unavailable
- **THEN** local deterministic tests do not claim authenticated access, revocation, or physical teardown

#### Scenario: A configured payments run lacks a buyer credential

- **WHEN** a payments target is configured but the buyer's marketplace credential is not
- **THEN** the payment scenario fails naming the missing setting, rather than reporting itself blocked
