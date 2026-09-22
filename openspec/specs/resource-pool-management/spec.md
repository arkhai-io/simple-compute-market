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

Replacement semantics MUST NOT apply to secret provider-configuration fields. A field whose value is never returned by a read cannot be restated by a caller performing a full replacement, so resetting it to a default on omission would destroy a credential in response to an unrelated edit. Secret fields MUST retain their stored value unless the request supplies an explicit replacement, on PUT as on PATCH.

#### Scenario: PUT omits optional mutable fields

- **WHEN** an operator replaces a pool with a valid full `PoolReplace` document that omits optional policy tags
- **THEN** the stored tags are reset to the model's replacement default rather than retaining prior state

#### Scenario: PATCH changes one field

- **WHEN** an operator patches only a pool label
- **THEN** the label changes and all omitted mutable fields remain unchanged

#### Scenario: PUT omits a secret provider-configuration field

- **WHEN** an operator replaces a pool or relay with a full document that omits a secret field the read path never returned
- **THEN** the stored secret is retained rather than reset, and the operation succeeds

#### Scenario: A caller supplies a replacement secret

- **WHEN** a request explicitly supplies a new value for a secret provider-configuration field
- **THEN** the stored value is replaced

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

Authority is what makes the document a declaration rather than a merge: an operator who removes an entry is stating that the pool should no longer be offered, and an import that silently kept it would make the document an incomplete description of the system it claims to describe. Disabling rather than erasing bounds the cost of that authority, so a mistaken omission is recoverable.

That authority is scoped to the act of submitting a document. A service MUST NOT re-apply a previously imported document merely because a process started. Import is idempotent with respect to the document, not with respect to the database: re-running it against state something else has changed reverts that change, because a diff against the document is what detects it. A process restart is not an operator declaring desired state, and treating it as one silently reverts administrative work on eviction, drain, and crash recovery.

A service that imports a definition document at startup MUST therefore record a durable digest of the document it imported and reconcile only when the current document differs from the recorded one. An explicit import request MUST reconcile regardless of the digest, because the operator has asked.

The recorded digest MUST be written in the same transaction that applies the reconciliation. A digest recorded after a separate, already-committed apply is indistinguishable at the next startup from one recorded before a crash, so the two must commit or fail together. Satisfying this requires a session-scoped import operation: an import that opens and commits its own transaction cannot be composed with the digest write.

#### Scenario: One imported entry is invalid

- **WHEN** a document contains valid changes and one invalid pool definition
- **THEN** the complete import is rejected and none of the valid changes are persisted

#### Scenario: Valid document is re-imported

- **WHEN** an operator imports the same valid document twice
- **THEN** the second response reports the declared pools unchanged and performs no semantic data change

#### Scenario: Canonical export is round-tripped

- **WHEN** an operator exports the current pool state and validates or imports that YAML without editing it
- **THEN** the document remains valid and represents the same complete pool and provider configuration state

#### Scenario: A process restarts against an unchanged document

- **WHEN** state is changed through the API and the service restarts with the same definition document still mounted
- **THEN** no reconciliation is performed and the change made through the API is retained

#### Scenario: A mounted document is edited and the service restarts

- **WHEN** a mounted definition document is edited and the service restarts
- **THEN** the document is reconciled authoritatively, including disabling entries it no longer names

#### Scenario: An operator submits an unchanged document explicitly

- **WHEN** an operator submits a document identical to the one last imported
- **THEN** reconciliation runs and the response reports the resulting diff

#### Scenario: An import is composed with other work in one transaction

- **WHEN** a caller applies a definition document and records its digest
- **THEN** both are visible together or neither is, under any interruption

#### Scenario: Reconciliation fails part way

- **WHEN** an import is attempted and the apply fails
- **THEN** the recorded digest is unchanged, so the next startup attempts the reconciliation again

### Requirement: Registered requirement delegates

An Ansible resource pool MUST persist a `requirement_delegate` identifier alongside its playbook configuration. The identifier MUST resolve through the VM provisioning adapter's allowlisted delegate registry; resource-pool configuration MUST NOT contain or load arbitrary Python import paths. The selected delegate owns compatibility validation and translation from canonical committed VM dimensions to the selected playbook's variable names, units, and derived values.

