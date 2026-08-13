# Physical Provisioning Specification

## Purpose

Define the implemented allocation-backed executor dispatch, asynchronous job, and lease release behavior in the compute provisioning service.

## Requirements

### Requirement: Allocation-backed executor registration
Market-managed VM and bare-metal leases MUST attach executor kind, target, and executor-specific reference data to an existing committed site allocation.

#### Scenario: Bare-metal lease is registered
- **WHEN** a caller registers a lease for a committed allocation and bare-metal machine
- **THEN** the allocation records the `bare_metal` executor kind, machine target, and physical-host reference

### Requirement: Executor-dispatched lifecycle
Market-managed release MUST dispatch by executor kind; direct VM host administration endpoints MAY remain separate operator surfaces.

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

Release submission and release-completion reads are separate, independently kind-routed seams, because what "teardown complete" means differs by executor kind: bare-metal submits one job to a shared job queue and polls that job directly; VM teardown is a durable, multi-step fulfillment aggregate (see the Fulfillment specification's "Fulfillment convergence worker") with its own dispatch and status-convergence passes, running independently of the lease watchdog's own poll cadence. Compute lease lifecycle stays kind-agnostic on both sides: a release-job port is resolved by the reservation's executor kind the same way release submission already resolves an executor delegate by kind, so adding or changing one executor's completion semantics does not touch the generic watchdog or any other kind's path. VM's specific delegation shape — the narrow fulfillment-teardown port, the durable `fulfillment_id` as release tracking identifier, and the failure-propagation contract for unexpected submission errors — is the formal subject of "VM release delegates to durable fulfillment teardown" and "Lease release and fulfillment teardown have separate retry ownership" below (`## Relationship to fulfillment`); this section states only the kind-routing rationale that applies to bare-metal too.

#### Scenario: VM lease release begins durable fulfillment teardown

- **WHEN** a VM lease is due for release, whether by watchdog-detected expiry or an explicit early-termination request
- **THEN** the executor delegate begins the fulfillment aggregate's teardown and returns its fulfillment identifier as the job the lease lifecycle polls, rather than submitting provider work directly

#### Scenario: Executor release delegate has nothing to poll

- **WHEN** an executor's release delegate reports no pollable job for a submitted release (e.g. no release mechanism configured for that kind)
- **THEN** the lease lifecycle treats it as immediately complete, independent of whether any other executor kind has a release-job port configured

### Requirement: Explicit early lease termination

An authorized caller MUST be able to end a lease before its natural expiry through the same release mechanism the watchdog's expiry sweep uses, rather than through a separate termination code path.

#### Scenario: Caller terminates a lease before its natural end

- **WHEN** an authorized caller requests termination of a lease whose end time has not yet passed
- **THEN** release begins immediately through the reservation's registered executor delegate, without waiting for a watchdog cycle and without bypassing the release-job tracking a watchdog-detected expiry would also go through

### Requirement: Lease registration tolerates omitted identity hints

Lease registration MUST NOT require a caller to resupply identity information the executor's own committed resource attributes already carry. Registration MAY omit an executor-kind-specific physical-target hint; a release delegate resolving that hint later from the reservation's own attributes MUST produce the same outcome as if the hint had been supplied at registration.

#### Scenario: Registration omits a physical-target hint already implied by the committed resource

- **WHEN** a lease is registered without an executor-kind-specific physical-target hint, and the reservation's committed resource already carries the equivalent attribute
- **THEN** release still resolves the correct physical target and no lease registration fails or degrades for the omission

### Requirement: Lifecycle dependency isolation
Generic lease lifecycle and watchdog scheduling MUST depend on executor and site ports rather than concrete VM, bare-metal, storefront, or HTTP client implementations.

#### Scenario: Lifecycle is tested with registered delegates
- **WHEN** a test registers independent site and executor delegates
- **THEN** lease expiry, failure, retry, and release transitions execute without importing a concrete domain or storefront composition root

### Requirement: Adapter-owned compute execution

VM and bare-metal execution MUST consume the common compute-provisioning envelope while concrete adapters own action validation, infrastructure invocation, result interpretation, credentials, and release behavior.

#### Scenario: Generic provisioner dispatches VM work

- **WHEN** a committed allocation identifies the VM executor and a supported action
- **THEN** generic orchestration selects the registered VM adapter without importing or inspecting VM request fields

#### Scenario: Generic provisioner dispatches bare-metal work

- **WHEN** a committed allocation identifies the bare-metal executor and a supported action
- **THEN** generic orchestration selects the registered bare-metal adapter without importing or inspecting access-grant fields

### Requirement: Compute-owned caller contract

Shared storefront/provisioner DTOs, executor-neutral resource-pool models, and generic client behavior MUST be owned by compute provisioning rather than the VM domain, while direct VM operator APIs MAY retain VM-owned host, VM action, Ansible job, credential, and lease models.

#### Scenario: Bare-metal storefront installs the shared client

- **WHEN** a bare-metal caller installs the compute-provisioning client without VM execution extras
- **THEN** it can submit and observe bare-metal lifecycle operations without importing VM request models

#### Scenario: Provisioning service exposes resource-pool administration

- **WHEN** the VM operator client or provisioning service creates, validates, imports, or returns a resource-pool model
- **THEN** that executor-neutral model resolves from `compute_provisioning` and no removed generic provisioning-client package is required

### Requirement: Compute-owned provisioning service

Cross-domain compute orchestration, including mechanism-neutral fulfillment coordination, MUST run from a deployable service owned by `provisioning/compute`, while VM and bare-metal packages retain their concrete executor and fulfillment-provider semantics and register them through explicit adapter bundles.

#### Scenario: Extracted service starts with current adapters

- **WHEN** the compute provisioner starts with VM and bare-metal adapters configured
- **THEN** it mounts generic job, lease, capacity, fulfillment, health, and watchdog surfaces plus each adapter's declared executor, provider, and operator surfaces

#### Scenario: Generic service is inspected for dependencies

- **WHEN** package and import boundaries are checked
- **THEN** generic compute service modules do not import concrete VM or bare-metal request, action, result, playbook, provider, fulfillment-requirement, or access models

### Requirement: Validated executor registration

Service composition MUST reject duplicate executor/action kinds, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor kind. Provider fulfillment and executor dispatch remain separate paths unless composition explicitly joins them through a supported lifecycle.

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for an executor/action kind
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers executor adapters and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace an executor adapter

### Requirement: Ansible fulfillment adapter

The VM Ansible fulfillment adapter MUST execute only against the scheduler-selected `SettlementResource`. Before dispatch it MUST reject disabled or missing pools, pool/resource/provider mismatches, missing host identity, malformed VM requirements, and provider variables that collide with authoritative job inputs. Accepted operations MUST snapshot the resolved playbook and provider variables with the submitted job. Create metadata MUST retain the exact `vm_host` and `vm_target`, and teardown MUST reuse those accepted values rather than infer them from a resource identifier. Provider-specific job states MUST map to the normalized fulfillment states `pending`, `succeeded`, `failed`, or `unknown`.

Reservation-governed VM shape is resolved from the committed reservation dimensions carried by the scheduled settlement resource. Caller-supplied sizing fields do not override or fill missing committed dimensions. For each dimension absent from the committed reservation, the adapter MAY apply the corresponding pool default; if neither a committed dimension nor a pool default exists, the provider input remains unset and the selected playbook or inventory supplies its own default. The pool-selected registered requirement delegate owns conversion from canonical VM dimensions into the selected playbook's variable names, units, and derived values.

The fulfillment request MAY carry a `connectivity` field (FRP relay address, domain, and dashboard credential) which the adapter forwards to the Ansible job unchanged. This is opaque connectivity metadata the adapter never interprets or validates beyond passing it through; it is not a sizing/feasibility requirement.

#### Scenario: Pool configuration changes after create dispatch

- **WHEN** an operator edits provider configuration after an Ansible create job is accepted
- **THEN** the accepted job retains the resolved configuration snapshot captured at dispatch

#### Scenario: Provider variables collide with job identity

- **WHEN** pool-supplied extra variables attempt to override an authoritative host, target, action, sizing, or executor field
- **THEN** validation rejects the operation before asynchronous dispatch

#### Scenario: VM teardown is dispatched

- **WHEN** teardown begins for an accepted VM fulfillment
- **THEN** the adapter targets the recorded `vm_host` and `vm_target` from fulfillment metadata

#### Scenario: A committed dimension is present

- **WHEN** the scheduled settlement resource carries a committed VM dimension
- **THEN** the adapter translates that value through the pool-selected requirement delegate and ignores any conflicting caller-supplied sizing field

#### Scenario: A committed dimension is absent and the pool has a default

- **WHEN** the committed reservation omits a VM dimension and the resolved pool configures the corresponding default
- **THEN** the adapter uses the pool default for that dimension

#### Scenario: A committed dimension and pool default are both absent

- **WHEN** neither the committed reservation nor the resolved pool supplies a VM dimension
- **THEN** the adapter leaves the corresponding provider input unset so the selected playbook or inventory may supply its own default

### Requirement: VM fulfillment result payload

`AnsibleFulfillmentProvider.fetch_credentials` (see `openspec/specs/fulfillment/spec.md#requirement-provider-contract`) MUST return a `vm.fulfillment.result.v1` versioned envelope, defined in `vm_provisioning_adapter/fulfillment_results.py`, nested inside the generic `fulfillment.result.v1` envelope's `domain_result` field. Its payload carries `provisioned_resources` (each output's `provisioned_resource_id` and `status`, mirroring the fulfillment-owned identity the kit already exposes) and `credentials`: a tuple of `role`, `password`, `ssh_commands`, `ssh_key_path_host`, `key_type`, and `provisioned_resource_ids` — the output identities that credential is associated with, expressed this way so a fulfillment with more than one provisioned resource can eventually express which credential belongs to which output rather than a single flat list. Today every VM fulfillment produces exactly one `ProvisionedResource`, so every credential's `provisioned_resource_ids` names that one output; this is a real limitation, not yet a genuine many-to-many resolution, since the adapter has no way to attribute an individual credential to a specific output when more than one exists. Credentials MUST be sourced from `AnsibleJobService.get_credentials(job_id)` and MUST NOT be persisted by this adapter or by the fulfillment kit — they exist only in the response constructed for one `get_fulfillment_result` call.

