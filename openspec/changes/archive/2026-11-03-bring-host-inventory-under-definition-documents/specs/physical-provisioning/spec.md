## ADDED Requirements

### Requirement: Host definitions are imported from a mounted document

The provisioning service MAY be configured with a host definitions document through `host_definitions_path`. At startup it MUST reconcile that document under the definition-document digest contract, with the document kind `hosts`: it applies the document only when it differs from the one last reconciled, and records the digest in the same transaction as the apply. An import through the host-definitions import API MUST reconcile regardless of the recorded digest and MUST NOT record one.

The startup import MUST run after resource-pool definitions, the fresh-site pool seed, and the stored-pool declaration check, and before capacity definitions. A configured document that is missing or cannot be applied MUST fail startup and record no digest.

#### Scenario: An operator adds a host to the document and restarts

- **WHEN** an operator adds an entry to the configured host definitions document and restarts the provisioner
- **THEN** the host is registered as the entry states, and work can be dispatched to it

#### Scenario: An unchanged document is present at restart

- **GIVEN** a host has been changed through the API since the last reconciliation
- **WHEN** the provisioner restarts with the same host definitions document
- **THEN** no reconciliation occurs and the API change survives

#### Scenario: An operator explicitly imports an unchanged document

- **WHEN** an operator submits through the import API a document whose digest matches the recorded one
- **THEN** the document is reconciled anyway
- **AND** the recorded startup digest is unchanged

#### Scenario: The document names a pool the pool document creates

- **WHEN** a fresh site starts with a pool document and a host document whose entry names one of its pools
- **THEN** the pool exists when the host is applied, and the host is registered in it

#### Scenario: Configured document is missing

- **WHEN** a host definitions path is configured but no document exists there
- **THEN** startup fails

#### Scenario: No host definitions are configured

- **WHEN** no host definitions path is configured
- **THEN** startup proceeds and leaves the registered hosts as they are

### Requirement: A host definitions entry declares the whole host

A host definitions document MUST hold a top-level `hosts` list whose entries use the host registration contract's field names: `host_id`, an optional `pool_id`, an optional `enabled`, and a `connection` of `kind`, a required `version`, and `public`. An explicit `null` `pool_id` MUST be read as an omitted one; an explicit `null` `enabled` is a value of the wrong type. An empty `hosts` list is a valid document that applies nothing. Applying an entry MUST register the host it names or replace that host's whole non-secret state: an omitted `pool_id` unplaces the host, an omitted `enabled` enables it, and the connection is replaced through its kind's codec, which keeps a stored protected key when the entry names no key path. An entry naming no key path for a host whose key is a key file MUST be refused naming the entry. A change of pool MUST go through the host pool-change hooks.

Each entry MUST be built through its kind's codec with the stored connection as the previous one, and the result compared with the stored host on connection kind, version, canonical public fields, and protected-value schemes, and on pool and enabled state. An entry equal to the stored host MUST write nothing, run no hook, and leave the host's update time unchanged.

#### Scenario: An entry omits the pool of a placed host

- **WHEN** a reconciled entry names a host placed in a pool and states no `pool_id`
- **THEN** the host is unplaced, through the pool-change hooks

#### Scenario: An entry omits `enabled` for a disabled host

- **WHEN** a reconciled entry names a host disabled through the API and states no `enabled`
- **THEN** the host is enabled

#### Scenario: An entry equals the stored host

- **WHEN** a document is reconciled whose entry states exactly the stored host's pool, enabled state, and connection
- **THEN** nothing is written for that host, no hook runs, and the host is reported unchanged

#### Scenario: An entry omits a field its codec defaults

- **GIVEN** a host stored with an `ssh` connection whose port is 22 and whose user is `root`
- **WHEN** a document is reconciled whose entry for that host states its pool, enabled state, and connection but omits `ssh_port` and `ssh_user`
- **THEN** the host is reported unchanged, nothing is written for it, and no hook runs

#### Scenario: An entry names no key for a host holding a key file

