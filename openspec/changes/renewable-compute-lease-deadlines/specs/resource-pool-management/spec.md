## ADDED Requirements

### Requirement: Providers declare provisioning allowance support and defaults

Provider declarations supplied by composition MUST state a positive integer provisioning allowance default or no allowance support. VM and bare-metal compute providers MUST declare defaults; the API-credits provider MUST declare none. A supporting pool MUST resolve its `provisioning_allowance_seconds` override or the provider default. A provider declaring none MUST resolve no allowance. The site MUST receive the resolved fact through its session-scoped pool-authority port.

#### Scenario: A compute pool has no explicit override

- **WHEN** a VM or bare-metal pool omits provisioning_allowance_seconds
- **THEN** it resolves its provider's declared default, not an absent deadline

#### Scenario: A quota provider declares none

- **WHEN** the API-credits composition resolves its quota pool's allowance
- **THEN** no allowance resolves and the site needs no API-credit-specific rule

#### Scenario: The ledger reads the allowance

- **WHEN** the site commits a reservation
- **THEN** it reads the allowance through the injected pool-facts port in the commit transaction without importing the pool authority

### Requirement: Provisioning allowance overrides are strictly validated and snapshotted

Pool create, replace, patch and document import MUST accept an allowance override only for a supporting provider and only as a positive integer number of seconds, excluding booleans. Explicit null, zero, negative and fractional values MUST be refused. Validate-only and applying writes MUST agree, and invalid imports MUST remain atomic. Pool policy changes MUST NOT alter deadlines already recorded by committed leases.

#### Scenario: An operator supplies a valid override

- **WHEN** a supporting pool is written with a positive integer allowance
- **THEN** its later commits use that override instead of the provider default

#### Scenario: An override attempts to disable the deadline

- **WHEN** an operator supplies zero, null or another invalid allowance value
- **THEN** the write is refused without changing the pool

#### Scenario: A provider without support receives an override

- **WHEN** an allowance override is supplied for a provider declaring none
- **THEN** the write is refused rather than silently enabling deadline behavior

#### Scenario: An invalid pool occurs in an import

- **WHEN** any pool in a document has an invalid allowance
- **THEN** validate-only reports the error and applying the import changes no pool

#### Scenario: Pool defaults change after commit

- **WHEN** a provider default or pool override changes after a lease is committed
- **THEN** the lease's recorded deadline remains unchanged
