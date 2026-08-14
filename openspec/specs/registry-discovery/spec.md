# Registry Discovery Specification

## Purpose

Define listing publication, schema-driven discovery, publisher identity, and filter-spec consistency.

## Requirements

### Requirement: Schema-driven listing validation
A registry MUST validate publish candidates and compile discovery filters from its configured filter-spec rather than hardcoding a concrete market schema into route signatures.

#### Scenario: Publisher submits a listing
- **WHEN** a signed listing candidate is published
- **THEN** the registry validates it against the filter-spec listing shape before storing it

### Requirement: Opaque market payload storage
The registry MUST treat domain offer payloads as opaque data except for declarative filter paths and validation rules supplied by the filter-spec.

#### Scenario: Registry serves a different schema
- **WHEN** an operator replaces the configured filter-spec and restarts the registry
- **THEN** discovery and validation use the replacement schema without domain-specific registry code

### Requirement: Canonical publisher ownership
The registry MUST authorize listing ownership through complete canonical `{scheme, identifier}` principals bound to a stable publisher subject. A first valid publication MAY lazily create the publisher and its initial Ed25519 or EIP-191 binding without a wallet or chain lookup. Authorization MUST compare both scheme and identifier; a listing identifier, bare address, embedded proof, or body claim MUST NOT confer publisher authority.

#### Scenario: Non-owner mutates a listing
- **WHEN** a valid signature is produced by a principal that is not active for the owning publisher
- **THEN** the registry rejects the mutation

#### Scenario: Publisher uses Ed25519
- **WHEN** a valid Ed25519 principal first publishes a schema-valid listing
- **THEN** the registry lazily creates or resolves the stable publisher and binds listing ownership without requiring an EVM wallet

### Requirement: Stable publisher-chosen listing identity
Every publication MUST carry a non-empty publisher-chosen `listing_id` inside the signed canonical body. The registry MUST retain that value unchanged as the listing resource identity; a repeated publication by the same publisher MAY update the existing listing, while another publisher MUST NOT claim it. Publisher credential rotation and supported legacy identity migration MUST preserve publisher and listing identifiers.

#### Scenario: Publisher republishes a known listing
- **WHEN** the owning publisher publishes a changed schema-valid body with an existing `listing_id`
- **THEN** the registry updates the listing under the same listing and publisher identifiers rather than allocating a replacement

#### Scenario: Another publisher reuses a listing identifier
- **WHEN** a different publisher submits an otherwise valid publication carrying an existing `listing_id`
- **THEN** the registry rejects the ownership conflict

### Requirement: Filter-spec consistency
The registry MUST identify a filter-spec version with an ETag and MUST reject a listing query carrying a stale `If-Match` value rather than evaluate it under different filter semantics.

#### Scenario: Cached filter spec is stale
- **WHEN** a client queries listings with an ETag that does not match the active filter-spec
- **THEN** the registry returns HTTP 412



### Requirement: Body-bound version 2 registry authentication

The registry client MUST receive an injected scheme-neutral signer and MUST NOT accept or derive publisher authority from a private-key string or address-only credential. Publication, update, close, publisher-identity rotation, and authenticated discovery MUST use the shared `arkhai.market-request-signature.v2` contract. The proof MUST bind the complete canonical body or empty-body marker together with the caller role, exact principal, method, semantic operation, resource, request ID, and timestamp before validation, dispatch, or persistence. Behavior-affecting query values MUST be included in the signed semantic body.

Every completed authenticated registry response MUST use the shared version 2 response contract to bind the registry authority, status, originating request, timestamp, and canonical response body. A client MUST verify that proof and the exact configured registry authority before accepting the result.

#### Scenario: Listing body changes after signing

- **WHEN** any listing payload field changes after the publisher creates its proof
- **THEN** the registry rejects the publication before validation or persistence

#### Scenario: Response comes from an unexpected authority

- **WHEN** a cryptographically valid response is signed by a principal outside the client's configured registry trust set
- **THEN** the client rejects the response

### Requirement: Durable replay reservation

The registry MUST durably reserve `(principal, request_id)` before dispatch. Reuse with different canonical request content MUST be rejected, an exact retry of a completed request MUST return the recorded status and body under a fresh signed response without repeating the operation, and a concurrent retry while the first attempt holds its lease MUST NOT dispatch a second operation. An expired unfinished lease MAY be reclaimed by one attempt.

#### Scenario: Completed publication is retried

- **WHEN** a publisher repeats the exact authenticated publication after losing its acknowledgement
- **THEN** the registry returns the recorded outcome without creating or mutating the listing again