- **WHEN** a reconciled entry names a host whose key is a key file and its connection names no `key_path`
- **THEN** the document is refused naming that entry, and nothing from it is applied

#### Scenario: A document lists no hosts

- **WHEN** a document whose `hosts` list is empty is reconciled
- **THEN** nothing is written, and every registered host is reported as registered and not named

#### Scenario: An entry names no key for a host holding a protected key

- **WHEN** a reconciled entry names a host that holds a protected private key and its connection names no `key_path`
- **THEN** the host keeps its protected key unchanged

#### Scenario: An entry names no key for a new host

- **WHEN** a document entry names an unregistered host whose connection names no `key_path`
- **THEN** the document is refused naming that entry, and nothing from it is applied

### Requirement: A host definitions document retains the hosts it does not name

A reconciliation MUST leave every registered host the document does not name unchanged, its enabled state included, and MUST report those hosts: in the startup log, and in the import API's response. Hosts are never deleted.

#### Scenario: A document stops naming a host

- **WHEN** a document is reconciled that omits a host an earlier document or the API registered
- **THEN** that host remains as it was, enabled or not
- **AND** the reconciliation reports it as registered and not named

### Requirement: A host definitions document is validated whole and carries no credential

Host definitions validation MUST be strict and MUST run in two stages. It MUST report every structural problem with its location — unparseable YAML, a root that is not a mapping (an empty document included), a missing or non-list `hosts`, an unknown field, a missing `host_id`, `connection`, or connection `version`, a `host_id` named twice, or a value of the wrong type — and MUST NOT check a document with any structural problem against stored state. For a structurally valid document it MUST report every refusal stored state decides: a pool that does not exist, a connection its kind's codec refuses — a quoted number among its public fields included, since the codec types them strictly — and a pool move a pool-change hook refuses. The apply MUST continue past a refusal so that every refusal is reported. Any problem MUST leave the whole document unapplied with no digest recorded.

A host definitions document MUST NOT carry a credential: an entry stating connection secrets is a structural problem. A key is named by its file path.

The import API MUST answer with one response: whether it applied, the created, updated, and unchanged hosts, the registered hosts the document does not name, and every problem, each with its location and a code; a hook's refusal is coded `pool_change_refused`. An applying import with any problem MUST answer 422 with that response and apply nothing. An applying import whose commit meets a host another request registered after the document was evaluated MUST answer 409 and apply nothing, as a duplicate registration through the host API does. The import API MUST offer a validate-only mode that answers 200 with the problems and the planned creations, updates, and unchanged hosts, applying nothing.

#### Scenario: A document has several structural problems

- **WHEN** a document carries an unknown field, an entry with no connection, and two entries naming the same host
- **THEN** all three are reported with their locations and nothing is applied

#### Scenario: A document has no hosts list

- **WHEN** a document is empty, or has no `hosts` key
- **THEN** it is refused as structurally invalid, and nothing is applied

#### Scenario: A document has structural and stored-state problems

- **WHEN** a document has an unknown field in one entry and names an unknown pool in another
- **THEN** the unknown field is reported and the unknown pool is not
- **AND** nothing is applied

#### Scenario: A pool-change hook refuses a move at startup

- **WHEN** a changed document moves a host whose VM tunnels a buyer holds to a pool dialling another relay
- **THEN** startup fails naming the host, no entry from the document is applied, and no digest is recorded

#### Scenario: A pool-change hook refuses a move on import

- **WHEN** an operator imports a document whose entry makes a move a hook refuses
- **THEN** the import answers 422 with the refusal among its problems, coded `pool_change_refused`, and no host the document names is created or changed

#### Scenario: A document has a hook refusal and another stored-state problem

- **WHEN** an operator imports a document one of whose entries names an unknown pool while another makes a move a hook refuses
- **THEN** the import answers 422 reporting both problems, and nothing is applied

#### Scenario: An entry quotes its SSH port

- **WHEN** an operator imports a document one of whose entries states `ssh_port: "2222"` beside a valid entry
- **THEN** the import answers 422 reporting a connection the codec refuses at that entry's connection, and neither entry is applied

