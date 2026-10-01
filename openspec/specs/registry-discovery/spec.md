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

### Requirement: Buyer discovery preserves registry authority identity

Production buyer fan-in MUST deduplicate records by `(registry authority,
listing_id)` and retain the first record's source URL and authority. Equal
listing IDs from independent registry authorities MUST remain separate records;
a publisher-chosen ID alone does not establish cross-authority equivalence.

#### Scenario: Multiple endpoints represent one authority

- **WHEN** two configured endpoints of the same registry authority return the same listing ID
- **THEN** buyer discovery retains one record with the first endpoint's provenance

#### Scenario: Independent authorities return the same listing ID

- **WHEN** two independent registry authorities return the same listing ID
- **THEN** buyer discovery retains both authority-scoped records and their respective provenance

#### Scenario: An endpoint is unavailable during ordinary discovery

- **WHEN** discovery without a resource query or explain request encounters an unreachable configured endpoint
- **THEN** it reports the read failure and retains results from reachable registries

#### Scenario: Query preparation cannot complete

- **WHEN** a resource query or explain request cannot prepare an authenticated query for every configured registry
- **THEN** discovery fails rather than silently selecting a subset of registries

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

### Requirement: Registry self-description is authority-authenticated

A registry MUST publish one strict descriptor containing its public base URL,
display name, operator identity, stable authority name and active principal set,
listing schema identity and version, and access posture. It MUST return the
descriptor at `/.well-known/arkhai/registry-descriptor.json` through the shared
version 2 authenticated request and signed-response contract.

The authority principal MUST come from the active registry signer, the schema
identity MUST come from the active filter specification, and the access posture
MUST come from the active read gate. Operator-authored public fields MUST remain
ordinary configuration. Signer credentials and read keys MUST NOT enter the
descriptor. A bootstrap client MUST verify the signed response against the
principal set carried in the validated descriptor before returning it.

#### Scenario: Client inspects a public registry

- **WHEN** an authenticated buyer, seller, or service requests the well-known descriptor
- **THEN** the registry returns the complete descriptor under a response proof from the principal named in that descriptor

#### Scenario: Registry reads require a key

- **WHEN** the registry requires a read key
- **THEN** the descriptor remains readable without that key and declares `key-gated` posture with an acquisition pointer

#### Scenario: Descriptor configuration contradicts access policy

- **WHEN** a key-gated registry has no acquisition pointer or a public registry configures one
- **THEN** startup fails before the registry serves a contradictory descriptor

#### Scenario: Descriptor is used as a trust bootstrap

- **WHEN** a client verifies the signed response against the principal carried in the descriptor
- **THEN** the proof establishes credential possession but does not by itself establish third-party endorsement of the operator or URL

### Requirement: The compute schema names its family, not one domain

The compute-family filter specification MUST declare a schema identity naming the
family rather than a single domain within it, since the schema carries bare-metal,
virtual-machine, and container listings alike. Buyer commands declare compatibility
with a schema identity, so changing it is backwards-incompatible and MUST bump the
specification version and the schema version together.

#### Scenario: A buyer declares schema compatibility

- **WHEN** a buyer command declares the compute-family schema identity it understands
- **THEN** it queries only registries declaring that identity
- **AND** a registry serving the retired identity is not queried

### Requirement: The published listing shape is named for the seller's listing

A registry's published listing shape MUST be named `listing_resource`, and the
offering-mode field within it MUST be named `offering_mode`. A registry MUST NOT
accept a second spelling of either, and `offer` MUST NOT name a published shape —
including as a client-side attribute or request field holding that shape, since a
second spelling in a client is the same collision as a second spelling on the wire.
A registry's own responses MUST NOT report a derived tag named for the retired shape
key.

Renaming a required field of the listing shape and its filter is
backwards-incompatible and MUST bump the specification version.

#### Scenario: A listing is published under the retired shape key

- **WHEN** a publisher submits a listing carrying its shape under `offer_resource` or `offer`
- **THEN** the submission is rejected rather than accepted under a second spelling

#### Scenario: A validation response reports the shape it checked

- **WHEN** a publisher dry-runs a listing against the registry's listing shape
- **THEN** the response reports validity and the listing identity without a resource-type tag naming the retired shape key

#### Scenario: A buyer filters on the offering mode

- **WHEN** a buyer filters listings by offering mode
- **THEN** the filter reads `listing_resource.offering_mode`
- **AND** a listing publishing no offering mode is excluded rather than matching

### Requirement: Compute listings publish their capacity backing

