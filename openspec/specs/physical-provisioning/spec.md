# Physical Provisioning Specification

## Purpose

Define scheduling, fulfillment execution, durable settlement records, jobs, and lease release behavior.

## Requirements

### Requirement: Scheduler-owned resource binding
A PhysicalSettlementScheduler MUST atomically bind an allocation/agreement to a Settlement Resource before a FulfillmentProvider executes create operations.

#### Scenario: Provider cannot use selected resource
- **WHEN** provider validation rejects the selected Settlement Resource
- **THEN** the provider reports failure and does not silently substitute another resource outside the scheduler boundary

### Requirement: Idempotent fulfillment
Fulfillment creation MUST be idempotent by `allocation_id`, and durable settlement state MUST retain the selected resource, provider, lifecycle state, and opaque provider metadata.

#### Scenario: Create request is retried
- **WHEN** the same allocation is submitted after an uncertain response
- **THEN** provisioning returns or resumes the existing settlement instead of double-provisioning

### Requirement: Executor-dispatched lifecycle
Market-managed create, status, and release MUST dispatch by executor kind; direct VM host administration endpoints MAY remain separate operator surfaces.

#### Scenario: Bare-metal allocation is released
- **WHEN** its lease lifecycle invokes release
- **THEN** dispatch selects the bare-metal reclaim executor rather than VM teardown

### Requirement: Durable asynchronous jobs
Provisioning operations MUST expose durable job identity and terminal status while the in-process worker queue executes provider actions.

#### Scenario: Client polls an accepted job
- **WHEN** the worker completes or fails the action
- **THEN** the job status exposes a terminal result or error linked to the allocation/deal

### Requirement: Allocation-backed lease release
Lease expiry MUST invoke the configured executor release delegate before capacity is reported released; failed release MUST remain observable and operator-repairable.

#### Scenario: Teardown fails
- **WHEN** the release delegate returns a failure
- **THEN** capacity remains unavailable, the lease enters `release_failed`, and retry/force-release controls remain available

<!-- Provenance: ARCHITECTURE.md provisioning and lease lifecycle sections; evidence: provisioning API, job queue, LeaseLifecycleService, executor dispatch and integration tests -->
