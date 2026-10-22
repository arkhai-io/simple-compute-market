## ADDED Requirements

### Requirement: Hosted authorities derive from the clause

An `arkhai.payments.v1` mandate MUST list the payee alone as `start` authority. Its `stop` authorities MUST be the initiators the selected option's `early_termination` entitlements name, or the mechanism's defaults for the part shape when the option has no clause.

#### Scenario: An on-demand mandate is derived

- **WHEN** a mandate is derived from an option whose clause has a `payer` entitlement only
- **THEN** the payer is the only stop authority and the payee the only start authority

### Requirement: Alkahest interruption is option configuration

The Alkahest interruptible release model MUST configure the Alkahest option it applies to and MUST NOT mark the listing as a whole. A listing MUST NOT carry a listing-level interruptible marker.

#### Scenario: A storefront offers hosted and interruptible Alkahest options

- **WHEN** a VM listing publishes a hosted option and an Alkahest option with the interruptible release model
- **THEN** only the Alkahest option's release condition describes interruption, and the listing resource has no interruptible field
