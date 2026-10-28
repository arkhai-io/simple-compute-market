# Compute Provisioning Contract Specification

## Purpose

Define the offering-mode-neutral, versioned caller contract for durable jobs, typed results and credentials, allocation-backed leases, fulfillment scheduling and acceptance, and deal-scoped lifecycle events.

## Requirements

### Requirement: Idempotent durable jobs

Job submission MUST be idempotent within allocation/action scope, and every submitted job MUST expose durable queued, running, succeeded, failed, or cancelled state with structured result or error evidence. Jobs are submitted by fulfillment providers on behalf of a fulfillment, not by callers of the contract. A job identity — a request's operation identity, or the reservation, action, and idempotency key a fulfillment provider submits under — stands for one job's content: a repeat with the same job parameters MUST return the original job, and a repeat with different parameters MUST be refused. The identity a provider submits under carries no job content of its own.

#### Scenario: Submission is retried

- **WHEN** a fulfillment provider repeats a job submission with the same operation identity
- **THEN** the job authority returns the original job identity and does not submit a second executor action

#### Scenario: A retried submission names different parameters

- **WHEN** a fulfillment provider repeats a submission under the same identity with different job parameters
- **THEN** the job authority refuses it, records no second job, and the original job is unchanged

#### Scenario: Job fails

- **WHEN** an executor action terminates with an error
- **THEN** job status exposes the offering mode, allocation and deal correlation, terminal error code/message, and any available logs reference

### Requirement: Typed result and credential envelopes

Terminal job results and credentials MUST identify the offering mode they were produced under and their own result or credential kinds, and MUST be validated by the domain's codec before they reach a fulfillment result.

#### Scenario: VM creation returns access credentials

- **WHEN** a VM create job succeeds with role-scoped credentials
- **THEN** the fulfillment result carries validated generic credential envelopes plus the VM-owned result payload

### Requirement: Allocation-backed lease control

The contract MUST support allocation-backed lease inspection, termination, retry release, and force release while retaining the lease's offering mode, its executor action target, and release evidence. It MUST NOT offer lease registration: commit records a lease's window, and provisioning its executor target when the allocation's fulfillment becomes active.

#### Scenario: Lease expires

- **WHEN** a lease reaches its end and executor release succeeds
- **THEN** the lease reaches released state and the corresponding site allocation becomes available exactly once

### Requirement: Fulfillment scheduling and acceptance

The shared client MUST expose `schedule_resource`, `begin_fulfillment`, `get_fulfillment_status`, and `get_fulfillment_result` as generic, offering-mode-neutral operations alongside lease control, since fulfillment scheduling and acceptance is domain-neutral kit behavior (see `openspec/specs/fulfillment/spec.md`), not a VM-specific concern requiring its own client package. A caller MUST schedule a resource before it can begin fulfillment for the same capacity reservation. Fulfillment is the only way a caller asks for delivery.

#### Scenario: Storefront schedules then begins fulfillment through the shared client

- **WHEN** a caller invokes `schedule_resource` and then `begin_fulfillment` for the same capacity reservation through the shared client
- **THEN** the second call succeeds using the resource the first call assigned, with no VM-specific type imported by the caller to do so

#### Scenario: Client is reused for bare-metal fulfillment

- **WHEN** a bare-metal caller uses the same shared client's fulfillment methods
- **THEN** it succeeds without importing VM-owned request or result models, matching the "Compute-owned caller contract" requirement `openspec/specs/physical-provisioning/spec.md` establishes for lease control

### Requirement: Deal-scoped lifecycle events

When a lease's release completes and its capacity returns to the site, the provisioner MUST notify the owning storefront through the storefront's capacity-released callback: a `service`-role signed request carrying the reservation ID, the site ID, and the release time when known. Its request identity MUST be derived from a stable identity of that release, so a retried notification is an exact replay, and the provisioner MUST retry it from durable state until the storefront acknowledges it. The provisioner's internal lifecycle event, which carries the event identity, deal reference, and event kind, is not sent. Capacity release is the one fulfillment transition a provisioner pushes to a storefront; a storefront learns every other transition by reading the fulfillment.

#### Scenario: A reservation's capacity is released

- **WHEN** a lease's release completes and its capacity returns to the site
- **THEN** the owning storefront receives one capacity-released notification for the reservation, signed by the provisioner under the `service` role

#### Scenario: The storefront's acknowledgement is lost

- **WHEN** the provisioner sends a capacity-released notification and does not learn that the storefront acknowledged it
- **THEN** it resends the notification under the same request identity, and the storefront answers it as an exact replay

#### Scenario: Provisioning succeeds

- **WHEN** an executor action progresses from accepted to usage-ready
- **THEN** no notification is sent, and the storefront observes the transition through the fulfillment's status

### Requirement: Explicit contract incompatibility

Clients and servers MUST reject unsupported major contract versions with actionable version information rather than coercing them through VM-specific or legacy shapes. The contract's major is 3, and every party MUST accept only major 3. A versioned contract is versioned rather than changed in place: a major-3 schedule response names its resource's host, and a major-3 lease has no `provisioning_failed` state. A major-2 schedule response names no host, which a caller comparing hosts would otherwise refuse as a conflict with its terms rather than by version. A provisioning service and the storefronts and clients that call it MUST therefore be upgraded, and rolled back, together.

#### Scenario: Old client calls new service

- **WHEN** a request uses an unsupported contract major version
- **THEN** the service performs no action and reports the supported version range

#### Scenario: A storefront calls a service that has not been upgraded

- **WHEN** a major-3 storefront schedules a resource through a service answering major 2
- **THEN** the storefront refuses the answer, naming the supported major, and begins nothing

### Requirement: A schedule response names the scheduled resource's host and machine

A schedule response MUST carry the `host_id` of the resource it scheduled, taken from that
resource's capacity declaration, and MUST omit it when the declaration names no host. The
resource's physical machine MUST be its `physical_host_id` in the response's top-level
attributes. A caller compares what was scheduled with what it sold from these, without
reading the declaration's publication settings.

#### Scenario: A whole host is scheduled

- **WHEN** a caller schedules a resource whose declaration names a host and a physical
  machine
- **THEN** the schedule response carries that `host_id`, and its top-level attributes carry
  that `physical_host_id`

#### Scenario: A resource with no host is scheduled

- **WHEN** a caller schedules a resource whose declaration names no host, from a pool whose
  provider needs none
- **THEN** the schedule response omits `host_id` and the schedule succeeds
