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

This change adds two validation guards plus one priority rule in
`compute_capacity_claim_from_order` — it does not change which keys are
*eligible* to appear in a claim (`_REQUIRED_COMPUTE_KEYS` is unchanged),
only whether the listing is well-formed and, when both `pool_id` and
`resource_id` are present, which one wins:

- **At listing model validation** (`Listing.model_validate`): normalize
  surrounding whitespace and reject missing, blank, or malformed `pool_id` /
  `resource_id` values. The rule is storefront-listing-specific rather than a
  global `ComputeResource` invariant because compute resources also exist before
  publication. Valid identifiers start with an alphanumeric character, contain
  only letters, digits, `.`, `_`, `:`, or `-`, and are at most 128 characters.
  At least one valid identity is required. The REST create path constructs this
  model before persistence, so it receives the validation automatically.
- **At claim build** (`compute_capacity_claim_from_order`): reject a missing or
  empty settlement order, and raise if the resulting claim carries neither key. A backstop for any listing that
  reaches this point despite the first guard (e.g. a row written by a
  future or as-yet-unaudited path), so a missing identity fails loudly at
  reservation time instead of silently matching on shape attributes alone.

**Both present (design review, 2026-07-16):** when a listing's offer
carries *both* `pool_id` and `resource_id`, `compute_capacity_claim_from_order`
treats it as an intentionally specific-resource listing: `resource_id` is
kept and `pool_id` is dropped from the built claim. Requiring both to match
would be a stricter, unintended constraint (only satisfiable by whichever
single resource happens to carry that exact `pool_id` *and* that exact
`resource_id`) rather than the two independent claim shapes this change
means to support; `resource_id` presence is the signal that a listing wants
resource-level pinning regardless of what pool it also happens to belong
to.

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

1. Brand-new databases create `compute_capacity_pools` directly in the
   historical schema-construction migration. Existing databases that already
   recorded that migration retain `compute_inventory_pools` and are upgraded by
   a new additive rename migration (`ALTER TABLE compute_inventory_pools RENAME
   TO compute_capacity_pools`). The rename is a no-op when only the new table
   exists or neither table exists, and fails with an actionable schema-drift
   error when both names exist so data is not silently abandoned.
   `compute_pool_members`'s foreign-key target is verified by test after rename.
   `compute_pool_members` itself is not renamed — the proposal scoped the
   rename to `compute_inventory_pools` specifically, and "members" doesn't
   carry the old "inventory" framing that motivated the rename.
2. Update `sqlite_client.py` and `listings/reconciler.py`'s raw-SQL
   references to the new table name.
3. Add the two validation guards (listing creation, claim build) described
   in Decision 2 above, with unit/integration tests for both the rejection
   path and the legitimate resource_id-only / pool_id-only cases.

### 4. Missing orders are not generic-capacity requests

A missing, empty, or malformed settlement order is invalid fulfillment input.
The planner and claim builder fail before probing or reserving capacity. The
absence of an order must never be translated into `claim=None`, because that
means "select any available capacity" at the capacity boundary. If a future
workflow needs an explicit generic-capacity operation, it receives a separately
named API rather than overloading missing order data.
