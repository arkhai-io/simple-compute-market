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
the job's `offering_mode` and the action its executor runs, populated by adapter
bundles, and MUST reject a duplicate `(offering_mode, action)` registration at startup.
Each entry MUST be one complete job executor that executes a job and returns a
normalized outcome and cancels through its own handle; the job engine, not the executor,
knows when a job has finished. The job engine MUST resolve
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
by `host_id` and MUST NOT own provisioning connection information. The provisioning
service's composition root MUST build exactly one job authority and one host authority
and supply both to every adapter runtime; no adapter runtime builds or owns either. The
root supplies the connection codecs a deployment supports, and a domain contributes its
host pool-change hooks as declarations the root merges.

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

Connection secrets MUST be persisted, stored, and passed to executors only in a protected
representation (a scheme and its ciphertext). A secret submitted with a host's
connection MUST be turned into a protected value by that connection kind's codec before
it is persisted, and the submitted secret MUST NOT be stored, returned, or logged. The
host authority MUST treat a protected value as opaque, MUST NOT encrypt or decrypt it, and
MUST keep it out of every read, logging, and error surface. Only a connection codec MAY
decrypt a protected value, just in time for execution, and plaintext MUST stay confined
to the submitting request, the codec, and the transient storage the connection requires.

#### Scenario: A host is registered with an embedded key

- **WHEN** an operator registers a host whose `ssh` connection submits a private key
- **THEN** the `ssh` codec protects it, the host authority stores only the protected
  value, and its responses name the protected value and its scheme without the ciphertext

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

### Requirement: Every provisioning route admits the administrator

Every route on the provisioning service's route table MUST admit the `admin` role, in
addition to any other role it admits. A route contract a domain contributes that does not
admit `admin` MUST be refused when the table is assembled.

#### Scenario: An operator calls a storefront route

- **WHEN** a request signed by the provisioning administrator calls a route that also
  admits the seller, such as lease registration or fulfillment begin
- **THEN** it is authorized as it would be for the seller

#### Scenario: A domain contributes a seller-only route

- **WHEN** a domain declares a route whose roles omit `admin`
- **THEN** the provisioning service refuses to assemble its route table

### Requirement: Leases have one family surface that records and releases

Compute provisioning MUST serve every offering mode's leases through one route surface
returning the neutral lease view: register, get, list, terminate, release-oversight,
retry-release, and force-release. Register, get, and terminate MUST admit the seller and
the administrator; list, release-oversight, retry-release, and force-release MUST admit
the administrator only. A lease MUST be addressed by its capacity reservation identifier;
the list MAY filter by lease status and offering mode and MUST NOT filter by a deal's
commercial identity or by host. A lease route MUST NOT deliver: no lease route grants
access, creates a workload, or submits provider work, and a domain MUST NOT add or
override lease routes. A domain MAY extend what a lease reports only by contributing a
versioned projection.

#### Scenario: An operator lists bare-metal leases

- **WHEN** an administrator lists leases filtered by offering mode `bare_metal`
- **THEN** the response carries every bare-metal lease as the neutral lease view

#### Scenario: A storefront asks for the lease list

- **WHEN** a request signed as the seller calls the lease list
- **THEN** it is refused, and the storefront reads its own leases by reservation id

#### Scenario: Bare-metal access is granted

- **WHEN** a bare-metal deal is delivered
- **THEN** access is granted only through the fulfillment aggregate, and the lease is
  registered on the reservation afterwards, recording only

### Requirement: A lease's executor identity and evidence are fixed at registration

Lease registration MUST write a reservation's lease tail once, through the site authority's
write-once registration: a lease is registered once its reservation records an executor
target; a first registration MUST be accepted on a `reserved`, `provisioning`, or `leased`
reservation; a repeated registration with the same executor target and lease start MUST
return the lease unchanged and MUST NOT move its end; one naming a different target or start
MUST be refused; a registration on a `releasing`, `release_failed`, or `unmanaged`
reservation MUST be refused; a recorded create handle MUST NOT be replaced. No lease route
MAY change a lease's executor identity, its start, or its create or release handles after
registration. Once registered, a lease's end MAY move only through the site authority's
lease truncation. A storefront MUST register a lease with the window its commit returned.

#### Scenario: A storefront re-registers after a restart

- **WHEN** a storefront repeats a registration for a lease that was since truncated
- **THEN** the lease is returned with its truncated end, and nothing is overwritten

#### Scenario: A registration names a different target

- **WHEN** a registration names an executor target other than the one recorded
- **THEN** it is refused, and the recorded target still governs teardown

