## MODIFIED Requirements

### Requirement: Scheduling and assignment

`PhysicalSettlementScheduler.schedule_resource` owns placement. It enumerates eligible candidates through the site and pool authorities, delegates ordering/selection to a `SettlementSchedulingPolicy`, and returns a `SettlementResource`.

`schedule_resource` is one atomic database transaction: it locks and validates the reservation, enumerates eligible candidates, applies scheduling policy, performs any fair capacity rebind, and creates or returns the settlement assignment, committing or rolling back all of it together. A caller never needs its own compensating error handling for a partially-completed schedule.

The current policy is deterministic two-level round-robin. It sorts eligible pool IDs and chooses the pool after the last automatic selection, then sorts eligible resource IDs in that pool and chooses the resource after that pool's last automatic selection. If a previous cursor no longer names an eligible candidate, selection resumes at the first sorted eligible value. For an unchanged candidate set and policy state, selection is reproducible. Policy remains replaceable; static pool priority is not part of the resource-pool schema.

Round-robin fairness state is durable and scoped per `resource_kind`: one cursor row exists per `resource_kind`, read and rewritten inside the same transaction as the settlement-record write it accompanies. A buyer negotiates for one `resource_kind` per reservation, so scheduling activity for one kind never perturbs another kind's fairness position. The policy itself remains a pure function of its explicit inputs (`requirement`, `candidates`, and the current cursor value) with no database access of its own; the scheduler owns reading and persisting the cursor.

An explicit resource constraint bypasses policy choice but not reservation, pool, resource, shape, attribute, or capacity eligibility. It also does not read or advance the durable fairness cursor.

Scheduling and fulfillment execution are separate calls. A provider receives the already-selected `SettlementResource` and MUST NOT substitute another resource. If a selected resource becomes unusable, execution reports a typed failure and orchestration returns to the scheduler boundary according to lifecycle policy.

The same `capacity_reservation_id` and equivalent request MUST return the existing assignment. A conflicting retry MUST fail rather than creating a second binding. Assignment and cursor state are durable: idempotency holds across process restart and across scheduler instances sharing the same database, not only within one running process.

The compute provisioning service uses SQLite. `schedule_resource` reserves SQLite's single writer slot with an immediate write transaction before reading the reservation, candidates, or cursor, so concurrent scheduling attempts serialize and observe one durable outcome. This is a database-wide SQLite writer guarantee, not PostgreSQL-style row locking, matching the concurrency contract already documented for fulfillment acceptance (see "Durable settlement persistence"). The scheduler receives a narrow scheduling unit of work rather than raw persistence services: one transaction-scoped interface exposes only reservation locking, candidate and pool reads, cursor access, capacity rebinding, and settlement assignment. This makes the shared commit boundary structural and provides a stable semantic seam for deterministic independent-session concurrency tests.

Scheduling errors distinguish a missing or expired reservation, a request that conflicts with reservation or existing-assignment state, and a valid request for which no candidate is eligible.

#### Scenario: Equivalent scheduling retry

- **WHEN** the same reservation and normalized requirements are scheduled again, whether against the same scheduler instance or a different one sharing the same database
- **THEN** the existing settlement-resource assignment is returned without advancing policy cursors

#### Scenario: Previous cursor is no longer eligible

- **WHEN** the previously selected pool or resource is absent from the eligible candidate set
- **THEN** round-robin resumes deterministically from the first sorted eligible pool or resource

#### Scenario: Explicit resource is ineligible

- **WHEN** a request identifies a resource in a disabled pool or without sufficient capacity
- **THEN** scheduling rejects it without invoking automatic policy or advancing cursors

#### Scenario: Scheduler process restarts

- **WHEN** a fresh scheduler instance is constructed against the same database after a restart
- **THEN** it reads the same durable assignment and cursor state and an equivalent retry still returns the existing assignment rather than being evaluated as new

#### Scenario: Scheduling fails after the cursor is written but before commit

- **WHEN** an error occurs after the fairness cursor is updated in-transaction but before the settlement record commits
- **THEN** the whole transaction rolls back, leaving neither a partial cursor advance, a partial capacity rebind, nor an orphaned settlement row

