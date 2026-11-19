## MODIFIED Requirements

### Requirement: Host registry records the connection port

The host registry MUST record the SSH port the provisioner connects to for each host, defaulting to 22. The registry is the authority for how a host is reached — address, user, key material, and port — and every execution path MUST derive its connection from a rendered inventory rather than constructing one, so that a host reached through a reverse tunnel, a NAT forward, or a bastion is reachable by every operation without any of them being changed individually.

Rendered inventories MUST emit `ansible_port` for every host, including hosts on the default port, so that a rendered inventory states what the registry holds rather than leaving the default implied by an absent line.

An `ansible_port` supplied through the INI input format MUST be preserved rather than discarded. A value that is not a port number between 1 and 65535 MUST cause its entry to be rejected rather than replaced with a default, because a substituted port produces an unreachable host whose failure resembles a network fault rather than a bad inventory line.

The registry MAY also record a tenant-facing port, `public_port`, for a host. The port belongs to version 2 of the `ssh` connection, which is version 1 with that one optional field, and version 2 is the only version of the kind the registry serves: every `ssh` connection is submitted and stored at version 2, whether it states a tenant-facing port, states none, or states it as null. A connection submission MUST state its version; the host contract carries no default. A rendered inventory MUST emit `public_port` for a host whose record states one, and MUST NOT emit it for a host whose record states none. A host whose record states no tenant-facing port MUST be stored with no `public_port` field, not even a null one. A `public_port` supplied through the INI input format MUST be preserved, and a value that is not a port number between 1 and 65535 MUST cause its entry to be rejected, as for `ansible_port`. A connection built from the INI format or the typed connection factory MUST be submitted at version 2.

#### Scenario: A host is registered on a tunnel port

- **WHEN** a host is registered with an SSH port other than 22
- **THEN** the recorded port is returned by the host endpoints and appears as `ansible_port` in every rendered inventory for that host

#### Scenario: A host is registered without a port

- **WHEN** a host is registered with no SSH port supplied
- **THEN** the registry records port 22 and rendered inventories state it explicitly

#### Scenario: An inventory file supplies a port

- **WHEN** an INI inventory carrying `ansible_port` is imported
- **THEN** the port is stored against the host and survives to the rendered inventory the provisioner connects with

#### Scenario: An inventory file supplies a malformed port

- **WHEN** an INI inventory entry carries an `ansible_port` that is not a port number between 1 and 65535
- **THEN** that entry is rejected with a warning naming the host, other entries in the same file are still imported, and no host is registered with a substituted port

#### Scenario: An inventory file supplies a tenant-facing port

- **WHEN** an INI inventory entry carrying `public_port` is imported
- **THEN** the port is stored against the host and appears as `public_port` in the rendered inventory for that host

#### Scenario: An inventory file supplies a malformed tenant-facing port

- **WHEN** an INI inventory entry carries a `public_port` that is not a port number between 1 and 65535
- **THEN** that entry is rejected with a warning naming the host, other entries in the same file are still imported, and no host is registered with a substituted or missing tenant-facing port

#### Scenario: A host is registered with no tenant-facing port

- **WHEN** a host is registered or imported with an `ssh` connection that states no tenant-facing port
- **THEN** it is stored at version 2 with no `public_port` field, and its rendered inventory carries the connection's own address and port

#### Scenario: A version-1 or unversioned connection is submitted

- **WHEN** a host is submitted with an `ssh` connection at version 1, or stating no version
- **THEN** a version-1 submission is refused naming version 2, the version served; an
  unversioned submission is refused as missing its required `version`; and nothing is
  stored

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
connection's version, as opaque material it neither reads nor decrypts. A stored
connection MUST NOT be rewritten to another version except by a submission that states
that version or by a recorded migration whose mapping from the stored version is exact;
no reader upgrades a stored connection. The provisioning migration chain MUST rewrite
every host's `ssh` connection stored at version 1 to version 2 with the same public
fields and protected values; a job holds no copy of a connection, reading its host's
when it is dispatched.

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
  serve
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

#### Scenario: A provisioning database holding version-1 connections is migrated

- **WHEN** the provisioning migration command runs against a database with hosts stored
  at `ssh` version 1 and a queued create job and a queued teardown job naming those hosts
- **THEN** the hosts are stored at `ssh` version 2 with the same public fields and
  protected values, the jobs are unchanged, and the create and the teardown run against
  version-2 connections when they are dispatched

#### Scenario: A version-1 connection's fields are not valid at version 2

- **WHEN** the provisioning migration finds a host's stored `ssh` version 1 connection
  whose public fields the version-2 codec refuses
- **THEN** the migration fails naming the host, and nothing is rewritten

## ADDED Requirements

