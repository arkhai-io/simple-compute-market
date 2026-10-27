## ADDED Requirements

### Requirement: Durable capacity-reservation settlement identity

The provisioning service MUST maintain exactly one durable fulfillment
aggregate for each accepted `capacity_reservation_id`. `begin_fulfillment`
MUST be idempotent by `capacity_reservation_id`: equivalent retries return the
same `fulfillment_id`, while conflicting reuse fails before provider command
submission.

#### Scenario: Equivalent fulfillment retry
- **WHEN** `begin_fulfillment` is repeated with an equivalent request for an
  already accepted capacity reservation
- **THEN** the existing `fulfillment_id` and state are returned and no second
  fulfillment aggregate is created

#### Scenario: Conflicting fulfillment retry
- **WHEN** the same capacity reservation is reused with conflicting selected
  resource, provider, requirements, or fulfillment identity
- **THEN** the request fails before any provider command is submitted

### Requirement: Separate scheduling and fulfillment acceptance

The provisioning service MUST expose scheduling and beginning fulfillment as
separate operations. Scheduling MUST accept a local `capacity_reservation_id`
and requirements that do not exceed the reservation, and MUST return the
selected settlement resource without beginning provider execution.
`begin_fulfillment` MUST resolve the durable scheduled assignment by
`capacity_reservation_id` and MUST NOT accept an arbitrary caller-selected
resource as authoritative.

#### Scenario: Resource selected before fulfillment
- **WHEN** the storefront schedules an active capacity reservation
- **THEN** the selected settlement resource is persisted and returned without
  submitting a provider command

#### Scenario: Unknown owning authority
- **WHEN** a site receives an unknown reservation, pool, or resource identifier
- **THEN** it rejects the request and does not forward, reinterpret, or fall
  back to another site

### Requirement: Atomic scheduling persistence

Capacity reassignment, where required for fair scheduling, and durable
settlement-record creation or transition MUST commit in one database
transaction. A changed requirement MUST supersede the capacity reservation
rather than mutate an accepted assignment under the same identifier.

#### Scenario: Crash during assignment transaction
- **WHEN** scheduling fails before the transaction commits
- **THEN** neither the capacity movement nor the settlement assignment is
  visible

#### Scenario: Reservation requirements change
- **WHEN** requirements change after an assignment is accepted
- **THEN** the original reservation is superseded and a new reservation is
  scheduled rather than mutating the existing assignment

### Requirement: Fulfillment and provisioned-resource identities

`begin_fulfillment` MUST return a durable `fulfillment_id`. A fulfillment MUST
support zero or more provisioned-resource outputs, each with a globally unique
`provisioned_resource_id` and an optional domain-specific reference. Whole
fulfillment status and teardown MUST use `fulfillment_id`; cross-domain
contracts MUST NOT use VM-specific identifiers as the generic teardown
identity.

#### Scenario: Multi-resource fulfillment representation
- **WHEN** one fulfillment creates multiple independently identifiable outputs
- **THEN** all outputs are represented under the same `fulfillment_id` with
  distinct `provisioned_resource_id` values

### Requirement: Versioned prepared provider operations

Before committing a pending provider-command state, the provider MUST prepare
and validate a normalized serializable payload containing a schema version and
kind discriminator. Recovery MUST dispatch from the stored payload and MUST
NOT reconstruct accepted input from mutable live pool or host configuration.

#### Scenario: Pool configuration changes after acceptance
- **WHEN** provider configuration changes after fulfillment acceptance but
  before a recovery retry
- **THEN** the retry uses the original stored prepared payload

### Requirement: Deterministic provider command idempotency

Create and teardown provider commands MUST use the job service's
contract-based deduplication path with deterministic identifiers derived from
`capacity_reservation_id` or `fulfillment_id`, action kind, and command schema
version. Repeated or concurrent submission of the same logical action MUST
observe one underlying job.

#### Scenario: Recovery retries create submission
- **WHEN** a pending create command is retried after an uncertain submission
- **THEN** at most one underlying create job is enqueued and the existing job
  identity is observed

