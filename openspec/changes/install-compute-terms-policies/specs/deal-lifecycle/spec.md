## MODIFIED Requirements

### Requirement: The delivery deadline is the site's availability term

`delivery_deadline_seconds` MUST be a positive integer: the seconds after the later of the commitment instant and the Agreement start within which the resource is available to the buyer, as the storefront's durable `available` record. A compute option whose mechanism has a lifecycle adapter MUST carry the deadline its site enforces and omit it where the site enforces none. Refusing such an option without it MUST be the buyer's terms policy's decision: the packaged `default` policy refuses it, and term validation does not.

#### Scenario: A default buyer meets an option without a deadline

- **WHEN** a buyer whose terms policy is `default` is offered a compute Arkhai payments option with no `delivery_deadline_seconds`
- **THEN** it refuses the option, naming the default buyer's refusal

#### Scenario: A buyer whose policy accepts a missing deadline

- **WHEN** a buyer whose terms policy refuses nothing is offered the same option, valid in every other respect and naming an accepted dispute authority
- **THEN** the option is selectable
