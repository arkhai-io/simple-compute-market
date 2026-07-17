# Physical provisioning delta

## ADDED Requirements

### Requirement: Capacity Settlement Assignment lifecycle

The provisioning domain SHALL distinguish Capacity Reservation, Capacity Settlement Assignment, Physical Settlement, and Provisioned Resource / Active Workload. A Capacity Settlement Assignment SHALL identify one concrete Settlement Resource but SHALL NOT by itself indicate that provisioning succeeded or that a workload is active.

#### Scenario: Assignment precedes physical settlement

- **GIVEN** an active Capacity Reservation
- **WHEN** scheduling succeeds
- **THEN** the service records a Capacity Settlement Assignment
- **AND** provider-specific physical settlement remains a separate downstream operation.

### Requirement: Idempotent assignment

The provisioning domain SHALL create at most one Capacity Settlement Assignment for an unchanged Capacity Reservation. Retrying the same allocation SHALL return the existing assignment without rerunning scheduling policy or advancing policy cursors.

#### Scenario: Retry returns the same resource

- **GIVEN** a reservation already assigned to a Settlement Resource
- **WHEN** the same unchanged reservation is scheduled again
- **THEN** the existing assignment is returned
- **AND** no new policy choice is made.

#### Scenario: Conflicting explicit retry

- **GIVEN** a reservation already assigned to one Settlement Resource
- **WHEN** a retry requests a different explicit resource
- **THEN** scheduling fails with a request-mismatch error.

### Requirement: Explicit selection preserves eligibility

An explicit resource identifier SHALL bypass policy choice but SHALL NOT bypass allocation, agreement, expiry, pool, resource, shape, attribute, or capacity eligibility checks. Explicit selection SHALL NOT advance automatic round-robin cursors.

#### Scenario: Explicit resource in disabled pool

- **GIVEN** an enabled resource in a disabled pool
- **WHEN** that exact resource is requested
- **THEN** scheduling rejects the request as ineligible.

### Requirement: Replaceable executor-neutral policy

Generic scheduling orchestration SHALL depend on a replaceable scheduling-policy protocol. Policy implementations SHALL receive eligible executor-neutral candidates and SHALL NOT depend on market-specific executor persistence models.

#### Scenario: VM host model is not required

- **GIVEN** generic candidates containing resource kind, units, pool identity, provider, and opaque attributes
- **WHEN** the policy selects a candidate
- **THEN** no VM Host ORM lookup is required.

### Requirement: Deterministic MVP policy

The initial automatic policy SHALL choose deterministically by round-robin across sorted eligible pool IDs and then sorted eligible resource IDs in the chosen pool.

#### Scenario: Pool fairness

- **GIVEN** two eligible pools with eligible resources
- **WHEN** three independent reservations are automatically assigned
- **THEN** the selected pools follow a stable alternating sequence.

#### Scenario: Ineligible pool is skipped

- **GIVEN** a previously selected pool that becomes disabled or has no eligible resource
- **WHEN** the next assignment is selected
- **THEN** the policy selects from the remaining eligible pools deterministically.
