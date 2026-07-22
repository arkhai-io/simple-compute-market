## Why

Originally framed around a literal `required_attributes=("vm_host",)` claim
shape. **Verified during design review (2026-07-16), and that framing was
already stale:** `vm_job_spec_service._REQUIRED_COMPUTE_KEYS` already
excludes `vm_host` — no such literal exists in current code. The real gap
is narrower: `ListingService.create_listing` accepts and stores a compute
offer with no cross-check that it carries any resource/pool identity at
all, so a reservation claim built from such a listing can end up matching
on shape attributes (`region`/`gpu_model`/`gpu_count`) alone — the same bug
class `test_claim_survives_listing_model_validation` was written to catch,
via a different missing field. See `design.md`'s Decision 2 for the full
trace and the resolved fix (two validation guards, plus an explicit
priority rule for listings that carry both `pool_id` and `resource_id`).

**Correction from the original plan (verified against current code, not
assumed):** the `SiteLedger`/`SiteResourcesService` rename this item
originally called for has already happened — the site authority is now
`CapacityLedgerService`/`SiteAuthorityPort` in `kit/site/src/market_site/`.
That work is done; it is not part of this change's remaining scope. The
`compute_inventory_pools` table name, however, is still unrenamed
(`domains/vms/storefront/src/market_storefront/utils/{sqlite_client,migrations}.py`,
`domains/vms/listings/reconciler.py`) and remains this change's scope.

## What Changes

- Add a listing-creation guard rejecting a compute offer that carries
  neither `pool_id` nor `resource_id`, and a claim-build backstop raising
  on the same condition — see `design.md` Decision 2.
- When a listing's offer carries **both** `pool_id` and `resource_id`, the
  reservation claim treats it as a specific-resource listing: `resource_id`
  is used and `pool_id` is dropped from the claim rather than requiring
  both to match. See `design.md` Decision 2 and the `site-capacity` spec
  delta's new scenario.
- Rename `compute_inventory_pools` to `compute_capacity_pools` in the
  storefront SQLite schema, and update `SQLiteClient`, the listings
  reconciler, and their tests.
- Confirm and, where prose has drifted, restate the ownership rule already
  expressed in `site-capacity`'s baseline spec: provisioning is the source
  of truth for physical inventory, resource pools, scheduling, and
  settlement resources; the storefront owns capacity offerings/projections
  and market reservations.
- Fail closed when a pre-existing listing violates the new identity invariant:
  attempts to resume or republish it return an actionable conflict without
  mutating local state. The storefront does not silently backfill or
  automatically unpublish legacy data; the operator must explicitly close the
  listing to remove it from registries.

## Non-Goals

- Renaming the `SiteResource`/`SiteAllocation` ORM model names — the
  service-level rename is done, but these model names still carry `Site`
  prefixes. Left as naming debt, not blocking.
- Any provider execution or scheduler behavior change — this change only
  changes what the storefront asks for, not how provisioning fulfills it.
- Package extraction (tracked by `market-platform-compute-30-extract-service`,
  which absorbed the now-closed `pools-5-shared-provisioning-package`).

## Capabilities

### Modified Capabilities

- `site-capacity`: a listing must carry `pool_id` and/or `resource_id`;
  reservation claims are pool-shaped when only `pool_id` is present and
  resource-specific when `resource_id` is present (with `pool_id` dropped
  from the claim if both are set).

## Dependencies and Related Changes

- Requires `pools-2-physical-settlement-scheduler`'s specific-resource
  request shape.
- The reservation-expiry (hold/commit/release TTL) model this proposal
  originally expected to need storefront-side wiring for is already fully
  implemented and interoperating correctly on both sides — verified during
  design review, no work item exists for it in `tasks.md`.
- Independent of `pools-3-fulfillment-provider` — does not require provider
  execution to exist.
- Landing this change is one of the two activation conditions for
  `pools-7-storefront-fulfillment-cutover`, which replaces the storefront's
  direct executor dispatch with the scheduler/provider path. This change
  makes reservations pool-shaped; it does not itself change what the
  storefront does after a reservation succeeds.

## Impact

- **Packages:** `core/storefront`, `domains/vms/storefront`,
  `domains/vms/listings`.
- **Database:** storefront SQLite migration renaming
  `compute_inventory_pools` to `compute_capacity_pools`.
- **API:** `POST /listings/create` now rejects a compute offer with neither
  `pool_id` nor `resource_id`; a listing carrying both is now matched as
  specific-resource (`resource_id`), not pool-scoped. Resuming a legacy-invalid
  listing returns `409 Conflict` and directs the operator to the explicit
  seller-authenticated close operation; it does not alter the paused state or
  publish the invalid row.
- **Compatibility:** breaking only for a caller relying on being able to
  publish a compute listing with neither `pool_id` nor `resource_id` set —
  verified no such caller exists in this repository today.

## Permanent documentation impact

- [ ] `docs/development/ARCHITECTURE.md`
- [x] Existing subsystem specification
- [ ] New subsystem specification
- [ ] No permanent documentation change

### Knowledge promoted

- Capacity-claim identity validation, resource-over-pool precedence, missing-order failure, and legacy-invalid listing remediation are recorded in `openspec/specs/site-capacity/spec.md#requirement-storefront-capacity-claim-identity`.
- The architecture ownership boundary was reviewed and already describes the accepted storefront/site split; no architecture edit is required.
- The storefront SQLite table rename is migration implementation detail and has no permanent specification destination.
