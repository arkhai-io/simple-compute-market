## ADDED Requirements

### Requirement: Listing-shape hint validation

A Resource Pool management surface that accepts `listing_shapes` MUST require a mapping from
offering mode to a non-empty list of structurally well-formed family-grouped capability
shapes. A well-formed shape is a non-empty mapping of family name to a non-empty mapping of
field name to a scalar value. The check MUST be the shared structural check the capability
shape utility provides, and MUST NOT depend on any domain's family or field names. Which
families and fields are meaningful, and which are required, MUST be validated by the domain
that reads the hint. Every surface capable of persisting a Resource Pool's `policy_tags` MUST
apply the same check: the bulk pool-document import path and the individual pool admin API
(`create`/`replace`/`update`).

#### Scenario: Operator supplies a malformed shape list

- **WHEN** an operator submits `listing_shapes` whose VM list is empty, or whose shape
  holds a family that is not a mapping, through any pool-write surface
- **THEN** Resource Pool validation rejects the update without changing the stored policy
  metadata

#### Scenario: Operator names a field no domain defines

- **WHEN** an operator submits a structurally well-formed shape naming a field the VM domain
  does not define
- **THEN** Resource Pool validation accepts it, and the VM storefront reports the pool's
  shapes as unreadable when it derives listings

## MODIFIED Requirements

### Requirement: Domain-neutral publication and hold hints

Resource Pool policy metadata MUST support stable domain-neutral keys for `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, `pricing`, and `listing_shapes` without defining domain-specific cardinality, region, SLA, pricing, or shape values in this shared capability. The key MUST be named for its scope: it carries how many listing candidates a pool yields and how each is independently identified, and a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. `listing_shapes` carries, per offering mode, the shapes a pool's listings are sold in; it describes what is offered, which is why it is a key of its own rather than a value of the cardinality hint. The former `listing_mode` key MUST remain accepted as a deprecated ingestion alias resolving to the same cardinality, because that key is optional and its silent absence resolves to a structural default rather than an error — an unupgraded producer whose alias were rejected would be reclassified rather than refused. The alias is a read-path concession only. Policy tags are projected verbatim, so the spelling an operator stored is the spelling a consumer receives and reconciliation belongs at the reading end; the reader this capability exposes MUST be named for the settled key and MUST resolve either spelling, and no other surface naming this hint may use the deprecated one. Unknown policy tags MUST remain forward-compatible opaque metadata. `pool_id` is a site-local operator slug, never made globally unique; every durable or public reference to a pool keys on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.

#### Scenario: Domain interprets the cardinality hint

- **WHEN** VM, bare-metal, or API-credit publication reads a Resource Pool's `listing_cardinality_mode`
- **THEN** the selected domain validates and interprets the value without adding its enum or default rule to this shared package

#### Scenario: A pool declares the deprecated key

- **WHEN** a Resource Pool's policy metadata carries `listing_mode` rather than `listing_cardinality_mode`
- **THEN** the value resolves to the same cardinality the deprecated key names
- **AND** the pool is neither refused nor reclassified to a structural default

#### Scenario: Consumer does not support a hint

- **WHEN** a storefront version does not recognize one projected policy tag
- **THEN** it ignores that tag without rejecting the Resource Pool or changing authoritative admission

#### Scenario: Domain interprets the shape hint

- **WHEN** VM publication reads a Resource Pool's `listing_shapes`
- **THEN** it reads only the list under the `vm` offering mode and interprets its shapes through the VM domain's schema, without that schema being added to this shared package
