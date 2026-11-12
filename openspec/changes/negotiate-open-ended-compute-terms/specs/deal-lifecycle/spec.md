## MODIFIED Requirements

### Requirement: The delivery deadline is the site's availability term

`delivery_deadline_seconds` MUST be a positive integer: the seconds after the later of the commitment instant and the Agreement start within which the resource is available to the buyer, as the storefront's durable `available` record. A compute option whose mechanism has a lifecycle adapter MUST carry the deadline its site enforces where the site enforces one; where it enforces none, it MUST carry the deadline its settlement clause configures, which the seller's deal-servicing journal files non-delivery at, and MUST omit the term where the clause configures none. A default buyer MUST refuse such an option without it, unless explicitly opted out.

#### Scenario: A default buyer meets an option without a deadline

- **WHEN** a default buyer is offered a compute Arkhai payments option with no `delivery_deadline_seconds`
- **THEN** it refuses the option unless its operator has explicitly opted out

### Requirement: Lifecycle terms are part of the selected option

The shared codec MUST own optional lifecycle terms beside price and schema-owned settlement parameters. The canonical option ID MUST include price, settlement and lifecycle, omitting lifecycle when absent. Compute delivery deadlines MUST follow site policy where the site enforces one, else the settlement clause's configured deadline, and MUST follow default buyer acceptance; bond MUST remain reserved until supported.

#### Scenario: A term changes the option ID

- **WHEN** a seller changes an option's dispute window and republishes
- **THEN** the option has a new option ID

#### Scenario: The delivery deadline is the site's

- **WHEN** a compute storefront publishes an option for a pool whose effective `delivery_deadline_seconds` is 1800
- **THEN** the option's `lifecycle.delivery_deadline_seconds` is 1800 and the site's activation deadline for a deal on it is the same 1800 seconds after the later of the commitment instant and the Agreement start
- **AND** a pool that enforces no deadline yields an option carrying its settlement clause's configured deadline, or, where the clause configures none, an option without the term, which the default buyer refuses