The payload also carries an optional `connection_info` object (`vm_name`, `host`, `timestamp`, `tenant_user`, `vm_ip_internal`, `ssh_port`) — structured VM identity/connection metadata, best-effort read from the same job's parsed Ansible result alongside credentials. A missing or unreadable result must not fail an otherwise-successful credential fetch, so every `connection_info` field, and `connection_info` itself, is optional. Each credential's `ssh_commands` already carries a ready-to-use connection string (host, port, and tenant user baked in), so `connection_info` is not required to connect — it exists for callers that want the pieces separately rather than parsing a command string.

#### Scenario: Result query on an active VM fulfillment includes the domain payload

- **WHEN** `get_fulfillment_result` is called for a `fulfillment_id` whose VM fulfillment is `active`
- **THEN** the envelope's `domain_result` is a `vm.fulfillment.result.v1` payload whose `credentials` reflect a live `AnsibleJobService.get_credentials` read for the recorded job, and whose `provisioned_resources` mirror the fulfillment kit's own `ProvisionedResource` rows

#### Scenario: Job result carries connection metadata

- **WHEN** the recorded job's parsed result includes VM identity/connection fields
- **THEN** `domain_result`'s `connection_info` carries them, without failing the credential fetch if any individual field is absent

### Requirement: Clean ownership cutover

