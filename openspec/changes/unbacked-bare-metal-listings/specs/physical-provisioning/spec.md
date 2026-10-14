## MODIFIED Requirements

### Requirement: A bare-metal publication view is built from its capacity declaration

A capacity declaration's bare-metal publication view SHALL take its Physical
Resource identity, pool, host, physical host identity, capacity, and availability
from that declaration alone, and SHALL NOT read a host inventory record. Its host
identity, physical host identity, access methods, and availability are delivery
terms, and the view SHALL carry them only as the declaring pool's backing delegate
passes them: a capacity-backed pool's view carries all of them, an unbacked pool's
view carries none. The view builder SHALL hold no branch on backing of its own.

A declaration in a capacity-backed pool whose publication is enabled but which names
no host SHALL be projected without the view rather than failing the projection
generation. A declaration in an unbacked pool whose publication is enabled SHALL be
projected with the view whether or not it names a host.

#### Scenario: An enabled publication names no host

- **GIVEN** a capacity declaration in a capacity-backed pool with an enabled
  bare-metal publication and no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration is projected without the bare-metal view and every
  other entry in the generation is unaffected

#### Scenario: The named host is not registered

- **GIVEN** a capacity declaration in a capacity-backed pool with an enabled
  bare-metal publication naming a host that has no registered record
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced and carries the declaration's host

#### Scenario: An unbacked declaration names no host

- **GIVEN** a capacity declaration in an unbacked pool with an enabled bare-metal
  publication and no host
- **WHEN** the resource-pool projection is produced
- **THEN** the view is produced carrying the resource's identity, pool, shape,
  capabilities, and region, and no host identity, access methods, or availability

#### Scenario: An unbacked declaration names a host

- **GIVEN** a capacity declaration in an unbacked pool with an enabled bare-metal
  publication naming a host and access methods
- **WHEN** the resource-pool projection is produced
- **THEN** the view carries neither the host identity nor the access methods

### Requirement: Domains contribute their inventory views

A domain view in the site's resource-pool projection, whether attached to a projected
resource or to a pool, MUST be produced by a projection the domain's adapter contributes.
The provisioning service MUST NOT name a domain's view, its source attributes, or its
provider configuration. Each projection MUST declare the view identifiers it produces and
the declaration attributes it consumes, a consumed attribute MUST NOT appear in the neutral
projected attributes, and composition MUST refuse a view identifier or consumed attribute
declared by two projections.

A projection producing a resource view MUST receive the context of the resource's pool —
its provider and its resolved declarations, the backing delegate among them — alongside
the resource's declaration. The provisioning service MUST resolve that context from the
pool records it already reads for the projection, and MUST NOT interpret it.

#### Scenario: A third domain contributes a view

- **WHEN** a domain contributes a projection producing a resource view under its own
  identifier
- **THEN** projected resources carry that view without any change to the provisioning
  service

#### Scenario: Two projections claim one view

- **WHEN** two contributed projections declare the same view identifier
- **THEN** composition refuses to start

#### Scenario: A resource view depends on its pool's backing

- **WHEN** a contributed projection builds a resource view for a resource whose pool
  declares itself unbacked
- **THEN** the projection receives that pool's backing delegate and the provisioning
  service makes no decision on backing itself
