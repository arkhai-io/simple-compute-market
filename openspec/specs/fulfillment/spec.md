# Fulfillment Specification

## Purpose

Define the domain-neutral physical-settlement scheduling and fulfillment-provider capability shared by storefront-facing orchestration, site capacity, resource-pool administration, and concrete provisioning adapters.

## Responsibilities

The fulfillment capability owns:

- opaque fulfillment lifecycle identifiers;
- the physical settlement request and multidimensional requirement carrier;
- settlement candidates and the selected Settlement Resource carrier;
- deterministic scheduling policy and scheduler orchestration;
- provider-neutral create, status, and teardown contracts;
- provider registration and resolution;
- structured validation and stable generic fulfillment errors;
- versioned envelopes for provider/domain dictionaries that cross persistence or package boundaries;
- the durable settlement/fulfillment aggregate's schema, state machine, equivalence checks, and repository.

It does not own:

- commercial agreement identity or storefront deal state;
- authoritative capacity admission and reservation storage;
- resource-pool CRUD or provider configuration persistence;
- VM, bare-metal, Kubernetes, storage, or other provider-specific request/result vocabulary;
- executor job queues or lease-watchdog policy;
- the provisioning-owned recovery sweep that consumes durable recovery claims (see "Durable settlement persistence").

## Ownership

The capability is distributed as `arkhai-kit-fulfillment` and imported as `market_fulfillment`.

Provider-neutral scheduling and provider execution contracts live together in this package. Resource-pool administration must not import fulfillment contracts merely to type its provider configuration, and fulfillment must not depend on a deployed provisioning service. Concrete providers and domain requirement translators live in domain adapters or service composition.

## Requirements

### Requirement: Dependency boundary

`market_fulfillment` is a higher kit layer than the site and resource-pool authorities. It may depend on `market_site` and `market_resource_pools`. Those lower layers MUST NOT import `market_fulfillment`, including under `TYPE_CHECKING`.

Carrier modules for IDs, envelopes, requests, requirements, resources, and provider protocols MUST remain independent of concrete service implementations. Scheduler modules MAY depend on site and resource-pool service interfaces required to enumerate and bind eligible resources.

#### Scenario: Type-only reverse import is introduced

- **WHEN** `market_site` or `market_resource_pools` imports `market_fulfillment` under `TYPE_CHECKING`
- **THEN** the repository dependency-boundary validation rejects the import as an upward dependency

#### Scenario: A concrete VM adapter implements fulfillment

- **WHEN** the VM provisioning composition registers an Ansible provider
- **THEN** the adapter depends on `market_fulfillment` and VM/Ansible packages while the fulfillment kit remains free of VM vocabulary

### Requirement: Fulfillment identities

Fulfillment lifecycle IDs MUST be opaque UUIDv7 strings:

- `capacity_reservation_id` identifies admitted capacity and is the idempotency boundary for scheduling and beginning fulfillment;
- `fulfillment_id` identifies the durable post-acceptance fulfillment aggregate;
- `settlement_resource_id` identifies selected physical supply;
- `provisioned_resource_id` identifies one provider-created output;
- `result_id` identifies one recorded result.

Authority identity such as `site_id` remains explicit. IDs MUST NOT encode site, pool, provider, or market fields. The public type remains `str`; callers must not rely on UUID timestamp layout beyond treating the value as opaque.

Commercial agreement IDs do not belong in the generic physical settlement request. The storefront retains commercial context and translates accepted terms into generic requirements before crossing the provisioning boundary.

#### Scenario: Several resources are created by one fulfillment

- **WHEN** one provider operation produces two VMs or pods
- **THEN** both outputs have distinct `provisioned_resource_id` values while sharing one `fulfillment_id` and capacity reservation

### Requirement: Physical settlement request

A `PhysicalSettlementRequest` MUST contain:

- `capacity_reservation_id`;
- the market or requirement namespace needed to select the correct domain translation;
- one or more positive finite multidimensional requirements;
- optional pool or specific-resource constraints when permitted by the accepted terms.

