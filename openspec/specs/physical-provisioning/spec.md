# Physical Provisioning Specification

## Purpose

Define the implemented allocation-backed executor dispatch, asynchronous job, and lease release behavior in the VM provisioning service.

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

## Evidence

- VM and bare-metal allocation executor metadata: `domains/vms/provisioning/service/tests/integration/test_leases_api.py` and `test_bare_metal_leases_api.py`.
- Persisted asynchronous job lifecycle and polling: `domains/vms/provisioning/service/tests/integration/test_vms_api.py`.
- Executor-specific release, failed-release capacity retention, retry, and force release: `domains/vms/provisioning/service/tests/integration/test_bare_metal_leases_api.py`, `test_leases_api.py`, and `unit/services/test_ledger_lease_lifecycle.py`.

`PhysicalSettlementScheduler`, `FulfillmentProvider`, and a durable mechanism-neutral settlement record are not implemented baseline contracts; the remaining ownership and package extraction is proposed in `migrate-compute-provisioning`.
