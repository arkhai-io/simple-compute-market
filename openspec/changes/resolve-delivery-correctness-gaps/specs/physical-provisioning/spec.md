## ADDED Requirements

### Requirement: A relayed delivery's relay is its declaration's pool's

A relayed delivery's port MUST be leased on the relay its capacity declaration's pool references, whatever pool, if any, its host is placed in. The job that adds the delivery's proxy MUST point the host's buyer-facing client at that relay — its address, port and admission token — before adding the proxy, restarting the client only when that baseline changes. A host has at most one capacity declaration, so every delivery on a host is leased on one relay at a time, and that relay is the one the host's client dials.

#### Scenario: A host placed under another relay delivers through its declaration's

- **GIVEN** a host placed in a pool referencing relay R2, whose capacity declaration sits in a pool referencing relay R1
- **WHEN** a relayed create is accepted and dispatched for that declaration
- **THEN** its port is leased on R1, and its job carries R1 as its relay

#### Scenario: An unplaced host delivers through its declaration's relay

- **GIVEN** a host placed in no pool, whose capacity declaration sits in a pool referencing a relay
- **WHEN** a relayed create is accepted and dispatched for that declaration
- **THEN** its port is leased on that relay, and its job carries it as its relay

#### Scenario: A proxy is added on a host whose client names another relay

- **WHEN** a job adds a buyer proxy on a host whose client baseline names another relay than the job's
- **THEN** the baseline is rewritten to the job's relay address, port and token, the client is restarted, and the proxy is added

### Requirement: A concurrent allocation for one owner receives that owner's lease

Allocation MUST read whether the owner already holds an active lease after it takes the relay's lock, not before, so an allocation that waited on that lock receives a lease committed for the same owner meanwhile. When a claim fails a uniqueness constraint, allocation MUST read the owner's active lease again and return it when one exists, and MUST move on to another port only when none does. `RelayWindowExhaustedError` MUST be raised only when every port in the window is held or quarantined. The two constraints MUST be told apart by reading the leases again, not by the database's constraint name, so the rule holds on SQLite and PostgreSQL alike.

#### Scenario: A claim for the owner waited on the relay's lock

- **WHEN** an allocation for an owner waits on the relay's lock while another allocation for the same owner commits a lease
- **THEN** it returns that lease and claims no port

#### Scenario: The owner's lease is committed on another relay meanwhile

- **WHEN** an allocation for an owner finds no lease, and its claim then fails because a lease for the same owner was committed meanwhile
- **THEN** it returns the owner's lease rather than trying further ports, and raises no `RelayWindowExhaustedError`

#### Scenario: Another owner holds the port

- **WHEN** a claim fails because another owner holds the port
- **THEN** allocation selects another free port, and raises `RelayWindowExhaustedError` only once every port in the window is held or quarantined

### Requirement: A job records that its execution is starting before it starts

An executor MUST report that a job's execution is starting immediately before it starts anything that can act on the host — the Ansible executor before it spawns the playbook — and the job authority MUST record that instant on the job, as `execution_started_at`, before the executor goes on. When the instant cannot be recorded, the executor MUST NOT start the execution, and the attempt fails. A retry MUST NOT clear the recorded instant or the recorded execution handle.

A job's execution never started when the job is `failed`, not `cancelled`, and records neither `execution_started_at` nor an execution handle. A job recorded before `execution_started_at` existed is classified by its execution handle alone. A recorded start without a handle MUST count as started.

#### Scenario: A job is refused before its playbook runs

- **WHEN** a job fails before its executor starts a playbook — its host is unregistered, its action unsupported, or its codec, inventory, host key or relay refuses it
- **THEN** the job records no `execution_started_at` and no execution handle, and its execution never started

#### Scenario: A job's playbook ran and failed

- **WHEN** a job's playbook is started and the job then fails
- **THEN** the job records when its execution started, and its execution started

#### Scenario: The start cannot be recorded

- **WHEN** the job authority cannot record that a job's execution is starting
- **THEN** no playbook is spawned for that attempt, and the attempt fails

#### Scenario: A playbook is spawned and its handle cannot be recorded

- **WHEN** a job's playbook is spawned and recording its execution handle fails
- **THEN** the job's recorded start remains, and its execution counts as started

#### Scenario: A job recorded before the start column existed

- **WHEN** a failed job recorded before `execution_started_at` existed is classified
- **THEN** it counts as started exactly when it records an execution handle