A compute listing MUST publish whether an admission authority stands behind it.
The value is part of the compute listing shape rather than an optional annotation,
because a buyer cannot otherwise tell a listing they can reserve capacity against
from one where reservation is a no-op and any number of buyers may settle against
the same supply.

This value describes what the marketplace will do with the listing, not how far a
buyer should trust it. Every field a listing publishes is a seller assertion, and
no requirement in this capability verifies any of them for either kind of
listing.

A registry filter on backing MUST match exactly and MUST exclude a listing that
does not publish the field. A permissive match would return listings a buyer
specifically excluded: a listing predating the field would satisfy a query for
unbacked supply while being backed.

Listings published before this field existed MUST be republished carrying an
explicit capacity-backed value. They are semantically known to be backed and MUST
NOT depend on an absent field to be classified.

Every compute-family domain publishing into the compute listing shape MUST publish
the value, including a domain whose listings are always capacity-backed. The value
belongs to the compute listing shape; a registry profile with a different schema
identity is not required to carry it.

#### Scenario: A buyer queries for unbacked supply

- **WHEN** a buyer filters for listings with no admission authority behind them
- **THEN** only listings publishing that value are returned

#### Scenario: A listing does not publish backing

- **WHEN** a listing publishes no backing value and a buyer filters on backing
- **THEN** that listing is excluded from the result rather than matching either value

#### Scenario: A listing published before the field existed

- **WHEN** a listing published before backing was part of the compute listing shape is republished
- **THEN** it carries an explicit capacity-backed value under its existing listing identity

#### Scenario: Backed and unbacked listings share one catalogue

- **WHEN** a buyer queries without filtering on backing
- **THEN** both capacity-backed and unbacked listings are returned together, each carrying its published backing value

#### Scenario: A bare-metal listing is published

- **WHEN** a bare-metal storefront publishes a listing into the compute listing shape
- **THEN** the listing carries an explicit capacity-backed value and is returned by an exact filter for backed supply

### Requirement: The filter grammar can compare exact decimal values

The filter specification MUST support a declared value type whose wire and stored
representation is a decimal-text string and whose comparison domain is finite
exact decimal. Range bounds declared under it MUST be parsed as exact decimals,
resolved listing values MUST be accepted when they are decimal text, and comparison
MUST NOT pass through a binary floating-point representation at any point.

Only finite values are decimal values of this type. A query bound that parses as a
non-number or an infinity MUST be refused as an invalid parameter, never evaluated.
A listing value that does MUST be treated as no value, so `on_missing` decides it:
because the registry validates the full listing shape only in its dry run, a
malformed stored listing must not be able to fail a query.

The type is domain-neutral: it names no market, field, or unit, and any
specification may declare it for any decimal quantity.

The existing JSON-number value type MUST be left unchanged. Retyping its
comparison domain would alter the meaning of filters that other deployments'
specifications already declare, so exact decimal comparison MUST be a distinct
declared type that a specification opts into.

A registry MUST refuse to load a filter specification declaring a value type it
does not implement, rather than ignoring the declaration. A specification whose
comparison semantics the engine cannot honour MUST NOT be served, because a
silently-ignored type would evaluate every query under semantics the operator did
not declare.

A buyer resource-query compiler MUST render a bound of this type without loss and
MUST resolve its type from the specification like any other.

#### Scenario: A bound compares against a high-precision listing value

- **WHEN** a buyer bounds a query against a decimal-text field and a listing's
  value carries more significant digits than a binary double represents exactly
- **THEN** the comparison is exact and the listing matches or is excluded on its
  true value

#### Scenario: A decimal-text value is compared at the bound

- **WHEN** a listing's decimal-text value equals an inclusive bound exactly
- **THEN** it matches, and it does not match an exclusive bound of the same value

#### Scenario: A query bound is not finite

- **WHEN** a request bounds a decimal-text filter by a non-number or an infinity
- **THEN** the registry refuses the parameter rather than evaluating the query

#### Scenario: A stored listing value is not finite

- **WHEN** a listing's decimal-text value is a non-number or an infinity and a query
  bounds that field
- **THEN** the listing is treated as publishing no value, and the query completes

#### Scenario: A registry is given a specification it cannot honour

- **WHEN** a registry configured with an engine that does not implement a declared
  value type loads that filter specification
- **THEN** it refuses the specification rather than serving queries under
  substituted semantics

#### Scenario: The existing number type is unaffected

- **WHEN** a filter declared under the JSON-number value type is evaluated
- **THEN** its behaviour is unchanged by the presence of the decimal type

### Requirement: A filter may declare co-required filters

