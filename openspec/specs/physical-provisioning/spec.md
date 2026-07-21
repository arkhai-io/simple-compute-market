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

Service composition MUST reject duplicate executor/action kinds, duplicate fulfillment-provider identities, and incomplete adapter bundles before accepting traffic. Executor and provider registries MUST remain separate authority dimensions: registering or resolving a provider does not claim, infer, or override an executor kind. This extraction does not join POOLS-3's provider-only fulfillment path to executor dispatch.

#### Scenario: Two adapters claim one executor kind

- **WHEN** composition registers duplicate ownership for an executor/action kind
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Two adapters claim one provider identity

- **WHEN** composition registers duplicate ownership for a fulfillment-provider identity
- **THEN** startup fails with both registrations identified and no server begins serving

#### Scenario: Provider and executor registrations coexist

- **WHEN** service composition registers executor adapters and fulfillment providers
- **THEN** each registration remains in its own namespace and provider availability does not select or replace an executor adapter

### Requirement: Clean ownership cutover

After callers and deployments migrate, generic provisioning service and client paths under the VM domain MUST be removed rather than retained as aliases or compatibility distributions.

#### Scenario: Extraction completes

- **WHEN** repository package, import, image, and manifest references are reconciled
- **THEN** generic compute provisioning resolves only from the top-level provisioning category and domain packages contain only their concrete adapters and assets

## Evidence

- VM and bare-metal allocation executor metadata: `provisioning/compute/service/tests/integration/test_leases_api.py` and `test_bare_metal_leases_api.py`.
- Multidimensional scheduling eligibility (fit rejected on a secondary dimension even when GPU count would fit, legacy gpu-only requests unaffected): `provisioning/compute/service/tests/unit/services/test_physical_settlement_scheduler.py` (POOLS-6 pass 1 tests).
- Persisted asynchronous job lifecycle and polling: `provisioning/compute/service/tests/integration/test_vms_api.py`.
- Executor-specific release, failed-release capacity retention, retry, and force release: `provisioning/compute/service/tests/integration/test_bare_metal_leases_api.py`, `test_leases_api.py`, and `unit/services/test_ledger_lease_lifecycle.py`.
- Adapter composition and generic import boundaries: `provisioning/compute/service/tests/unit/test_composition.py` and `test_import_boundaries.py`.

`PhysicalSettlementScheduler` and the process-local fulfillment-provider coordination implemented by the extracted service are baseline contracts. Durable mechanism-neutral settlement recovery remains deferred to `pools-7-storefront-fulfillment-cutover`.

## Capacity settlement lifecycle

Physical provisioning distinguishes **Capacity Reservation → Capacity Settlement Assignment → Physical Settlement → Provisioned Resource / Active Workload**. Generic scheduling chooses an eligible Settlement Resource. Physical Settlement is provider-specific execution on that assigned resource. Provider-specific reachability, credentials, topology, and execution failures remain downstream of generic scheduling eligibility.

The current scheduling policy is deterministic round-robin through a replaceable policy interface. Generic policy and orchestration code use resource kind, a per-dimension quantity map (`dimensions`/`available`, checked against every dimension a candidate declares — POOLS-6 pass 1), pool identity, and opaque attributes and do not import market-specific executor persistence models.

## Relationship to fulfillment

The [fulfillment specification](../fulfillment/spec.md) owns provider-neutral settlement requests, settlement-resource scheduling, provider contracts, lifecycle identifiers, and versioned provider envelopes. This specification begins at compute-service composition and concrete executor/provider dispatch.

The compute provisioner may compose both a fulfillment-provider registry and an executor registry, but they remain distinct namespaces. Scheduling selects a `SettlementResource`; provider execution acts on that resource; executor dispatch performs domain-specific infrastructure actions. No one registration implicitly selects another.

Generic compute service modules may import `market_fulfillment`. `market_fulfillment` must not import the deployed compute service or VM/bare-metal adapters.