#### Scenario: Recovery retries teardown submission
- **WHEN** a pending teardown command is retried after an uncertain submission
- **THEN** at most one underlying teardown job is enqueued and the existing job
  identity is observed

### Requirement: Provisioning-owned lifecycle convergence

After `begin_fulfillment` is durably accepted, the provisioning service MUST
own provider submission, retry, provider-status convergence, output
persistence, settlement-result delivery, teardown, and final physical-resource
reclamation. Progress MUST NOT depend on storefront polling.

Pending and in-progress work MUST be recovered periodically through durable
claims that stay safe under concurrent claim attempts; on the service's SQLite
database the single writer serializes those attempts, which is not a
distributed multi-replica protocol. Database locks MUST be released before
external provider calls.

#### Scenario: Process restarts after acceptance
- **WHEN** the provisioning process restarts with a pending or in-progress
  fulfillment
- **THEN** periodic recovery resumes and converges the lifecycle without a new
  storefront command

#### Scenario: Worker dies after claiming work
- **WHEN** a worker dies after committing a claim but before completing the
  external call
- **THEN** the claim expires and another worker can safely retry the operation

### Requirement: Durable fulfillment status and result queries

The provisioning service MUST expose `get_fulfillment_status(fulfillment_id)`
and `get_fulfillment_result(fulfillment_id)` over the existing
storefront→provisioning authenticated channel. Both MUST read directly
from durably persisted fulfillment state; neither requires a separate
delivery-acknowledgement mechanism, since a read reflects current state
on demand rather than requiring retry-until-acknowledged delivery.

The provisioning service does not push `SettlementResult` to the
storefront, and this requirement's durability guarantee does not depend
on push delivery: a terminal or otherwise reportable fulfillment
transition commits atomically with the state these queries read,
regardless of whether or when it is polled.

#### Scenario: Status query after process restart
- **WHEN** `get_fulfillment_status` is called for a fulfillment whose
  provisioning process previously restarted mid-lifecycle
- **THEN** it returns the current, recovered state without requiring the
  storefront to have polled during the restart window

#### Scenario: Result query for a completed fulfillment
- **WHEN** `get_fulfillment_result` is called for a fulfillment that
  reached a terminal successful state
- **THEN** it returns the normalized result and, if applicable,
  credentials obtained fresh for this call

#### Scenario: Repeated result queries are idempotent by construction
- **WHEN** `get_fulfillment_result` is called more than once for the same
  `fulfillment_id`
- **THEN** each call independently reflects current durable state; no
  deduplication bookkeeping is required because reads have no delivery
  side effect to duplicate

### Requirement: Credentials stay with the job authority and are read on demand

Raw credentials MUST NOT be persisted in the fulfillment aggregate, its
settlement records or provider metadata, or any result row. The job
authority's records of the credentials its jobs' executors reported are the
only provisioning store that holds them. `get_fulfillment_result` MUST read
the credentials its fulfillment's create job reported from that store at the
moment it is called, only for an `active` fulfillment, and MUST return them
only in that response over the authenticated channel.

#### Scenario: Fulfillment succeeds but is never queried
- **WHEN** a fulfillment reaches a successful terminal state and
  `get_fulfillment_result` is never called
- **THEN** fulfillment remains successful and credentials remain
  obtainable on demand whenever the storefront does call, with no
  separate delivery-retry state to manage

### Requirement: Atomic abandonment and release

Transitioning an unfulfilled assigned settlement to `abandoned` and releasing
or superseding its capacity reservation MUST occur in one database
transaction. Lease lifecycle code SHOULD perform this transition directly;
periodic watchdog processing MUST reconcile missed transitions.

#### Scenario: Reservation expires before fulfillment begins
- **WHEN** an assigned reservation expires before `begin_fulfillment`
- **THEN** the assignment becomes abandoned and its held capacity is released
  atomically

### Requirement: Active fulfillment migration

