## MODIFIED Requirements

### Requirement: Domain-neutral publication and hold hints

Resource Pool policy metadata MUST support stable domain-neutral keys for `listing_cardinality_mode`, `max_reservation_hold_seconds`, `region`, `sla`, and `pricing` without defining domain-specific cardinality, region, SLA, or pricing values in this shared capability. The key MUST be named for its scope: it carries how many listing candidates a pool yields and how each is independently identified, and a value describing what is offered, how a deal settles, or whether an admission authority backs the listing is out of scope for it. The former `listing_mode` key MUST remain accepted as a deprecated ingestion alias resolving to the same cardinality, because that key is optional and its silent absence resolves to a structural default rather than an error — an unupgraded producer whose alias were rejected would be reclassified rather than refused. The alias is an ingestion concession only: this capability MUST emit the settled key, and the reader it exposes MUST be named for the settled key, so the deprecated spelling survives on the read path and nowhere else. Unknown policy tags MUST remain forward-compatible opaque metadata. `pool_id` is a site-local operator slug, never made globally unique; every durable or public reference to a pool keys on `(site_id, pool_id[, resource_id])`, never `pool_id` alone.

#### Scenario: Domain interprets listing mode

- **WHEN** VM, bare-metal, or API-credit publication reads a Resource Pool's `listing_cardinality_mode`
- **THEN** the selected domain validates and interprets the value without adding its enum or default rule to this shared package

#### Scenario: A pool declares the deprecated key

- **WHEN** a Resource Pool's policy metadata carries `listing_mode` rather than `listing_cardinality_mode`
- **THEN** the value resolves to the same cardinality the deprecated key names
- **AND** the pool is neither refused nor reclassified to a structural default

#### Scenario: Consumer does not support a hint

- **WHEN** a storefront version does not recognize one projected policy tag
- **THEN** it ignores that tag without rejecting the Resource Pool or changing authoritative admission
