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
- versioned envelopes for provider/domain dictionaries that cross persistence or package boundaries.

It does not own:

- commercial agreement identity or storefront deal state;
- authoritative capacity admission and reservation storage;
- resource-pool CRUD or provider configuration persistence;
- VM, bare-metal, Kubernetes, storage, or other provider-specific request/result vocabulary;
- durable settlement-record persistence until the owning compute-provisioning lifecycle implements it;
- executor job queues or lease-watchdog policy.

## Ownership

The capability is distributed as `arkhai-kit-fulfillment` and imported as `market_fulfillment`.

Provider-neutral scheduling and provider execution contracts live together in this package. Resource-pool administration must not import fulfillment contracts merely to type its provider configuration, and fulfillment must not depend on a deployed provisioning service. Concrete providers and domain requirement translators live in domain adapters or service composition.

## Dependency boundary

`market_fulfillment` is a higher kit layer than the site and resource-pool authorities. It may depend on `market_site` and `market_resource_pools`. Those lower layers MUST NOT import `market_fulfillment`, including under `TYPE_CHECKING`.

Carrier modules for IDs, envelopes, requests, requirements, resources, and provider protocols MUST remain independent of concrete service implementations. Scheduler modules MAY depend on site and resource-pool service interfaces required to enumerate and bind eligible resources.

#### Scenario: Type-only reverse import is introduced

- **WHEN** `market_site` or `market_resource_pools` imports `market_fulfillment` under `TYPE_CHECKING`
- **THEN** the repository dependency-boundary validation rejects the import as an upward dependency

#### Scenario: A concrete VM adapter implements fulfillment

- **WHEN** the VM provisioning composition registers an Ansible provider
- **THEN** the adapter depends on `market_fulfillment` and VM/Ansible packages while the fulfillment kit remains free of VM vocabulary

## Identities

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

## Physical settlement request

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

## Multidimensional eligibility

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

## Scheduling and assignment

`PhysicalSettlementScheduler` owns placement. It enumerates eligible candidates through the site and pool authorities, delegates ordering/selection to a `SettlementSchedulingPolicy`, and returns a `SettlementResource`.

The current policy is deterministic round-robin. For an unchanged ordered candidate set and policy state, selection is reproducible. Policy remains replaceable; static pool priority is not part of the resource-pool schema.

Scheduling and fulfillment execution are separate calls. A provider receives the already-selected `SettlementResource` and MUST NOT substitute another resource. If a selected resource becomes unusable, execution reports a typed failure and orchestration returns to the scheduler boundary according to lifecycle policy.

The same `capacity_reservation_id` and equivalent request MUST return the existing assignment when durable assignment is available. A conflicting retry MUST fail rather than creating a second binding.

#### Scenario: Equivalent scheduling retry

- **WHEN** the same reservation and normalized requirements are scheduled again
- **THEN** the existing settlement-resource assignment is returned

#### Scenario: Provider attempts independent placement

- **WHEN** a provider cannot use the selected resource
- **THEN** it reports validation or execution failure and does not choose a replacement resource

## Provider contract

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

## Versioned envelopes

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

## Error taxonomy

Generic orchestration distinguishes stable categories including:

- provider missing or unavailable;
- provider configuration invalid;
- request invalid;
- equivalent/conflicting fulfillment;
- create, status, or teardown failure;
- no eligible settlement resource;
- reservation expired or missing;
- request/assignment mismatch.

Concrete provider errors may carry additional diagnostics but MUST map into these categories at the shared boundary. Errors should identify retryability or operator action when the lifecycle begins persisting operations.

## Packaging and typing

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
