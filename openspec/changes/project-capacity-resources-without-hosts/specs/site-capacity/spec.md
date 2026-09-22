## ADDED Requirements

### Requirement: The resource-pool projection is built from capacity declarations

The resource-pool projection SHALL enumerate every capacity declaration and SHALL
NOT read host inventory records. Each projected entry's Physical Resource
identity, pool, resource type and subtype, capacity, reported availability,
attributes, and `enabled` state SHALL come from its declaration alone. Whether a
declaration names a host, and whether a named host is registered, SHALL NOT
affect whether or how the declaration projects.

A generic projected entry SHALL NOT carry host connection identity: no host
identifier, connection address, or tenant-facing address. A domain publication
view MAY carry the host its declaration names where that domain sells a specific
host.

#### Scenario: A declaration names no host

- **GIVEN** a capacity declaration that names no host
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears with its declared capacity, attributes, and
  Physical Resource identity

#### Scenario: A declaration names an unregistered host

- **GIVEN** a capacity declaration naming a host that has no registered host
  record
- **WHEN** the resource-pool projection is produced
- **THEN** the declaration appears exactly as a declaration naming no host would

#### Scenario: A generic entry carries no host connection identity

- **GIVEN** a capacity declaration naming a registered host that has a
  connection address and a tenant-facing address
- **WHEN** the resource-pool projection is produced
- **THEN** the entry's attributes carry neither the host identifier nor either
  address

#### Scenario: A disabled host does not change a projected declaration

- **GIVEN** an enabled capacity declaration naming a registered host that is
  disabled
- **WHEN** the resource-pool projection is produced
- **THEN** the entry is projected enabled, matching the declaration

### Requirement: Admission applies the pool provider's host requirement

Where its composition supplies a host requirement for fulfillment providers, a
site authority SHALL treat a capacity declaration that names no host as an
ineligible admission candidate when the provider of the declaration's pool needs
a host. A provider identity absent from a supplied requirement SHALL be treated
as needing a host. A composition that supplies no requirement SHALL NOT apply
one. Probe and reserve SHALL apply the same eligibility.

An ineligible candidate is refused in the ordinary capacity-refusal way: it does
not match, and a claim that no other candidate satisfies receives the same no-
capacity answer as any other unservable claim. Admission SHALL NOT require the
named host to be registered; registration is checked at dispatch.

#### Scenario: A host-requiring pool holds a declaration naming no host

- **GIVEN** a composition supplying a host requirement in which the pool's
  provider needs a host
- **AND** a matching capacity declaration in that pool names no host
- **WHEN** a claim is probed or reserved
- **THEN** that declaration does not match and no hold is created against it

#### Scenario: The pool's provider is absent from the supplied requirement

- **GIVEN** a composition supplying a host requirement that does not name the
  pool's provider
- **WHEN** a claim matches a declaration in that pool that names no host
- **THEN** the declaration does not match

#### Scenario: A composition supplies no host requirement

- **GIVEN** a composition that supplies no host requirement
- **WHEN** a claim matches a capacity declaration that names no host
- **THEN** it is admitted as any other matching declaration is

## MODIFIED Requirements

### Requirement: Resource-pool projection metadata
The `site_resource_pools` projection MAY carry allowlisted, additive pool-level metadata alongside per-resource inventory: `label`, `enabled`, `mechanism` (the pool's configured provider kind, e.g. `"ansible"` -- never provider credentials or connection configuration), opaque `policy_tags`, and a generic `pool_views` map. A projection producer omitting pool metadata, or a pool absent from a supplied metadata source, MUST yield a resource-pool row with no `pool_metadata` key at all, not an empty one -- older producers and consumers observe no behavioral change. Any change to projected pool metadata MUST advance that projection's existing revision and digest identically to a resource-level change.

`pool_views` is domain-neutral at this layer: the site-capacity projection carries it as an opaque `dict[str, Any]` and MUST NOT interpret its contents or require any provider-specific key names. Domain-owned content lives under a versioned key inside it (mirroring the existing per-resource `publication_views` convention) -- for example, an Ansible-provider pool's configured VM size defaults are published as `pool_views["vm.ansible_pool_defaults.v1"]`, a mapping shaped and populated entirely by the VM provisioning domain, never by the generic site-capacity or resource-pool packages. A view keyed by a domain/mechanism name (for example `vm.*`) MUST only be published for a pool whose `mechanism` actually matches that domain -- a stale or orphaned provider-specific configuration row for a pool that no longer uses that provider MUST NOT surface that provider's view.

A resource-pool row's per-resource `attributes` are the capacity declaration's own declared attributes, except domain view configuration published as a view. An attribute the declaration does not declare MUST be omitted from `attributes`, not published as null.

#### Scenario: Older producer omits pool metadata
- **WHEN** a resource-pool projection is produced with no pool-metadata source configured
- **THEN** every resource-pool row is emitted with the same shape as before pool metadata existed, with no `pool_metadata` key

#### Scenario: Pool metadata changes with unchanged resource inventory
- **WHEN** only a pool's `label`, `enabled` state, `policy_tags`, or `pool_views` content changes and its resource inventory does not
- **THEN** the resource-pool projection's revision and digest advance, identically to a resource-level change

#### Scenario: Provider credentials never enter the projection
- **WHEN** a pool's provider-specific configuration contains connection details or credentials alongside allowlisted fields
- **THEN** the projected `pool_metadata` and `pool_views` contain only the allowlisted fields; credentials and connection configuration are never present

#### Scenario: A stale provider-specific configuration row does not leak its view
- **WHEN** a pool's `mechanism` no longer matches the provider that a leftover provider-specific configuration row belongs to
- **THEN** that provider's versioned view is absent from `pool_views`, regardless of whether the stale row still exists

#### Scenario: An unset host-level attribute is omitted, not published as null
- **WHEN** a capacity declaration declares no GPU model, whether or not the host it names holds one on its host record
- **THEN** the corresponding resource-pool row's `attributes` carries no key for it, rather than a null value or the host record's value

### Requirement: A capacity declaration names the host it is delivered through

A capacity declaration delivered through a host MUST name that host as a `host_id`
field of the declaration, not as one of its attributes, and at most one
declaration MAY name a given host. A declaration delivered through no host names
none; naming a host is not required for a declaration to be valid, stored, or
projected. A registration naming a host another declaration names MUST be refused.
Execution references and a reservation's claim facts MUST take the host from that
field.

#### Scenario: A second declaration names a held host

- **WHEN** a declaration is registered with a `host_id` another declaration names
- **THEN** the registration is refused as a conflict and neither declaration changes

#### Scenario: A reservation is bound to a host

- **WHEN** a reservation is admitted against a declaration that names a host
- **THEN** its execution reference carries that declaration's `host_id`

#### Scenario: A declaration names no host

- **WHEN** a declaration is registered with no `host_id`
- **THEN** it is stored as declared and no host is inferred for it

### Requirement: Projected inventory is internally consistent

Projected physical inventory MUST NOT report attribute values that contradict the
same resource's projected capacity. A projected resource's capacity and its
descriptive attributes MUST derive from one authoritative record for that resource:
its capacity declaration, with every declared attribute projected except domain view
configuration already published as a view. No host inventory record contributes to
a projected resource. A quantity MUST appear only in the projected capacity, never
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