#### Scenario: Provider attempts independent placement

- **WHEN** a provider cannot use the selected resource
- **THEN** it reports validation or execution failure and does not choose a replacement resource

`schedule_resource` is exposed over HTTP as `POST /fulfillment/schedule`, accepting `capacity_reservation_id`, `market`, `requirements`, and an optional `resource_id` constraint, and returning the assigned `SettlementResource`'s fields. It maps `SettlementEntityNotFoundError` to a 404 `fulfillment_not_found`, `CapacityReservationExpiredError` and `SettlementRequestMismatchError` to a 409 `fulfillment_conflict`, and `NoEligibleSettlementResourceError` to a 422 `no_eligible_resource` — the same error-mapping convention `/fulfillment/begin` already uses for its own error taxonomy. A caller MUST schedule before it can begin fulfillment: `begin_fulfillment`/`POST /fulfillment/begin` reads the already-scheduled resource from the row and returns `fulfillment_not_found` if none has been scheduled yet.

#### Scenario: Storefront schedules over HTTP before beginning fulfillment

- **WHEN** a storefront calls `POST /fulfillment/schedule` for a capacity reservation and then `POST /fulfillment/begin` for the same reservation
- **THEN** the begin call uses the resource the schedule call assigned, without either endpoint accepting or requiring the caller to resupply it

#### Scenario: Begin is attempted before scheduling

- **WHEN** `POST /fulfillment/begin` is called for a capacity reservation that has never been scheduled
- **THEN** it responds 404 `fulfillment_not_found` rather than scheduling implicitly

<a id="fulfillment-convergence-worker"></a>

**Fulfillment convergence worker.** The compute provisioning composition runs a periodic fulfillment convergence worker alongside its other lifecycle workers. Each pass claims a bounded batch in a short SQLite write transaction, closes that transaction before provider I/O, and applies the provider outcome in a second transaction only while the same worker still owns the claim and the aggregate remains in the expected source state. Create dispatch, create-status convergence, teardown dispatch, and teardown-status convergence are independently callable passes so recovery behavior can be tested and operated without coupling all work to one monolithic cycle. There is no attempt-count ceiling: a row that keeps failing keeps retrying with backoff rather than being abandoned to a terminal state on its own, and durable claim state (not worker-local memory) is what a fresh worker instance resumes from after a restart. The attempt count counts consecutive claims that produced only a failure: an applied outcome, or a provider answering that its operation is still pending, starts it again, so a phase never inherits the backoff of an earlier one. A pending answer keeps the claim for the initial poll interval, so a healthy operation is polled again after that interval whatever the row's earlier claims cost, and only consecutive failures grow the lease. The one exception is unresolvable persisted resource identity on a provider-reported create success: since the metadata that failed to resolve is already durable and will not change on a later retry, that specific condition transitions directly to `failed` rather than retrying indefinitely behind diagnostics indistinguishable from a healthy in-progress row. The worker emits exactly one structured recovery-diagnostics event after each completed cycle rather than logging diagnostics per row. The snapshot contains a stable entry for every recovery lifecycle state, including states with zero rows. Each state reports total rows, actively claimed rows, expired claims eligible for reclamation, oldest-row age, and maximum attempt count. Provider-reported `failed` and `teardown_failed` rows are reported as separate counts. Counts follow the row's current state: a row whose compensating teardown has begun leaves the `failed` count, is counted in its teardown state and in `teardown_failed` while that teardown has failed, and once it reaches `torn_down` leaves every recovery-state and failure count, never counted as failed. Age and attempt metrics are calculated per lifecycle state; the contract does not expose global oldest-age or maximum-attempt fields.

<a id="durable-settlement-persistence"></a>

**Durable settlement persistence.** One durable `SettlementRecord` aggregate exists per `capacity_reservation_id`, which is its primary key. There is no separate scheduler-owned assignment table and no separate fulfillment record: scheduling creates the row, `begin_fulfillment` accepts it in place, and provider dispatch/teardown converge the same row. `fulfillment_id` is a distinct, nullable-until-accepted, unique column on that row — not a second primary key or a second row — generated the first time the aggregate is accepted past `assigned`. Whole-fulfillment status and teardown are addressed by `fulfillment_id`; scheduling and acceptance idempotency are addressed by `capacity_reservation_id`.

