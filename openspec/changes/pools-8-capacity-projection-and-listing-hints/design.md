## Context

The site authority now publishes two independent projections: `site_resource_pools` for host/resource facts and `site_capacity_buckets` for grouped advisory capacity. Each has revision/digest identity. VM storefront startup loads and polls both into atomic in-memory caches with stale retention. No production publication or claim-building reader consumes those caches, accepted identities are not durable across restart, and pool labels/provider/enabled/policy tags are absent from the resource projection.

Storefront `resources` and capacity-pool tables still combine commercial metadata with locally authored physical identity. Wholesale replacement would remove pricing, settlement, and operator state that the site authority does not own.

## Goals / Non-Goals

**Goals:**
- Persist complete independently versioned projection generations per trusted site.
- Map provisioning identity into storefront-owned commercial publication without conflating authorities.
- Consume mapped identity for listings and Capacity Reservation claims.
- Add additive, advisory, domain-owned listing and hold hints.
- Remove only local physical-authority state proven superseded.

**Non-Goals:**
- Make projections authoritative for admission or assignment.
- Rebuild existing producer/cache behavior.
- Equate Resource Pools with storefront commercial pools.
- Put domain enum values in `kit/resource-pools` or `kit/site`.

## Decisions

### Persist configured sites and projection families independently

Storefront persistence records each operator-trusted `site_id` binding separately from remote payloads. For each `(site_id, projection_kind)`, it stores the accepted revision, digest, fetched/stale metadata, and one complete generation. Replacement is transactional per family; failure retains the previous generation as stale and never writes an empty projection.

A restart loads durable generations before polling. Revision sequences are authority-local and projection-family-local; comparing revisions across sites or families is invalid.

### Keep projection identity separate from commercial inventory

A mapping layer relates projected `(site_id, pool_id, resource_id?)` identity to storefront-owned publication records containing pricing, settlement mechanisms, seller policy, and listing history. Site projection refresh updates physical facts and availability inputs; it does not overwrite commercial policy.

The mapping must define missing, disabled, moved, and conflicting identities. Disappearing physical support closes or suppresses derived listings but does not erase agreement history.

### Route pinned claims directly

Listings derived from one site carry an internal trusted mapping to that site and projected pool/resource identity. Claim construction uses the mapping and routes reservation to the producing authority. It does not broadcast a pinned state-changing request across sites. Public listing payloads expose only intended market identity/labels, not authority credentials or URLs.

### Extend resource projection with pool metadata

The resource-pool projection adds the minimum normalized metadata required by publication: pool label, enabled state, provider/mechanism reference where safe, and opaque `policy_tags`. Any payload change advances that projection's revision/digest. Credentials and provider secrets are never projected.

A separate pool-metadata projection was considered but rejected for the first implementation because publication needs an atomic view of member identity and pool hints. If payload size or update frequency later warrants separation, it requires its own independent identity and cache.

### Keep hints advisory and domain-owned

`kit/resource-pools` defines only stable key names:

- `listing_mode`
- `max_reservation_hold_seconds`

Each domain validates values and applies defaults. VM and bare metal may distinguish pooled versus specific-resource publication; API credits may use quota/key semantics. Unknown or invalid values produce an operator-visible explanation and fall back to the domain's structural default.

A cooperating storefront caps its requested hold TTL to the nonnegative operator preference and its own policy. The site ledger continues enforcing only the actual caller-supplied TTL and does not treat the tag as authority.

### Retire local physical state reader by reader

Before removing any table or field, inventory publication, claim construction, negotiation, pricing, admin, recovery, migration, and e2e readers. Remove `resource_capacity_validator.py` only after its local physical-inventory input has no caller. Preserve commercial metadata and transition/idempotency state even if stored in an existing table.

### Share contracts, not domain semantics

Core storefront may own schema-opaque projection persistence and reconciliation ports. Domain packages own projection-to-listing interpretation and hint enums. Site/resource-pool kits do not import storefront or domain code.

## Risks / Trade-offs

- **[Projection data becomes stale]** → Retain last complete generation with explicit freshness and require live admission for every reservation.
- **[Mapping duplicates identity]** → Store references and commercial overlays, not an independently authored physical truth.
- **[Pool metadata leaks secrets]** → Project allowlisted normalized fields only and test payload redaction.
- **[Pinned site is unavailable]** → Report/retry that authority; do not silently reserve elsewhere under the same listing.
- **[Local inventory removal breaks operator workflows]** → Gate each deletion on reader inventory, migration, and focused compatibility evidence.

## Migration Plan

1. Add durable configured-site and projection-generation tables without changing current publication.
2. Extend producer payloads additively and load old payloads with absent optional metadata.
3. Backfill commercial mappings from current listings/local inventory where identity is unambiguous; quarantine ambiguous rows.
4. Switch publication and claim construction behind observable comparison/feature controls.
5. Remove proven-superseded physical-authority writers/readers only after parity and restart tests.

Rollback restores the previous publication/claim reader while retaining additive projection tables. Listings created from mappings retain enough provenance to close safely; no migration deletes agreement history.

## Open Questions

- Are Resource Pool IDs globally generated after POOLS-7 identity cleanup, or must every persistent/publication reference remain explicitly site-scoped?
- Which existing storefront table should own the commercial overlay versus a new mapping table?
- Should provider identity be projected directly, or reduced to a non-sensitive mechanism label for publication?

## Permanent Documentation Promotion

| Decision | Permanent destination |
|---|---|
| Independent durable projection generations and stale behavior | `openspec/specs/site-capacity/spec.md` and `architecture.md` |
| Commercial mapping, direct claim routing, and retirement boundary | `openspec/specs/storefront-publication/spec.md` and `architecture.md` |
| Domain-neutral hint keys and domain-owned values | `openspec/specs/resource-pool-management/spec.md` and `architecture.md` |
