## MODIFIED Requirements

### Requirement: Resource-pool projection metadata
The `site_resource_pools` projection MAY carry allowlisted, additive pool-level metadata alongside per-resource inventory: `label`, `enabled`, `mechanism` (the pool's configured provider kind, e.g. `"ansible"` -- never provider credentials or connection configuration), opaque `policy_tags`, and a generic `pool_views` map. A projection producer omitting pool metadata, or a pool absent from a supplied metadata source, MUST yield a resource-pool row with no `pool_metadata` key at all, not an empty one -- older producers and consumers observe no behavioral change. Any change to projected pool metadata MUST advance that projection's existing revision and digest identically to a resource-level change.

`pool_views` is domain-neutral at this layer: the site-capacity projection carries it as an opaque `dict[str, Any]` and MUST NOT interpret its contents or require any provider-specific key names. Domain-owned content lives under a versioned key inside it (mirroring the existing per-resource `publication_views` convention) -- for example, an Ansible-provider pool's configured VM size defaults are published as `pool_views["vm.ansible_pool_defaults.v1"]`, a mapping shaped and populated entirely by the VM provisioning domain, never by the generic site-capacity or resource-pool packages. A view keyed by a domain/mechanism name (for example `vm.*`) MUST only be published for a pool whose `mechanism` actually matches that domain -- a stale or orphaned provider-specific configuration row for a pool that no longer uses that provider MUST NOT surface that provider's view.

A resource-pool row's per-resource `attributes` are the capacity declaration's own declared attributes, except domain view configuration published as a view. An attribute the declaration does not declare MUST be omitted from `attributes`, not published as null.

Every per-resource member MUST carry a non-empty `resource_type`: the resource kind the site records for its declaration, which is the site's default kind when the declaration names none. A consumer judges whether a member can serve a claim by its kind, so a producer MUST NOT omit it or publish it as null, and a consumer MAY treat a member without one as malformed.

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

#### Scenario: A declaration naming no resource kind is projected with the recorded one
- **WHEN** a capacity declaration is registered without naming a resource kind
- **THEN** its projected member carries the kind the site recorded for it, never an absent or null `resource_type`