The aggregate's lifecycle states are `assigned`, `dispatch_pending`, `dispatching`, `active`, `failed`, `teardown_dispatch_pending`, `tearing_down`, `torn_down`, `teardown_failed`, and `abandoned`. `torn_down` and `abandoned` are terminal; `teardown_failed` is not, since recovery may retry teardown. `failed` is terminal except for one edge, `failed` → `teardown_dispatch_pending`, taken only by a compensating teardown (below). Transitions are checked against one compact table-driven validator shared by every caller (scheduler, fulfillment acceptance, provider recovery, teardown, and abandonment) rather than a bespoke check per edge. A retry that finds the row already at its target state is a no-op return, not a transition-table lookup — self-transitions are intentionally absent from the table so it describes only real state changes.

#### Scenario: Illegal state skip

- **WHEN** a caller attempts to move the aggregate directly from `assigned` to `active`
- **THEN** the transition validator rejects it

Two independently-persisted, independently-immutable-once-written request shapes govern two independent equivalence checks, because they answer different questions for different callers:

- **Scheduling equivalence** governs `schedule_resource`/`select_resource` retries. It compares `market` and the normalized `SettlementRequirement` (`scheduling_requirements`) against the stored values. A caller-supplied resource constraint, if present, is checked separately for consistency against the row's `settlement_resource_id` once assigned — it is not folded into the `market`/`requirements` comparison, since it is an optional pre-selection constraint on the request, not part of the requirement identity being scheduled.
- **Fulfillment equivalence** governs `begin_fulfillment` acceptance and retries. The supplied `market` must match the immutable market established by scheduling, including on the first acceptance, and the domain-specific `fulfillment_request` envelope must match once written. Acceptance never rewrites the scheduled market. There is no caller-supplied resource to compare on this path: `begin_fulfillment` loads the already-scheduled `SettlementResource` from the row rather than trusting one supplied by the caller.

Either check rejects a retry whose stored values differ as a conflict; it does not silently return the existing assignment for a shape the caller no longer means.

#### Scenario: Conflicting fulfillment retry

- **WHEN** `begin_fulfillment` is retried for the same `capacity_reservation_id` with a different `fulfillment_request`
- **THEN** it reports a fulfillment conflict rather than returning the first fulfillment's result

#### Scenario: Equivalent retry after provider acknowledgement

- **WHEN** an equivalent `begin_fulfillment` retry finds provider metadata already acknowledged
- **THEN** it returns the existing fulfillment without dispatching again

#### Scenario: Dispatch fails after durable acceptance

- **WHEN** provider dispatch fails after the acceptance transaction commits
- **THEN** the fulfillment remains accepted in `dispatch_pending` and the accepted fulfillment view is returned for recovery

Provider submission acknowledgement is a second short transaction. Identical metadata is idempotent; conflicting provider identity is rejected without rewriting the stored value. The gap between provider submission and acknowledgement is recovered by redispatching the persisted prepared operation with the same deterministic idempotency key.

`begin_fulfillment_teardown` is the whole-fulfillment teardown entrypoint, addressed by `fulfillment_id`. It is valid only from `active`; a caller receives the current view without error for a fulfillment already at or past `teardown_dispatch_pending` (including terminal `torn_down` and the retryable `teardown_failed`), so a caller does not need to track whether it already asked for teardown before asking again. Unlike `begin_fulfillment`, it performs no synchronous dispatch attempt of its own: it prepares the teardown envelope — reusing one already captured on the row rather than re-preparing it, which is what makes a backfilled row's frozen-at-migration-time teardown envelope survive unchanged — and transitions the aggregate to `teardown_dispatch_pending`. The fulfillment convergence worker's teardown dispatch and status-convergence passes (see "Fulfillment convergence worker") own everything from there; nothing about them differs for a `begin_fulfillment_teardown`-initiated row versus a backfilled one, since both reach `teardown_dispatch_pending` through the same transition with the same prepared-operation shape.

