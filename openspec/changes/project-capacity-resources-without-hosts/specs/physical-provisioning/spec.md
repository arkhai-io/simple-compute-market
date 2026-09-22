## ADDED Requirements

### Requirement: Execution inventory comes only from the registered host record

The inventory an execution path hands to its executor SHALL be rendered from the
registered host record named by the selected settlement resource, and from no
other source. A host name with no registered host record SHALL fail the operation
before any playbook or executor command runs. A configured inventory file SHALL be
used only as a startup seed input that populates host records; no execution path
SHALL read it as an inventory, and no execution path SHALL target a host named only
by a request or a capacity declaration.

#### Scenario: Dispatch names an unregistered host

- **WHEN** fulfillment dispatch reaches an execution path for a host name with no
  registered host record
- **THEN** the operation fails before any playbook runs, and no fallback inventory
  is consulted

#### Scenario: A static inventory file names the host

- **GIVEN** a configured inventory file naming a host that has no registered host
  record
- **WHEN** an execution path runs for that host name
- **THEN** it fails exactly as it would with no inventory file present

#### Scenario: The inventory file seeds the host registry

- **WHEN** the provisioning service starts with a configured inventory file
- **THEN** the hosts it names are seeded into the host registry, and later
  execution renders from those records

### Requirement: The tenant-facing host address falls back to the connection address

The address a tenant receives for a host SHALL be that host record's configured
tenant-facing address when one is set, and otherwise the record's connection
address. It SHALL NOT be read from a configured inventory file.

#### Scenario: A host has no tenant-facing address

- **GIVEN** a registered host record with a connection address and no
  tenant-facing address
- **WHEN** a tenant's connection details are produced for that host
- **THEN** they carry the connection address

### Requirement: A bare-metal publication view is built from its capacity declaration

A capacity declaration's bare-metal publication view SHALL take its Physical
Resource identity, pool, host, physical host identity, capacity, and availability
from that declaration alone, and SHALL NOT read a host inventory record. A
declaration whose publication is enabled but which names no host SHALL be
projected without the view rather than failing the projection generation.

#### Scenario: An enabled publication names no host

- **GIVEN** a capacity declaration with an enabled bare-metal publication and no
  host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration is projected without the bare-metal view and every
  other entry in the generation is unaffected

#### Scenario: The named host is not registered

- **GIVEN** a capacity declaration with an enabled bare-metal publication naming
  a host that has no registered record
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced and carries the declaration's host

## MODIFIED Requirements

### Requirement: Host inventory is connection identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST NOT read host inventory records at all, and MUST NOT
project a host that no capacity declaration names. A host record is joined to a
capacity declaration only where its connection is used: at dispatch.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a host record still holds a capacity value from before capacity
  declarations existed
- **THEN** capacity projection does not read it and the projected capacity comes from
  the declared capacity resource for that Physical Resource

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no host inventory record contributes to the projection

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration names a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

### Requirement: Bare-metal inventory binds an existing provider pool

The compute provisioner MUST import configured Resource Pool definitions before
seeding inventory. A bare-metal inventory host MAY name its exact pool through
`pool_id`; the seed MUST reject an unknown pool and MUST preserve that binding
on create and update. A capacity declaration's explicit `bare_metal_publication`
view MUST carry the declaration's own pool. The `bare_metal.ansible` provider accepts no pool-local
playbook, inventory-group, credential, or executor-target configuration:
execution uses service-owned configuration and the scheduler-selected Physical
Resource. The operator MUST register that Physical Resource and its explicit
`bare_metal_publication` view through the authenticated capacity administration
surface before the host is publishable.

#### Scenario: Fresh selected-site inventory binds to a bare-metal pool

- **WHEN** startup imports a `bare_metal.ansible` pool and then seeds a host whose inventory row names that pool
- **THEN** the durable host row retains the exact pool id and unknown pool ids fail instead of falling back to `default`

#### Scenario: Publication retains the inventory pool binding

- **GIVEN** a bare-metal inventory host is bound to a configured provider pool
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
