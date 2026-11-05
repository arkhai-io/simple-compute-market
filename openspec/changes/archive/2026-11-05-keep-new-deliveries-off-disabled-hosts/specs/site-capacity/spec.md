## MODIFIED Requirements

### Requirement: Admission applies the pool provider's host requirement

Where its composition supplies a host requirement for fulfillment providers, a
site authority SHALL treat a capacity declaration as an ineligible admission
candidate when the provider of the declaration's pool needs a host and the
declaration has no usable host. A declaration has a usable host only when it
names a host its composition reports as taking new delivery: a host that is
registered and enabled. A provider identity absent from a supplied requirement
SHALL be treated as needing a host. A composition that supplies no requirement
SHALL NOT apply one. A composition that supplies a requirement but no report of
the hosts taking new delivery SHALL treat every named host as usable.

Probe, reserve, resize, and the reassignment of a reservation to another
settlement resource SHALL apply the same eligibility, each reading the hosts
taking new delivery in its own transaction. The site authority SHALL learn of
hosts only the identifiers of those taking new delivery, as its composition
supplies them, and SHALL NOT read host connection information.

An ineligible candidate is refused in the ordinary capacity-refusal way: it does
not match, and a claim that no other candidate satisfies receives the same no-
capacity answer as any other unservable claim. A reassignment to an ineligible
settlement resource is refused as a capacity conflict.

#### Scenario: A host-requiring pool holds a declaration naming no host

- **GIVEN** a composition supplying a host requirement in which the pool's
  provider needs a host
- **AND** a matching capacity declaration in that pool names no host
- **WHEN** a claim is probed or reserved
- **THEN** that declaration does not match and no hold is created against it

#### Scenario: A declaration names a disabled host

- **GIVEN** a composition supplying a host requirement in which the pool's
  provider needs a host
- **AND** a matching capacity declaration in that pool names a registered host
  that is disabled
- **WHEN** a claim is probed, reserved, or resized onto it
- **THEN** that declaration does not match, and a claim no other declaration
  satisfies receives the ordinary no-capacity answer

#### Scenario: A disabled host is enabled again

- **GIVEN** a declaration that did not match because its host was disabled
- **WHEN** the host is enabled and a matching claim is reserved
- **THEN** the declaration matches as any other eligible declaration does

#### Scenario: A declaration names a host with no registration

- **GIVEN** a composition supplying a host requirement in which the pool's
  provider needs a host
- **AND** a matching capacity declaration in that pool names a host that has no
  registered host record
- **WHEN** a claim is probed or reserved
- **THEN** that declaration does not match and no hold is created against it

#### Scenario: A reservation is reassigned to a declaration with no usable host

- **WHEN** scheduling reassigns a held reservation to a settlement resource whose
  declaration names a disabled host, in a pool whose provider needs a host
- **THEN** the reassignment is refused as a capacity conflict and the
  reservation's debit is unchanged

#### Scenario: The pool's provider is absent from the supplied requirement

- **GIVEN** a composition supplying a host requirement that does not name the
  pool's provider
- **WHEN** a claim matches a declaration in that pool that names no host
- **THEN** the declaration does not match

#### Scenario: A composition supplies no host requirement

- **GIVEN** a composition that supplies no host requirement
- **WHEN** a claim matches a capacity declaration that names no host
- **THEN** it is admitted as any other matching declaration is

#### Scenario: A composition supplies no report of hosts taking new delivery

- **GIVEN** a composition that supplies a host requirement but no report of the
  hosts taking new delivery
- **WHEN** a claim matches a declaration naming a host, in a pool whose provider
  needs one
- **THEN** it is admitted as any other matching declaration is

### Requirement: Projected inventory is internally consistent

Projected physical inventory MUST NOT report attribute values that contradict the
same resource's projected capacity. A projected resource's capacity and its
descriptive attributes MUST derive from one authoritative record for that resource:
its capacity declaration, with every declared attribute projected except domain view
configuration already published as a view. No host inventory record contributes to
a projected resource's capacity or attributes. A projected resource's `enabled`
state MAY reflect whether the host its declaration names takes new delivery, as
"The resource-pool projection is built from capacity declarations and offers only
a usable host" states. A quantity MUST appear only in the projected capacity, never
duplicated as an attribute.

#### Scenario: Declared capacity disagrees with a legacy inventory value

- **WHEN** an operator-declared capacity resource reports a different quantity for a
  dimension than a legacy inventory record holds for the same resource
- **THEN** the projection reports the declared value in capacity, reports no
  attribute carrying the same quantity, and never reports the two disagreeing in one
  projected row

#### Scenario: Categorical hardware identity is projected

- **WHEN** a capacity declaration carries a categorical hardware attribute matched by
  equality rather than by sufficiency
- **THEN** the projection reports it as an attribute rather than as a capacity
  dimension, sourced from the same authoritative record as the capacity

## REMOVED Requirements

