## Context

Recovered from `docs/development/ARCHITECTURE.md`'s "Physical Settlement
Scheduler and FulfillmentProvider Architecture" section and the
pre-migration `TODO.md`'s POOLS-4 item; see `pools-2`'s design.md Context
for the provenance note. Verified and corrected against current code
before writing this down — see proposal.md's "Correction from the original
plan."

## Goals / Non-Goals

See proposal.md.

## Decisions

### 1. `fill_first`/`most_available` never decided host placement — correcting this file

Verified against code during design review (2026-07-16), correcting what
this file originally said: `AggregateCapacityClient`'s placement policies
(`core_storefront/aggregation.py`) only ever order *sites* for a
multi-site aggregator to try — there is no host-level selection logic
anywhere in that module. The concrete physical resource a reservation
resolves to has always been decided by whichever site's `CapacityLedgerService`
answers the claim (`kit/site/src/market_site/ledger.py`'s `_resource_matches`),
not by the storefront choosing a host up front. This change does not
touch `aggregation.py`. `pools-7`'s design.md already carries the open
question of whether `fill_first`/`most_available` should later become a
pool-level preference hint once `PhysicalSettlementScheduler` has a
production caller — that's unaffected by this correction.

### 2. What actually forced host-specificity, and what this change fixes

`vm_job_spec_service._REQUIRED_COMPUTE_KEYS` (`pool_id`, `resource_id`,
`region`, `gpu_model`, `gpu_count`) already excludes `vm_host` — verified,
this part of the original proposal was already true before this change
started. The real gap is a missing invariant, not a wrong claim key: a
compute listing's `offer_resource` can end up with **neither** `pool_id`
nor `resource_id` set, because `ListingService.create_listing`
(`domains/vms/storefront/src/market_storefront/services/listing_service.py`)
accepts and stores an `offer` payload with no cross-check against pool/
resource identity — unlike the reconciler-driven publish path
(`available_compute_slices`/`cli_publish.py`), which always populates at
least `pool_id` (defaulting to `resource_id` for a single-resource pool).
A claim built from such a listing carries only `region`/`gpu_model`/
`gpu_count` — exactly the under-specified-claim bug class
`test_claim_survives_listing_model_validation` was written to catch,
just via a different missing field than that test currently exercises.

**Resolved invariant (design review, 2026-07-16):** a listing needs *at
least one* of `pool_id` / `resource_id` — a `resource_id`-only listing
with no `pool_id` is a legitimate, intentional specific-resource listing,
not an error to correct by backfilling a default. `pool_id` is never
forced onto a listing that didn't have one.

This change adds two guards, not a change to which keys
`compute_capacity_claim_from_order` pulls into a claim:

- **At listing creation** (`ListingService._parse_offer_and_escrows` or
  equivalent): reject a compute offer that has neither `pool_id` nor
  `resource_id`. This is the actual choke point for every way a listing's
  `offer_resource` gets stored — the reconciler-driven publish path
  already satisfies it; this only closes the direct
  `POST /listings/create` path.
- **At claim build** (`compute_capacity_claim_from_order`): raise if the
  resulting claim carries neither key. A backstop for any listing that
  reaches this point despite the first guard (e.g. a row written by a
  future or as-yet-unaudited path), so a missing identity fails loudly at
  reservation time instead of silently matching on shape attributes alone.

### 3. Rename is schema + call sites, not a behavior change

`compute_inventory_pools` → `compute_capacity_pools` is a pure rename: same
columns, same foreign-key relationships, same reconciler behavior. Doing it
as part of this change rather than deferring keeps the storefront's
internal naming aligned with the capacity-shaped claim vocabulary this
change also introduces, instead of landing capacity-language reservations
on top of a table still named for the old host-inventory model.

## Risks / Trade-offs

- **Listing creation gets stricter.** Any caller of
  `POST /listings/create` (or a future caller of `ListingService.create_listing`)
  that was relying on being able to publish a compute offer with neither
  `pool_id` nor `resource_id` set will now be rejected. Verified no such
  caller in this repository (`cli_publish.py`'s reconciler-driven path
  always sets at least `pool_id`); this only affects hypothetical external
  or future callers of the raw endpoint.
- **`RemoteCapacityClient`/`AggregateCapacityClient` need no changes.**
  Verified both are already claim-shape-agnostic (opaque `Mapping`
  passthrough) — correcting the proposal's original framing, which implied
  these call sites needed updating for the claim-shape change. They don't;
  only `vm_job_spec_service.py`'s two guards do.
- **Ownership-rule prose drift.** The baseline `site-capacity` spec already
  states the provisioning-owns-inventory / storefront-owns-projection rule;
  this change should confirm current prose still matches rather than
  assume it does, since the codebase has moved since this item was
  originally written (see the `SiteLedger` correction above). Verified
  during this design review: still matches.

## Migration Plan

1. Add a new, additive `compute_capacity_pools` rename migration
   (`ALTER TABLE compute_inventory_pools RENAME TO compute_capacity_pools`)
   rather than editing the historical `_migrate_compute_inventory_pools`
   migration in place — that function already ran against deployed
   databases under the old name, so rewriting it wouldn't rename an
   already-created table. `compute_pool_members`'s `FOREIGN KEY(pool_id)
   REFERENCES compute_inventory_pools(pool_id)` needs verifying after the
   rename — SQLite's `RENAME TO` is expected to rewrite the reference
   automatically, but this hasn't been confirmed against this schema.
   `compute_pool_members` itself is not renamed — the proposal scoped the
   rename to `compute_inventory_pools` specifically, and "members" doesn't
   carry the old "inventory" framing that motivated the rename.
2. Update `sqlite_client.py` and `listings/reconciler.py`'s raw-SQL
   references to the new table name.
3. Add the two validation guards (listing creation, claim build) described
   in Decision 2 above, with unit/integration tests for both the rejection
   path and the legitimate resource_id-only / pool_id-only cases.