#### Scenario: An entry carries key material

- **WHEN** a document entry states `connection.secrets`
- **THEN** the document is refused naming that entry's location, and nothing is applied

#### Scenario: An operator validates a document

- **WHEN** an operator submits a document to the import API in validate-only mode
- **THEN** the import answers 200, and the response reports the problems and the planned creations, updates, and unchanged hosts
- **AND** nothing is applied

#### Scenario: Another request registers a named host during an import

- **WHEN** an applying import would create a host, and another request registers that host before the import commits
- **THEN** the import answers 409 and applies nothing

### Requirement: The host registry exports a canonical host definitions document

The host routes MUST offer an export at `GET /api/v1/hosts/definitions/export`, admitting the administrator, that returns every registered host as a host definitions document in a YAML body without any secret: a host holding a protected key appears with no key path. Its entries MUST be ordered by `host_id`, and each MUST state its host's pool and enabled state, so the export reads the same for the same registry and an entry never relies on the defaults an omitted pool or enabled state takes. A host whose connection kind no composed codec serves, or whose stored connection is at a version its kind's codec does not serve, MUST NOT be stated as an entry. Importing an unedited export MUST change nothing.

#### Scenario: An operator exports the registry and imports it unedited

- **WHEN** an operator exports the host registry and imports the result without editing it
- **THEN** every host is reported unchanged, and nothing is written

#### Scenario: A host holds a protected key

- **WHEN** the registry holds a host registered with embedded key material
- **THEN** its exported entry carries no key path and no secret, and importing it keeps the protected key

#### Scenario: A host is stored at an unserved connection version

- **WHEN** the registry holds a host stored at `ssh` version 1
- **THEN** the export emits no entry for that host
- **AND** importing that export leaves the host unchanged and reports it as registered and not named

#### Scenario: A host's connection kind is not served

- **WHEN** the registry holds a host whose connection kind no composed codec serves
- **THEN** the export emits no entry for that host, and states every other host

### Requirement: Startup reads no INI inventory

The provisioning service MUST NOT read an INI inventory at startup. `inventory_ini` and `inventory_path` are retired settings: a configuration stating either in any layer MUST refuse startup, naming `host_definitions_path`, whatever value it states, an empty one included. No packaged configuration states either. The INI inventory format MUST remain only the input of the Ansible implementation's host import route.

#### Scenario: A configuration states a retired inventory setting

- **WHEN** the provisioning service starts with a configuration stating `inventory_ini` or `inventory_path`
- **THEN** it refuses to start, naming the setting and `host_definitions_path`

#### Scenario: A configuration states an empty `inventory_ini`

- **WHEN** the provisioning service starts with a profile stating `inventory_ini: ""`
- **THEN** it refuses to start, naming `inventory_ini` and `host_definitions_path`

#### Scenario: The packaged configuration is started unchanged

- **WHEN** the provisioning service starts with its packaged settings and any packaged profile, and no operator configuration
- **THEN** no retired inventory setting is refused

#### Scenario: An operator imports an INI inventory

- **WHEN** an operator submits an INI inventory to `POST /api/v1/hosts/import`
- **THEN** the Ansible implementation's route applies it as before, and no startup digest is read or recorded

## MODIFIED Requirements

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
importing host definitions. A bare-metal host MAY name its exact pool through
`pool_id`; the host import MUST reject an unknown pool and MUST preserve that binding
on create and update. A capacity declaration's explicit `bare_metal_publication`
view MUST carry the declaration's own pool. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration:
execution uses service-owned configuration and the scheduler-selected Physical
Resource, and a bare-metal job's stored parameters carry the service's
`bare_metal_playbook_path` as configured when the job is prepared. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then a host definitions document whose entry names that pool
- **THEN** the durable host row retains the exact pool id, and an unknown pool id fails the import and startup rather than leaving the host unplaced or assigning another pool

#### Scenario: Publication retains the inventory pool binding

- **GIVEN** a bare-metal host is bound to a configured provider pool
- **AND** the capacity declaration naming that host is in the same pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is that pool, taken from the declaration