Pool create, replace, patch, import, and validation operations MUST reject an unknown delegate identifier as invalid provider configuration before committing any change. Existing pools and omitted identifiers MUST resolve to the repository's documented default delegate. Fulfillment acceptance MUST snapshot the resolved delegate output together with the playbook and other provider inputs so later pool edits do not alter an accepted operation.

#### Scenario: Pool names an unknown requirement delegate

- **WHEN** an operator creates, updates, imports, or validates an Ansible pool whose `requirement_delegate` is not registered
- **THEN** provider-config validation rejects the operation before persistence or fulfillment dispatch

#### Scenario: Pool omits the requirement delegate

- **WHEN** an existing or newly submitted Ansible pool omits `requirement_delegate`
- **THEN** normalization selects the documented default delegate and canonical export includes the resolved identifier

#### Scenario: Delegate configuration changes after fulfillment acceptance

- **WHEN** an operator changes a pool's delegate or playbook after fulfillment has accepted and persisted prepared provider input
- **THEN** retries and dispatch use the snapshotted prepared input rather than re-reading the live pool configuration

### Requirement: Session-scoped pool reads

Resource-pool management MUST expose a session-scoped pool lookup that loads provider configuration using the caller's open database session. Fulfillment uses this operation while freezing prepared provider input so the pool snapshot and aggregate write share one transaction.

Provider configuration MUST be readable at two levels of disclosure. The unqualified read MUST omit secret fields and is what serves API responses, exported documents, administrative round-trips, and reconciliation comparison. A separately named execution read MAY include decrypted secrets and is reserved for preparing provider input at dispatch.

The unqualified name MUST belong to the read that omits secrets, so that a caller which does not ask for them does not receive them. Reconciliation MUST compare stored state against a definition document using the unqualified read on both sides, so that a field one side cannot see does not report as perpetual drift.

#### Scenario: Pool configuration is frozen with acceptance

- **WHEN** fulfillment prepares provider input inside its acceptance transaction
- **THEN** the pool and provider configuration are read through the same caller-owned session before the prepared operation is persisted

#### Scenario: An API response is serialized

- **WHEN** provider configuration is read for a pool detail, list, or export response
- **THEN** no secret field is present in the serialized output

#### Scenario: Reconciliation compares an unchanged document

- **WHEN** a definition document that has not changed is compared against stored state holding a secret
- **THEN** the comparison reports no difference

### Requirement: Domain-neutral publication and hold hints

Resource Pool policy metadata MUST support stable domain-neutral keys for `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` without defining domain-specific cardinality, region, SLA, or pricing values in this shared capability. The key MUST be named for its scope: it carries how many listing candidates a pool yields and how each is independently identified, and a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. The former `listing_mode` key MUST remain accepted as a deprecated ingestion alias resolving to the same cardinality, because that key is optional and its silent absence resolves to a structural default rather than an error — an unupgraded producer whose alias were rejected would be reclassified rather than refused. The alias is a read-path concession only. Policy tags are projected verbatim, so the spelling an operator stored is the spelling a consumer receives and reconciliation belongs at the reading end; the reader this capability exposes MUST be named for the settled key and MUST resolve either spelling, and no other surface naming this hint may use the deprecated one. Unknown policy tags MUST remain forward-compatible opaque metadata. `pool_id` is a site-local operator slug, never made globally unique; every durable or public reference to a pool keys on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.

#### Scenario: Domain interprets the cardinality hint

- **WHEN** VM, bare-metal, or API-credit publication reads a Resource Pool's `listing_cardinality_mode`
- **THEN** the selected domain validates and interprets the value without adding its enum or default rule to this shared package

#### Scenario: A pool declares the deprecated key

- **WHEN** a Resource Pool's policy metadata carries `listing_mode` rather than `listing_cardinality_mode`
- **THEN** the value resolves to the same cardinality the deprecated key names
- **AND** the pool is neither refused nor reclassified to a structural default