The migration MUST place existing hosts into a default resource pool and MUST
backfill settlement/fulfillment records for every active or releasing VM
capacity reservation. It MUST infer the selected resource, provider, and
versioned teardown input from durable fields used by the existing release
path. Historical create input MAY be absent for already-active fulfillments.
The migration MUST fail when an active reservation cannot be mapped
unambiguously.

#### Scenario: Existing active VM
- **WHEN** the migration encounters an active VM with resolvable host, target,
  and executor metadata
- **THEN** it creates a backfilled fulfillment record capable of durable
  teardown without a legacy release branch

#### Scenario: Ambiguous active VM mapping
- **WHEN** an active VM cannot be mapped unambiguously to a resource and
  teardown input
- **THEN** migration fails visibly rather than creating a partial record

## MODIFIED Requirements

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job; the resolved playbook is the pool's `playbook_path` when the pool states one, and otherwise the service's `vm_playbook_path` as configured when the job is prepared. Create metadata MUST retain the exact `host_id` and `executor_target` (the guest provisioning named), and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

Reservation-governed VM shape is resolved from the committed reservation dimensions carried by the scheduled settlement resource. Caller-supplied sizing fields do not override or fill missing committed dimensions. For each dimension absent from the committed reservation, the adapter MAY apply the corresponding pool default; if neither a committed dimension nor a pool default exists, the provider input remains unset and the selected playbook or inventory supplies its own default. The pool-selected registered requirement delegate owns conversion from canonical VM dimensions into the selected playbook's variable names, units, and derived values.

A VM fulfillment request MUST NOT say how its guest is reached, and the adapter MUST refuse one that carries a `connectivity` field or any other field the request does not declare. Which relay a host dials is a durable property of the deployment, recorded on the relay a pool references, and MUST NOT be selectable per request: a request-supplied relay would make a fleet-wide fact depend on a caller's configuration and would let two requests for one host disagree about how that host is reached. The buyer-facing address and port are returned in the fulfillment result rather than supplied with the request. The refusal happens while the request is prepared, inside the transaction that would accept it, so a refused request is never stored and nothing it carried, such as a relay credential, is kept at rest.

#### Scenario: A request supplies relay configuration

- **WHEN** a fulfillment request's payload carries a `connectivity` field, such as a relay address, domain, or dashboard credential
- **THEN** validation reports the request invalid, `begin_fulfillment` refuses it, and no fulfillment is accepted, no job is dispatched, and the request is not stored

#### Scenario: Pool configuration changes after create dispatch

- **WHEN** an operator edits provider configuration after an Ansible create job is accepted
- **THEN** the accepted job retains the resolved configuration snapshot captured at dispatch

#### Scenario: Provider variables collide with job identity

- **WHEN** pool-supplied extra variables attempt to override an authoritative host, target, action, sizing, or executor field
- **THEN** validation rejects the operation before asynchronous dispatch

#### Scenario: VM teardown is dispatched

- **WHEN** teardown begins for an accepted VM fulfillment
- **THEN** the adapter targets the recorded `host_id` and `executor_target` from fulfillment metadata

#### Scenario: A committed dimension is present

- **WHEN** the scheduled settlement resource carries a committed VM dimension
- **THEN** the adapter translates that value through the pool-selected requirement delegate and ignores any conflicting caller-supplied sizing field

#### Scenario: A committed dimension is absent and the pool has a default

- **WHEN** the committed reservation omits a VM dimension and the resolved pool configures the corresponding default
- **THEN** the adapter uses the pool default for that dimension

#### Scenario: A committed dimension and pool default are both absent

- **WHEN** neither the committed reservation nor the resolved pool supplies a VM dimension
- **THEN** the adapter leaves the corresponding provider input unset so the selected playbook or inventory may supply its own default

#### Scenario: A VM pool states no playbook

- **WHEN** a VM job is prepared for a pool whose provider configuration states no `playbook_path`
- **THEN** the job's stored parameters carry the service's `vm_playbook_path` as configured at preparation
