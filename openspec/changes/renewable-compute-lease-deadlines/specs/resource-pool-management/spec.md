## ADDED Requirements

### Requirement: Providers declare provisioning allowance support and defaults

Composition MUST declare a positive integer allowance default for VM/bare-metal providers and no support for API credits. A supporting pool MUST resolve its provisioning_allowance_seconds override or provider default; unsupported providers MUST resolve none. The site MUST receive the effective allowance through its session-scoped pool-facts port, not caller input.

#### Scenario: A compute pool has no explicit override

- **WHEN** an enabled VM or bare-metal pool omits provisioning_allowance_seconds
- **THEN** it resolves its provider's declared default, not an absent deadline

#### Scenario: A quota provider declares none

- **WHEN** the API-credits composition resolves its quota pool's allowance
- **THEN** no allowance resolves and the site needs no API-credit-specific rule

#### Scenario: The ledger reads the allowance

- **WHEN** the site commits a reservation
- **THEN** it reads the allowance through the injected pool-facts port in the commit transaction without importing the pool authority

### Requirement: Activation safeguards are explicitly enabled by composition

The compute composition MUST expose activation_deadlines_enabled, default false. While false, the pool-facts port MUST supply no effective allowance without disabling provider support or pool validation. Enablement MUST affect only new commits; disabling MUST NOT clear snapshotted deadlines. Production enablement MUST wait for the delivery caller owner's qualification.

#### Scenario: Site code lands before compatible callers

- **WHEN** the site upgrades with the default setting
- **THEN** new commits retain null deadline and phase and existing leases stay unchanged

#### Scenario: Protection is enabled then disabled

- **WHEN** a qualified deployment enables protection, commits a lease, then disables it
- **THEN** that lease retains its deadline and later new commits receive null fields
- **AND** invalid pool overrides remain invalid in either setting

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