#### Scenario: Consumer does not support a hint

- **WHEN** a storefront version does not recognize one projected policy tag
- **THEN** it ignores that tag without rejecting the Resource Pool or changing authoritative admission

### Requirement: Pool-declared offering modes

Each Resource Pool MUST declare the set of offering modes its configured provider can deliver under the domain-neutral `deliverable_modes` policy tag. The shared resource-pool capability MUST validate this declaration as a JSON-compatible set of unique, non-empty strings and expose typed resolution and membership behavior without defining which names are meaningful to a domain. An absent or empty declaration authorizes no mode and MUST NOT be widened by a default.

Create, replace, patch, bulk import, projection, and canonical export MUST use the existing policy-tag channel and precedence. An existing pool's initial set MUST be derived only from durable provider, playbook, and registered requirement-delegate configuration that proves the pool can deliver that mode. Derivation MUST include the system-owned `default` pool, MUST NOT use reservation history as capability evidence, MUST replace an unproved legacy declaration with the exact proved set, and MUST report each derived set at INFO.

#### Scenario: Pool declares two modes

- **WHEN** an operator stores `deliverable_modes: [bare_metal, vm]`
- **THEN** typed resolution returns exactly those two opaque mode names through ordinary projection and administration paths

#### Scenario: Declaration is absent

- **WHEN** a Resource Pool has no `deliverable_modes` tag
- **THEN** typed resolution returns an empty set and the pool delivers no offering mode

#### Scenario: Existing default pool is migrated

- **WHEN** the default pool has an Ansible playbook and the registered VM requirement delegate
- **THEN** migration declares exactly `vm`, reports that conclusion, and does not infer another mode from historical reservations

#### Scenario: Legacy declaration is wider than configuration

- **WHEN** a pool's durable provider configuration proves no deliverable mode but its legacy policy metadata names one or more modes
- **THEN** migration narrows the declaration to empty rather than retaining an unproved capability

#### Scenario: Declaration is malformed

- **WHEN** any Resource Pool write supplies a non-list, duplicate, empty, or non-string deliverable mode
- **THEN** validation rejects the write without changing the pool

### Requirement: Reservation hold and SLA preference validation

A Resource Pool management surface that accepts `max_reservation_hold_seconds` MUST require a nonnegative integer, or `sla` MUST require a nonnegative number (integer or fractional), and MUST expose the normalized value as advisory metadata rather than an admission rule. This applies identically to every surface capable of persisting a Resource Pool's `policy_tags` — the bulk pool-document import path and the individual pool admin API (`create`/`replace`/`update`) both validate through the same shared check.

#### Scenario: Operator supplies an invalid hold preference

- **WHEN** an operator submits a negative, fractional, or nonnumeric hold preference through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy metadata

#### Scenario: Operator supplies an invalid SLA value

- **WHEN** an operator submits a negative or nonnumeric `sla` through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy metadata, the same as an invalid hold preference

### Requirement: Pool-declared advertisable modes

Each Resource Pool MUST declare the set of offering modes its listings may
advertise under the domain-neutral `advertisable_modes` policy tag. The shared
resource-pool capability MUST validate this declaration as a JSON-compatible set
of unique, non-empty strings without defining which names are meaningful to a
domain. An empty declaration authorizes no mode, and neither an empty nor an
absent declaration MAY be widened by a default. Membership MUST be offered only on
declarations resolved through the shared resolver, never on raw policy tags,
because a raw read would treat an absent declaration as an empty one.

Advertisement authorization is a separate claim from delivery authorization. A
pool MUST NOT be required to prove it can deliver a mode in order to advertise
it, and `deliverable_modes` MUST retain its existing meaning, derivation, and
every execution recheck unchanged.

Where a Resource Pool declares `capacity_backing: backed`, its advertisable set
MUST be a subset of its deliverable set. A write that would violate the relation
from either side — widening the advertisable set or narrowing the deliverable set
— MUST be rejected without changing the pool, and MUST NOT be repaired by
rewriting the other declaration. Where a Resource Pool declares
`capacity_backing: unbacked`, its advertisable set is not constrained by its
deliverable set.