A filter declaration MAY name other declared filters that MUST be supplied
alongside it. A query supplying a filter without every filter it co-requires MUST
be refused rather than evaluated, because a constraint missing a dimension it
depends on has no interpretation.

The dependency MUST be one-directional: a co-required filter supplied on its own
remains a valid constraint in its own right.

Both the registry and the buyer resource-query compiler MUST resolve
co-requirements from the active filter specification. Neither may encode a
specific field's dependency in code, consistent with the requirement that every
field, operator, type, alias, and missing-value rule is resolved from the
specification and that no domain field is added. The registry's refusal is
authoritative: a buyer that does not understand co-requirements is still refused.

Specification validation MUST reject a co-requirement naming an undeclared filter,
naming its own declaration, or participating in a cycle. Each is a specification
defect that would otherwise surface as a query that can never be satisfied.

A filter declaring no co-requirement MUST serialize, in the served specification
and in the input to its etag, exactly as it would under an engine without this
capability. The etag signals that the semantics a buyer compiled against have
changed; an engine upgrade that changes no specification's semantics MUST NOT
rotate any specification's etag.

#### Scenario: A co-required filter is missing from a query

- **WHEN** a buyer supplies a filter whose declaration co-requires another and
  omits it
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A co-required filter is supplied alone

- **WHEN** a buyer supplies only a filter that others co-require
- **THEN** the query is evaluated normally as a constraint on that field

#### Scenario: A client bypasses compiler validation

- **WHEN** a request reaches the registry supplying a filter without its
  co-requirements, without having been compiled by the buyer client
- **THEN** the registry refuses it

#### Scenario: A specification declares a cyclic co-requirement

- **WHEN** a filter specification declares co-requirements that form a cycle, name
  an undeclared filter, or name their own declaration
- **THEN** specification validation fails rather than the registry serving it

#### Scenario: A specification declares no co-requirement

- **WHEN** a registry whose engine supports co-requirements loads a specification
  that declares none
- **THEN** the served specification and its etag are identical to those an engine
  without the capability produces

### Requirement: The compute schema carries a listing's asking rate

The compute filter specification MUST describe an optional `asking_rate` object on
the published listing resource, carrying `amount`, `asset`, and `period`, all
required when the object is present. `amount` is exact decimal text; `asset` is an
opaque, non-empty identifier of the same kind a settlement option's published asset
carries, requiring no contract address, token decimals, or chain identity; `period`
is the time unit the amount is quoted per, `hour` in this version. The object is a
sibling of the listing's flattened dimension fields and is not nested under a
capability family.

The object is declared in the compute specification, which is data the generic
registry serves, and not in registry engine code. The registry validates it only
where it validates the listing shape today — the dry run — and does not refuse it at
the publish boundary; the storefront that builds the listing is responsible for
publishing only a complete, valid rate. No registry surface may interpret the asset
beyond comparing it for equality.

#### Scenario: A listing is dry-run with a partial asking rate

- **WHEN** a publisher dry-runs a compute listing whose `asking_rate` omits its asset
  or its period
- **THEN** the dry run reports the listing invalid, naming the asking rate

#### Scenario: A rate is quoted in an off-chain asset

- **WHEN** a listing publishes an asking rate in an asset that has no contract
  address, decimals, or chain identity
- **THEN** the registry stores and serves the asset identifier opaquely

### Requirement: Rate filters match the period and asset rather than normalizing across them

The compute filter specification MUST declare exact, fail-on-missing filters over
the asking rate's amount, asset, and period. The amount filters MUST use the exact
decimal comparison type and MUST co-require the asset and period filters, so the
refusal below is declared in the specification rather than encoded in the registry
or the buyer client.

A rate-bounded query MUST name the asset and the period it asks about, and MUST be
refused rather than evaluated when either is absent: a bare bound states neither
what is being counted nor per what.

A listing quoting a different period MUST be excluded rather than converted,
because a period signals the commitment a seller expects: a buyer shopping hourly
is not asking for supply quoted monthly.

A listing quoting a different asset MUST likewise be excluded rather than
converted. Converting between assets requires an external exchange rate that moves
continuously, which would make one query's result depend on when it ran and would
make the registry an authority on relative asset value.

A listing publishing no rate MUST be excluded from a rate-bounded query rather than
matching it, consistent with every other filter over the published listing shape. An
unstated rate has not been shown to satisfy a stated bound.

The upper bound's query name MUST be the bare `asking_rate`, and the lower bound's
`asking_rate_min`, following the bound-naming rule below: a buyer searches a price
from above.