#### Scenario: Publication carries the declaration's pool

- **GIVEN** a capacity declaration with an enabled `bare_metal_publication` in a configured provider pool
- **WHEN** the compute service projects its explicit `bare_metal_publication` view
- **THEN** the view's `pool_id` is the declaration's pool

#### Scenario: Pool-local executor configuration is supplied

- **WHEN** a `bare_metal.ansible` pool contains a non-empty `provider_config`
- **THEN** validation rejects the pool before it can authorize or dispatch fulfillment

#### Scenario: The bare-metal playbook setting changes after a grant is prepared

- **WHEN** `bare_metal_playbook_path` changes after a grant or reclaim job is prepared
- **THEN** the job runs the playbook its stored parameters carry, and a job prepared afterwards carries the new one

### Requirement: Execution inventory comes only from the registered host record

The inventory an execution path hands to its executor SHALL be rendered from the
registered host record named by the selected settlement resource, and from no
other source. A host name with no registered host record SHALL fail the operation
before any playbook or executor command runs. A host definitions document SHALL
only populate host records; no execution path SHALL read a document or a file as an
inventory, and no execution path SHALL target a host named only by a request, a
capacity declaration, or a document entry that was not applied.

#### Scenario: Dispatch names an unregistered host

- **WHEN** fulfillment dispatch reaches an execution path for a host name with no
  registered host record
- **THEN** the operation fails before any playbook runs, and no fallback inventory
  is consulted

#### Scenario: A static inventory file names the host

- **GIVEN** a file, or a host definitions document that was refused, naming a host
  that has no registered host record
- **WHEN** an execution path runs for that host name
- **THEN** it fails exactly as it would with no such file or document present

#### Scenario: The inventory file seeds the host registry

- **WHEN** the provisioning service starts with a changed host definitions document
- **THEN** the hosts it names are registered, and later execution renders from
  those records

### Requirement: Host writes declare no capacity

A compute provisioner MUST NOT create a capacity declaration from a host record on any host write: not when a host definitions document is applied, at startup or through its import API, not when an INI inventory is submitted through the host import API, and not when a host is created or updated through the individual host API. Capacity MUST be declared only through capacity registration, a capacity-definitions document, or capacity import. The ordered migration derived a declaration once for host records with a positive legacy GPU count present at upgrade.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner applies a host definitions document, at startup or through its
  import API, or an INI inventory through the host import API, and no capacity
  declarations exist
- **THEN** the hosts are registered, no capacity declaration is created for them, and
  the capacity projection contains no entry for them

#### Scenario: Existing hosts at upgrade

- **WHEN** the ordered migration runs against a database holding hosts with legacy
  GPU counts and no correlated declarations
- **THEN** each such host receives a derived declaration before the service serves
  requests

#### Scenario: Operator declaration and legacy host value disagree

- **WHEN** a host held a legacy GPU count and an operator has declared different capacity
  for the same Physical Resource
- **THEN** the operator's declaration is retained unchanged, and dropping the host's GPU
  columns does not affect it

#### Scenario: A host has no GPUs

- **WHEN** a host is registered for a machine without GPUs
- **THEN** no declaration is created for it, as for any host

#### Scenario: A declaration's resource id differs from its host

- **WHEN** a declaration whose resource id differs from a host's `host_id` names that
  host as its `host_id`
- **THEN** the host is treated as declared

#### Scenario: A host is created through the individual host API

- **WHEN** an operator creates a host through the individual host API
- **THEN** no declaration is created, and the host's capacity is declared through the
  capacity administration surface

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
definitions and host definitions.

A document entry MUST state a declaration with the registration contract's own fields
and MUST replace the whole declaration it names, exactly as a registration request
does. The document MUST NOT accept the legacy scalar unit total, MUST require each
entry's resource type rather than defaulting it, and MUST reject unknown fields.
Document validation MUST be strict: a value of the wrong type, such as a quoted
number, MUST be reported as a structural problem rather than coerced.
Document validation MUST report every structural problem it finds, each with its
location, rather than stopping at the first. A document with any structural problem
MUST NOT be evaluated against stored state.