The request MUST NOT carry an `agreement_id` or legacy `allocation_id` alias. Domain-specific requirement values may remain structured, but generic scheduling MUST evaluate only normalized settlement requirements.

#### Scenario: A requirement contains a non-positive dimension

- **WHEN** a request declares an empty dimension map, zero, a negative quantity, NaN, or infinity
- **THEN** model validation rejects the request before scheduling

#### Scenario: Buyer-selected specific resource

- **WHEN** accepted terms intentionally identify a concrete physical resource
- **THEN** the request may constrain scheduling to that resource and the scheduler verifies eligibility rather than silently selecting another resource

### Requirement: Multidimensional eligibility

A candidate is eligible only when it is enabled, satisfies pool and resource constraints, has the required resource kind, and has availability greater than or equal to every requested dimension.

A dimension absent from a candidate's availability is treated as zero. Passing GPU fit does not compensate for insufficient RAM, CPU, disk, or another requested dimension.

This check is `market_site`'s exported `resource_satisfies_requirement`, not a separate implementation in the scheduler: reservation-time admission and scheduling-time eligibility evaluate the same predicate so they cannot independently drift on what "fits" means.

A scheduling request MAY narrow the dimensions it asks for relative to what the capacity reservation holds, but MUST NOT exceed the reservation in any dimension the reservation itself declares. A dimension the reservation does not declare is not governed by it and is not subject to this check; whether a candidate has room for it is an ordinary eligibility question.

#### Scenario: Secondary dimension does not fit

- **WHEN** a candidate has sufficient GPU but insufficient RAM
- **THEN** the scheduler excludes it

#### Scenario: Legacy single-dimension request

- **WHEN** a request declares only GPU units
- **THEN** candidates are evaluated using that dimension without requiring unrelated dimensions

#### Scenario: Scheduling request exceeds the reservation

- **WHEN** a schedule request asks for more of a dimension than the capacity reservation holds for that same dimension
- **THEN** scheduling rejects the request rather than silently admitting a shape reservation-time admission never verified fits anywhere

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

## Fulfillment convergence worker

The compute provisioning composition runs a periodic fulfillment convergence worker alongside its other lifecycle workers. Each pass claims a bounded batch in a short SQLite write transaction, closes that transaction before provider I/O, and applies the provider outcome in a second transaction only while the same worker still owns the claim and the aggregate remains in the expected source state. Create dispatch, create-status convergence, teardown dispatch, and teardown-status convergence are independently callable passes so recovery behavior can be tested and operated without coupling all work to one monolithic cycle. There is no attempt-count ceiling: a row that keeps failing keeps retrying with backoff rather than being abandoned to a terminal state on its own, and durable claim state (not worker-local memory) is what a fresh worker instance resumes from after a restart. The one exception is unresolvable persisted resource identity on a provider-reported create success: since the metadata that failed to resolve is already durable and will not change on a later retry, that specific condition transitions directly to `failed` rather than retrying indefinitely behind diagnostics indistinguishable from a healthy in-progress row. The worker emits exactly one structured recovery-diagnostics event after each completed cycle rather than logging diagnostics per row. The snapshot contains a stable entry for every recovery lifecycle state, including states with zero rows. Each state reports total rows, actively claimed rows, expired claims eligible for reclamation, oldest-row age, and maximum attempt count. Provider-reported `failed` and `teardown_failed` rows are reported as separate counts. Age and attempt metrics are calculated per lifecycle state; the contract does not expose global oldest-age or maximum-attempt fields.

## Durable settlement persistence

One durable `SettlementRecord` aggregate exists per `capacity_reservation_id`, which is its primary key. There is no separate scheduler-owned assignment table and no separate fulfillment record: scheduling creates the row, `begin_fulfillment` accepts it in place, and provider dispatch/teardown converge the same row. `fulfillment_id` is a distinct, nullable-until-accepted, unique column on that row — not a second primary key or a second row — generated the first time the aggregate is accepted past `assigned`. Whole-fulfillment status and teardown are addressed by `fulfillment_id`; scheduling and acceptance idempotency are addressed by `capacity_reservation_id`.