#### Scenario: An execution-less pool advertises a mode

- **GIVEN** a Resource Pool declaring `capacity_backing: unbacked` and an empty deliverable set
- **WHEN** an operator declares `advertisable_modes: [vm]`
- **THEN** typed resolution returns exactly that mode and the resolved declaration advertises `vm`
- **AND** the declaration is not narrowed by the absence of a deliverable proof

#### Scenario: A backed pool advertises beyond what it delivers

- **GIVEN** a Resource Pool declaring `capacity_backing: backed` and `deliverable_modes: [bare_metal]`
- **WHEN** an operator declares `advertisable_modes: [bare_metal, vm]`
- **THEN** the write is rejected and the pool is unchanged

#### Scenario: A backed pool's delivery is narrowed below its advertisement

- **GIVEN** a Resource Pool declaring `capacity_backing: backed`, `deliverable_modes: [vm]`, and `advertisable_modes: [vm]`
- **WHEN** an operator writes `deliverable_modes: []` without also narrowing `advertisable_modes`
- **THEN** the write is rejected and neither declaration is changed

#### Scenario: Advertisement declaration is empty

- **WHEN** a Resource Pool declares `advertisable_modes: []`
- **THEN** typed resolution returns an empty set and the pool authorizes no mode for advertisement

### Requirement: Pool-declared capacity backing

Each Resource Pool MUST declare whether it can be admitted against under the
domain-neutral `capacity_backing` policy tag, whose values are `backed` and
`unbacked`. `backed` means an admission authority stands behind the pool;
`unbacked` means none does, so nothing may be reserved, committed, or released
against it.

A Resource Pool declaring `capacity_backing: unbacked` MUST declare an empty
deliverable set. Every reservation, scheduling, and dispatch layer already refuses
a pool that declares no deliverable mode, so this rule is what keeps every
capacity path unreachable for an unbacked pool without any layer reading backing.
A write declaring an unbacked pool with a non-empty deliverable set MUST be
rejected without changing the pool.

A value outside `backed` and `unbacked` MUST be rejected on write. A discriminator
MUST NOT resolve to a default: unlike a cardinality hint, where a structural
default is a reasonable assumption about how many candidates to publish, a backing
default would assert whether anything stands behind a listing.

`capacity_backing` MUST be fixed at pool creation. A replace, patch, or
authoritative-document entry for an existing pool supplying a backing value that
differs from the stored one MUST be rejected and the pool left unchanged. Moving
inventory between backed and unbacked supply is a second pool declaring the
intended backing with its capacity resources migrated across, because backing is a
property every listing derived from the pool inherits, and changing it in place
would silently reinterpret listings already published.

A stored pool carrying no backing value MAY be given one; supplying a value
where none is stored is not a change to it. That state arises only from a version
predating the declaration rewriting a pool's tags, and a service refuses to start
while any stored pool lacks valid declarations, so in practice the value is
supplied by a changed definition document imported before that check.

#### Scenario: Backing is changed on an existing pool

- **WHEN** a replace, patch, or imported document entry supplies a `capacity_backing` value differing from the pool's own
- **THEN** the request is rejected and the pool is unchanged
- **AND** the supported path is a second pool declaring the intended backing with capacity resources migrated across

#### Scenario: A pool without stored backing is repaired

- **GIVEN** a stored pool whose policy tags carry no `capacity_backing`, written by a version predating the declaration
- **WHEN** a changed definition document declaring its backing is imported at startup
- **THEN** the pool records that backing and the startup declaration check passes

#### Scenario: An unbacked pool declares a deliverable mode

- **WHEN** any pool write declares `capacity_backing: unbacked` together with a non-empty `deliverable_modes`
- **THEN** the write is rejected and the pool is unchanged

#### Scenario: A malformed backing value is written

- **WHEN** any pool write declares a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** the write is rejected and the pool is unchanged

### Requirement: Required advertisement and backing declarations

