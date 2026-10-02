## ADDED Requirements

### Requirement: Storefront teardown goes through lease termination

A storefront requesting teardown of a delivered lease MUST request it through the site's
storefront-role lease termination, the same release path lease expiry takes, and MUST
NOT begin fulfillment teardown or release a site reservation directly. A repeated
termination request MUST return the same releasing or released lease. The storefront
MUST learn that capacity was released only from the site's capacity-released callback.

#### Scenario: Buyer requests bare-metal teardown

- **WHEN** a buyer requests teardown of a delivered bare-metal lease at the storefront
- **THEN** the storefront terminates the lease at the site, which begins the lease's
  fulfillment teardown, and the storefront makes no site release call of its own

#### Scenario: Teardown is requested twice

- **WHEN** the storefront repeats termination for a lease already releasing or released
- **THEN** the site returns that lease unchanged and starts no second teardown

### Requirement: Job execution resolves its executor by offering mode and action

Compute provisioning MUST own the table that selects the executor running a job, keyed by
the job's `offering_mode` and action, populated by adapter bundles, and MUST reject a
duplicate `(offering_mode, action)` registration at startup. Each entry MUST be one
complete job executor that executes a job and returns a normalized outcome, cancels
through its own handle, and receives job-done notification. The job engine MUST resolve
each job's executor through that table and MUST NOT know how a job runs: no playbook,
fact, inventory, process identifier, or SSH vocabulary, and no domain's parameter
construction. Job persistence and the pre-execution host lookup MUST be independent of
which executor runs. Under the mock profile an adapter MUST register a mock executor for
its own offering mode only.

#### Scenario: A bare-metal access job runs

- **WHEN** a job with offering mode `bare_metal` and a grant or reclaim action runs
- **THEN** it runs through the executor the bare-metal bundle registered, and its result
  is interpreted by bare metal's codec whether that executor is real or mock

#### Scenario: Two bundles claim the same executor key

- **WHEN** two adapter bundles register an executor for the same offering mode and action
- **THEN** compute provisioning refuses to start

### Requirement: Compute provisioning owns the job and host authorities

Compute provisioning MUST own durable physical-execution jobs — their identity, state,
route key, `host_id`, retry counts and timing, scheduling, cancellation through the
executor and its opaque handle, logs, and results and credentials, persisted and served as
`ResultEnvelope` and `CredentialEnvelope` — and operational host registration — host
identity, enabled state, pool association, a connection envelope whose secrets it holds
only in a protected form, and the lookup made immediately before execution, which yields
an immutable execution-host value. An executor MUST decide whether its failure is retryable
and MUST redact what it reports; the job authority decides whether and when a retry
happens. Shared execution technology MAY own the mechanics of invoking a prepared
execution: process lifecycle, transient inventory rendering, redaction, failure
classification, and connectivity probes. The site authority MUST reference a host only
by `host_id` and MUST NOT own provisioning connection information.

#### Scenario: A host changes pool

- **WHEN** an operator moves a registered host to another pool
- **THEN** the host authority records it and notifies subscribers, and a domain's
  dependent state (such as VM relay rebinding) reacts through that notification

#### Scenario: An executor reports a non-retryable failure
- **WHEN** a job's executor returns a failure it classifies as not retryable
- **THEN** the job fails without another attempt, whatever attempts remain under the retry policy

#### Scenario: A VM and a bare-metal job are in flight

- **WHEN** both run at once
- **THEN** one job engine and one host registry serve both, and neither domain's adapter
  holds either

### Requirement: A cancelled job stays cancelled

Once a job is cancelled, no outcome its executor reports later MAY change its state. A
cancellation requested before the executor reports its cancellation handle MUST take
effect when the handle is reported.

#### Scenario: A running job is cancelled and its execution then completes

- **WHEN** an operator cancels a running job and its executor afterwards reports success
- **THEN** the job remains cancelled and records no result or credentials from that outcome

#### Scenario: A job is cancelled before its executor reports a handle

- **WHEN** cancellation is requested before the executor has reported a handle
- **THEN** the executor is asked to cancel through the handle as soon as it is reported

### Requirement: Host connections are typed by their implementation's codec

