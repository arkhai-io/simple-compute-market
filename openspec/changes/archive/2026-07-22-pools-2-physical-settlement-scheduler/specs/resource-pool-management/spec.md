# Resource pool management delta

## ADDED Requirements

### Requirement: Exactly one scheduling pool

Every resource eligible for physical settlement SHALL belong to exactly one Resource Pool.

#### Scenario: Resource has no pool

- **GIVEN** an otherwise enabled resource with no pool membership
- **WHEN** settlement candidates are evaluated
- **THEN** the resource is excluded as unschedulable.

#### Scenario: Resource appears in multiple pools

- **GIVEN** one physical resource represented as capacity in more than one pool
- **WHEN** configuration is validated
- **THEN** the configuration is rejected because it overstates true capacity.

### Requirement: Pool disablement drains new assignments

Disabling a Resource Pool SHALL exclude it from new Capacity Settlement Assignments. Existing reservations, assignments, physical settlements, and active workloads SHALL NOT prevent disablement and SHALL NOT be invalidated solely by the disable action.

#### Scenario: Disable pool with existing assignment

- **GIVEN** a pool with an existing Capacity Settlement Assignment
- **WHEN** an operator disables the pool
- **THEN** disablement succeeds
- **AND** the existing assignment remains readable.

#### Scenario: New scheduling after disablement

- **GIVEN** a disabled pool
- **WHEN** a new automatic or explicit scheduling request is evaluated
- **THEN** resources in that pool are ineligible.