After callers and deployments migrate, generic provisioning service and client paths under the VM domain MUST be removed rather than retained as aliases or compatibility distributions.

#### Scenario: Extraction completes

- **WHEN** repository package, import, image, and manifest references are reconciled
- **THEN** generic compute provisioning resolves only from the top-level provisioning category and domain packages contain only their concrete adapters and assets

### Requirement: VM lease migration uses current provider contracts

When an existing VM lease is represented in the fulfillment aggregate, the selected resource SHALL resolve through the current host and resource-pool configuration. The VM target SHALL be derived from the consistent legacy VM/executor target fields, and known create or teardown job identifiers SHALL be retained in provider metadata. Any prepared teardown operation SHALL be produced by the current VM Ansible provider's `prepare_teardown` contract using the snapshotted pool configuration rather than by constructing provider payload JSON independently.

#### Scenario: Migrated lease resolves through current configuration
- **WHEN** a pre-cutover VM lease is backfilled into the fulfillment aggregate
- **THEN** its selected resource, VM target, and any prepared teardown operation are derived through the current host/resource-pool configuration and provider contract, not reconstructed by hand from legacy fields


### Requirement: VM release delegates to durable fulfillment teardown

For VM reservations, lease release SHALL initiate teardown through a narrow fulfillment-teardown port. The VM release adapter SHALL use the durable `fulfillment_id` as the release tracking identifier and SHALL NOT submit or poll a provider job directly. Release-status lookup SHALL be selected by `executor_kind`; VM lookup SHALL read fulfillment aggregate state while bare-metal lookup MAY read its executor job service.

#### Scenario: Unexpected teardown submission failure remains diagnosable

- **WHEN** composition, persistence, or an unexpected implementation failure prevents VM teardown submission
- **THEN** the failure SHALL propagate to lease lifecycle handling and be recorded as `release_submit_error` rather than being converted to an absent job identifier

### Requirement: Lease release and fulfillment teardown have separate retry ownership

Lease lifecycle SHALL own the reservation's `releasing` and terminal release states, final capacity return, and release notification. Fulfillment convergence SHALL own teardown dispatch, provider polling, retry, and recovery through `torn_down` or `teardown_failed`. An operator lease retry SHALL re-observe the same fulfillment aggregate and SHALL NOT create a second teardown operation. Capacity SHALL remain held until the fulfillment reaches `torn_down` or an explicit force-release occurs.