#### Scenario: Request ID is reused with a changed body

- **WHEN** the same principal reuses a request ID for different canonical request content
- **THEN** the registry rejects the request as changed reuse before dispatch

### Requirement: Publisher principal rotation

The registry MUST rotate a stable publisher only from a canonical intent that names the current and replacement principals, `publisher:<publisher_id>` subject, registry authority, nonce, bounded overlap, and expiry and is proven by both principals. The authenticated caller MUST be the active current primary. Applying the same nonce and intent MUST be idempotent; reusing the nonce for another intent, binding an already-owned replacement, or starting a second active overlap MUST fail. The replacement becomes primary, the current principal remains active only for the requested bounded overlap, and only the active replacement primary MAY retire it early. Rotation MUST preserve the publisher and all owned listing identifiers and history.

#### Scenario: Replacement principal lacks its proof

- **WHEN** the current publisher submits a replacement identifier without a valid replacement proof
- **THEN** the registry does not bind or promote the replacement

#### Scenario: Rotation is retried

- **WHEN** the same valid rotation intent is submitted again with its publisher nonce
- **THEN** the registry returns the recorded rotation state without creating another binding

### Requirement: Publisher identity migration preserves ownership

A registry database upgrade from a supported legacy address-owned population MUST validate and atomically convert every owner to a canonical `eip191` principal before the version 2 identity schema is served. It MUST preserve publisher IDs, publisher-to-listing ownership relations, and listing IDs, and retire the legacy ownership columns in the same schema boundary. Malformed or ambiguous identities, duplicate canonical or active bindings, partial prior conversion, conflicting ownership metadata, or referential gaps MUST abort and roll back the complete migration.

#### Scenario: Existing publisher is migrated

- **WHEN** a valid address-owned listing population is upgraded
- **THEN** each address becomes an `eip191` principal and the same publisher retains authority over the same stable listing identifiers

#### Scenario: Legacy ownership is inconsistent

- **WHEN** any legacy listing lacks its publisher or two legacy identities canonicalize to a conflicting active binding
- **THEN** no publisher or listing ownership row is partially migrated

### Requirement: Resource query compilation preserves filter-spec authority

A buyer resource-query compiler MUST resolve every field, operator, type, alias, and missing-value rule from the active registry filter specification and MUST compile only declared filters into the registry's canonical query input. The compiled request MUST carry the matching filter-spec ETag and all behavior-affecting values in the authenticated semantic body. The compiler MUST NOT add domain fields, reinterpret missing values, or weaken strict filtering.

#### Scenario: Filter specification changes during query construction

- **WHEN** the buyer compiles a resource query under one filter-spec ETag and the registry activates another before execution
- **THEN** the registry rejects the request with HTTP 412 rather than evaluating it under changed semantics

#### Scenario: DSL operator is not declared for a field

- **WHEN** the user applies a range operator to a field whose filter declaration accepts only set membership
- **THEN** the buyer rejects compilation before sending the listing query

### Requirement: Pushdown remains semantic rather than physical

Resource-query explanation MUST identify which canonical predicates are evaluated by the registry and which settlement constraints remain buyer-local. Declaring or compiling a predicate MUST NOT activate database indexing, change the registry HTTP route, or promise a physical execution plan. Any future indexed execution MUST remain semantically equivalent under the separate measured activation contract.

#### Scenario: Query uses an unindexed filter

- **WHEN** a valid DSL comparison compiles to a declared filter whose `indexed` marker is absent or behaviorally inert
- **THEN** the registry evaluates it with current filter semantics and explanation makes no indexing claim

## Evidence

- Schema loading, validation, and ETag behavior: `core/registry/tests/unit/test_filter_spec.py`, `core/registry/tests/integration/test_filter_spec.py`, and `core/registry/tests/integration/test_validate_publish.py`.
- Declarative filtering and stale `If-Match`: `core/registry/tests/unit/test_filter_eval.py` and `core/registry/tests/integration/test_listings_filtering.py`.
- Injected dual-scheme publisher identity, stable listing ownership, body-bound requests, signed responses, and replay behavior: `core/registry/tests/integration/test_identity_publish.py`, `core/registry/tests/integration/test_listings.py`, `core/registry/tests/unit/test_publisher_auth.py`, and `core/registry-client/tests/test_auth.py`.
- Publisher rotation and stable-subject ownership: `core/registry/tests/integration/test_publisher_rotation.py`.
- Atomic canonical-principal migration and rollback: `core/registry/tests/unit/test_principal_migrations.py`.