### Requirement: The resource-pool projection is built from capacity declarations

**Reason**: Its `enabled` came from the declaration alone, so a declaration naming
a disabled or unregistered host, or none where its provider needs one, projected
enabled while admission refused it. Replaced by "The resource-pool projection is
built from capacity declarations and offers only a usable host".

**Migration**: None. The projection's shape is unchanged; such a declaration now
projects as not enabled, and storefronts close its listings through their
existing disabled-source rules.

## ADDED Requirements

### Requirement: The resource-pool projection is built from capacity declarations and offers only a usable host

The resource-pool projection SHALL enumerate every capacity declaration and SHALL
NOT read host connection information. Each projected entry's Physical Resource
identity, pool, resource type and subtype, capacity, reported availability, and
attributes SHALL come from its declaration alone.

Each entry's `enabled` state SHALL be the declaration's own `enabled`, except that
a declaration in a backed pool whose provider needs a host, and which has no
usable host as admission judges it, SHALL project as not enabled. That judgement
SHALL read of hosts only the identifiers of those taking new delivery, as the
composition supplies them. A declaration in an unbacked pool, or in a pool whose
provider needs no host, SHALL project its own `enabled` whatever host it names or
whether it names one. The site authority SHALL judge a pool that delivers no
offering mode as unbacked, as admission does, since an unbacked pool delivers
none, and SHALL NOT read a pool's backing for this judgement. A domain publication view SHALL be built from the
declaration with this projected `enabled` state, so a view that reports
availability reports a declaration with no usable host as unavailable.

A generic projected entry SHALL NOT carry host connection identity: no host
identifier, connection address, or tenant-facing address. A domain publication
view MAY carry the host its declaration names where that domain sells a specific
host.

#### Scenario: A declaration names no host in an unbacked pool

- **GIVEN** a capacity declaration in an unbacked pool that names no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears with its declared capacity, attributes,
  Physical Resource identity, and its own `enabled` state

#### Scenario: A backed declaration names no host where its provider needs one

- **GIVEN** an enabled capacity declaration in a backed pool whose provider needs
  a host, naming no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears with its declared capacity, attributes, and
  Physical Resource identity, and is projected not enabled

#### Scenario: A pool delivers no offering mode

- **GIVEN** an enabled capacity declaration in a pool whose provider needs a
  host and which declares no deliverable offering mode, naming a host not taking
  new delivery
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration projects its own `enabled` state, as an unbacked
  pool's does

#### Scenario: A declaration names an unregistered host

- **GIVEN** an enabled capacity declaration in a backed pool whose provider needs
  a host, naming a host that has no registered host record
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears and is projected not enabled

#### Scenario: A generic entry carries no host connection identity

- **GIVEN** a capacity declaration naming a registered host that has a
  connection address and a tenant-facing address
- **WHEN** the resource-pool projection is produced
- **THEN** the entry's attributes carry neither the host identifier nor either
  address

#### Scenario: A disabled host projects its declaration not enabled

- **GIVEN** an enabled capacity declaration in a backed pool whose provider needs
  a host, naming a registered host that is disabled
- **WHEN** the resource-pool projection is produced
- **THEN** the entry is projected not enabled, and a bare-metal publication view
  built for it reports itself unavailable

#### Scenario: A disabled host is enabled again

- **GIVEN** an enabled declaration projected not enabled because its host was
  disabled
- **WHEN** the host is enabled and the projection is produced again
- **THEN** the entry is projected enabled, with its derivation identity unchanged

### Requirement: Every capacity surface offers only a declaration with a usable host

The capacity-bucket projection and the advisory snapshot SHALL leave out a
declaration that the resource-pool projection projects as not enabled for want of
a usable host, as they leave out a disabled declaration. The site authority SHALL
state each declaration's offered `enabled` state, its own `enabled` and the
usable-host rule together, in one read that takes the declarations and the hosts
taking new delivery in the same transaction, and both projections and the
snapshot SHALL be built from that read. The administrative
listing of capacity declarations SHALL report each declaration's own `enabled`
state, so an operator sees what they declared. A change of a host's enabled state
or registration SHALL NOT itself record a capacity event or advance the capacity
version; each projection's revision and digest SHALL advance when it is next
produced.

#### Scenario: A host is disabled

- **GIVEN** an enabled declaration in a backed pool whose provider needs a host,
  naming a host that is then disabled
- **WHEN** the capacity-bucket projection and the snapshot are produced
- **THEN** neither includes the declaration, and the capacity-bucket projection's
  revision and digest advance

#### Scenario: An operator lists capacity declarations

- **WHEN** an operator lists capacity declarations while a declaration's host is
  disabled
- **THEN** the listing reports the declaration's own `enabled` state

#### Scenario: A host's state changes

- **WHEN** a host is enabled, disabled, or registered
- **THEN** no capacity event is recorded and the capacity version is unchanged
