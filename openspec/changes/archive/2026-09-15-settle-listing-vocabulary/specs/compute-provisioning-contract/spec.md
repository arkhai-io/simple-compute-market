## MODIFIED Requirements

### Requirement: Versioned executor action submission

A compute provisioner MUST accept a versioned action envelope containing allocation ID, deal reference, offering mode, action kind, idempotency key, and executor-owned parameters, and MUST validate the parameters through the selected adapter before execution. The adapter MUST be selected by the envelope's `offering_mode` together with its action kind, and no model in this contract may name that value `executor_kind`, `offering_type`, or `virtualization_type` — it is the same value the capacity claim carries, the Resource Pool declares deliverable, and the published listing exposes.

Renaming a required field across this contract's models is backwards-incompatible and MUST advance the contract major, and the retired major MUST NOT remain accepted — honouring it would mean honouring the retired spelling of the selector. A caller pinned to any unsupported major is rejected with actionable version information rather than coerced.

This contract MUST NOT re-declare the offering mode's value set as a closed enumeration. The mode crosses this boundary as a validated string resolved against the adapter registry, and the authority that owns mode declarations treats them as opaque strings so a domain may add a mode without editing a shared type.

The contract's `executor_`-prefixed compounds naming the abstraction's own targets, references, and actions retain their names, since `executor` carries its action-dispatch sense in them. Only the selector moves.

#### Scenario: VM action is submitted

- **WHEN** a storefront submits a supported VM action for a committed VM allocation
- **THEN** the provisioner validates the VM payload, returns a durable job ID, and retains all correlation fields

#### Scenario: Bare-metal action is submitted

- **WHEN** a storefront submits a supported bare-metal action for a committed bare-metal allocation
- **THEN** the same endpoint validates it through the bare-metal adapter without interpreting access-grant fields in generic code

#### Scenario: Executor kind is unknown

- **WHEN** no registered adapter supports the requested offering-mode and action pair
- **THEN** the provisioner rejects the action before infrastructure work and preserves the allocation for operator-visible recovery

#### Scenario: A caller pins the retired contract major

- **WHEN** a caller submits an action under the contract major that preceded the selector rename
- **THEN** the action is refused with the supported major identified, and no infrastructure work begins

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
- **AND** each envelope names the offering mode it was produced under

### Requirement: Allocation-backed lease control

The contract MUST support allocation-backed lease registration, inspection, termination, retry release, and force release while retaining the lease's offering mode, its executor action target, and release evidence.

#### Scenario: Lease expires

- **WHEN** a registered lease reaches its end and executor release succeeds
- **THEN** the lease reaches released state and the corresponding site allocation becomes available exactly once

#### Scenario: A lease retains both its mode and its action target

- **WHEN** a lease is registered for a committed allocation
- **THEN** the registration records the offering mode under `offering_mode` and the executor action's target under its retained `executor_`-prefixed name