The aggregate's lifecycle states are `assigned`, `dispatch_pending`, `dispatching`, `active`, `failed`, `teardown_dispatch_pending`, `tearing_down`, `torn_down`, `teardown_failed`, and `abandoned`. `failed`, `torn_down`, and `abandoned` are terminal; `teardown_failed` is not, since recovery may retry teardown. Transitions are checked against one compact table-driven validator shared by every caller (scheduler, fulfillment acceptance, provider recovery, teardown, and abandonment) rather than a bespoke check per edge. A retry that finds the row already at its target state is a no-op return, not a transition-table lookup — self-transitions are intentionally absent from the table so it describes only real state changes.

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

A fulfillment produces zero or more `ProvisionedResource` rows, each with a globally unique `provisioned_resource_id` and a denormalized `fulfillment_id`. Resource identities are resolved from validated provider metadata only after the provider reports create success; replay is idempotent for the same fulfillment-owned output identity, backed by the globally unique `provisioned_resource_id` primary key, not just an application-level existence check — a genuine concurrent insert race is resolved by re-reading and returning the winning row rather than raising. Confirmed teardown updates those existing rows rather than resolving or creating resource identities again. Per-resource teardown is not exposed unless a caller requires it; teardown addresses the whole fulfillment.

There is no persisted `SettlementResult` model. A caller-facing fulfillment result is a read-time projection over the aggregate's state/failure fields and its `ProvisionedResource` children, not a value stored independently — there is no case needing it durable on its own absent a `SettlementResult` CRUD API, and persisting one would create a second place credential-adjacent data could live when credentials are already fetched live and never persisted.

Prepared provider create/teardown input is captured as a `VersionedEnvelope`-typed payload on the aggregate, frozen before the transaction that marks the corresponding dispatch-pending state commits, so a recovery retry dispatches from what was accepted rather than a live re-read of pool or provider configuration.

Repository callers provide validated canonical `SettlementRequirement` and `VersionedEnvelope` models. Persistence serializes their JSON-compatible model form and uses structural equality; it does not accept arbitrary dictionaries as an equivalence boundary or infer equivalence among unvalidated representations.

The generic lifecycle transition operation may update only prepared create/teardown operation payloads, provider and teardown metadata, and failure reason/message fields. Aggregate identity, scheduled-resource identity, market, scheduling requirements, fulfillment identity/request, lifecycle state, recovery leases, timestamps, and unknown fields are not writable through lifecycle updates. Unsupported updates are rejected before state or in-memory row mutation.

The compute provisioning service uses SQLite. Fulfillment acceptance reserves SQLite's single writer slot with an immediate write transaction before reading and updating the aggregate, so concurrent acceptance attempts serialize and observe one durable `fulfillment_id`. This is a database-wide SQLite writer guarantee, not PostgreSQL-style row locking. Aggregate creation remains protected by the `capacity_reservation_id` primary key; an observed uniqueness race is resolved by re-reading the winning row and applying the ordinary equivalence rule.

Recovery-lease fields (a claim owner, a claim expiry, and an attempt count) live directly on the aggregate row rather than in a separate claims table: one aggregate has at most one pending provider operation at a time, so a separate table would only add a join with no independent-claiming benefit. Recovery acquisition uses a short `BEGIN IMMEDIATE` transaction that selects eligible unclaimed or expired rows, assigns the worker and expiry, increments the attempt count, and commits before provider I/O. SQLite's single-writer reservation serializes concurrent claim attempts; this is not represented as portable row locking or a distributed multi-replica protocol. Provider calls run without an open database transaction. A second short transaction applies an outcome only when the expected lifecycle state and current claim owner still match, preventing a worker whose lease was reclaimed from writing a stale result or clearing another worker's claim.

#### Scenario: Expired claim is reclaimed

- **WHEN** a claimed row's claim has expired and no other claim has replaced it
- **THEN** a subsequent claim attempt may claim it again

### Requirement: Provider contract

A `FulfillmentProvider` separates pure synchronous preparation from asynchronous side effects:

- `prepare_create(capacity_reservation_id, request, resource, pool_config) -> VersionedEnvelope`;
- `dispatch_create(prepared) -> FulfillmentResult`;
- `prepare_teardown(settlement_result, pool_config) -> VersionedEnvelope`;
- `dispatch_teardown(prepared) -> FulfillmentResult`;
- `get_status(capacity_reservation_id, resource, provider_metadata) -> ProviderStatus`;
- `resolve_provisioned_resources(provider_metadata) -> tuple[str, ...]`;
- `fetch_credentials(provider_metadata, provisioned_resources) -> VersionedEnvelope`.

Preparation receives the durable `capacity_reservation_id` explicitly plus caller-supplied pool configuration captured in the acceptance transaction and MUST NOT query resource-pool state independently or derive the reservation identity from the storefront payload. Teardown receives a provider-neutral durable settlement-result view containing the selected resource, provisioned outputs, and provider metadata. Concrete adapters own validation and interpretation of their metadata; shared orchestration treats it as opaque.

`fetch_credentials` is async, since it performs provider I/O, unlike the pure and synchronous `resolve_provisioned_resources`. It is called only by `get_fulfillment_result` (see "Fulfillment status and result queries"), only when the aggregate is `active`, and carries no claim, lease, or generation bookkeeping of its own — it is a stateless read, not a coordinated mutation. Concrete adapters decode whatever provider-owned metadata they persisted at dispatch acknowledgement time to locate the credential source; shared orchestration does not interpret that metadata. Shared orchestration wraps the call: an adapter's own `CredentialFetchFailedError` propagates unchanged, but any other exception is caught, logged with safe structured diagnostics only (`fulfillment_id`, provider identity, stable error category — never raw provider metadata or credential material), and re-raised as `CredentialFetchFailedError` so an unexpected adapter bug surfaces to the caller as the same retryable category rather than leaking an adapter-internal exception type.

Prepared operations are immutable and persisted before dispatch. Dispatch commands use deterministic reservation-scoped idempotency keys. Provider metadata is normalized and validated by the concrete adapter before it crosses the shared persistence boundary. Credentials and sensitive access material use a dedicated secure channel rather than generic metadata.

`ProviderRegistry` maps a provider identity to exactly one provider instance. Duplicate provider identities fail composition. Provider registration remains separate from executor-kind registration; neither namespace implies the other.

#### Scenario: Unknown provider

- **WHEN** a selected resource names an unregistered provider
- **THEN** validation and execution report `provider_not_found` without falling through to another provider

#### Scenario: Equivalent create retry

- **WHEN** create is retried for the same reservation, requirements, selected resource, and provider operation
- **THEN** the existing result is returned and no second physical resource is created

#### Scenario: Conflicting create retry

- **WHEN** the same reservation is retried with different requirements or a different selected resource
- **THEN** orchestration reports a fulfillment conflict

### Requirement: Versioned envelopes

Generic dictionaries crossing a domain, provider, process, or persistence boundary MUST be wrapped in `VersionedEnvelope` or a more specific typed model.

An envelope contains:

- non-empty `kind` identifying the payload schema;
- integer `schema_version >= 1`;
- the payload.

Envelopes are immutable after validation. A reader that does not recognize the `(kind, schema_version)` pair MUST refuse interpretation. Incompatible shape changes increment the schema version.

This contract applies to prepared provider inputs, provider metadata snapshots, and settlement/fulfillment result payloads once those values cross a durable or cross-domain boundary. Internal transient dictionaries that never cross such a boundary do not require an envelope.

#### Scenario: Unknown envelope version

- **WHEN** a reader receives a recognized kind with an unsupported schema version
- **THEN** it rejects the payload rather than attempting best-effort decoding

#### Scenario: Typed payload is invalid

- **WHEN** a generic envelope is parameterized with a typed payload model and required payload fields are missing
- **THEN** validation fails before dispatch or persistence

### Requirement: Stable error taxonomy

Generic orchestration MUST distinguish stable categories including:

- provider missing or unavailable;
- provider configuration invalid;
- request invalid;
- equivalent/conflicting fulfillment;
- create, status, or teardown failure;
- credential fetch failure;
- no eligible settlement resource;
- reservation expired or missing;
- request/assignment mismatch.