### Requirement: A teardown that never started is run again under a new job identity, within a bound

When a fulfillment's teardown job failed and its execution never started, the compute family's job-backed provider MUST run the teardown again under a new job identity, within a bound. A teardown job whose execution started, or that was cancelled, MUST NOT be run again: its teardown stays failed, and its capacity held, until an operator verifies the host and force-releases it.

Dispatching a teardown MUST adopt the reservation's latest teardown job, unless that job's execution never started and a rerun is ready; then it MUST submit rerun *n* under the job identity `"{reservation}:teardown:rerun-{n}"`, where *n* counts the teardown jobs already bound to the reservation, with the parameters of the teardown operation prepared before. A first teardown keeps the identity `"{reservation}:teardown"`. A dispatch that finds the rerun it submitted earlier as the latest job MUST adopt it. The fulfillment's teardown metadata MUST name the latest teardown job; its create job and the lease's release handle are unchanged.

Rerun *n* is ready once the previous teardown job has been finished for the job retry policy's delay after *n* − 1 retries, and no more than `teardown_rerun_limit` reruns are run. `teardown_rerun_limit` MUST default to 3; 0 disables reruns, and the provisioning service MUST refuse to start with a negative value. One compute-owned predicate MUST decide whether a teardown is not rerunnable, waiting for a rerun, ready for one, or has spent its reruns, and dispatch, the release status, and operator reporting MUST all use it. A compensating teardown is run again by the same rule and keeps the reason `create_compensation`.

#### Scenario: A teardown fails before its playbook starts

- **WHEN** a fulfillment's teardown job fails and its execution never started
- **THEN** once the rerun's delay has passed, the teardown is dispatched again under `"{reservation}:teardown:rerun-1"`, and the fulfillment's teardown metadata names the new job

#### Scenario: A rerun succeeds

- **WHEN** a teardown's rerun succeeds
- **THEN** the fulfillment reaches `torn_down`, and the reservation's capacity is released through its lease without an operator

#### Scenario: A teardown's playbook ran and failed

- **WHEN** a fulfillment's teardown job fails after its execution started
- **THEN** no further teardown job is submitted, and the teardown stays failed with its capacity held for an operator

#### Scenario: A teardown job was cancelled

- **WHEN** a fulfillment's teardown job was cancelled before its execution started
- **THEN** no rerun is submitted

#### Scenario: The reruns are spent

- **WHEN** a teardown has failed without starting `teardown_rerun_limit` times after its first attempt
- **THEN** no further teardown job is submitted, and the release status reports the teardown failed, saying its execution never started and how many reruns were spent

#### Scenario: Dispatch is repeated after a rerun was submitted

- **WHEN** a dispatch submitted a rerun and stopped before recording it, and dispatch runs again
- **THEN** it adopts the rerun as the reservation's latest teardown job and submits no other

#### Scenario: A compensating teardown fails before its playbook starts

- **WHEN** a compensating teardown's job fails and its execution never started
- **THEN** it is run again by the same rule, and the fulfillment keeps the reason `create_compensation`

#### Scenario: Reruns are disabled

- **WHEN** `teardown_rerun_limit` is 0 and a teardown job fails without starting
- **THEN** no rerun is submitted, and the teardown stays failed for an operator

#### Scenario: The rerun limit is negative

- **WHEN** the provisioning service is configured with a negative `teardown_rerun_limit`
- **THEN** it refuses to start, naming the setting

## MODIFIED Requirements

### Requirement: Allocation-backed lease release
Lease expiry MUST invoke the configured executor release delegate before capacity is reported released; failed release MUST remain observable and operator-repairable.

#### Scenario: Teardown fails
- **WHEN** the release delegate returns a failure that no rerun of the teardown will retry
- **THEN** capacity remains unavailable, the lease enters `release_failed`, and retry/force-release controls remain available

### Requirement: Site-backed release lifecycle
Compute lease lifecycle MUST use an injected site-authority port and MUST NOT report capacity released until the selected executor release succeeds or an operator performs an explicit force-release action.

#### Scenario: Executor release succeeds
- **WHEN** a lease expires and its registered executor completes teardown or reclaim
- **THEN** compute lifecycle records successful allocation release through the site-authority port and capacity becomes available