Every pool write MUST carry both `advertisable_modes` and `capacity_backing`
explicitly: create, replace, patch whenever it supplies policy tags, and every
entry of an authoritative definition document, validated or imported. The create
and replace models MUST declare policy tags as a required field rather than
defaulting it to an empty map that validation then refuses, so the published
schema states that it cannot be omitted. A write
omitting either MUST be rejected with a validation problem naming the missing tag.
The service MUST NOT default, preserve, or merge either tag from any other source;
the policy tags a write supplies are the policy tags stored. The replacement rule
that resets omitted optional policy tags does not reach these two tags, because
they are not optional.

The shape of `deliverable_modes`, the presence and shape of both new
declarations, the backed subset rule, and the unbacked empty-deliverable rule
MUST be applied by one shared validation, identically for the typed
administration models, the service, and authoritative document validation and
import, so a typed client cannot construct a write the service would refuse for
its declarations. Backing immutability is evaluated against stored state and MUST be reported
as a structured problem on the validate-only path as well as refusing an import.

A service that seeds Resource Pools at startup, whether from a definition document
or from its own bootstrap, MUST refuse to start when a seeded pool does not carry
valid declarations, naming the pool and the problem. A service MUST likewise refuse
to start when a stored Resource Pool does not carry valid declarations.

Canonical export MUST emit both tags for every pool, so an exported document is a
valid import.

#### Scenario: A write omits a declaration

- **WHEN** a create, replace, patch supplying policy tags, or imported document entry omits `advertisable_modes` or `capacity_backing`
- **THEN** the write is rejected with a problem naming the missing tag and no pool is changed

#### Scenario: A document predating the declarations is imported

- **WHEN** an authoritative document whose pool entries carry neither tag is validated or imported
- **THEN** validation reports each missing tag per entry and the import changes nothing

#### Scenario: A seeded pool lacks declarations

- **WHEN** a service starts with a changed pool definition document, or a bootstrap seed, producing a pool without valid declarations
- **THEN** the service refuses to start and names the pool and the problem

#### Scenario: A stored pool lacks declarations

- **WHEN** a service starts against a database holding a Resource Pool without valid declarations
- **THEN** the service refuses to start and names the pool and the problem

#### Scenario: An export carrying declarations is round-tripped

- **WHEN** an operator exports the current pool state and imports it unedited
- **THEN** every pool entry carries both declarations and the import reports every pool unchanged

### Requirement: Shared resolution of advertisement and backing declarations

The shared resource-pool capability MUST expose one domain-neutral resolver that
turns a pool's policy tags into typed advertisable modes and backing, sharing its
implementation with write-side validation. It MUST fail rather than resolve to a
default for a malformed value of either tag, a backed pool whose advertisable set
exceeds its deliverable set, and an unbacked pool with a non-empty deliverable set.
It MUST report an absent tag distinctly from a malformed one, so a consumer can
apply a producer-version rule to a producer that emits a tag for no pool while
failing a single omitting pool closed.

Any reader of projected pool declarations MUST resolve them through this resolver,
so the site that writes a declaration and every consumer that reads it agree on
what a valid declaration is.

#### Scenario: A projected backed pool advertises beyond what it delivers

- **WHEN** the resolver receives policy tags declaring `capacity_backing: backed` with an advertisable set exceeding the deliverable set
- **THEN** it fails for that pool rather than returning either set

#### Scenario: A projected backing value is malformed

- **WHEN** the resolver receives a `capacity_backing` value outside `backed` and `unbacked`
- **THEN** it fails for that pool rather than resolving to either value

#### Scenario: A projected pool omits a declaration

- **WHEN** the resolver receives policy tags carrying neither `advertisable_modes` nor `capacity_backing`
- **THEN** it reports each tag as absent, distinctly from malformed, and returns no default

### Requirement: Complete emission and upgrade derivation

Create, replace, patch, bulk import, projection, and canonical export MUST carry
both tags on the existing policy-tag channel. A producer that emits either tag MUST
emit it for every Resource Pool it projects, so that a consumer can distinguish a
producer that predates the tag from a producer that omitted it for one pool.