Concrete provider errors may carry additional diagnostics but MUST map into these categories at the shared boundary. Errors SHOULD identify retryability or operator action when the lifecycle persists operations. A credential fetch failure on an otherwise-healthy `active` fulfillment is a distinct, retryable category from create/status/teardown failure: it reflects a transient inability to read live access material, not a workload-lifecycle failure, and does not change the aggregate's durable state.

#### Scenario: Concrete provider reports an execution failure

- **WHEN** a provider-specific create, status, or teardown operation fails
- **THEN** the shared boundary maps it to a stable generic category while retaining safe diagnostics

### Requirement: Packaging and typing

The distribution MUST include `market_fulfillment/py.typed`. Consumers install it from the repository `.dist` wheel during local development and builds. Touched projects MUST NOT add editable relative sibling sources for internal kit dependencies.

The aggregate kit build/test flow MUST build prerequisite site and resource-pool wheels, build fulfillment, and run every kit subproject's default suite.

#### Scenario: Fulfillment wheel is inspected

- **WHEN** the wheel is built
- **THEN** it contains the public modules and `market_fulfillment/py.typed`

## Evidence

- Identifier generation and ordering: `kit/fulfillment/tests/unit/test_ids.py`.
- Request and multidimensional validation: `kit/fulfillment/tests/unit/test_settlement_types.py`.
- Deterministic scheduler behavior: `kit/fulfillment/tests/unit/test_scheduler.py`.
- Envelope constraints and round trips: `kit/fulfillment/tests/unit/test_envelopes.py`.
- Dependency boundaries: `kit/fulfillment/tests/unit/test_import_boundaries.py` and repository-level architecture tests as introduced.
- Provider contracts and registry behavior: `kit/fulfillment/tests/unit/test_provider.py` and compute provisioning service tests.
- Shared feasibility predicate: `kit/site/tests/unit/test_resource_satisfies_requirement.py`; scheduling-time exceeds-reservation rejection: `kit/fulfillment/tests/unit/test_scheduler.py`.
- Durable aggregate schema and constraints: `kit/fulfillment/tests/unit/test_settlement_db.py`.
- State transition validation: `kit/fulfillment/tests/unit/test_transitions.py`.
- Repository equivalence scopes, conflict rejection, provisioned resources, and recovery claims: `kit/fulfillment/tests/unit/test_settlement_repository.py`.
- Session-scoped ledger entry points consumed by cross-package transactions: `kit/site/tests/unit/test_settlement_assignment.py`.
- Durable, atomic `schedule_resource` (equivalent/conflicting retry, explicit-resource cursor bypass, full-transaction rollback) and resource_kind-scoped cursor durability/isolation: `kit/fulfillment/tests/unit/test_scheduler.py`. `POST /fulfillment/schedule`'s HTTP contract (assignment, idempotent retry, unknown-reservation rejection, and schedule-then-begin using the assigned resource): `provisioning/compute/service/tests/integration/test_fulfillment_api.py::TestScheduleEndpoint`.
- Status/result read paths (no-provider-call status reads, active-only provisioned-resource and credential projection, empty outputs/credentials across all non-active states, unknown-identifier rejection, live credential-fetch failure isolation): `kit/fulfillment/tests/unit/test_fulfillment.py`. `fulfillment.result.v1` envelope shape and round-trip: `kit/fulfillment/tests/unit/test_results.py`. End-to-end HTTP coverage against a real SQLite-backed repository and a real `AnsibleFulfillmentProvider.fetch_credentials` read: `provisioning/compute/service/tests/integration/test_fulfillment_api.py::TestStatusAndResultQueries`.

### Requirement: Fulfillment validation

The fulfillment validation endpoint accepts the same reservation, market, and fulfillment-request signature as acceptance. It uses the same internal preparation path to load the already-scheduled aggregate, selected resource, current pool configuration, and provider, but runs in a read-only session without reserving SQLite's writer slot and performs no lifecycle transition, prepared-operation write, provider dispatch, or other durable mutation. The result is provider-neutral and non-binding because pool configuration may change before acceptance.