#### Scenario: Teardown requested for a fulfillment already tearing down

- **WHEN** `begin_fulfillment_teardown` is called for a fulfillment already in `teardown_dispatch_pending`, `tearing_down`, `torn_down`, or `teardown_failed`
- **THEN** it returns the current view without re-preparing or re-transitioning

#### Scenario: Teardown requested for a fulfillment that was never active

- **WHEN** `begin_fulfillment_teardown` is called for a fulfillment in any state other than `active` or one of the already-tearing-down states above
- **THEN** it reports a conflict rather than beginning teardown

A failed create may have left effects the provider can undo. `begin_compensating_teardown`, addressed by `fulfillment_id`, begins a **compensating teardown** for a `failed` fulfillment. Its caller passes an `authorize` predicate, which the operation evaluates inside its write transaction over the record's state, failure reason, and provider metadata. The kit treats that metadata as opaque and never judges eligibility itself; the caller's predicate does. The operation answers by the aggregate's state in that transaction:

- an unknown `fulfillment_id` is not found;
- a fulfillment at or past `teardown_dispatch_pending` returns its current view, writing nothing, as `begin_fulfillment_teardown` does;
- a `failed` fulfillment the predicate refuses, or whose provider raises a configuration error preparing its teardown, is refused with a compensation-refused conflict, writing nothing, and stays `failed`;
- a `failed` fulfillment the predicate authorizes and whose provider prepares its teardown has that teardown recorded, and moves to `teardown_dispatch_pending` with the failure reason `create_compensation`, keeping its failure message; convergence then dispatches and observes it as any teardown;
- any other state is a conflict, writing nothing.

`create_compensation` is the kit's reason for a compensating teardown, and no other path writes it. A fulfillment carrying it was compensated, and it ended compensated when it is `torn_down`; a `torn_down` fulfillment carrying any other reason, or none, was delivered. A non-null reason alone marks nothing, because a delivered fulfillment's failed teardown records a reason that its later success does not clear. When a compensating teardown fails, convergence keeps the reason `create_compensation` and replaces only the failure message with the teardown's diagnostic, so the message holds the latest diagnostic. The kit does not keep the earlier message elsewhere; what the provider recorded of the create, such as its job, is the provider's to keep.

#### Scenario: A failed create is compensated

- **WHEN** a compensating teardown is begun for a `failed` fulfillment the caller authorizes and whose provider prepares its teardown
- **THEN** the aggregate moves to `teardown_dispatch_pending` with the reason `create_compensation` and its message kept, and convergence dispatches the provider's teardown

#### Scenario: A failed create's teardown cannot be prepared

- **WHEN** a compensating teardown is begun for a `failed` fulfillment whose provider cannot prepare a teardown from its metadata
- **THEN** the operation refuses with a compensation-refused conflict and the aggregate stays `failed` with nothing prepared

#### Scenario: The caller does not authorize compensation

- **WHEN** a compensating teardown is begun for a `failed` fulfillment its caller's predicate refuses
- **THEN** the operation refuses with a compensation-refused conflict, writing nothing

#### Scenario: A compensating teardown is requested twice

- **WHEN** a compensating teardown is begun for a fulfillment whose compensating teardown has already begun
- **THEN** it returns the current view without preparing or transitioning again

#### Scenario: A compensating teardown fails and is retried

- **WHEN** a compensating teardown reaches `teardown_failed` and convergence's later attempt reaches `torn_down`
- **THEN** the aggregate carries `create_compensation` throughout, its message holding the last teardown diagnostic recorded

#### Scenario: A delivered fulfillment's teardown fails once

- **WHEN** an `active` fulfillment's teardown reaches `teardown_failed` and later `torn_down`
- **THEN** it does not carry `create_compensation`, and is not read as compensated

#### Scenario: Ordinary teardown of a failed fulfillment

- **WHEN** `begin_fulfillment_teardown` is called for a `failed` fulfillment
- **THEN** it reports a conflict, as before; only the compensating operation begins a failed fulfillment's teardown