A host's connection MUST be held as a connection envelope (a kind, a version, public
fields, and protected values) whose kind names the codec of the implementation
distribution that supports it. Compute provisioning MUST NOT define per-kind connection
fields; it validates an envelope through its codec. An executor MUST receive an immutable
execution-host value, not the persistence record, and MUST refuse a connection kind it
does not support.

#### Scenario: A compute domain needs another connection kind

- **WHEN** a domain's executor reaches its targets by a means other than SSH
- **THEN** an implementation distribution adds a codec for that kind, and neither the host
  authority's model nor the executor contract changes

### Requirement: Connection secrets stay protected

Connection secrets MUST cross service boundaries and be persisted only in a protected
representation (a scheme and its ciphertext). The host authority MUST treat a protected
value as opaque, MUST NOT decrypt it, and MUST keep it out of every read, logging, and
error surface. Only a connection codec MAY decrypt a protected value, just in time for
execution, and plaintext MUST stay confined to the execution boundary and the transient
storage the connection requires.

#### Scenario: A host is registered with an embedded key

- **WHEN** an operator registers a host whose `ssh` connection carries a caller-encrypted
  private key
- **THEN** the host authority validates the envelope through the `ssh` codec, stores the
  ciphertext as received, and its responses name the protected value and its scheme
  without the ciphertext

#### Scenario: A job runs against a host with an embedded key

- **WHEN** an executor runs a job against that host
- **THEN** it receives the protected envelope, and only the `ssh` codec decrypts the key,
  into transient storage removed when execution ends

### Requirement: Provisioning adapters import neither each other nor the deployed service

A compute provisioning adapter MUST NOT depend on or import another provisioning
adapter or the deployed provisioning service, including under `TYPE_CHECKING`. It
receives its collaborators from composition. No neutral provisioning module MAY import a
domain's operator client; compatibility flows from a domain client to the neutral
contract.

#### Scenario: Package boundaries are checked

- **WHEN** the import-boundary check runs
- **THEN** neither the VM nor the bare-metal provisioning adapter imports
  `compute_provisioning_service` or the other adapter, and no `compute_provisioning`
  module imports `vm_provisioning_operator`

## MODIFIED Requirements

### Requirement: Adapter-owned compute execution
VM and bare-metal execution MUST consume the common compute-provisioning envelope. Domain adapter contributions MUST own action-specific validation, execution preparation, codec and playbook selection, domain result interpretation, credential meaning, and release behavior; reusable execution technology MAY own the mechanics of invoking a prepared execution.

#### Scenario: Generic provisioner dispatches VM work
- **WHEN** a committed allocation identifies the VM executor and a supported action
- **THEN** generic orchestration selects the registered VM adapter without importing or inspecting VM request fields

#### Scenario: Generic provisioner dispatches bare-metal work
- **WHEN** a committed allocation identifies the bare-metal executor and a supported action
- **THEN** generic orchestration selects the registered bare-metal adapter without importing or inspecting access-grant fields

#### Scenario: Shared Ansible mechanics run a domain's job
- **WHEN** a VM or bare-metal job runs through the shared Ansible executor
- **THEN** the domain's codec renders its variables and interprets its result, and the shared mechanics hold no VM or bare-metal meaning

### Requirement: Compute-owned caller contract
Shared storefront/provisioner DTOs, offering-mode-neutral resource-pool models, the job, host, credential, and readiness wire models, and generic client behavior MUST be owned by compute provisioning rather than the VM domain. Direct VM operator APIs MAY retain VM-owned VM action, relay, and VM pool-configuration models; callers import compute-owned models from compute provisioning. Compute provisioning MUST NOT name a domain's routes: a domain MUST contribute the route contracts of the routes it mounts, and the client and the service's request authentication MUST read the table the provisioning service assembles from those contributions.

#### Scenario: Bare-metal storefront installs the shared client
- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: Provisioning service exposes resource-pool administration
- **WHEN** the VM operator client or provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that offering-mode-neutral model resolves from `compute_provisioning` without depending on a VM-domain generic provisioning-client package

#### Scenario: A domain's routes are signed and authenticated
- **WHEN** a compute domain mounts routes on the provisioning service
- **THEN** it contributes their route contracts, and neither the compute-provisioning client nor the service's authentication needs a compute-provisioning change to sign or authorize them

#### Scenario: An operator reads a lease
- **WHEN** an operator reads a VM or bare-metal lease through the generic lease routes
- **THEN** the response is the neutral lease view, carrying no VM-only field

