# Resource Pool Management Specification

## Purpose

Define operator-managed provisioning resource pools, provider configuration boundaries, host membership, lifecycle invariants, and canonical administrative reconciliation before later settlement-selection integration.

## Requirements

### Requirement: Persistent provider-neutral pool identity

The provisioning service MUST persist each resource pool under a stable operator-chosen ID with a label, provider kind, enabled state, policy tags, and provider-owned configuration; shared pool wire models MUST represent provider configuration generically rather than adding provider-specific fields.

#### Scenario: An Ansible pool is created

- **WHEN** an operator creates a pool with a unique ID and valid Ansible provider configuration
- **THEN** the service persists the provider-neutral pool row and its Ansible configuration atomically and returns the complete normalized pool

#### Scenario: An unknown provider is requested

- **WHEN** a create, replace, patch, or import request names a provider with no registered pool configuration handler
- **THEN** the service rejects the request before persisting any change

### Requirement: Explicit valid host membership

Every provisioning host MUST reference an existing resource pool; existing hosts and create requests that omit a pool ID MUST resolve to the system-owned `default` pool.

#### Scenario: Existing schema is migrated

- **WHEN** the resource-pool migration runs against a database containing hosts
- **THEN** it creates the default pool before adding the non-null foreign key and assigns every existing host to `default`

#### Scenario: Host names an unknown pool

- **WHEN** an operator creates or updates a host with a pool ID that does not exist
- **THEN** the service rejects the host mutation without changing the stored host

### Requirement: Non-destructive pool lifecycle

Pool removal MUST disable the pool rather than delete it, and the system-owned `default` pool MUST remain present and enabled.

#### Scenario: Operator deletes a non-default pool

- **WHEN** an operator sends DELETE for an existing non-default pool
- **THEN** the service sets `enabled=false` and the pool remains retrievable by ID

#### Scenario: Operator attempts to disable the default pool

- **WHEN** create, replace, patch, delete, or authoritative import would leave `default` disabled
- **THEN** the service rejects the operation and leaves `default` enabled

### Requirement: Complete and partial administrative updates

The pool API MUST implement POST create, GET list/detail/export, PUT full replacement, PATCH partial update, DELETE disable, POST authoritative import, and POST validation-only behavior with typed request and response models.

#### Scenario: PUT omits optional mutable fields

- **WHEN** an operator replaces a pool with a valid full `PoolReplace` document that omits optional policy tags
- **THEN** the stored tags are reset to the model's replacement default rather than retaining prior state

#### Scenario: PATCH changes one field

- **WHEN** an operator patches only a pool label
- **THEN** the label changes and all omitted mutable fields remain unchanged

### Requirement: Strict lossless YAML validation

Pool YAML validation MUST reject malformed structure, unknown fields, duplicate IDs, missing or disabled default pool definitions, unknown providers, and invalid provider configuration; it MUST accumulate all independently detectable structured problems and MUST NOT write data.

#### Scenario: Document contains several independent errors

- **WHEN** validation receives unknown fields, a duplicate ID, an invalid field type, and an unsupported provider in one document
- **THEN** the response is invalid, contains stable path/code/message entries for each detectable problem, has no reconciliation diff, and leaves persistence unchanged

#### Scenario: Valid document is dry-run

- **WHEN** validation receives a valid canonical document
- **THEN** it returns the proposed created, updated, disabled, and unchanged IDs without writing any pool or provider configuration

### Requirement: Atomic authoritative reconciliation

Pool YAML import MUST treat the supplied definitions as authoritative, validate the complete document before mutation, apply valid changes atomically, disable enabled pools omitted from the document, never hard-delete omitted pools, and return a deterministic reconciliation diff.

#### Scenario: One imported entry is invalid

- **WHEN** a document contains valid changes and one invalid pool definition
- **THEN** the complete import is rejected and none of the valid changes are persisted

#### Scenario: Valid document is re-imported

- **WHEN** an operator imports the same valid document twice
- **THEN** the second response reports the declared pools unchanged and performs no semantic data change

#### Scenario: Canonical export is round-tripped

- **WHEN** an operator exports the current pool state and validates or imports that YAML without editing it
- **THEN** the document remains valid and represents the same complete pool and provider configuration state

## Evidence

- Pool persistence, provider validation, strict import, dry-run, idempotency, lifecycle, and provider replacement: `domains/vms/provisioning/service/src/tests/unit/services/test_resource_pool_service.py`.
- Typed administrative API, default-pool invariant, canonical round trip, and host assignment: `domains/vms/provisioning/service/src/tests/integration/test_pools_api.py`.
- Migration ordering, legacy host backfill, and schema-drift rejection: `domains/vms/provisioning/service/src/tests/unit/test_database.py`.

## Scheduling membership and draining

Every resource eligible for physical settlement belongs to exactly one Resource Pool. Zero memberships makes the resource unschedulable; multiple memberships misrepresent system capacity and are invalid configuration.

Disabling a Resource Pool is a draining action. It blocks new Capacity Settlement Assignments to that pool but does not invalidate existing reservations, assignments, physical settlements, or active workloads, and those existing records do not prevent disablement.

## Relationship to fulfillment scheduling

Resource-pool management owns administrative routing metadata: pool identity, enabled state, policy tags, provider kind, provider-specific configuration, and host/resource membership. It does not own fulfillment-provider protocols or settlement-resource assignment.

The higher-layer [fulfillment capability](../fulfillment/spec.md) reads enabled pool and resource information when evaluating candidates. Disabling a pool prevents new scheduling assignments while preserving existing reservations, assignments, fulfillment records, and active workloads. `market_resource_pools` must not import `market_fulfillment`, including for type-only annotations.


### Requirement: Session-scoped pool reads

Resource-pool management exposes a session-scoped pool lookup that loads provider configuration using the caller's open database session. Fulfillment uses this operation while freezing prepared provider input so the pool snapshot and aggregate write share one transaction.

#### Scenario: Pool configuration is frozen with acceptance

- **WHEN** fulfillment prepares provider input inside its acceptance transaction
- **THEN** the pool and provider configuration are read through the same caller-owned session before the prepared operation is persisted
