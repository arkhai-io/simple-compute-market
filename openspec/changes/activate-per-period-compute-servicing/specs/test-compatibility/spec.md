## ADDED Requirements

### Requirement: Rate activation evidence identifies the real authority boundary

Activation evidence MUST distinguish proposed-contract qualification, published-contract qualification and live hosted evidence per scenario. Both compute lanes MUST pass published-contract qualification against the payment and mediation doubles. Activation MUST additionally record both-domain live complete deals and hosted rate/stop/hold/case acceptance effects against the intended deployment; missing required live evidence MUST block completion, not be counted as a passing double run.

#### Scenario: Double passes all scenarios

- **WHEN** both compute lanes pass against the double but hosted checks have not run
- **THEN** results are published-contract qualification only and production activation remains unqualified

#### Scenario: Hosted effects are observed

- **WHEN** live start, priced payer stop, seller notice, exhaustion, exceptional_end, acknowledged buyer_end, case extension/lift and partial reversal after stop are exercised
- **THEN** the report records actual authority effects, physical recovery and kept evidence, identifies the deployed revision using public-safe provenance, and names any controlled outage/race that was tested only in the double

#### Scenario: Required live target is unavailable

- **WHEN** credentials, target readiness or a required hosted test control are unavailable
- **THEN** that required scenario is unrun with its setup cause and activation cannot close on qualification evidence alone
