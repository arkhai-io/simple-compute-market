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
- the periodic multi-replica recovery sweep that consumes recovery claims (see "Durable settlement persistence").

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

`PhysicalSettlementScheduler` owns placement. It enumerates eligible candidates through the site and pool authorities, delegates ordering/selection to a `SettlementSchedulingPolicy`, and returns a `SettlementResource`.

The current policy is deterministic two-level round-robin. It sorts eligible pool IDs and chooses the pool after the last automatic selection, then sorts eligible resource IDs in that pool and chooses the resource after that pool's last automatic selection. If a previous cursor no longer names an eligible candidate, selection resumes at the first sorted eligible value. For an unchanged candidate set and policy state, selection is reproducible. Policy remains replaceable; static pool priority is not part of the resource-pool schema.

An explicit resource constraint bypasses policy choice but not reservation, pool, resource, shape, attribute, or capacity eligibility, and it does not advance automatic-selection cursors.

Scheduling and fulfillment execution are separate calls. A provider receives the already-selected `SettlementResource` and MUST NOT substitute another resource. If a selected resource becomes unusable, execution reports a typed failure and orchestration returns to the scheduler boundary according to lifecycle policy.

The same `capacity_reservation_id` and equivalent request MUST return the existing assignment when assignment state is available. A conflicting retry MUST fail rather than creating a second binding. Current assignment and cursor storage is process-local: idempotency is guaranteed only within one running scheduler instance, not across restart or replica boundaries, until the compute lifecycle supplies durable assignment persistence.

Scheduling errors distinguish a missing or expired reservation, a request that conflicts with reservation or existing-assignment state, and a valid request for which no candidate is eligible.

#### Scenario: Equivalent scheduling retry

- **WHEN** the same reservation and normalized requirements are scheduled again in the scheduler instance that holds the assignment
- **THEN** the existing settlement-resource assignment is returned without advancing policy cursors

#### Scenario: Previous cursor is no longer eligible

- **WHEN** the previously selected pool or resource is absent from the eligible candidate set
- **THEN** round-robin resumes deterministically from the first sorted eligible pool or resource

#### Scenario: Explicit resource is ineligible

- **WHEN** a request identifies a resource in a disabled pool or without sufficient capacity
- **THEN** scheduling rejects it without invoking automatic policy or advancing cursors

#### Scenario: Scheduler process restarts

- **WHEN** an assignment exists only in process-local state and the scheduler restarts
- **THEN** the process does not claim distributed idempotency and a retry may be evaluated as a new assignment

#### Scenario: Provider attempts independent placement

- **WHEN** a provider cannot use the selected resource
- **THEN** it reports validation or execution failure and does not choose a replacement resource

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

A fulfillment produces zero or more `ProvisionedResource` rows, each with a globally unique `provisioned_resource_id`, denormalized `fulfillment_id`, and an optional domain-specific `domain_resource_ref`. Per-resource teardown is not exposed unless a caller requires it; teardown addresses the whole fulfillment.

There is no persisted `SettlementResult` model. A caller-facing fulfillment result is a read-time projection over the aggregate's state/failure fields and its `ProvisionedResource` children, not a value stored independently — there is no case needing it durable on its own absent a `SettlementResult` CRUD API, and persisting one would create a second place credential-adjacent data could live when credentials are already fetched live and never persisted.

Prepared provider create/teardown input is captured as a `VersionedEnvelope`-typed payload on the aggregate, frozen before the transaction that marks the corresponding dispatch-pending state commits, so a recovery retry dispatches from what was accepted rather than a live re-read of pool or provider configuration.

Repository callers provide validated canonical `SettlementRequirement` and `VersionedEnvelope` models. Persistence serializes their JSON-compatible model form and uses structural equality; it does not accept arbitrary dictionaries as an equivalence boundary or infer equivalence among unvalidated representations.

The generic lifecycle transition operation may update only prepared create/teardown operation payloads, provider and teardown metadata, and failure reason/message fields. Aggregate identity, scheduled-resource identity, market, scheduling requirements, fulfillment identity/request, lifecycle state, recovery leases, timestamps, and unknown fields are not writable through lifecycle updates. Unsupported updates are rejected before state or in-memory row mutation.

The compute provisioning service uses SQLite. Fulfillment acceptance reserves SQLite's single writer slot with an immediate write transaction before reading and updating the aggregate, so concurrent acceptance attempts serialize and observe one durable `fulfillment_id`. This is a database-wide SQLite writer guarantee, not PostgreSQL-style row locking. Aggregate creation remains protected by the `capacity_reservation_id` primary key; an observed uniqueness race is resolved by re-reading the winning row and applying the ordinary equivalence rule.

Recovery-lease fields (a claim owner, a claim expiry, and an attempt count) live directly on the aggregate row rather than in a separate claims table: one aggregate has at most one pending provider operation at a time, so a separate table would only add a join with no independent-claiming benefit. The repository exposes only a single-worker SQLite selection primitive at this layer. The provisioning-owned recovery workflow defines duplicate-dispatch prevention and any concurrent acquisition semantics.

#### Scenario: Expired claim is reclaimed

- **WHEN** a claimed row's claim has expired and no other claim has replaced it
- **THEN** a subsequent claim attempt may claim it again

### Requirement: Provider contract

A `FulfillmentProvider` implements asynchronous:

- `create(request, resource) -> FulfillmentResult`;
- `get_status(capacity_reservation_id, resource, provider_metadata) -> ProviderStatus`;
- `teardown(capacity_reservation_id, resource, provider_metadata) -> FulfillmentResult`.

`create` and `teardown` MUST be idempotent for equivalent retries. Provider metadata is opaque to generic orchestration and contains only normalized, serializable operational state needed for later status or teardown. Credentials and sensitive access material should be referenced or delivered through a dedicated secure channel rather than assumed to be generic metadata.

A provider may expose side-effect-free `validate_create` or preparation behavior. Validation errors MUST be represented as structured issues when used by dry-run surfaces and mapped to typed failures for execution.

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
- no eligible settlement resource;
- reservation expired or missing;
- request/assignment mismatch.

Concrete provider errors may carry additional diagnostics but MUST map into these categories at the shared boundary. Errors SHOULD identify retryability or operator action when the lifecycle persists operations.

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
- Repository equivalence scopes, conflict rejection, provisioned resources, and recovery claims: `kit/fulfillment/tests/unit/test_repository.py`.
- Session-scoped ledger entry points consumed by cross-package transactions: `kit/site/tests/unit/test_settlement_assignment.py`.