### Requirement: Execution readiness is reported in system status

The provisioning service's system status MUST report whether execution is mocked, as a
boolean for the deployment and per composed executor by offering mode, derived from the
composed executors rather than from deployment profiles, together with each contributed
readiness component's readiness and a versioned detail. A component that is not ready MUST
degrade the status. The status MUST NOT disclose a database URL or any credential.
Readiness MUST have no route of its own, and an execution implementation MUST contribute
its readiness rather than serve it.

#### Scenario: Every executor is mocked

- **WHEN** the service runs with every composed executor mocked
- **THEN** status reports execution as mocked, and lists each offering mode's executor as
  mocked

#### Scenario: A domain's playbook is missing

- **WHEN** the Ansible executor for one offering mode names a playbook that does not exist
- **THEN** the Ansible component reports that playbook and is not ready, and the status is
  degraded

### Requirement: Host connectivity is probed by connection kind

A host connectivity check MUST run the probe registered for the host's connection kind and
return a neutral connectivity result. A host whose connection kind has no registered probe
MUST be refused. The probe's execution resources MUST be composed by the provisioning
service, not borrowed from a domain's runtime.

#### Scenario: A bare-metal host is probed

- **WHEN** an operator checks connectivity to a registered bare-metal host with an `ssh`
  connection
- **THEN** the `ssh` probe runs over the service's own runner and returns the neutral result

### Requirement: Delivery happens only through fulfillment

No provisioning route MAY submit delivery work (creating a workload or granting access) outside a fulfillment aggregate, for any offering mode. The provisioning service MUST NOT serve a generic executor-action route, and a domain MUST NOT contribute one.

#### Scenario: An operator looks for a direct grant

- **WHEN** an operator wants to grant bare-metal access or create a VM for a reservation
- **THEN** the only path is the reservation's fulfillment, and no provisioning route submits that work directly

### Requirement: An undelivered lease is released by what its fulfillment proves

A lease's release MUST follow the state of its reservation's fulfillment aggregate:

- An `active` aggregate MUST be torn down before capacity returns.
- An aggregate whose teardown has already begun — `teardown_dispatch_pending`, `tearing_down`, or `teardown_failed` — MUST have that teardown adopted, not a second one begun.
- A `torn_down` aggregate MUST return the capacity as a completed release.
- An absent, `assigned`, or `abandoned` aggregate MUST return the capacity directly, as a completed release, only when the reservation's provenance proves nothing was dispatched: no create handle on the reservation and no job bound to the reservation. An `assigned` aggregate MUST be abandoned before the proof is checked, so a concurrent dispatch cannot outrun it.
- When the create is in flight (`dispatch_pending` or `dispatching`), the release MUST be remembered durably, with the reservation `releasing` and the fulfillment as its release handle, and teardown MUST begin once the aggregate reaches `active`; the grace timeout MUST NOT run while the create is in flight.
- A `failed` aggregate, or an absent, `assigned`, or `abandoned` one without that proof, MUST put the lease in `release_failed` for an operator to verify and force-release.
- A teardown observed as `teardown_failed` while the lease is `releasing` MUST put the lease in `release_failed`; an operator's retry-release MUST re-observe the same aggregate.

The compute provisioning composition MUST supply the site authority's release guard, which permits freeing a reservation's capacity only for a `torn_down` aggregate or for an absent, `assigned`, or `abandoned` one whose provenance proof holds, and MUST check that proof in the transaction that frees the capacity. Every direct capacity return, whether by the lease lifecycle or by any caller of the site's release, MUST pass that guard; force-release remains the operator's recorded override.

#### Scenario: A committed lease whose fulfillment never began expires

- **WHEN** a lease's reservation was committed but its fulfillment was never dispatched, and the lease reaches its end
- **THEN** the assigned aggregate is abandoned, the capacity returns, and no teardown is attempted

#### Scenario: A lease is terminated while its create is in flight

- **WHEN** a lease is terminated while its fulfillment is `dispatching`
- **THEN** the reservation becomes `releasing` at once, survives a restart in that state, and its teardown begins when the aggregate reaches `active`

#### Scenario: A create failed

- **WHEN** a lease is released and its aggregate is `failed`
- **THEN** the lease enters `release_failed`, and capacity stays held until an operator force-releases it

#### Scenario: Teardown fails while the lease is releasing

- **WHEN** a releasing lease's aggregate reaches `teardown_failed`
- **THEN** the lease enters `release_failed`, and when convergence's retry later reaches `torn_down`, an operator's retry-release adopts that teardown and releases the capacity

