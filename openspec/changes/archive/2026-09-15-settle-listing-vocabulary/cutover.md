# Cutover — settle the listing vocabulary

Operational sequence for this change's coordinated deploy. Temporary: it describes
one transition, not a durable convention, so it stays in the change directory. The
pattern it follows is the identity-contract cutover in
[`DEPLOYMENT_AND_CONFIG.md`](../../../docs/development/DEPLOYMENT_AND_CONFIG.md)
("For an identity-contract cutover…"); only the pins and gates below are specific
to this change.

## Why a coordinated deploy is required

Three wires and one operator surface change their field names at once, and none of
them carries a compatibility alias:

| Boundary | Retired | Settled | Failure mode if skewed |
|---|---|---|---|
| Capacity claim (storefront → site) | `executor_kind` | `offering_mode` | Loud. The field is required; a claim missing it is refused at the first reservation |
| Provisioning contract (storefront → provisioning service) | `executor_kind` | `offering_mode` | Loud. Contract-version mismatch is rejected with actionable version information |
| Published listing shape (storefront → registry → buyer) | `offer_resource`, `virtualization_type` | `listing_resource`, `offering_mode` | **Quiet.** The published mode field is optional, so a buyer filtering on it silently matches nothing |
| Listing creation (seller tooling → storefront) | `offer` | `listing_resource` | Loud. `extra="forbid"` rejects the retired key |

The quiet one is why the listing shape carries the closest verification, and why
the post-migration row counts below are gates rather than diagnostics.

The projected cardinality hint is the one exception: `listing_mode` remains
accepted on ingestion, so a site that has not been upgraded does not need to move
in lockstep for that field. Everything else does.

## Pinned versions

Every participant must report these before mutations resume.

| Component | Pin |
|---|---|
| Compute filter specification | `version: 5`, `schema.id: compute.market`, `schema.version: 2` |
| API-credits filter specification | `version: 3`, `schema.id: api_credits` |
| Introductions filter specification | `version: 2`, `schema.id: introductions.market` |
| Provisioning contract | advanced `contract_version` |
| `arkhai-core-registry-client` | `0.12.0` |
| `arkhai-core-storefront-client` | `0.18.0` |
| `arkhai-core-storefront` | `0.4.0` |
| `arkhai-kit-site-client` | unchanged — schema-opaque to the claim, so no bump is owed |

Buyer commands declare the schema identity they understand, so a buyer pinned to
the retired identity stops querying the compute registry rather than receiving
wrong results. That is the mechanism working; it still means buyer clients ship
with the registries they query.

## Sequence

1. **Land the cardinality rename first.** Independent of everything below: the
   ingestion alias means an unupgraded site keeps resolving correctly.
2. **Quiesce authenticated mutations** across storefronts, registries, the
   provisioning service, and hosted authorities.
3. **Migrate, in any order — the three databases are independent.**
   - Compute provisioning service: `20260911_001_reservation_offering_mode_name`
     (reservation column + the `scheduling_requirements` payload key).
   - Registry: Alembic `018_listing_resource_column`.
   - Storefront: `20260911_001_listing_resource_column` (listing-shape column + the
     nested offering-mode key).
4. **Run the payload gates. A non-zero count blocks resuming.**
   - `count_rows_carrying_retired_offering_mode_key` (compute provisioning service)
   - `count_listings_carrying_retired_offering_mode_key` (each storefront database)

   Both read whichever shape column is present, so a zero means "no stale rows",
   not "wrong column inspected". Count rather than sample: both payloads are JSON,
   so a missed row is not a type error and would not surface until a settlement
   retry or a listing read.
5. **Deploy storefronts, sites, the provisioning service, registries, and buyer
   clients together**, then verify every participant reports its pin from the table
   above.
6. **Resume mutations.**

## Rollback boundary

Rollback is limited to the boundary **before step 3**. Once migrated state has
taken effects, recovery is rolling forward rather than restoring stale state —
the same constraint the identity-contract pattern already carries. Each migration
is individually idempotent and safe to re-run, but none is reversible in the
presence of post-migration writes.

The registry's Alembic revision does define a `downgrade`, which is
revision-framework hygiene rather than an invitation: running it after buyers have
queried the renamed schema identity puts the registry back on an identity no
shipped buyer claims compatibility with.

## Internal package resolution

The three client bumps are only resolvable if every consumer resolves internal
wheels from `.dist` rather than a published index. Two library distributions —
`domains/vms/domain` and `domains/bare_metal` — were locked against
`https://pypi.org/simple`, so their locks pinned whatever version was published
and could not satisfy a constraint on a version built in this tree but not yet
released. Both now declare `[tool.uv] find-links` and their locks record the
local registry.

Four exact pins (`==`) and seven floors (`>=`) on the bumped distributions were
also raised. The floors mattered on their own terms: `>=0.11.0` on
`arkhai-core-registry-client` would have permitted a client with no
`listing_resource` at all.

## Related persistence work

[`migrate-registry-to-postgres`](../migrate-registry-to-postgres/) rewrites registry
persistence. It is blocked on external infrastructure and on step 2 of its own
chain, so there is no ordering conflict to resolve here. The only requirement is
that whichever lands second targets `listings.listing_resource` rather than the
retired column name.
