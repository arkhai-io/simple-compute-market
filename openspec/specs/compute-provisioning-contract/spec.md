# Compute Provisioning Contract Specification

## Purpose

Define the executor-neutral, versioned caller contract for compute action submission, durable jobs, typed results and credentials, allocation-backed leases, and deal-scoped lifecycle events.

## Requirements

### Requirement: Versioned executor action submission

A compute provisioner MUST accept a versioned action envelope containing allocation ID, deal reference, executor kind, action kind, idempotency key, and executor-owned parameters, and MUST validate the parameters through the selected adapter before execution.

#### Scenario: VM action is submitted

- **WHEN** a storefront submits a supported VM action for a committed VM allocation
- **THEN** the provisioner validates the VM payload, returns a durable job ID, and retains all correlation fields

#### Scenario: Bare-metal action is submitted

- **WHEN** a storefront submits a supported bare-metal action for a committed bare-metal allocation
- **THEN** the same endpoint validates it through the bare-metal adapter without interpreting access-grant fields in generic code

#### Scenario: Executor kind is unknown

- **WHEN** no registered adapter supports the requested executor/action kind
- **THEN** the provisioner rejects the action before infrastructure work and preserves the allocation for operator-visible recovery

### Requirement: Idempotent durable jobs

Action submission MUST be idempotent within allocation/action scope, and every accepted action MUST expose durable queued, running, succeeded, failed, or cancelled state with structured result or error evidence.

#### Scenario: Submission is retried

- **WHEN** a caller repeats an action with the same idempotency key
- **THEN** the provisioner returns the original job identity and does not submit a second executor action

#### Scenario: Job fails

- **WHEN** an executor action terminates with an error
- **THEN** job status exposes the executor kind, allocation and deal correlation, terminal error code/message, and any available logs reference

### Requirement: Typed result and credential envelopes

Terminal job results and credentials MUST identify their executor and result kinds and MUST be validated by the registered adapter before being returned to callers.

#### Scenario: VM creation returns access credentials

- **WHEN** a VM action succeeds with role-scoped credentials
- **THEN** the shared client returns validated generic credential envelopes plus the VM-owned result payload

### Requirement: Allocation-backed lease control

The contract MUST support allocation-backed lease registration, inspection, termination, retry release, and force release while retaining executor identity and release evidence.

#### Scenario: Lease expires

- **WHEN** a registered lease reaches its end and executor release succeeds
- **THEN** the lease reaches released state and the corresponding site allocation becomes available exactly once

### Requirement: Deal-scoped lifecycle events

Provisioner lifecycle events MUST carry stable event identity, allocation ID, deal reference, event kind, and versioned event payload, and event sinks MUST handle duplicate delivery idempotently.

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** the owning storefront can observe correlated started and usage-ready events without the provisioner depending on the full storefront client

### Requirement: Explicit contract incompatibility

Clients and servers MUST reject unsupported major contract versions with actionable version information rather than coercing them through VM-specific or legacy shapes.

#### Scenario: Old client calls new service

- **WHEN** a request uses an unsupported contract major version
- **THEN** the service performs no action and reports the supported version range
