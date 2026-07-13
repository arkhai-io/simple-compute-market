## ADDED Requirements

### Requirement: Executor-neutral site authority

The site authority MUST own Physical Resources, Resource Pools, Capacity Reservations, committed allocations, deal ownership references, capacity versions, and capacity events without depending on lease watchdogs, job runners, or concrete executor teardown states.

#### Scenario: Allocation is committed

- **WHEN** a valid Capacity Reservation is committed for executor work
- **THEN** the site authority records its allocation identity, physical accounting mode, executor kind, and deal ownership while leaving execution policy to the compute lifecycle

#### Scenario: Generic site package is installed alone

- **WHEN** site authority modules are imported without VM or bare-metal provisioning packages
- **THEN** resource, reservation, allocation, and event behavior remains available without concrete executor imports

### Requirement: Idempotent release recording

The site authority MUST record release exactly once for an allocation and advance capacity version only when the authoritative allocation transition commits.

#### Scenario: Release command is repeated

- **WHEN** the compute lifecycle repeats a successful release command with the same allocation identity
- **THEN** the site authority returns the released state without duplicating capacity or event transitions

### Requirement: Separate capacity and deal event semantics

Capacity projection events MUST remain anonymous and versioned, while deal-scoped lifecycle events MUST retain the owning deal/storefront reference recorded on the allocation.

#### Scenario: Allocation changes capacity and deal state

- **WHEN** an executor lifecycle transition releases an allocation
- **THEN** projection subscribers can reconcile from the capacity version and the owning storefront can correlate its deal event without either channel exposing the other's private payload
