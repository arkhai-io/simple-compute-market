## ADDED Requirements

### Requirement: Kit-owned settlement runtime

The settlement lifecycle runtime — settlement job orchestration, claim servicing, and
failure handling — MUST live in the kit layer and be composed by a market domain. A
domain MUST supply its escrow verification, settlement plan construction, and
configuration, and MUST NOT reimplement the orchestration, retry, or idempotency
behavior. Every domain implementing it MUST be composed onto the kit implementation, and
a domain that lacked it MUST gain it by composition.

#### Scenario: A domain settles a deal

- **WHEN** a market domain settles an accepted deal
- **THEN** job orchestration, claim servicing, and failure handling come from the kit
  implementation, with the domain supplying verification, plan construction, and
  configuration

#### Scenario: A failure-handling action is added

- **WHEN** a failure-handling action is added to the settlement runtime
- **THEN** every composing domain obtains it, rather than one domain gaining it while
  the others silently lack it

#### Scenario: A domain has no settlement runtime

- **WHEN** a domain without its own settlement implementation is composed
- **THEN** it can settle a deal through the kit runtime

#### Scenario: Settlement is interrupted and resumed

- **WHEN** a settlement is interrupted part-way and resumed
- **THEN** the kit runtime's idempotency and resume behavior applies identically for
  every composing domain
