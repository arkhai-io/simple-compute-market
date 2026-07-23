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

### Requirement: Resource-kind-scoped provider routing

The provisioning service MUST resolve fulfillment providers using the selected resource's exact `(provider, resource_kind)` pair. Different domain adapters MAY register the same infrastructure provider identity for distinct resource kinds. Dispatch MUST NOT fall through to a provider registered for another resource kind.

#### Scenario: VM and bare-metal resources use Ansible
- **WHEN** both resource kinds are assigned from pools whose provider identity is `ansible`
- **THEN** each fulfillment is dispatched to its own domain adapter's scoped Ansible provider

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

Pending and in-progress work MUST be recovered periodically with a
multi-replica-safe claim/lease mechanism. Database locks MUST be released
before external provider calls.

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

Push-based delivery of `SettlementResult` to the storefront is out of
scope for this requirement — see `provisioning-result-push-delivery`
(separate change, not yet started). This requirement's durability
guarantee is unaffected by that change's absence: a terminal or
otherwise reportable fulfillment transition commits atomically with the
state these queries read, regardless of whether or when it is polled.

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

### Requirement: Fulfillment APIs authenticate durable storefront ownership

The provisioning service MUST authenticate fulfillment callers from operator-configured credentials rather than caller-asserted identity headers. Capacity reservation creation MUST bind an opaque authenticated storefront principal, scheduling and fulfillment acceptance MUST preserve that owner, and status, result, and teardown MUST fail without revealing existence when called by another valid principal.

#### Scenario: Another storefront knows a fulfillment identifier
- **WHEN** a valid but non-owning storefront principal requests status, result, or teardown for the fulfillment
- **THEN** the provisioning service returns not found and exposes no fulfillment state or credential material

#### Scenario: Caller asserts another agent identity
- **WHEN** a caller changes an unauthenticated identity header while retaining the same credential
- **THEN** authority remains bound to the credential's configured principal and the header grants no additional ownership

### Requirement: Credentials are fetched on read, never persisted at rest

Raw credentials MUST NOT be persisted in settlement records, generic JSON
columns, or any other durable storage. `get_fulfillment_result`'s handler
MUST obtain or refresh credentials at the moment it is called, return
them only in that response over the authenticated encrypted channel, and
MUST NOT persist them afterward. Where credentials can rotate, each
response MUST include a monotonic `credential_generation` so a caller
holding an earlier cached response can detect staleness.

#### Scenario: Credentials rotate between two queries
- **WHEN** credentials are rotated between two `get_fulfillment_result`
  calls for the same fulfillment
- **THEN** the later call returns a higher `credential_generation` than
  the earlier one, and the caller can detect that its cached copy is
  stale

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
