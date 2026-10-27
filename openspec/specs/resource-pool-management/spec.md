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

Resource Pool policy metadata MUST support stable domain-neutral keys for `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, `pricing`, and `listing_shapes` without defining domain-specific cardinality, region, SLA, pricing, or shape values in this shared capability. The key MUST be named for its scope: it carries how many listing candidates a pool yields and how each is independently identified, and a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. `listing_shapes` carries, per offering mode, the shapes a pool's listings are sold in; it describes what is offered, which is why it is a key of its own rather than a value of the cardinality hint. The former `listing_mode` key MUST remain accepted as a deprecated ingestion alias resolving to the same cardinality, because that key is optional and its silent absence resolves to a structural default rather than an error — an unupgraded producer whose alias were rejected would be reclassified rather than refused. The alias is a read-path concession only. Policy tags are projected verbatim, so the spelling an operator stored is the spelling a consumer receives and reconciliation belongs at the reading end; the reader this capability exposes MUST be named for the settled key and MUST resolve either spelling, and no other surface naming this hint may use the deprecated one. Unknown policy tags MUST remain forward-compatible opaque metadata. `pool_id` is a site-local operator slug, never made globally unique; every durable or public reference to a pool keys on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.

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

#### Scenario: Domain interprets the shape hint

- **WHEN** VM publication reads a Resource Pool's `listing_shapes`
- **THEN** it reads only the list under the `vm` offering mode and interprets its shapes through the VM domain's schema, without that schema being added to this shared package

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
turns a pool's policy tags into typed advertisable modes and the backing delegate the
pool's `capacity_backing` label selects, sharing its implementation with write-side
validation. It MUST fail rather than resolve to a default for a malformed value of
either tag, a backed pool whose advertisable set exceeds its deliverable set, and an
unbacked pool with a non-empty deliverable set. It MUST report an absent tag
distinctly from a malformed one, so a consumer can apply a producer-version rule to a
producer that emits a tag for no pool while failing a single omitting pool closed.

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

#### Scenario: A projected pool resolves

- **WHEN** the resolver receives valid declarations
- **THEN** it returns the advertisable modes and the backing delegate the declared label selects

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

### Requirement: Listing-shape hint validation

A Resource Pool management surface that accepts `listing_shapes` MUST require a mapping from
offering mode to a non-empty list of structurally well-formed stated listing shapes. A
well-formed stated listing shape is a non-empty mapping of family name to a non-empty
mapping of field name to either a scalar value or a structurally valid constraint mapping.
The check MUST be the shared structural split the shape admissibility kit provides, which
applies the capability shape utility's structural check to the base shape, and MUST NOT
depend on any domain's family or field names. Which families and fields are meaningful,
which are required, and which may carry constraints MUST be validated by the domain that
reads the hint. A list whose entries state one base shape with different constraints
MUST be rejected, because it contradicts itself whichever storefront reads it; the
shared list-level split detects it without domain vocabulary, and identical entries MUST
be accepted. A pool's stated shapes MUST NOT be judged against any storefront's
configured constraints at write. Every surface capable of persisting a Resource Pool's
`policy_tags` MUST apply the same check: the bulk pool-document import path and the
individual pool admin API (`create`/`replace`/`update`).

#### Scenario: Operator supplies a malformed shape list

- **WHEN** an operator submits `listing_shapes` whose VM list is empty, or whose shape
  holds a family that is not a mapping, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy
  metadata

#### Scenario: Operator names a field no domain defines

- **WHEN** an operator submits a structurally well-formed shape naming a field the VM domain
  does not define
- **THEN** Resource Pool validation accepts it, and the VM storefront reports the pool's
  shapes as unreadable when it derives listings

#### Scenario: Operator supplies a malformed constraint

- **WHEN** an operator submits a stated shape whose constraint mapping states a `min`
  above its `max`, a non-positive value, an `offer` outside its own range, no key, or an
  unknown key, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy
  metadata

#### Scenario: Operator constrains an attribute

- **WHEN** an operator submits a structurally valid constraint mapping on a field the VM
  domain defines as an attribute
- **THEN** Resource Pool validation accepts it, and the VM storefront reports that
  listing's constraints as unusable when it derives listings

#### Scenario: Operator states one base shape with different constraints

- **WHEN** an operator submits a VM list holding `gpu: {model: H100, count: {offer: 1,
  max: 4}}` and `gpu: {model: H100, count: {offer: 1, max: 8}}`, through any pool-write
  surface
- **THEN** Resource Pool validation rejects the update naming both entries, without
  changing the stored policy metadata

#### Scenario: Operator repeats an identical shape

- **WHEN** an operator submits a VM list holding the same shape twice, with the same
  constraints
- **THEN** Resource Pool validation accepts it

### Requirement: Asking-rate hint validation

Resource Pool policy metadata MUST support a domain-neutral `asking_rates` key
carrying, per offering mode, the rates a site asks for the shapes its listings are
sold in. It is a key of its own rather than a value inside `pricing`, because every
compute-family domain reads it through one shared reader and one structural check,
as `listing_shapes` is read.

A Resource Pool management surface that accepts `asking_rates` MUST require a mapping
from offering mode to a list of entries. Each entry MUST carry a `shape` that is a
structurally well-formed family-grouped capability shape, checked by the shared
structural check the capability shape utility provides; an `amount` that is positive
decimal text without an exponent; an `asset` that is a trimmed, non-empty string; and
a `period` that is a canonical lowercase unit token. An empty list MUST be accepted.

The check MUST NOT depend on any domain's family or field names, and MUST NOT restrict
which periods are accepted: which families and fields are meaningful, and which
periods a published rate may use, MUST be validated by the domain that reads the hint.
Every surface capable of persisting a Resource Pool's `policy_tags` MUST apply the
same check: the bulk pool-document import path and the individual pool admin API
(`create`/`replace`/`update`). The value MUST be projected verbatim.

#### Scenario: Operator supplies a malformed asking rate

- **WHEN** an operator submits an `asking_rates` entry whose amount is a JSON number,
  whose asset is blank, or whose shape holds a family that is not a mapping, through
  any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored
  policy metadata

#### Scenario: Operator quotes a period no domain accepts

- **WHEN** an operator submits a structurally well-formed entry quoted per `month`
- **THEN** Resource Pool validation accepts it, and a storefront that accepts only
  `hour` holds the pool's listings and reports the declaration unreadable

### Requirement: Pricing rate-list hint validation

A Resource Pool management surface that accepts the `pricing` key MUST check the structure of every
rate list it carries: any `rates` value found under a family, or under a key within a family, of
`pricing` MUST be a list of entries, each carrying an `asset` that is a trimmed, non-empty string, a
`rate` that is positive decimal text without a sign or an exponent, and a `per` that is a canonical
lowercase unit token, with no asset appearing twice in one list. An empty list MUST be accepted.

The check MUST NOT depend on any domain's family or field names, and MUST NOT restrict which units
are accepted: which families are priced, by what key, and which units a rate may use MUST be
validated by the domain that reads the hint. Every surface capable of persisting a Resource Pool's
`policy_tags` MUST apply the same check, as it does for `asking_rates`, and the value MUST be
projected verbatim. Values of `pricing` other than rate lists are unaffected.

#### Scenario: Operator supplies a malformed family rate

- **WHEN** an operator submits a pool whose `pricing.memory.rates` holds an entry whose rate is a
  JSON number, whose asset is blank, or whose asset repeats another entry's, through any pool-write
  surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy metadata,
  naming the entry

#### Scenario: Operator prices a family no domain defines

- **WHEN** an operator submits a structurally well-formed rate list under a family no domain prices
- **THEN** Resource Pool validation accepts it, and a storefront whose pricing projection does not
  name that family holds the pool's listings and reports the rate unreadable

### Requirement: The pool wire contract and client are thin distributions

The resource-pool capability MUST own its pool wire models and pool route contracts in a
contracts distribution that depends on no persistence or web-framework package, and its
typed client in a separate client distribution depending only on those contracts. The
client MUST offer async and sync variants with identical operations over any transport
that provides authenticated requests, so it depends on no compute-provisioning package. The
pool authority imports its models from the contracts distribution, and the provisioning
service that hosts the pool routes assembles the capability's route contracts into its
table without owning them.

#### Scenario: An operator administers pools

- **WHEN** an operator creates or updates a pool through the resource-pool client
- **THEN** the client signs the request from the resource-pool route contracts, and the
  operator's environment installs neither SQLAlchemy nor the compute provisioning kit

#### Scenario: A compute domain hosts no pool model

- **WHEN** the compute provisioning contracts distribution is inspected
- **THEN** it declares no resource-pool model or pool route contract

### Requirement: Capacity backing is interpreted by one delegate

A pool's declared `capacity_backing` label MUST select one backing delegate, and every
decision that differs between backed and unbacked supply MUST be made by that delegate:
the pool declaration rules, admission of a capacity effect, hold placement, judging a
listing against availability, the scope of availability reconciliation, settlement
option admissibility, the backing an older producer's pools resolve to, and the
backing an admitted reservation implies. No consumer MAY compare the label or test a
binding's type to make one of these decisions.

The label MUST remain the value pool declarations, listing bindings, and the
resource-pool projection carry, and the value a published listing carries wherever its
market's registry schema publishes backing; no surface MAY carry a representation of
the delegate in its place. Whether a market's listings publish backing is its registry
schema's decision. A label with no delegate MUST be unresolvable, as an unrecognized
value is.

#### Scenario: A consumer decides by backing

- **WHEN** a storefront, a site, or a pool authority needs a decision that differs between backed and unbacked supply
- **THEN** it asks the delegate the pool's or binding's label selects, and holds no branch of its own on the label

#### Scenario: A label has no delegate

- **WHEN** a pool declaration or a durable binding carries a backing label no delegate is registered for
- **THEN** it is refused as unresolvable rather than read as either backing

#### Scenario: The label is carried unchanged

- **WHEN** a pool is projected, a listing is bound, or a listing is published under a registry schema that carries backing
- **THEN** each carries the declared `capacity_backing` label, not a representation of the delegate

### Requirement: The default pool is created with its intended provider

A provisioning database is empty when it stores no pool and no host, whatever
schema tables or migration records it holds.
On an empty provisioning database with a configured pool definition document,
schema initialization MUST leave default-pool creation to ordinary atomic
startup document import. Contributed definitions MUST be imported before pools,
and host inventory MUST follow pools. Without a configured document, schema
initialization MUST retain the VM bootstrap.
A database storing a pool or a host MUST retain default-pool identity and host
backfill; a mounted document MUST NOT change an existing pool's provider.

#### Scenario: A fresh bare-metal site declares its default

- **WHEN** a fresh provisioning database starts with a valid document declaring `default` as `bare_metal.ansible`
- **THEN** import creates that pool with its declared configuration and records the digest atomically before admitting inventory
- **AND** no implicit VM default is created, including on repeated migration before first startup

#### Scenario: An interrupted first migration is retried

- **WHEN** a first migration with a configured pool document stopped after creating schema tables but before storing any pool or host, and migration runs again
- **THEN** the database is still empty and no implicit VM default is created
- **AND** startup import creates `default` from the document

#### Scenario: A fresh site has no pool document

- **WHEN** a fresh provisioning database has no configured pool document
- **THEN** migration creates the enabled VM default with its configured VM playbook

#### Scenario: An existing site gains a pool document

- **WHEN** migration runs against existing state with a newly configured pool document
- **THEN** existing host membership and the default pool are preserved
- **AND** startup import refuses a differing default provider

#### Scenario: The configured document is missing or invalid

- **WHEN** a fresh provisioning database has a configured pool document that cannot be imported
- **THEN** startup fails without substituting an implicit VM default

### Requirement: VM provider identity is namespaced

The VM adapter MUST register as `vm.ansible`, alongside `bare_metal.ansible`.
Upgrade MUST canonicalize historical `ansible` routing columns in pools and
fulfillment records while preserving pool IDs, configuration, host membership,
lifecycle state, job identity and accepted operation envelopes. Runtime documents
and callers MUST use the canonical name; no historical-name alias is required.

#### Scenario: Existing VM state is upgraded

- **WHEN** migration encounters pools or fulfillment records with provider `ansible`
- **THEN** only their provider routing columns become `vm.ansible`
- **AND** configuration, members and accepted work retain their values, including on repeated migration
- **AND** bare-metal records are unchanged

#### Scenario: A canonical VM pool is administered

- **WHEN** an operator creates or edits a VM pool with provider `vm.ansible`
- **THEN** the VM adapter validates its configuration and handles fulfillment through that registration

### Requirement: A pool's provider is fixed at creation

A Resource Pool's provider MUST NOT change after creation. Replace, patch and
authoritative import MUST reject a differing provider before mutation, preserving
metadata and configuration. An otherwise-valid request naming a registered
differing provider MUST receive HTTP 400 with both providers named and the
second-pool member-migration path explained.

Provider configuration MUST remain editable within the declared provider.
`PoolUpdate.provider` MUST remain accepted; an equal value MUST act as omission
and MUST NOT by itself trigger a configuration write.

#### Scenario: Replace supplies a different registered provider

- **WHEN** an otherwise-valid replacement supplies a registered provider differing from the pool's own
- **THEN** the request is rejected with HTTP 400 before any mutation
- **AND** all metadata and existing provider configuration are unchanged
- **AND** the message names both providers and directs the operator to declare a second pool and migrate its members

#### Scenario: Patch supplies a different registered provider

- **WHEN** an otherwise-valid patch supplies a registered differing provider alongside other changes
- **THEN** the request is rejected with HTTP 400
- **AND** none of its metadata or configuration changes are applied

#### Scenario: Patch supplies only the same provider

- **WHEN** patch supplies only the pool's own provider
- **THEN** the pool remains unchanged
- **AND** the provider configuration handler performs no configuration write

#### Scenario: Configuration is edited within the provider

- **WHEN** replacement or patch supplies valid new configuration for the pool's own provider
- **THEN** configuration is updated under the existing replacement or patch semantics
- **AND** provider is unchanged and existing secret-retention rules still apply

#### Scenario: Inventory moves to a different provider

- **WHEN** an operator needs inventory delivered by a different provider
- **THEN** the supported path is a second pool declaring that provider and explicit member reassignment
- **AND** capacity-resource reassignment remains subject to the site-capacity requirement “A capacity resource does not move pools under live obligations” in `openspec/specs/site-capacity/spec.md`
- **AND** host reassignment continues through existing pool-change hooks

### Requirement: Shared validation of pool immutability

Provider and backing immutability MUST use shared stored-state validation across
individual writes and document administration. Request-only validation MUST
precede the stored-state comparison. Omitted patch fields MUST retain their
stored values for comparison. The allowance for supplying backing where none is
stored MUST remain unchanged.

#### Scenario: A patch omits immutable fields

- **WHEN** a valid patch changes only mutable metadata and omits provider and policy tags
- **THEN** the immutability comparison treats both as unchanged
- **AND** the metadata change succeeds without rewriting provider configuration

#### Scenario: A pool without stored backing is repaired

- **GIVEN** a stored pool whose tags lack backing
- **WHEN** an otherwise valid write supplies backing without changing provider
- **THEN** the existing backing repair allowance accepts the declaration

#### Scenario: Request-only document validation fails first

- **WHEN** a document fails request-only validation and also proposes an immutable-field change
- **THEN** validation reports its request-only problems without a stored-state comparison or diff
- **AND** no data is changed

### Requirement: Documents report immutable providers atomically

After a document passes request-only and provider-configuration validation,
validate-only MUST report a differing provider at `pools[<i>].provider` with code
`provider_immutable`, using the submitted index, and no diff. That stage MUST report
every immutable-field problem. Import MUST refuse the whole document before
application, retaining HTTP 400 with path-named detail text. A refused startup
import MUST leave its recorded digest unchanged.

#### Scenario: A document changes an existing provider

- **WHEN** an otherwise-valid document names a registered differing provider for an existing pool
- **THEN** validate-only returns `valid: false`, no diff and a `provider_immutable` problem at that entry's provider path
- **AND** validation writes no metadata or configuration
- **AND** import refuses with HTTP 400 and applies none of the document's changes

#### Scenario: Both immutable fields change

- **WHEN** an otherwise-valid document changes provider and an existing backing value
- **THEN** validate-only reports both `provider_immutable` and `capacity_backing_immutable` at their field paths
- **AND** import refuses without applying any entry or omitted-pool disablement

#### Scenario: A changed mounted document changes provider

- **WHEN** startup reconciles a changed document changing an existing pool's provider
- **THEN** startup fails with the offending entry named
- **AND** no entry or new digest is committed, so the next startup retries

#### Scenario: A new document entry declares its provider

- **WHEN** a valid document contains an ID absent from stored pools
- **THEN** the entry may create that pool with its declared registered provider
- **AND** the comparison does not treat creation as a provider change

### Requirement: Typed pool models validate policy hints

`PoolCreate`, `PoolReplace` and a `PoolUpdate` supplying tags MUST reject malformed
hold, SLA, listing-shape, asking-rate and pricing rate-list hints through shared
contracts-owned checks reused by raw document validation. Individual service
writes MUST rely on validated models rather than repeat those checks. Malformed
hints in individual HTTP bodies MUST receive HTTP 422 before mutation. Unknown
tags and structurally valid domain-owned values MUST keep existing acceptance.

#### Scenario: A typed caller constructs a malformed hint

- **WHEN** create, replace or tag-supplying patch construction supplies a hint rejected by its shared structural check
- **THEN** Pydantic construction fails before any request is sent

#### Scenario: A malformed hint reaches the server

- **WHEN** an individual API request body contains a malformed policy hint
- **THEN** the server rejects it with HTTP 422
- **AND** no metadata or provider configuration changes

#### Scenario: A document carries the same malformed hint

- **WHEN** a raw document entry carries a hint rejected by the shared structural check
- **THEN** validate-only reports its existing field-specific structured problem
- **AND** import retains HTTP 400 and changes nothing

#### Scenario: A hint is structurally valid but domain-specific

- **WHEN** a hint passes structural checks but names a family, field or period no reading domain supports
- **THEN** model validation accepts it
- **AND** the reading domain retains responsibility for its meaning

#### Scenario: A patch leaves policy tags alone

- **WHEN** patch construction omits policy tags
- **THEN** model validation does not require replacement tags
- **AND** the write retains stored tags

### Requirement: Provider validation remains service-owned

Handler registration, provider-specific configuration validation and semantics
requiring stored state MUST remain service-owned. Pool model hint validation
MUST NOT import service or provider implementations. Asking-rate structural
validation MUST be contracts-owned while its resolution behavior remains unchanged.

#### Scenario: Provider knowledge is needed

- **WHEN** a structurally valid typed request names an unregistered provider or invalid provider-owned configuration
- **THEN** the service refuses it through the existing boundary with HTTP 400
- **AND** the contracts model gains no dependency on provider implementations

#### Scenario: An asking rate is resolved

- **WHEN** the authority resolves a declared asking rate
- **THEN** it uses the contracts-owned structural entry check
- **AND** its domain checks, accepted publication periods and source precedence remain unchanged

### Requirement: Configuration handlers follow the non-destructive lifecycle

The pool configuration handler protocol MUST support validation, reads and
same-provider replacement without exposing a standalone configuration-deletion
operation. Disablement MUST retain configuration needed to resolve existing work.

#### Scenario: A handler implements pool configuration

- **WHEN** a provider implements the pool configuration protocol
- **THEN** no deletion operation is required or exposed by that protocol

#### Scenario: A pool is disabled

- **WHEN** an operator disables a pool
- **THEN** its provider configuration remains available for existing work

## Evidence

- Domain-neutral hint keys, typed deliverable-mode resolution and membership, advertisement and backing declaration shape, both cross-tag rules, and the strict resolver including absent-versus-malformed discrimination: `kit/resource-pools-contracts/tests/unit/test_hints.py`.
- Pool write models requiring `policy_tags` and refusing invalid declarations and every malformed domain-neutral hint on create, replace, and tag-supplying patch, while accepting omitted patch tags, unknown tags, and structurally valid domain-owned values: `kit/resource-pools-contracts/tests/unit/test_pool_models.py`.
- Pool persistence, registered requirement-delegate validation, strict import, dry-run, idempotency, lifecycle, provider refusal on replace, patch, and import with every pool field and configuration preserved and no handler write, the no-write equal-provider patch, indexed `provider_immutable` and `capacity_backing_immutable` document problems with atomic refusal, identical declaration validation across individual and bulk administration, backing immutability and repair, path-named import errors, and stored-declaration checks including the startup repair path: `kit/resource-pools/tests/integration/test_resource_pool_service.py`.
- The pure provider and backing comparison, including the backing repair allowance and exact messages: `kit/resource-pools/tests/unit/test_pool_immutability.py`.
- Composition accepting a configuration handler without a deletion operation and refusing one missing a remaining required hook: `provisioning/compute/tests/unit/test_composition.py`.
- Existing VM state upgraded to `vm.ansible` with configuration, membership, and accepted work preserved, bare-metal rows unchanged, and idempotent rerun: `provisioning/compute/service/tests/integration/test_vm_provider_identity_migration.py`.
- Existing-pool derivation, default-pool inclusion, idempotency, narrowing, drift rejection, and INFO evidence: `provisioning/compute/service/tests/unit/test_pool_offering_mode_migration.py`.
- Advertisement and backing migration on every existing pool, clobbering prior opaque values, unchanged admission, and malformed-delivery drift: `provisioning/compute/service/tests/integration/test_pool_advertisement_backing_migration.py`, `domains/api/authority/tests/integration/test_pool_declarations_migration.py`.
- Startup refusal of a seeded or stored pool without valid declarations, and the check's position after the pool document import: `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`, `domains/api/authority/tests/integration/test_pool_declarations_migration.py`.
- A changed-provider startup document failing with its entry named and state and digest unchanged, then retried and corrected; the fresh default created from the mounted bare-metal fixture or a VM document with no implicit VM pool on repeated migration; missing or invalid documents creating nothing; and interrupted first migration resumed with and without a document: `provisioning/compute/service/tests/integration/test_pool_declaration_startup.py`.
- Typed administrative API, default-pool invariant, canonical round trip, host assignment, an execution-less pool advertising through a configuration-free provider, server-side refusal of invalid declarations, HTTP 422 for malformed hints with stored state unchanged, and HTTP 400 provider refusal with the member-migration message, preserved state and export, and the no-write equal-provider patch: `provisioning/compute/service/tests/integration/test_pools_api.py`.
- Both declarations on every projected pool, each resolving through the shared resolver: `provisioning/compute/service/tests/integration/test_capacity_api.py`.
- Migration ordering, legacy host backfill, and schema-drift rejection: `provisioning/compute/service/tests/integration/test_database.py`.
- `listing_shapes` hint structure, including constraint mappings and a base shape stated twice with different constraints, validated identically on create, replace, patch, and bulk import: `kit/resource-pools-contracts/tests/unit/test_hints.py` (`TestListingShapesHint`) and `kit/resource-pools/tests/integration/test_resource_pool_service.py`; refused and projected verbatim by the provisioning service: `provisioning/compute/service/tests/integration/test_pools_api.py` and `test_capacity_api.py`.
- `asking_rates` structure, including the unit-token period and a stated null: `kit/resource-pools-contracts/tests/unit/test_asking_rates.py`; its validation identically on every pool-write surface: `kit/resource-pools/tests/integration/test_resource_pool_service.py`; resolution through the contracts-owned entry check with exact matching, override precedence, and unreadable input: `kit/resource-pools/tests/unit/test_asking_rates.py`.

## Scheduling membership and draining

Every resource eligible for physical settlement belongs to exactly one Resource Pool. Zero memberships makes the resource unschedulable; multiple memberships misrepresent system capacity and are invalid configuration.

Disabling a Resource Pool is a draining action. It blocks new Capacity Settlement Assignments to that pool but does not invalidate existing reservations, assignments, physical settlements, or active workloads, and those existing records do not prevent disablement.

## Relationship to fulfillment scheduling

Resource-pool management owns administrative routing metadata: pool identity, enabled state, policy tags, provider kind, provider-specific configuration, and host/resource membership. It does not own fulfillment-provider protocols or settlement-resource assignment.

The higher-layer [fulfillment capability](../fulfillment/spec.md) reads enabled pool and resource information when evaluating candidates. Disabling a pool prevents new scheduling assignments while preserving existing reservations, assignments, fulfillment records, and active workloads. `market_resource_pools` must not import `market_fulfillment`, including for type-only annotations.
