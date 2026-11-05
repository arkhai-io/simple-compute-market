## MODIFIED Requirements

### Requirement: Host inventory is connection identity

Host inventory records MUST describe how to reach and dispatch work to a machine —
addressing, credentials, machine alias, pool membership, and enabled state — and
MUST NOT be the authoritative source of a Physical Resource's sellable capacity.
Capacity projection MUST NOT read host inventory records for capacity,
attributes, or connection identity, and MUST NOT project a host that no capacity
declaration names. A host record is joined to a capacity declaration only where
its connection is used: at dispatch. Site admission, settlement scheduling, and
capacity projection MUST learn of hosts only the identifiers of those taking new
delivery, as the compute composition reports them.

#### Scenario: Host record carries a legacy capacity column

- **WHEN** a database still holds host capacity values from before capacity declarations
  existed
- **THEN** capacity projection does not read them, the projected capacity comes from the
  declared capacity resource for that Physical Resource, and the ordered migrations drop the
  values

#### Scenario: Host inventory is inspected for capacity authority

- **WHEN** the projection path is traced from host inventory to published capacity
- **THEN** no host inventory record contributes capacity or attributes to the
  projection, and the projection reads of hosts only the identifiers of those
  taking new delivery

#### Scenario: A host has no capacity declaration

- **WHEN** no capacity declaration names a registered host
- **THEN** the projection contains no entry for that host
- **AND** no entry with empty or omitted capacity is published in its place

## ADDED Requirements

### Requirement: Disabling a host keeps new deliveries off it

Disabling a registered host MUST keep new deliveries off it: no capacity
declaration naming it, in a backed pool whose provider needs a host, MAY be
admitted against, placed on, or projected enabled while it is disabled. Work
already placed on it MUST be unaffected: an assignment made before the host was
disabled keeps the host, its create waits at dispatch until the host is enabled
again, and teardown and operator jobs run against the host. Enabling the host MUST
lift that restriction: its declarations are then offered as any other declaration
is, subject to their own `enabled`, their pool, fit, and availability. The host
authority MUST report the hosts taking new
delivery, as the identifiers of registered, enabled hosts, to the compute
composition, which supplies the report to the site authority, for admission and
its projections, and to settlement scheduling.

#### Scenario: A host is disabled

- **WHEN** an operator disables a host named by an enabled declaration in a backed
  pool whose provider needs a host
- **THEN** a new claim is neither admitted against nor placed on that declaration,
  and the declaration is projected not enabled

#### Scenario: A disabled host already holds an assignment

- **GIVEN** an assignment placed on a host before it was disabled
- **WHEN** the assignment's create is dispatched while the host is disabled
- **THEN** the create is refused and retried, and is submitted once the host is
  enabled again

#### Scenario: A disabled host is enabled again

- **GIVEN** an enabled declaration, in an enabled backed pool whose provider needs
  a host, naming a disabled host
- **WHEN** an operator enables the host
- **THEN** the declaration is again admitted against, placed on, and projected
  enabled as any other eligible declaration is

#### Scenario: A declaration is itself disabled when its host is enabled again

- **GIVEN** a disabled declaration naming a disabled host
- **WHEN** an operator enables the host
- **THEN** the declaration is still neither admitted against, placed on, nor
  projected enabled