#### Scenario: Executor release fails
- **WHEN** VM teardown or bare-metal reclaim returns a failure that no rerun of the teardown will retry
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
- **AND** any rerun of the teardown is submitted by the fulfillment's provider under that `fulfillment_id`, never by lease lifecycle
- **AND** capacity SHALL remain unavailable until that aggregate reaches `torn_down`

### Requirement: An undelivered lease is released by what its fulfillment proves

A lease's release MUST follow the state of its reservation's fulfillment aggregate. Deciding
a release MUST NOT write: the reservation MUST be recorded `releasing`, with the fulfillment
as its release handle, before teardown is begun, so that a restart between the two resumes
the release from `releasing`, and a failure to begin teardown leaves it for the lease
lifecycle's next cycle. A lease whose teardown is still in progress after the grace period
MUST be counted in the lease lifecycle's cycle diagnostics, and MUST NOT be moved to another
state for that alone: the lease stays `releasing` while its fulfillment's teardown is in
progress or a rerun of it is pending. The grace period MUST run from when the reservation
entered `releasing`, not from the lease's end. When the site refuses one of the lifecycle's
writes because the reservation changed since it was read, the lifecycle MUST re-read the
reservation and leave it in the state another actor recorded; in particular, it MUST NOT
begin teardown after a refused move to `releasing`.

- An `active` aggregate MUST be torn down before capacity returns.
- An aggregate whose teardown has already begun — `teardown_dispatch_pending`, `tearing_down`, or `teardown_failed` — MUST have that teardown adopted, not a second one begun.
- A `torn_down` aggregate MUST return the capacity as a completed release.
- An absent, `assigned`, or `abandoned` aggregate MUST return the capacity directly, as a completed release, only when the reservation's provenance proves nothing was dispatched: no create handle on the reservation and no job bound to the reservation. An `assigned` aggregate MUST be abandoned only by a compare-and-set taken after the proof is checked, so a concurrent dispatch cannot outrun it and a refused release writes nothing.
- When the create is in flight (`dispatch_pending` or `dispatching`), the release MUST be remembered durably, with the reservation `releasing` and the fulfillment as its release handle, and teardown MUST begin once the aggregate reaches `active`, or once it reaches a compensable `failed`; the grace period MUST NOT be counted while the create is in flight.
- A `failed` aggregate is compensable when the provider reported its dispatched create failed (`provider_reported_failure`) and its durable provider metadata is the job-backed provider's, naming its create operation, job, host, and target. One compute-owned predicate MUST decide this, and the release decision, the release status, and the begin of teardown MUST all use it. A compensable aggregate MUST have its domain's ordinary teardown begun as a compensating teardown, the same way for every offering mode, and capacity returns only once the aggregate reaches `torn_down`. The begin MUST re-judge eligibility from the aggregate's state at that moment, not from an earlier decision.
- A compensating teardown records the failure reason `create_compensation`. A `torn_down` aggregate carrying that reason ended compensated; a `torn_down` aggregate carrying any other reason, or none, was delivered and torn down. A teardown failure of a compensating teardown MUST keep that reason and replace only the failure message, which therefore holds the latest diagnostic. The create job itself stays durable, with its status, result, and log; the fulfillment's earlier diagnostic is not kept verbatim, and the job's error MAY be empty, as for a create that succeeded without usable delivery evidence.
- When a compensable aggregate's provider cannot prepare its teardown, because its create job is missing or names another resource, beginning the teardown MUST be refused writing nothing, and the lease MUST enter `release_failed` with the reason `compensation_refused`, its capacity held. The failure MUST be recorded under the release handle the lifecycle recorded when it entered `releasing`, so that a refusal observed for one release cannot land on another. Any other failure to begin is transient: the lease stays `releasing`, and the lifecycle's next cycle retries it.
- Any other `failed` aggregate — quarantined, failed for metadata that cannot name its output, or carrying no or unreadable provider metadata — or an absent, `assigned`, or `abandoned` one without the provenance proof, MUST put the lease in `release_failed` for an operator to verify and force-release. An operator's retry-release of such a lease whose aggregate has since become compensable MUST begin the compensating teardown.
- Only a release of the lease — termination, expiry, or an operator's retry-release — begins a compensating teardown. A lease already `released` or `force_released` MUST NOT be revisited.
- A teardown observed as `teardown_failed` while the lease is `releasing` MUST keep the lease `releasing` while a rerun of the teardown is pending, as "A teardown that never started is run again under a new job identity, within a bound" decides, and MUST put the lease in `release_failed` once none is pending. An operator's retry-release MUST re-observe the same aggregate, and the lease then waits for any rerun pending.

