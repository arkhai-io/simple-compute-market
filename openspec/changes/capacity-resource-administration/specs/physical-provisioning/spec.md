## ADDED Requirements

### Requirement: Host inventory is connection identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST read declared capacity resources rather than host inventory
columns, and MUST NOT project a host that no capacity declaration correlates to.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a host record still holds a capacity value from before capacity
  declarations existed
- **THEN** capacity projection does not read it and the projected capacity comes from
  the declared capacity resource for that Physical Resource

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no capacity dimension reaches the projection from a host inventory record

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration correlates to a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

### Requirement: Legacy host capacity is derived into declarations

A compute provisioner MUST create a capacity declaration for a host inventory record
that carries a positive legacy GPU count and has no correlated declaration, at two
points only: when host inventory is applied from an INI document — whether seeded at
startup or submitted through the host import API — in the same transaction as the
host upsert, and once, by ordered migration, for host records present at upgrade.
Derivation MUST NOT run on a process start that applies no inventory, and MUST NOT
run when a host is created or updated through the individual host API.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.
Derivation MUST NOT overwrite or merge into an existing declaration, and an
operator-supplied declaration MUST win over any derivable legacy value.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner seeds host inventory carrying legacy GPU counts from an INI
  document and no capacity declarations exist
- **THEN** a declaration is derived for each such host in the same transaction as
  its host record
- **AND** published capacity is unchanged from before declarations existed

#### Scenario: Existing hosts at upgrade

- **WHEN** the ordered migration runs against a database holding hosts with legacy
  GPU counts and no correlated declarations
- **THEN** each such host receives a derived declaration before the service serves
  requests

#### Scenario: Operator declaration and legacy host value disagree

- **WHEN** a host carries a legacy capacity value and an operator has declared
  different capacity for the same Physical Resource
- **THEN** the operator's declaration is retained unchanged and no derivation occurs
  for that resource

#### Scenario: A declaration's resource id differs from its host

- **WHEN** a declaration whose resource id differs from a host's `host_id` names that
  host as its `host_id`
- **THEN** the host is treated as declared and no second declaration is derived for it

#### Scenario: A host is created through the individual host API

- **WHEN** an operator creates a host with a legacy GPU count through the individual
  host API
- **THEN** no declaration is derived, and the host's capacity is declared through the
  capacity administration surface

#### Scenario: A host has no GPUs

- **WHEN** host inventory is applied for a host whose legacy GPU count is zero
- **THEN** no declaration is derived for it

### Requirement: Capacity definitions are imported from a mounted document

A compute provisioner MUST reconcile a configured capacity-definitions document
before serving requests, under the same digest contract as resource-pool
definitions: the provisioner records the digest of the document it last reconciled
at startup and applies a document only when the current one differs. The digest MUST
be recorded in the same transaction as the apply. A process start MUST NOT be treated
as a submission: reapplying an unchanged document would revert capacity administration
performed through the API since the last import.

An operator-submitted import through the capacity-definitions import API MUST
reconcile regardless of the recorded digest and MUST NOT record a digest.

Every import MUST upsert the declarations the document names and MUST leave every
declaration the document does not name unchanged. A declaration naming a resource
pool that does not exist MUST fail the whole import, naming the pool, with nothing
applied. A configured document that cannot be read or applied MUST fail startup
rather than be skipped silently, and the startup import MUST run after resource-pool
definitions and host inventory seeding.

A document entry MUST state a declaration with the registration contract's own fields
and MUST replace the whole declaration it names, exactly as a registration request
does. The document MUST NOT accept the legacy scalar unit total, MUST require each
entry's resource type rather than defaulting it, and MUST reject unknown fields.
Document validation MUST report every problem it finds, each with its location,
rather than stopping at the first.

An import MUST compare each entry with the stored declaration before writing, and an
entry equal to the stored declaration MUST write nothing and emit no capacity event,
so reconciling an unchanged or reformatted document does not advance the capacity
version. A refusal only stored state can decide (an unknown pool, a host already
named by an unnamed declaration, a pool move under a live obligation) MUST come from
the same rules registration enforces. Every such refusal MUST be reported, and any
refusal MUST leave the whole import unapplied with no digest recorded. The import API
MUST offer a validate-only mode that reports the problems and the planned changes
without applying either.

#### Scenario: Capacity definitions change between restarts

- **WHEN** an operator edits the configured capacity-definitions document and
  restarts the provisioner
- **THEN** the edited declarations are applied, rather than being ignored because
  declarations already existed

#### Scenario: An unchanged document is present at restart

- **GIVEN** capacity has been administered through the API since the last import
- **WHEN** the provisioner restarts with the same capacity-definitions document
- **THEN** no reconciliation occurs and the API administration survives

#### Scenario: An operator explicitly imports an unchanged document

- **WHEN** an operator submits through the import API a document whose digest matches
  the recorded one
- **THEN** the document is reconciled anyway, because the operator has asked
- **AND** the recorded startup digest is unchanged

#### Scenario: A document stops naming a declaration

- **WHEN** a document is imported that omits a declaration an earlier document, the
  API, or derivation created
- **THEN** that declaration remains as it was, including its enabled state

#### Scenario: A declaration names an unknown pool

- **WHEN** a capacity-definitions document names a resource pool that does not exist
- **THEN** the import fails naming the pool, no declaration from the document is
  applied, and no digest is recorded

#### Scenario: A document is reapplied unchanged

- **WHEN** an import names declarations identical to the stored ones
- **THEN** no declaration is written and no capacity event is emitted
- **AND** the import reports them as unchanged

#### Scenario: An entry omits an optional field

- **WHEN** a document entry names an existing declaration but omits its host or
  attributes
- **THEN** the declaration is replaced as a registration request would replace it,
  and the omitted fields are cleared rather than retained

#### Scenario: A document has several problems

- **WHEN** a document carries an unknown field, a missing resource type, and two
  entries naming the same host
- **THEN** the import reports all three with their locations and applies nothing

#### Scenario: A later entry is refused by stored state

- **WHEN** an import's earlier entries are acceptable and a later entry would move a
  resource that holds a live obligation to another pool
- **THEN** the refusal is reported, no entry from the document is applied, and no
  digest is recorded

#### Scenario: An operator validates a document

- **WHEN** an operator submits a document to the import API in validate-only mode
- **THEN** the response reports the problems and the planned creations, updates, and
  unchanged entries
- **AND** nothing is applied

#### Scenario: Configured document is missing

- **WHEN** a capacity-definitions path is configured but no document exists there
- **THEN** startup fails rather than proceeding with stale or absent declarations

#### Scenario: No capacity definitions are configured

- **WHEN** no capacity-definitions path is configured
- **THEN** startup proceeds and declarations come only from derivation and the
  administration surface
