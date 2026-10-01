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
duplicate `(offering_mode, action)` registration at startup. A job service MUST resolve
each job's executor through that table and MUST NOT hold its own routing for another
adapter's actions. Job persistence, host validation, inventory rendering, and result
parsing MUST be independent of which executor runs, and job-done notification MUST reach
the executor that ran the job. Under the mock profile an adapter MUST register its mock
executor for its own offering mode only.

#### Scenario: A bare-metal access job runs

- **WHEN** a job with offering mode `bare_metal` and a grant or reclaim action runs
- **THEN** it runs through the executor the bare-metal bundle registered, and its result
  is parsed by the same bare-metal result path whether that executor is real or mock

#### Scenario: Two bundles claim the same executor key

- **WHEN** two adapter bundles register an executor for the same offering mode and action
- **THEN** compute provisioning refuses to start

## MODIFIED Requirements

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