On upgrade, every existing Resource Pool — including the system-owned `default`
pool and pools held by any service that stores its own Resource Pools — MUST have
both tags written by migration: `advertisable_modes` equal to its proved
deliverable set, and `capacity_backing: backed`. Migration MUST overwrite any value
previously stored under either key, MUST report each derived value at INFO, and MUST
NOT change any pool's advertising surface or admission behavior.

#### Scenario: An existing pool is migrated

- **GIVEN** a Resource Pool whose proved deliverable set is `[vm]`
- **WHEN** migration runs
- **THEN** its advertisable set is exactly `[vm]` and its backing is `backed`
- **AND** both values are reported at INFO and its admission behavior is unchanged

#### Scenario: An existing pool held an opaque value under a new key

- **GIVEN** a Resource Pool whose policy tags already carry `capacity_backing` or `advertisable_modes` as unrecognized opaque metadata
- **WHEN** migration runs
- **THEN** both keys are overwritten with the derived values

#### Scenario: A migrated site is projected

- **WHEN** a migrated producer projects its Resource Pools
- **THEN** every projected pool carries both tags

#### Scenario: A producer emits the tags incompletely

- **WHEN** a producer emits `capacity_backing` for some Resource Pools and omits it for another it projects
- **THEN** the projection is malformed with respect to this requirement, and the omitted pool is not treated as predating the tag

## Evidence

- Domain-neutral hint keys, typed deliverable-mode resolution and membership, advertisement and backing declaration shape, both cross-tag rules, and the strict resolver including absent-versus-malformed discrimination: `kit/resource-pools/tests/unit/test_hints.py`.
- Pool write models requiring `policy_tags` and refusing invalid declarations, including a malformed deliverable set: `kit/resource-pools/tests/unit/test_pool_models.py`.
- Pool persistence, registered requirement-delegate validation, strict import, dry-run, idempotency, lifecycle, provider replacement, identical declaration validation across individual and bulk administration, backing immutability, path-named import errors, and stored-declaration checks including the startup repair path: `kit/resource-pools/tests/integration/test_resource_pool_service.py`.
- Existing-pool derivation, default-pool inclusion, idempotency, narrowing, drift rejection, and INFO evidence: `provisioning/compute/service/tests/unit/test_pool_offering_mode_migration.py`.
- Advertisement and backing migration on every existing pool, clobbering prior opaque values, unchanged admission, and malformed-delivery drift: `provisioning/compute/service/tests/integration/test_pool_advertisement_backing_migration.py`, `domains/apicredits/service/tests/integration/test_pool_declarations_migration.py`.
- Startup refusal of a seeded or stored pool without valid declarations, and the check's position after the pool document import: `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`, `domains/apicredits/service/tests/integration/test_pool_declarations_migration.py`.
- Typed administrative API, default-pool invariant, canonical round trip, host assignment, an execution-less pool advertising through a configuration-free provider, and server-side refusal of invalid declarations: `provisioning/compute/service/tests/integration/test_pools_api.py`.
- Both declarations on every projected pool, each resolving through the shared resolver: `provisioning/compute/service/tests/integration/test_capacity_api.py`.
- Migration ordering, legacy host backfill, and schema-drift rejection: `provisioning/compute/service/tests/unit/test_database.py`.

## Scheduling membership and draining

Every resource eligible for physical settlement belongs to exactly one Resource Pool. Zero memberships makes the resource unschedulable; multiple memberships misrepresent system capacity and are invalid configuration.

Disabling a Resource Pool is a draining action. It blocks new Capacity Settlement Assignments to that pool but does not invalidate existing reservations, assignments, physical settlements, or active workloads, and those existing records do not prevent disablement.

## Relationship to fulfillment scheduling

Resource-pool management owns administrative routing metadata: pool identity, enabled state, policy tags, provider kind, provider-specific configuration, and host/resource membership. It does not own fulfillment-provider protocols or settlement-resource assignment.

The higher-layer [fulfillment capability](../fulfillment/spec.md) reads enabled pool and resource information when evaluating candidates. Disabling a pool prevents new scheduling assignments while preserving existing reservations, assignments, fulfillment records, and active workloads. `market_resource_pools` must not import `market_fulfillment`, including for type-only annotations.
