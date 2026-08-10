## ADDED Requirements

### Requirement: Deployable stack per market domain

Every market domain intended for deployment MUST have a stack definition that stands its
services up, following the same topology conventions as the other domains' stacks. A
domain without a stack definition MUST NOT be described as deployable.

#### Scenario: A domain is stood up

- **WHEN** an operator stands up a market domain's services
- **THEN** a stack definition exists for it, following the same conventions as the other
  domains

#### Scenario: A domain's deployment topology changes

- **WHEN** a domain's services are composed differently — for example as an additional
  contract inside another storefront process rather than as its own service
- **THEN** the stack definition reflects the composition actually deployed
