# Compute Provisioning Contract Specification

## Purpose

Define the offering-mode-neutral, versioned caller contract for compute action submission, durable jobs, typed results and credentials, allocation-backed leases, fulfillment scheduling and acceptance, and deal-scoped lifecycle events.

## Requirements

### Requirement: Versioned executor action submission

A compute provisioner MUST accept a versioned action envelope containing allocation ID, deal reference, offering mode, action kind, idempotency key, and executor-owned parameters, and MUST validate the parameters through the selected adapter before execution. The adapter MUST be selected by the envelope's `offering_mode` together with its action kind, and no model in this contract may name that value `executor_kind`, `offering_type`, or `virtualization_type` — it is the same value the capacity claim carries, the Resource Pool declares deliverable, and the published listing exposes.

Renaming a required field across this contract's models is backwards-incompatible and MUST advance the contract version, so a caller pinned to the previous version is rejected with actionable version information rather than coerced.

The contract's `executor_`-prefixed compounds naming the abstraction's own targets, references, and actions retain their names, since `executor` carries its action-dispatch sense in them. Only the selector moves.

#### Scenario: VM action is submitted

- **WHEN** a storefront submits a supported VM action for a committed VM allocation
- **THEN** the provisioner validates the VM payload, returns a durable job ID, and retains all correlation fields

#### Scenario: Bare-metal action is submitted

- **WHEN** a storefront submits a supported bare-metal action for a committed bare-metal allocation
- **THEN** the same endpoint validates it through the bare-metal adapter without interpreting access-grant fields in generic code

#### Scenario: Offering mode is unknown

- **WHEN** no registered adapter supports the requested offering-mode and action pair
- **THEN** the provisioner rejects the action before infrastructure work and preserves the allocation for operator-visible recovery

#### Scenario: An action envelope names the mode under a retired key

- **WHEN** a caller submits an action envelope carrying the requested mode under `executor_kind`
- **THEN** the envelope is rejected as carrying no offering mode rather than being accepted under a second spelling

### Requirement: Idempotent durable jobs

Action submission MUST be idempotent within allocation/action scope, and every accepted action MUST expose durable queued, running, succeeded, failed, or cancelled state with structured result or error evidence.

#### Scenario: Submission is retried

- **WHEN** a caller repeats an action with the same idempotency key
- **THEN** the provisioner returns the original job identity and does not submit a second executor action

#### Scenario: Job fails

- **WHEN** an executor action terminates with an error
- **THEN** job status exposes the offering mode, allocation and deal correlation, terminal error code/message, and any available logs reference

### Requirement: Typed result and credential envelopes

Terminal job results and credentials MUST identify the offering mode they were produced under and their own result or credential kinds, and MUST be validated by the registered adapter before being returned to callers.

#### Scenario: VM creation returns access credentials

- **WHEN** a VM action succeeds with role-scoped credentials
- **THEN** the shared client returns validated generic credential envelopes plus the VM-owned result payload

### Requirement: Allocation-backed lease control

The contract MUST support allocation-backed lease registration, inspection, termination, retry release, and force release while retaining the lease's offering mode, its executor action target, and release evidence.

#### Scenario: Lease expires

- **WHEN** a registered lease reaches its end and executor release succeeds
- **THEN** the lease reaches released state and the corresponding site allocation becomes available exactly once

### Requirement: Fulfillment scheduling and acceptance

The shared client MUST expose `schedule_resource`, `begin_fulfillment`, `get_fulfillment_status`, and `get_fulfillment_result` as generic, offering-mode-neutral operations alongside action submission and lease control, since fulfillment scheduling and acceptance is domain-neutral kit behavior (see `openspec/specs/fulfillment/spec.md`), not a VM-specific concern requiring its own client package. A caller MUST schedule a resource before it can begin fulfillment for the same capacity reservation.

#### Scenario: Storefront schedules then begins fulfillment through the shared client

- **WHEN** a caller invokes `schedule_resource` and then `begin_fulfillment` for the same capacity reservation through the shared client
- **THEN** the second call succeeds using the resource the first call assigned, with no VM-specific type imported by the caller to do so

#### Scenario: Client is reused for bare-metal fulfillment

- **WHEN** a bare-metal caller uses the same shared client's fulfillment methods
- **THEN** it succeeds without importing VM-owned request or result models, matching the "Compute-owned caller contract" requirement `openspec/specs/physical-provisioning/spec.md` already establishes for action submission and lease control

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