#### Scenario: Validation succeeds without acceptance

- **WHEN** a valid fulfillment request is submitted to the validation endpoint
- **THEN** preparation validation succeeds and the aggregate remains in its prior state with no prepared operation persisted

### Requirement: Fulfillment status and result queries

`get_fulfillment_status(fulfillment_id)` and `get_fulfillment_result(fulfillment_id)` are storefront-callable pull reads over the durable aggregate (see "Durable settlement persistence" above), addressed by `fulfillment_id` rather than `capacity_reservation_id`. Neither performs a lifecycle transition, prepared-operation write, or other durable mutation; both use a read-only session that does not reserve SQLite's writer slot. There is no separate outbox or delivery-acknowledgement state for either read: a call reflects current durable state on demand, and the caller decides when to call again.

`get_fulfillment_status` returns the aggregate's identity, current state, and failure reason/message only. It never calls a `FulfillmentProvider` method.

`get_fulfillment_result` returns a `fulfillment.result.v1` versioned envelope (see "Versioned envelopes") carrying `fulfillment_id`, `capacity_reservation_id`, `state`, failure reason/message, provisioned-resource outputs, and an optional versioned `domain_result` envelope. Provisioned-resource outputs and the domain result are populated only when the aggregate's state is `active`; every other lifecycle state returns empty outputs and no domain result rather than an error, since a fulfillment that has not yet produced a resource, or has already torn one down, has nothing a provider call could meaningfully return. When `active`, `get_fulfillment_result` calls `FulfillmentProvider.fetch_credentials(provider_metadata, provisioned_resources)` directly and unconditionally, after the read transaction that loaded the aggregate has already closed — a live credential fetch is provider I/O and must not run with a database transaction open, matching the fulfillment convergence worker's own "no DB transaction open during provider I/O" principle. This is a stateless read: no claim, lease, or generation counter guards it, because nothing durable is being coordinated or mutated and this codebase has no credential-rotation source to track. A fetch failure raises a distinct `credential_fetch_failed` error category (see "Stable error taxonomy") rather than the generic provider-unavailable or status-failure categories, so a caller can distinguish "retry the read" from an actual workload failure; the aggregate's own durable state is unaffected by a fetch failure.

A query for an unknown `fulfillment_id` is rejected as a not-found error by both reads. This is an existence check against this provisioning service's own database, not a per-caller ownership check — the service currently trusts exactly one caller by construction (see "Provider contract" and `docs/development/ARCHITECTURE.md` for the deployment's single-storefront trust model), so there is no second caller identity to compare against yet.

**Active-result consistency and failure semantics.** Every `active`-state result read performs a fresh `fetch_credentials` call — there is no caching layer between reads, so two calls in a row against an unchanged aggregate each independently hit the provider. The aggregate-derived fields (`state`, failure reason/message, provisioned-resource outputs) are stable across repeated reads for as long as the aggregate itself does not change, since they come straight from the durable row each time; the `domain_result` content is not guaranteed stable across reads in the same way, since it reflects whatever the provider's live fetch returns at that moment — a provider legitimately returning different content on two calls (a rotated secret, a changed role set) is not itself an error condition for the read path to detect or reject. A result read never opens a write transaction and never mutates the aggregate, regardless of outcome. Any credential-fetch failure — whether the provider's own `CredentialFetchFailedError` or an unexpected exception the shared orchestration wrapper catches and re-categorizes (see "Provider contract") — rejects the whole result; there is no partial result containing some fields and omitting others, because the failure is raised before any payload is constructed.

#### Scenario: Repeated active-state reads each perform a fresh credential fetch

- **WHEN** `get_fulfillment_result` is called twice in a row against an unchanged `active` aggregate
- **THEN** `FulfillmentProvider.fetch_credentials` is called once per read, not cached from the first call

#### Scenario: Durable fields are stable across reads; domain result content is not required to be

