## Why

Split out of `pools-7-storefront-fulfillment-cutover`'s design review
(2026-07-17), not independently discovered. `pools-7` designed a
storefront-side read-only mirror of every connected provisioning
service's pool/capacity state (`CapacityProjection`), plus two operator
hints that ride on top of it (`ResourcePool.policy_tags`'
`listing_mode` and a reservation-hold TTL preference). All three are a
materially separate subsystem from `pools-7`'s fulfillment-cutover
mechanics — pull schedules, freshness, multi-site keys, publication
reactions, their own storage and migrations — not inherently part of
scheduling/dispatch/persistence. `pools-7` was already large; this was
split out to keep both changes reviewable, migratable, and separately
rollback-able, per outside design-review feedback (2026-07-17) that
`pools-7` had accumulated too much unrelated scope, which on reflection
was correct for this piece specifically.

**This split has a real consequence that must stay visible, not be
quietly absorbed:** `pools-7`'s `site_resource_pools`/
`PhysicalSettlementScheduler` fix makes the *provisioning service* side
of the `pool_id`-namespace-collision bug (`pools-7`'s `design.md`,
"`SiteResource` is retired") correct — pool identity is sourced from
`hosts`/`resource_pools`, not guessed. But the *storefront's* own
claim-building (`vm_job_spec_service.py`) still sources the `pool_id`/
`resource_id` it sends from the storefront's local, independently
authored inventory table until this change replaces it with
`CapacityProjection`. `pools-7` alone fixes provisioning-side
correctness (bad claims now fail cleanly at admission instead of
silently matching the wrong thing); this change is required for the
storefront to reliably send *valid* claims in the first place.

## What This Change Covers

- **`CapacityProjection`**: a storefront-side, pull-based, read-only
  mirror of every connected provisioning service's pool/capacity state,
  replacing the storefront's local, independently-authored resource
  inventory table (`resources`, hand-curated CSV import) as the source
  of pool/resource identities used when building reservation claims and
  publishing listings. Sourced from `GET /api/v1/pools` — already
  exists, already reachable (the storefront already holds each
  configured site's admin key). Keyed by `(site, pool_id)`, since pool
  IDs are only unique per provisioning service. Explicitly
  advisory/display-only for pricing and listing publication — never the
  thing reservation admission checks against; the live, per-request
  `AggregateCapacityClient` snapshot remains the routing/admission input,
  unchanged.
- **Operator-declared listing-mode hint**: `ResourcePool.policy_tags`
  (`kit/resource-pools`) gains a `listing_mode` entry a pool operator can
  set to declare whether their pool prefers pool-scoped or
  specific-resource listing behavior. Non-binding — a storefront that
  never reads it falls back to the existing structural default (single-
  resource pool -> resource-pinned; real multi-member pool -> pool-
  scoped), and `pools-2`'s "Explicit selection preserves eligibility"
  requirement is unaffected either way (an explicit `resource_id`
  request is honored regardless of a pool's declared mode).
- **Pool-level reservation TTL hint**: a `policy_tags` entry
  (`max_reservation_hold_seconds`) an operator can set to express a
  preference for how long their resources should sit reserved-but-
  unscheduled. Same non-binding posture — read and voluntarily respected
  by a cooperating storefront choosing the `ttl_seconds` it passes to
  `reserve()`; never provisioning-enforced.
- **Extensibility for `apicredits`**: the `listing_mode` tag key is
  domain-neutral (`kit/resource-pools` owns the key name only); each
  domain owns its own enum of valid values and default rule. Verified,
  not just asserted, against a concrete `apicredits` sketch during
  `pools-7`'s design review — see `design.md`.

## Non-Goals

- Reservation-admission correctness, scheduling, `SettlementRecord`
  persistence, provider dispatch idempotency, and release-path wiring —
  all `pools-7`.
- Any change to how `PhysicalSettlementScheduler` or `CapacityLedgerService`
  make admission/eligibility decisions. `CapacityProjection` is never
  consulted for that; see "Why" above.

## Dependencies and Related Changes

- Depends on `pools-4-storefront-capacity-boundary` (pool-shaped claims)
  and benefits from, but does not strictly require, `pools-7` landing
  first — the two can proceed in parallel, but `pools-7`'s `pool_id`-
  correctness fix is not complete end-to-end until this change also
  lands (see "Why" above).
- Depends on `kit/resource-pools`' `GET /api/v1/pools` admin API
  (already exists) for the pull source.

## Impact

Touches the VM storefront (new `CapacityProjection` cache tables and
sync job, reconciler/listing-publication changes to consume
`listing_mode`, replacement of the local `resources` table as claim-
building's source of truth) and `kit/resource-pools` (`policy_tags`
convention for the two new hint keys — additive, no schema change, it's
already a free-form dict). Detailed file-level impact is a planning-step
output; this change has not yet been planned (no `tasks.md`).