#### Scenario: Failed teardown is requeued without duplicate teardown

- **GIVEN** a VM reservation is `releasing` and its fulfillment is `teardown_failed`
- **WHEN** fulfillment convergence requeues teardown and an operator retries lease release
- **THEN** both paths SHALL continue using the same `fulfillment_id`
- **AND** capacity SHALL remain unavailable until that aggregate reaches `torn_down`

### Requirement: Provisioning shape comes from committed capacity

A fulfillment provider MUST derive reservation-governed resource shape from the dimensions carried by the scheduled settlement resource -- which reflect what was actually scheduled, bounded by but not necessarily equal to the capacity reservation (see `openspec/specs/site-capacity/spec.md#requirement-committed-dimensions-remain-authoritative-through-scheduling`). It MUST NOT use caller-supplied fulfillment fields as fallback values for that shape.

For an Ansible-backed VM pool, provider configuration identifies both the playbook and a registered requirement delegate. The adapter resolves the delegate through an allowlisted registry. The delegate validates that the committed canonical VM dimensions are representable by the playbook and translates them into the playbook's variable names, units, and derived values. Resource-pool configuration MUST NOT load arbitrary Python import paths.

#### Scenario: Provider derives shape from the scheduled resource, not caller-supplied fields
- **WHEN** a fulfillment provider prepares a create operation for a scheduled settlement resource
- **THEN** it derives the provisioned shape from that resource's own committed dimensions, not from any shape fields the caller's fulfillment request happens to carry

## Evidence

- VM and bare-metal allocation executor metadata: `provisioning/compute/service/tests/integration/test_leases_api.py` and `test_bare_metal_leases_api.py`.
- Multidimensional scheduling eligibility, including secondary-dimension rejection and legacy GPU-only requests: `provisioning/compute/service/tests/unit/services/test_physical_settlement_scheduler.py`.
- Persisted asynchronous job lifecycle and polling: `provisioning/compute/service/tests/integration/test_vms_api.py`.
- Executor-specific release, failed-release capacity retention, retry, and force release: `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`, `test_leases_api.py`, and `unit/services/test_ledger_lease_lifecycle.py`.
- Adapter composition and generic import boundaries: `provisioning/compute/service/tests/unit/test_composition.py` and `test_import_boundaries.py`.
- VM sizing precedence (committed reservation, pool default, unset), connectivity forwarding, and result credential/connection-metadata fields: `provisioning/compute/service/tests/unit/services/test_ansible_fulfillment_provider.py` (`TestSizingPrecedence`, `TestConnectivity`), plus end-to-end HTTP coverage in `provisioning/compute/service/tests/integration/test_fulfillment_api.py::TestStatusAndResultQueries`.

`PhysicalSettlementScheduler` and fulfillment-provider coordination are durable, not process-local: scheduling, acceptance, and dispatch state live in the fulfillment aggregate (see `openspec/specs/fulfillment/spec.md#durable-settlement-persistence`), and a dedicated periodic worker recovers in-flight provider operations after a crash or restart (see `openspec/specs/fulfillment/spec.md#fulfillment-convergence-worker` and `docs/development/ARCHITECTURE.md#recovery-workers`). This is a database-wide SQLite writer guarantee, not a distributed multi-replica protocol.

## Capacity settlement lifecycle

Physical provisioning distinguishes **Capacity Reservation → Capacity Settlement Assignment → Physical Settlement → Provisioned Resource / Active Workload**. Generic scheduling chooses an eligible Settlement Resource. Physical Settlement is provider-specific execution on that assigned resource. Provider-specific reachability, credentials, topology, and execution failures remain downstream of generic scheduling eligibility.

The current scheduling policy is deterministic round-robin through a replaceable policy interface. Generic policy and orchestration code use resource kind, a per-dimension quantity map (`dimensions`/`available`, checked against every requested dimension), pool identity, and opaque attributes and do not import market-specific executor persistence models.

## Relationship to fulfillment

The [fulfillment specification](../fulfillment/spec.md) owns provider-neutral settlement requests, settlement-resource scheduling, provider contracts, lifecycle identifiers, and versioned provider envelopes. This specification begins at compute-service composition and concrete executor/provider dispatch.

The compute provisioner may compose both a fulfillment-provider registry and an executor registry, but they remain distinct namespaces. Scheduling selects a `SettlementResource`; provider execution acts on that resource; executor dispatch performs domain-specific infrastructure actions. No one registration implicitly selects another.

Generic compute service modules may import `market_fulfillment`. `market_fulfillment` must not import the deployed compute service or VM/bare-metal adapters.