An import MUST compare each entry with the stored declaration before writing, and an
entry equal to the stored declaration MUST write nothing and emit no capacity event,
so reconciling an unchanged or reformatted document does not advance the capacity
version. A refusal only stored state can decide (an unknown pool, a host already
named by an unnamed declaration, a pool move under a live obligation) MUST come from
the same rules registration enforces. For a structurally valid document every such
refusal MUST be reported, and any
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

#### Scenario: An entry quotes a quantity

- **WHEN** a document entry states a capacity quantity as a quoted number, such as
  `gpu_count: "8"`
- **THEN** the import reports a structural problem at that quantity's location
  and applies nothing

#### Scenario: A document has structural and stored-state problems

- **WHEN** a document has an unknown field in one entry and names an unknown pool in
  another
- **THEN** the unknown field is reported and the unknown pool is not, because stored
  state is not consulted for a structurally invalid document
- **AND** nothing is applied

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

### Requirement: Host connections are typed by their implementation's codec

A host's connection MUST be held as a connection envelope (a kind, a version, public
fields, and protected values) whose kind names the codec of the implementation
distribution that supports it. Compute provisioning MUST NOT define per-kind connection
fields; it validates an envelope through its codec. An executor MUST receive an immutable
execution-host value, not the persistence record, and MUST refuse a connection kind it
does not support.

A codec MUST validate the public fields it defines strictly, for every submission alike
— the host API, an INI import, and a host definitions document: a value of the wrong
type, such as a quoted number, MUST be refused rather than coerced.

A deployment MUST register one codec per kind, and each codec serves one version;
composition MUST refuse two codecs for one kind. A connection MUST be built by the codec
of its own kind, at the version that codec serves. A connection at a kind no codec
serves, or at another version than its kind's codec serves, MUST be refused naming the
kinds or the version that is served. A reader of a stored connection MUST check its kind
and version before reading its fields, and MUST refuse a version it does not serve
rather than read it as another, so a host stored at a version no longer served runs no
work until it is submitted again at the served version. Such a submission MUST carry
forward a protected value it still needs and does not resubmit, whatever the previous
connection's version, as opaque material it neither reads nor decrypts. A stored connection MUST NOT
be rewritten to another version except by a submission that states that version, and
nothing upgrades a stored connection on its own.

#### Scenario: A compute domain needs another connection kind

- **WHEN** a domain's executor reaches its targets by a means other than SSH
- **THEN** an implementation distribution adds a codec for that kind, and neither the host
  authority's model nor the executor contract changes

#### Scenario: A connection quotes a number

- **WHEN** a host is submitted through the host API with an `ssh` connection whose
  `ssh_port` is the string `"2222"`
- **THEN** the submission is refused naming the field, and nothing is stored

#### Scenario: A connection states a version no codec serves

- **WHEN** a host is submitted with an `ssh` connection at a version other than the one the
  registered `ssh` codec serves
- **THEN** the submission is refused naming the version served, and nothing is stored

#### Scenario: A stored connection is at an unsupported version

- **WHEN** an execution path reads a stored connection whose version its codec does not
  serve, such as a host stored at `ssh` version 1
- **THEN** it refuses the connection before any playbook runs, rather than reading it
  under another version's fields

#### Scenario: A host stored at version 1 is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 whose key is protected, with no key file,
  is updated with a version-2 connection that restates its public fields and submits
  no key
- **THEN** the host is stored at version 2, its protected key is kept unchanged, and work
  runs against it again

#### Scenario: A host stored at version 1 with a key file is submitted again at version 2

- **WHEN** a host stored at `ssh` version 1 whose key is a file is updated with a
  version-2 connection restating its public fields, `key_path` included
- **THEN** the host is stored at version 2 with the same key file; an update omitting
  `key_path` names no key and is refused

#### Scenario: A host stored at version 1 is imported again

- **WHEN** an inventory naming a host stored at `ssh` version 1 is imported
- **THEN** the host is stored at version 2 with the connection and key its entry names
