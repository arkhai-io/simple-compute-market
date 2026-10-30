## MODIFIED Requirements

### Requirement: Host inventory is connection identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST NOT read host inventory records at all, and MUST NOT
project a host that no capacity declaration names. A host record is joined to a
capacity declaration only where its connection is used: at dispatch.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a database still holds host capacity values from before capacity declarations
  existed
- **THEN** capacity projection does not read them, the projected capacity comes from the
  declared capacity resource for that Physical Resource, and the ordered migrations drop the
  values

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no host inventory record contributes to the projection

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration names a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

### Requirement: Host writes declare no capacity

A compute provisioner MUST NOT create a capacity declaration from a host record on any host write: not when host inventory is applied from an INI document, whether seeded at startup or submitted through the host import API, and not when a host is created or updated through the individual host API. Capacity MUST be declared only through capacity registration, a capacity-definitions document, or capacity import. The ordered migration derived a declaration once for host records with a positive legacy GPU count present at upgrade.

A host MUST be treated as already declared when any declaration names it as its
`host_id`, which is also the only rule the capacity projection uses to correlate
declarations to hosts.

#### Scenario: Deployment configured only through host inventory

- **WHEN** a provisioner applies host inventory from an INI document, at startup or through
  the host import API, and no capacity declarations exist
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

- **WHEN** host inventory is applied for a machine without GPUs
- **THEN** no declaration is created for it, as for any host

#### Scenario: A declaration's resource id differs from its host

- **WHEN** a declaration whose resource id differs from a host's `host_id` names that
  host as its `host_id`
- **THEN** the host is treated as declared

#### Scenario: A host is created through the individual host API

- **WHEN** an operator creates a host through the individual host API
- **THEN** no declaration is created, and the host's capacity is declared through the
  capacity administration surface

## ADDED Requirements

### Requirement: A host record describes no hardware

A host record MUST NOT carry a GPU count, a GPU model, or any other description of the
machine's hardware: a Physical Resource's hardware is stated only by its capacity
declaration. The host API's create, update, and response models MUST NOT define such a field,
and a request carrying `gpu_count` or `gpu_model` MUST be accepted with those fields ignored,
as any field the models do not define is. The INI inventory format MUST NOT read `gpus=` or
`gpu_model=`; like any variable it does not read, they are ignored without a warning. The
provisioning service's ordered migrations MUST drop the host table's GPU columns after the
migration that derived declarations from them.

#### Scenario: A host is created with GPU fields

- **WHEN** an operator creates a host through the host API with a body carrying `gpu_count`
  and `gpu_model`
- **THEN** the host is created, and neither its stored record nor its response carries a GPU
  field

#### Scenario: An inventory line carries GPU variables

- **WHEN** host inventory is applied from an INI line carrying `gpus=8 gpu_model=H200`
- **THEN** the host is registered from its connection fields and its pool, and nothing is
  recorded or reported for the GPU variables

#### Scenario: An existing database is upgraded

- **WHEN** the ordered migrations run against a database whose hosts carry GPU counts and
  models
- **THEN** every host keeps its identity, connection, pool, and enabled state, and the host
  table has no GPU column