### Requirement: Host inventory is connection identity, not capacity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST NOT read host inventory records for capacity,
attributes, or connection identity, and MUST NOT project a host that no capacity
declaration names. A host record is joined to a capacity declaration only where
its connection is used: at dispatch. Site admission, settlement scheduling, and
capacity projection MUST learn of hosts only the identifiers of those taking new
delivery, as the compute composition reports them.

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no host inventory record contributes capacity or attributes to the
  projection, and the projection reads of hosts only the identifiers of those
  taking new delivery

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration names a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

### Requirement: Host writes create no capacity declaration

A compute provisioner MUST NOT create a capacity declaration from a host record on any host write: not when a host definitions document is applied, at startup or through its import API, not when an INI inventory is submitted through the host import API, and not when a host is created or updated through the individual host API. Capacity MUST be declared only through capacity registration, a capacity-definitions document, or capacity import.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner applies a host definitions document, at startup or through its
  import API, or an INI inventory through the host import API, and no capacity
  declarations exist
- **THEN** the hosts are registered, no capacity declaration is created for them, and
  the capacity projection contains no entry for them

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

### Requirement: A host record carries no hardware description

A host record MUST NOT carry a GPU count, a GPU model, or any other description of the
machine's hardware: a Physical Resource's hardware is stated only by its capacity
declaration. The host API's create, update, and response models MUST NOT define such a field,
and a request carrying `gpu_count` or `gpu_model` MUST be accepted with those fields ignored,
as any field the models do not define is. The INI inventory format MUST NOT read `gpus=` or
`gpu_model=`; like any variable it does not read, they are ignored without a warning.

#### Scenario: A host is created with GPU fields

- **WHEN** an operator creates a host through the host API with a body carrying `gpu_count`
  and `gpu_model`
- **THEN** the host is created, and neither its stored record nor its response carries a GPU
  field

#### Scenario: An inventory line carries GPU variables

- **WHEN** host inventory is applied from an INI line carrying `gpus=8 gpu_model=H200`
- **THEN** the host is registered from its connection fields and its pool, and nothing is
  recorded or reported for the GPU variables

## REMOVED Requirements

### Requirement: Existing host identities migrate without loss

**Reason**: The migration it governs (`20260921_001_host_identity`) is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so no supported database reaches it and its body is deleted with the pre-floor history.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database.

### Requirement: Active fulfillment migration

**Reason**: The migrations that placed existing hosts in a resource pool and backfilled fulfillment records for active VM reservations (among them `20260713_002_resource_pools_and_hosts_pool_id` and `20260724_001_legacy_vm_leases_to_fulfillment`) are part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run them, and the chain refuses any older database as unsupported, so their bodies are deleted with the pre-floor history.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database.

### Requirement: A bare-metal storefront refuses state written under a retired listing kind

**Reason**: The refusal it governs (`bare-metal-storefront-0009-refuse-retired-listing-kind`) is part of the bare-metal storefront's v0.3.0 floor: every database its migration command adopts has already passed it, so none holds state written under the retired listing kind, and the command refuses any older database as unsupported, directing the operator to a fresh database. The refusal is deleted with the storefront's pre-floor chain; a fresh database's schema is governed by `deployment-state`'s "A chain begins at its supported baseline".

**Migration**: An operator holding a bare-metal storefront database from before the marketplace v0.3.0 release starts the storefront from a fresh database.

### Requirement: Host inventory is connection identity

**Reason**: Its scenario "Host record carries a legacy capacity column" governs the migration that dropped the host table's capacity columns (`20261028_002_hosts_drop_gpu_columns`), which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its normative text is kept unchanged as "Host inventory is connection identity, not capacity", with every other scenario, since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: Host writes declare no capacity

**Reason**: Its sentence on the declaration derived once at upgrade, and its scenarios "Existing hosts at upgrade" and "Operator declaration and legacy host value disagree", govern the migrations `20260921_004_legacy_host_capacity_declarations` and `20261028_002_hosts_drop_gpu_columns`, which are part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run them, and the chain refuses any older database as unsupported, so their bodies are deleted with the pre-floor history. Its remaining rule is kept unchanged as "Host writes create no capacity declaration", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.

### Requirement: A host record describes no hardware

**Reason**: Its rule that the ordered migrations drop the host table's GPU columns, and its scenario "An existing database is upgraded", govern the migration `20261028_002_hosts_drop_gpu_columns`, which is part of compute provisioning's v0.3.0 floor: every database the chain adopts has already run it, and the chain refuses any older database as unsupported, so its body is deleted with the pre-floor history. Its remaining rule is kept unchanged as "A host record carries no hardware description", since a MODIFIED requirement cannot drop a scenario.

**Migration**: An operator holding a provisioning database from before the marketplace v0.3.0 release starts the service from a fresh database; the rule is unchanged under the new requirement's name.