#### Scenario: A storefront releases a delivered lease

- **WHEN** a storefront asks the site to release a reservation whose aggregate is `active`
- **THEN** the release guard refuses, the reservation keeps its capacity and state, and the lease is released only through its lifecycle

### Requirement: Host import belongs to the execution implementation that reads its format

A host-import route that reads an implementation's inventory format MUST be contributed by that implementation, with its route contract, route service, and typed client; the compute family's host routes MUST serve only format-neutral host administration and connectivity.

#### Scenario: Hosts are imported from an Ansible inventory

- **WHEN** an operator imports hosts from an Ansible INI inventory
- **THEN** the Ansible implementation's import route parses it and registers the hosts through the host authority, and the family's host route contracts name no inventory format

### Requirement: Lease release delegates to durable fulfillment teardown

For every offering mode, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The release adapter SHALL be provider-neutral, SHALL use the durable `fulfillment_id` as the release tracking identifier, and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL read fulfillment aggregate state and SHALL NOT be selected by the reservation's offering mode.

#### Scenario: Release status is read from the aggregate

- **WHEN** lease lifecycle reads release status for a VM or a bare-metal reservation
- **THEN** both reads go through the same status port to the fulfillment aggregate, whose teardown state decides the outcome

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

#### Scenario: A bare-metal lease expires

- **WHEN** a delivered bare-metal lease passes its end
- **THEN** release begins the bare-metal fulfillment's teardown, the aggregate leaves `active`, and capacity stays held until it reaches `torn_down`

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
Shared storefront/provisioner DTOs, the job, host, credential, lease, and system-status wire models, and the family's route contracts MUST be owned by compute provisioning rather than the VM domain, in a contracts distribution that depends on no service, persistence, or web-framework package. Routes the provisioning service hosts for another capability, such as resource-pool administration and capacity-definition import, MUST keep that capability's models, contracts, and client; hosting a route does not make it compute provisioning's. The family's typed client MUST be a separate client distribution depending on no service, persistence, or web-framework package: only that contracts distribution, the core carrier package, the identity kit, its HTTP library, and its model library; it offers async and sync variants with identical operations, and the family kit itself MUST contain no client. Direct VM operator APIs MAY retain VM-owned VM action, relay, and VM pool-configuration models and a VM client extension over the family client's authenticated transport; callers import compute-owned models from the contracts distribution. Compute provisioning MUST NOT name a domain's routes: a domain, an execution implementation, or another capability MUST contribute the route contracts of the routes it mounts. The service's request authentication MUST resolve requests against the table the provisioning service's composition root assembles from those contributions; each typed client MUST sign its routes from its owner's contracts. Where the owner's contracts are one declaration that both the service's table and the client read, as the compute family's, the resource-pool authority's, the Ansible implementation's, and each domain's are, operation, resource binding, and roles cannot diverge. Where an owner keeps separate server and client declarations, as the site capacity authority does, a contract-parity test MUST hold the two equal in method, path, operation, resource binding, and the models they exchange.

#### Scenario: Bare-metal storefront installs the shared client
- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: A storefront installs the client without the family kit
- **WHEN** a storefront depends on the compute-provisioning client
- **THEN** it installs the contracts and client distributions only, and no persistence, web-framework, or job-authority package arrives with them

#### Scenario: Provisioning service exposes resource-pool administration
- **WHEN** an operator client or the provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that offering-mode-neutral model resolves from the resource-pool capability's contracts distribution, not from compute provisioning or a VM-domain package

#### Scenario: A domain's routes are signed and authenticated
- **WHEN** a compute domain mounts routes on the provisioning service
- **THEN** it contributes their route contracts, and neither the compute-provisioning client nor the service's authentication needs a compute-provisioning change to sign or authorize them

#### Scenario: An operator reads a lease
- **WHEN** an operator reads a VM or bare-metal lease through the generic lease routes
- **THEN** the response is the neutral lease view, carrying no VM-only field

### Requirement: Validated executor registration

Service composition MUST reject duplicate job-executor registrations for one `(offering_mode, action)` key, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. A job executor MUST be selected by the `offering_mode` it serves together with its action; no surface may name that selector `executor_kind`, `offering_type`, or `virtualization_type`. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor's offering mode. A fulfillment provider submits its jobs to the job authority, which resolves each job's executor through the executor table.

