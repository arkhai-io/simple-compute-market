## ADDED Requirements

### Requirement: A bare-metal delivery that conflicts with its recorded result is refused

When the site reports, for an active bare-metal fulfillment, a delivery other than the
result the storefront recorded, the buyer's status, result, and access reads MUST answer a
typed 409 `delivery_conflict`, and the recorded result MUST stand. The storefront MUST NOT
answer such a read with an unhandled error.

#### Scenario: The site reports a different delivery

- **WHEN** a buyer reads the status of a fulfillment whose site now reports a delivery that
  differs from the recorded result
- **THEN** the read answers 409 `delivery_conflict` and the recorded result is unchanged

### Requirement: Bare-metal begin reads the scheduled resource's own identity

Bare-metal fulfillment MUST begin only when the scheduled resource's host and physical
machine, as the schedule response names them, equal the accepted terms'. It MUST NOT
require the declaration's publication settings to repeat them.

#### Scenario: A declaration names its machine once

- **WHEN** a deal is settled on a Physical Resource whose declaration names its host and
  physical machine and whose publication settings repeat neither
- **THEN** fulfillment begins

#### Scenario: The scheduled resource is another machine

- **WHEN** the schedule response names a physical machine other than the accepted terms'
- **THEN** fulfillment does not begin, and the deal reports the conflict