#### Scenario: A buyer bounds a query by rate

- **WHEN** a buyer queries for listings at or below a rate in a named asset and period
- **THEN** only listings quoting that asset and period and satisfying the bound are returned

#### Scenario: A rate bound names no asset or no period

- **WHEN** a buyer submits a rate bound without an asset, or without a period
- **THEN** the query is refused rather than evaluated against an unstated dimension

#### Scenario: A listing quotes a different period

- **WHEN** a listing quotes its rate in a period the query did not name
- **THEN** it is excluded rather than converted into the queried period

#### Scenario: A listing quotes a different asset

- **WHEN** a listing quotes its rate in an asset the query did not name
- **THEN** it is excluded rather than converted into the queried asset

#### Scenario: A listing publishes no rate

- **WHEN** a buyer bounds a query by rate and a listing publishes none
- **THEN** that listing is excluded from the result

#### Scenario: A rate bound compares exactly

- **WHEN** a listing's asking amount carries more significant digits than a binary
  double represents exactly and a buyer bounds a query near it
- **THEN** the listing is matched or excluded on its exact value

### Requirement: A bound filter's bare query name is the bound a buyer searches by

When a filter specification declares a bound over a field, the field's bare query
name MUST name the bound a buyer searching that field would mean by default, and
any other bound over the same field MUST carry a suffixed name. For a field where
more is at least as good for the buyer, such as a capacity dimension, that is the
lower bound; for a field where less is better, such as a price, it is the upper
bound.

This is a rule for filter authors choosing query names, not a behaviour the engine
enforces: each declaration states which bound it carries, so evaluation never
depends on the name. It exists so a buyer reading the vocabulary can predict what
a bare name means from what the field measures, and so the first field where more
is not better does not have to be reasoned about afresh.

#### Scenario: A capacity field declares a lower bound

- **WHEN** a specification declares a lower bound over a capacity field
- **THEN** the bound carries the field's bare query name

#### Scenario: A price field declares both bounds

- **WHEN** a specification declares an upper and a lower bound over a price
- **THEN** the upper bound carries the field's bare query name and the lower bound a
  suffixed one

## Evidence

- Schema loading, validation, and ETag behavior: `core/registry/tests/unit/test_filter_spec.py`, `core/registry/tests/integration/test_filter_spec.py`, and `core/registry/tests/integration/test_validate_publish.py`.
- Declarative filtering and stale `If-Match`: `core/registry/tests/unit/test_filter_eval.py` and `core/registry/tests/integration/test_listings_filtering.py`.
- Injected dual-scheme publisher identity, stable listing ownership, body-bound requests, signed responses, and replay behavior: `core/registry/tests/integration/test_identity_publish.py`, `core/registry/tests/integration/test_listings.py`, `core/registry/tests/unit/test_publisher_auth.py`, and `core/registry-client/tests/test_auth.py`.
- Publisher rotation and stable-subject ownership: `core/registry/tests/integration/test_publisher_rotation.py`.
- Atomic canonical-principal migration and rollback: `core/registry/tests/unit/test_principal_migrations.py`.
- Strict descriptor carriers, startup derivation, access posture, signed reads, and durable replay: `core/tests/unit/test_registry_descriptor.py`, `core/registry/tests/unit/test_registry_descriptor.py`, and `core/registry/tests/integration/test_registry_descriptor.py`.
- Helm descriptor configuration and Secret separation: `helm/scripts/test-render.sh`.
- Published capacity backing and its filter: `core/registry/tests/integration/test_capacity_backing_filter.py` and `core/registry/tests/unit/test_filter_eval.py`.
- Finite exact decimal comparison, refused non-finite bounds, and non-finite listing values read as no value: `core/registry/tests/unit/test_filter_eval.py` and `core/registry/tests/unit/test_filter_spec.py`.
- Declared co-requirements, their specification validation, and an undeclaring specification's unchanged etag: `core/registry/tests/unit/test_filter_spec.py` and `core/registry/tests/unit/test_filter_eval.py`; on the buyer side: `core/tests/unit/test_query_dsl.py` and `core/registry-client/tests/test_query.py`.
- The compute schema's asking rate and its filters through the canonical client and the real registry — exact bounds by both names, asset and period exclusion, a rateless-introduction listing found by its rate, and the registry's own refusal of a bound without its co-requirements: `core/registry/tests/integration/test_asking_rate_filter.py`; across running services: `e2e-tests/tests/e2e/roles/scenarios/bare_metal/test_bare_metal_publication.py` (stages 05b–05d).
