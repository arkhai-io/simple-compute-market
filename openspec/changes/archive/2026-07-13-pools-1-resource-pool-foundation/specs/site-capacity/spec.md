## MODIFIED Requirements

### Requirement: Executor-neutral site authority

The site authority MUST own Physical Resources, settlement-relevant Resource Pool identities, Capacity Reservations, committed allocations, deal ownership references, capacity versions, and capacity events without depending on lease watchdogs, job runners, or concrete executor teardown states. A provisioner MAY stage administrative pool membership and provider configuration, but those records MUST NOT alter settlement selection until integrated through the site-authority boundary.

#### Scenario: Allocation is committed

- **WHEN** a valid Capacity Reservation is committed for executor work
- **THEN** the site authority records its allocation identity, physical accounting mode, executor kind, and deal ownership while leaving execution policy to the compute lifecycle

#### Scenario: Generic site package is installed alone

- **WHEN** site authority modules are imported without VM or bare-metal provisioning packages
- **THEN** resource, reservation, allocation, and event behavior remains available without concrete executor imports

#### Scenario: Administrative pool is created before settlement integration

- **WHEN** an operator creates or assigns hosts to a provisioning resource pool during POOLS-1
- **THEN** existing site-capacity reservation and allocation selection behavior remains unchanged
