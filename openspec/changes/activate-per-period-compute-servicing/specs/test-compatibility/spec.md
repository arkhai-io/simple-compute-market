## ADDED Requirements

### Requirement: Rate activation evidence identifies the real authority boundary

> **Owned by `switch-on-hosted-per-period-vm`.** Live evidence recorded apart from lane-double evidence for the MVP's VM rows, and the scenarios "Double passes all scenarios" and "Required live target is unavailable" for those rows; kept until that change's design writes its delta.

> **Stale.** The cited requirement "Lane qualification identifies readiness and evidence class" does not exist; the evidence classes are lane-double evidence and live evidence (test-compatibility's lane-double requirement). The scenario "Producer vectors are missing" and its proposed-contract class are moot: the vectors are vendored and no proposed contract exists (`kit/arkhai-payments/schema/SOURCE.md`).

Reports MUST follow "Lane qualification identifies readiness and evidence class" per scenario. Both compute lanes MUST pass published qualification against both doubles. Activation MUST also record both-domain live complete deals and required hosted rate/stop/hold/case effects; missing live evidence MUST block completion, never count as a passing double run.

#### Scenario: Producer vectors are missing

- **WHEN** a producer-published signed snapshot, before/after-start, or partial-reversal before/after-stop vector is absent
- **THEN** Qualification against the published contract is blocked; pinned kit-owned candidates permit only Qualification against a proposed contract, never production enablement

#### Scenario: Double passes all scenarios

- **WHEN** both compute lanes pass against the double but hosted checks have not run
- **THEN** results are published-contract qualification only and production activation remains unqualified

#### Scenario: Hosted effects are observed

- **WHEN** live activation-before-start, priced payer stop plus hint, per-stopper partial-period billing, setup once, seller notice, exhaustion/read-before-timer-end, delivery_end filing and payee-signed delivery_end rule with cause-specific remedies, buyer-half same-key stop retry through outage with billing until landing, receipt evidence and payee-signed delivery_end or human triage, case extension/lift and partial reversal after stop are exercised
- **THEN** the report records actual authority effects, physical recovery and kept evidence, identifies the deployed revision using public-safe provenance, and names any controlled outage/race that was tested only in the double

#### Scenario: Required live target is unavailable

- **WHEN** credentials, target readiness or a required hosted test control are unavailable
- **THEN** that required scenario is unrun with its setup cause and activation cannot close on qualification evidence alone