`begin_fulfillment_teardown` is exposed over HTTP as `POST /fulfillment/{fulfillment_id}/begin-teardown`, returning the same fulfillment-acceptance view shape `/fulfillment/begin` returns, with the same `fulfillment_not_found`/`fulfillment_conflict` error-mapping convention.

A fulfillment produces zero or more `ProvisionedResource` rows, each with a globally unique `provisioned_resource_id` and a denormalized `fulfillment_id`. Resource identities are resolved from validated provider metadata only after the provider reports create success; replay is idempotent for the same fulfillment-owned output identity, backed by the globally unique `provisioned_resource_id` primary key, not just an application-level existence check — a genuine concurrent insert race is resolved by re-reading and returning the winning row rather than raising. Confirmed teardown updates those existing rows rather than resolving or creating resource identities again. Per-resource teardown is not exposed unless a caller requires it; teardown addresses the whole fulfillment.

There is no persisted `SettlementResult` model. A caller-facing fulfillment result is a read-time projection over the aggregate's state/failure fields and its `ProvisionedResource` children, not a value stored independently — there is no case needing it durable on its own absent a `SettlementResult` CRUD API, and persisting one would create a second place credential-adjacent data could live, when the aggregate holds no credentials and the provider supplies them on each read.

Prepared provider create/teardown input is captured as a `VersionedEnvelope`-typed payload on the aggregate, frozen before the transaction that marks the corresponding dispatch-pending state commits, so a recovery retry dispatches from what was accepted rather than a live re-read of pool or provider configuration.

Repository callers provide validated canonical `SettlementRequirement` and `VersionedEnvelope` models. Persistence serializes their JSON-compatible model form and uses structural equality; it does not accept arbitrary dictionaries as an equivalence boundary or infer equivalence among unvalidated representations.

The generic lifecycle transition operation may update only prepared create/teardown operation payloads, provider and teardown metadata, and failure reason/message fields. Aggregate identity, scheduled-resource identity, market, scheduling requirements, fulfillment identity/request, lifecycle state, recovery leases, timestamps, and unknown fields are not writable through lifecycle updates. Unsupported updates are rejected before state or in-memory row mutation.

The compute provisioning service uses SQLite. Fulfillment acceptance reserves SQLite's single writer slot with an immediate write transaction before reading and updating the aggregate, so concurrent acceptance attempts serialize and observe one durable `fulfillment_id`. This is a database-wide SQLite writer guarantee, not PostgreSQL-style row locking. Aggregate creation remains protected by the `capacity_reservation_id` primary key; an observed uniqueness race is resolved by re-reading the winning row and applying the ordinary equivalence rule.

Recovery-lease fields (a claim owner, a claim expiry, and an attempt count) live directly on the aggregate row rather than in a separate claims table: one aggregate has at most one pending provider operation at a time, so a separate table would only add a join with no independent-claiming benefit. Recovery acquisition uses a short `BEGIN IMMEDIATE` transaction that selects eligible unclaimed or expired rows, assigns the worker and expiry, increments the attempt count, and commits before provider I/O; the owning worker's healthy progress starts the count again. SQLite's single-writer reservation serializes concurrent claim attempts; this is not represented as portable row locking or a distributed multi-replica protocol. Provider calls run without an open database transaction. A second short transaction applies an outcome only when the expected lifecycle state and current claim owner still match, preventing a worker whose lease was reclaimed from writing a stale result or changing another worker's claim, its expiry, or its attempt count.

#### Scenario: Expired claim is reclaimed

- **WHEN** a claimed row's claim has expired and no other claim has replaced it
- **THEN** a subsequent claim attempt may claim it again

#### Scenario: A healthy pending teardown after a long create

- **WHEN** a teardown's status reads pending on a row whose create took nine claims
- **THEN** the claim is kept only for the initial poll interval and its attempt count starts
  again, so the next cycle observes the finished teardown and the lease is released within the
  lease watchdog's grace period

#### Scenario: Status reads keep failing

- **WHEN** consecutive status reads of a row fail
- **THEN** each claim's lease grows with the attempt count until a read succeeds