- **WHEN** two `get_fulfillment_result` reads happen against an unchanged `active` aggregate but the provider returns different domain-result content on the second call
- **THEN** `state`, failure detail, and provisioned-resource outputs are identical across both reads, and the differing domain-result content is not treated as an error

#### Scenario: A result read never mutates the aggregate

- **WHEN** `get_fulfillment_result` is called any number of times, in any state, successfully or not
- **THEN** no write transaction is opened and the aggregate's durable state is unchanged by the read itself

#### Scenario: Status query never calls a provider

- **WHEN** `get_fulfillment_status` is called for an existing `fulfillment_id`
- **THEN** the durable aggregate's state and failure detail are returned and no `FulfillmentProvider` method is invoked

#### Scenario: Result query on a non-active aggregate omits outputs and credentials

- **WHEN** `get_fulfillment_result` is called for a `fulfillment_id` whose aggregate is not in the `active` state
- **THEN** the returned envelope's provisioned-resource outputs and credentials are both empty and no `FulfillmentProvider` method is invoked

#### Scenario: Result query on an active aggregate includes provisioned-resource outputs and live credentials

- **WHEN** `get_fulfillment_result` is called for a `fulfillment_id` whose aggregate is `active`
- **THEN** the returned envelope's provisioned-resource outputs reflect that aggregate's `ProvisionedResource` rows, and its domain result reflects a live `fetch_credentials` call against the aggregate's provider metadata

#### Scenario: Live credential fetch fails on an otherwise-healthy fulfillment

- **WHEN** `FulfillmentProvider.fetch_credentials` raises during a `get_fulfillment_result` call for an `active` fulfillment
- **THEN** the read is rejected with the `credential_fetch_failed` error category and the aggregate's durable state is unchanged

#### Scenario: Query for an unknown fulfillment identifier

- **WHEN** either read is called with a `fulfillment_id` not present in this provisioning service's database
- **THEN** it is rejected as a not-found error

### Requirement: Existing lease continuity during fulfillment cutover

A database cutover that converts legacy VM leases into fulfillment aggregates SHALL enumerate nonterminal legacy leases as the authoritative candidate set and SHALL preserve every known in-flight provider operation.

- A legacy `provisioning` lease with a known create job becomes `dispatching` and continues observing that job.
- An active lease becomes `active` with its provisioned VM recorded as a `ProvisionedResource`.
- A releasing lease becomes `tearing_down` when a teardown job is already known, otherwise `teardown_dispatch_pending`.
- A failed release becomes `teardown_failed`.
- Terminal or expired legacy leases do not create fulfillment aggregates.

The cutover SHALL NOT submit a replacement create operation merely because an existing provider job cannot be identified. A known failed job may subsequently follow the provider's normal retry behavior. Equivalent target rows make the cutover idempotent; conflicting rows cause the cutover to fail without overwriting them. Equivalence SHALL compare every field a provider operation depends on for correctness — resource attributes, provider metadata (including the tracked create job), teardown provider metadata (including the active teardown job), the prepared teardown envelope, and the corresponding `ProvisionedResource` population — not only placement fields such as state, resource, pool, and provider; a row that matches on placement alone but differs in tracked job identity or provisioned-resource population is a conflict. A candidate with a live target (active or tearing down) but no known create job identity is rejected rather than backfilled without one, since a teardown operation must be able to record which create job produced the resource it tears down.

#### Scenario: Legacy lease population is backfilled atomically

- **WHEN** the cutover enumerates a population of nonterminal legacy leases and one candidate fails validation
- **THEN** no candidate's settlement or provisioned-resource rows are committed, and a rerun against the same unmodified population is idempotent

## Evidence

- Legacy lease state derivation, provider-envelope preparation, and per-candidate validation: `provisioning/compute/service/tests/unit/services/test_legacy_vm_fulfillment_backfill.py`.
- Cross-candidate enumeration, conflict rejection, idempotent rerun, and whole-migration atomicity: `provisioning/compute/service/tests/unit/test_legacy_vm_lease_migration.py`.
- Convergence observing and progressing backfilled rows: `provisioning/compute/service/tests/unit/services/test_fulfillment_convergence_after_legacy_backfill.py`.