### Requirement: Executor-dispatched lifecycle
Market-managed release MUST dispatch by offering mode; direct VM host administration endpoints MAY remain separate operator surfaces.

#### Scenario: Bare-metal allocation is released
- **WHEN** its lease lifecycle invokes release
- **THEN** release begins the bare-metal fulfillment's durable teardown, whose provider dispatches the bare-metal reclaim rather than VM teardown

### Requirement: Site-backed release lifecycle
Compute lease lifecycle MUST use an injected site-authority port and MUST NOT report capacity released until the selected executor release succeeds or an operator performs an explicit force-release action.

#### Scenario: Executor release succeeds
- **WHEN** a lease expires and its registered executor completes teardown or reclaim
- **THEN** compute lifecycle records successful allocation release through the site-authority port and capacity becomes available

#### Scenario: Executor release fails
- **WHEN** VM teardown or bare-metal reclaim returns a failure
- **THEN** the allocation remains unavailable, the lease exposes `release_failed`, and retry and force-release controls retain the failure evidence

#### Scenario: Operator force-releases allocation
- **WHEN** an authorized operator force-releases after an unrecoverable executor failure
- **THEN** the audit state distinguishes the operator override from successful physical teardown

Release submission and release-completion reads are separate, kind-routed seams. Every offering mode's teardown is a durable, multi-step fulfillment aggregate (see the Fulfillment specification's "Fulfillment convergence worker") with its own dispatch and status-convergence passes, running independently of the lease watchdog's own poll cadence; what a provider does to tear down differs by mode, not how lease lifecycle observes completion. Compute lease lifecycle stays kind-agnostic on both sides: a release-job port is resolved by the reservation's offering mode the same way release submission resolves an executor delegate by mode, so adding a mode registers its delegates without touching the generic watchdog or any other mode's path. The delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "Lease release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" below (`## Relationship to fulfillment`).

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Bare-metal lease release begins durable fulfillment teardown

- **WHEN** a bare-metal lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the same provider-neutral delegate begins the bare-metal fulfillment's teardown and returns its fulfillment identifier, and no reclaim job is submitted outside the aggregate

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** an executor's release delegate reports no pollable job for a submitted release (e.g. no release mechanism configured for that kind)
- **THEN** the lease lifecycle treats it as immediately complete, independent of whether any other offering mode has a release-job port configured

### Requirement: Lease release delegates to durable fulfillment teardown

For every offering mode, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The release adapter SHALL be provider-neutral, SHALL use the durable `fulfillment_id` as the release tracking identifier, and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL be selected by the reservation's `offering_mode`, the same value the capacity claim carries and the Resource Pool declares, and SHALL read fulfillment aggregate state.

#### Scenario: Release status is selected by the offering mode

- **WHEN** lease lifecycle resolves a release-status lookup for a reservation
- **THEN** the lookup is selected by the reservation's recorded `offering_mode`
- **AND** a reservation carrying the retired selector key is treated as carrying no offering mode rather than defaulting to one

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

#### Scenario: A bare-metal lease expires

- **WHEN** a delivered bare-metal lease passes its end
- **THEN** release begins the bare-metal fulfillment's teardown, the aggregate leaves `active`, and capacity stays held until it reaches `torn_down`

### Requirement: Lease release and fulfillment teardown have separate retry ownership

Lease lifecycle SHALL own the reservation's `releasing` and terminal release states, final capacity return, and release notification. Fulfillment convergence SHALL own teardown dispatch, provider polling, retry, and recovery through `torn_down` or `teardown_failed`. An operator lease retry SHALL re-observe the same fulfillment aggregate and SHALL NOT create a second teardown operation. Capacity SHALL remain held until the fulfillment reaches `torn_down` or an explicit force-release occurs.

#### Scenario: Failed teardown is requeued without duplicate teardown

- **GIVEN** a reservation is `releasing` and its fulfillment is `teardown_failed`
- **WHEN** fulfillment convergence requeues teardown and an operator retries lease release
- **THEN** both paths SHALL continue using the same `fulfillment_id`
- **AND** capacity SHALL remain unavailable until that aggregate reaches `torn_down`

## RENAMED Requirements

- FROM: `### Requirement: VM release delegates to durable fulfillment teardown`
- TO: `### Requirement: Lease release delegates to durable fulfillment teardown`