`executor` names the job-execution abstraction and nothing else when it is the head noun. It MUST NOT stand in for the offering mode, the machine, or the delivery handler: the mode is an offering mode, the machine is a host, and the handler is a provider. The abstraction keeps the name because it executes a job and returns its outcome; only its selector moves.

`executor_`-prefixed compounds naming the abstraction's own targets, references, or actions MUST retain the name, because `executor` carries its execution sense in them rather than standing in for another concept. `executor_ref` is the executor's reference, `executor_target` is the target of an executor action, and an executor action envelope carries an executor action; none of these is the mode, the machine, or the handler as a head noun. This requirement's prohibition therefore applies to the head noun and MUST NOT be read as a prohibition on the prefix.

#### Scenario: An executor-prefixed compound names the abstraction's own target

- **WHEN** a durable reservation or lease records the target or reference an executor action acts on
- **THEN** those fields retain their `executor_`-prefixed names
- **AND** the offering-mode selector on the same record does not, because its head noun is the mode

#### Scenario: Two adapters claim one offering mode

- **WHEN** composition registers two job executors for the same `offering_mode` and action pair
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers job executors and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace a job executor

### Requirement: Allocation-backed executor registration
Market-managed leases MUST attach the executor target and the lease window to an existing committed site allocation. The allocation's offering mode is the one the site recorded when capacity was claimed; registration MUST NOT name an offering mode, and executor-specific reference data such as a physical-host identity MUST stay with the fulfillment that delivered the workload rather than the lease.

#### Scenario: Bare-metal lease is registered
- **WHEN** a caller registers a lease for a committed bare-metal allocation
- **THEN** the allocation keeps its recorded `bare_metal` offering mode and records the machine target and lease window, and the physical-host identity stays in the fulfillment's metadata

### Requirement: Executor-dispatched lifecycle
Market-managed release MUST begin the reservation's fulfillment teardown through one provider-neutral release executor, whatever the reservation's offering mode; the fulfillment's provider dispatches the domain's teardown. Direct VM host administration endpoints MAY remain separate operator surfaces.

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

Release submission and release-completion reads are separate seams, and neither is selected by offering mode. Every offering mode's teardown is a durable, multi-step fulfillment aggregate (see the Fulfillment specification's "Fulfillment convergence worker") with its own dispatch and status-convergence passes, running independently of the lease watchdog's own poll cadence; what a provider does to tear down differs by mode, not how lease lifecycle begins it or observes completion. Compute lease lifecycle is therefore mode-agnostic: one provider-neutral release executor begins the aggregate's teardown and one status port reads the aggregate, so adding a mode registers a fulfillment provider and touches neither seam. The delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "Lease release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" below (`## Relationship to fulfillment`).

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Bare-metal lease release begins durable fulfillment teardown

- **WHEN** a bare-metal lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the same provider-neutral delegate begins the bare-metal fulfillment's teardown and returns its fulfillment identifier, and no reclaim job is submitted outside the aggregate

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** a lease is due for release but the release executor finds no fulfillment aggregate to tear down, so it reports no job to poll
- **THEN** capacity is released directly only if the reservation's provenance proves that nothing was dispatched; otherwise the lease enters `release_failed` and capacity stays held until an operator force-releases it, and nothing to poll never counts as a completed release by itself

### Requirement: Lease release and fulfillment teardown have separate retry ownership

Lease lifecycle SHALL own the reservation's `releasing` and terminal release states, final capacity return, and release notification. Fulfillment convergence SHALL own teardown dispatch, provider polling, retry, and recovery through `torn_down` or `teardown_failed`. An operator lease retry SHALL re-observe the same fulfillment aggregate and SHALL NOT create a second teardown operation. Capacity SHALL remain held until the fulfillment reaches `torn_down` or an explicit force-release occurs.

#### Scenario: Failed teardown is requeued without duplicate teardown

- **GIVEN** a reservation is `releasing` and its fulfillment is `teardown_failed`
- **WHEN** fulfillment convergence requeues teardown and an operator retries lease release
- **THEN** both paths SHALL continue using the same `fulfillment_id`
- **AND** capacity SHALL remain unavailable until that aggregate reaches `torn_down`

## REMOVED Requirements

### Requirement: VM release delegates to durable fulfillment teardown

**Reason**: Release no longer differs by offering mode. Every mode's lease release begins
the fulfillment aggregate's teardown through one provider-neutral executor and reads
completion through one status port, so a VM-specific requirement, and its selection of the
release-status lookup by offering mode, no longer describe the system.

**Migration**: Replaced by "Lease release delegates to durable fulfillment teardown"
above, which states the same delegation for every offering mode.