The compute provisioning composition MUST supply the site authority's release guard, which permits freeing a reservation's capacity only for a `torn_down` aggregate or for an absent, `assigned`, or `abandoned` one whose provenance proof holds, and MUST check that proof in the transaction that frees the capacity. Every direct capacity return, whether by the lease lifecycle or by any caller of the site's release, MUST pass that guard; force-release remains the operator's recorded override.

#### Scenario: A committed lease whose fulfillment never began expires

- **WHEN** a lease's reservation was committed but its fulfillment was never dispatched, and the lease reaches its end
- **THEN** the assigned aggregate is abandoned, the capacity returns, and no teardown is attempted

#### Scenario: A lease is terminated while its create is in flight

- **WHEN** a lease is terminated while its fulfillment is `dispatching`
- **THEN** the reservation becomes `releasing` at once, survives a restart in that state, and its teardown begins when the aggregate reaches `active`

#### Scenario: A create failed

- **WHEN** a lease is released and its aggregate is `failed` after its provider reported the dispatched create failed, with provider metadata naming its create job
- **THEN** the lease becomes `releasing` with the fulfillment as its handle, the domain's teardown is begun as a compensating teardown recording `create_compensation`, and capacity returns only when the aggregate reaches `torn_down`

#### Scenario: A create in flight at termination then fails

- **GIVEN** a lease terminated while its fulfillment was `dispatching`, so its reservation is `releasing`
- **WHEN** the provider reports the create failed, leaving a compensable `failed` aggregate
- **THEN** the release status reports it ready for teardown, the lifecycle's next cycle begins the compensating teardown, and capacity returns only when the aggregate reaches `torn_down`

#### Scenario: A failed create cannot be compensated

- **WHEN** a lease is released and its aggregate is `failed` with no provider metadata, as a quarantined row, or for metadata that cannot name its output
- **THEN** the lease enters `release_failed`, no teardown is begun, and capacity stays held until an operator force-releases it

#### Scenario: A compensating teardown cannot be prepared

- **WHEN** a lease is released and its compensable aggregate's provider cannot prepare the teardown because the create job it names is missing
- **THEN** nothing is written to the aggregate, the lease enters `release_failed` with the reason `compensation_refused`, and capacity stays held

#### Scenario: A compensating teardown fails

- **WHEN** a compensating teardown reaches `teardown_failed` and no rerun of it is pending
- **THEN** the aggregate keeps the reason `create_compensation` with the teardown's diagnostic as its message, and the lease enters `release_failed` with capacity held, as for an active fulfillment's failed teardown

#### Scenario: A delivered fulfillment's teardown fails once and then succeeds

- **WHEN** an `active` fulfillment's teardown reaches `teardown_failed` and a later attempt reaches `torn_down`
- **THEN** the aggregate does not carry `create_compensation` and is not read as compensated

#### Scenario: Teardown fails while the lease is releasing

- **WHEN** a releasing lease's aggregate reaches `teardown_failed` and no rerun of its teardown is pending
- **THEN** the lease enters `release_failed` with capacity held, and an operator's retry-release re-observes the same aggregate

#### Scenario: A teardown that never started fails while the lease is releasing

- **WHEN** a releasing lease's aggregate reaches `teardown_failed` and a rerun of its teardown is pending
- **THEN** the lease stays `releasing`, and when the rerun reaches `torn_down` the capacity is released without an operator

#### Scenario: A teardown outlasts the grace period

- **WHEN** a releasing lease's teardown is still in progress after the grace period, its job retrying
- **THEN** the lease stays `releasing` and is counted in the cycle's diagnostics, and when the teardown reaches `torn_down` the capacity is released without an operator

#### Scenario: A failed lease's teardown has a rerun pending

- **GIVEN** a lease in `release_failed` whose aggregate is `teardown_failed` with a rerun of its teardown pending
- **WHEN** an operator retries its release
- **THEN** the lease becomes `releasing` under the same fulfillment, waits for the rerun, and is released when the aggregate reaches `torn_down`

#### Scenario: A storefront releases a delivered lease

- **WHEN** a storefront asks the site to release a reservation whose aggregate is `active`
- **THEN** the release guard refuses, the reservation keeps its capacity and state, and the lease is released only through its lifecycle
