## Why

The two compute storefronts read their sites' resource-pool projections by two routes.
The VM storefront holds each site's projections in memory, polls them, wakes its
publication loop when a site's resource-pool generation changes, and publishes on a
timer. The state lives in VM's own `site_projection_cache` module, 272 lines of
composition over the shared `ProjectionCache` primitive in `core/storefront`. The
bare-metal storefront holds nothing: its publication fetches every site's projection
live on each run, its opening recheck fetches the listing's site live on each
opening, and its publication runs only when an operator invokes it.

That difference now blocks Goal 7. `unbacked-bare-metal-listings` publishes bare-metal
listings that are never judged against availability, so source reconciliation is the
only reconciliation they get. While bare-metal publication runs only when an operator
invokes it, an unbacked listing whose pool is withdrawn stays advertised until someone
runs it — the failure source reconciliation exists to prevent. And because the recheck
fetches live, that change had to scope the inventory guard so an unbacked listing's
recheck may call its origin site, and accept that every opening of one is refused while
its site is unreachable.

Holding projections is already the agreed end state for every storefront
(`resolve-compute-family-findings`), and moving VM's projection state into the kit was
an item of `kit-owned-listing-and-fulfillment-lifecycles`, which waits on the
storefront shell. The item does not depend on the shell, so it is carved out here as
`unbacked-bare-metal-listings`' prerequisite.

## What Changes

- Move the per-site projection state VM's `site_projection_cache` composes into
  `kit/capacity-publication`, over any aggregate capacity client: each configured
  site's resource-pool and capacity-bucket caches, their poller as a storefront
  lifecycle loop, the publication wake on a resource-pool generation change, the
  per-site refresh an override write or an inline reconciliation asks for, the
  topology-error refresh, and the per-site, per-family status summary. VM composes it
  and keeps only what is VM's, such as its `listing_cardinality_mode` explanations.
- The bare-metal storefront composes the same state over the aggregate it already
  builds. Its publication derives from the held projections, and a site whose
  projection is not held holds its listings, as an unreachable site does today. Its
  opening recheck reads the held projection of the listing's site rather than fetching
  it.
- Bare-metal publication runs as a timer-driven lifecycle loop on the storefront's
  existing loop controller, as VM's does: held by the lifecycle pause, stepped and
  previewed while held, woken by a resource-pool generation change and by an accepted
  pool-override write. The publication command keeps running one cycle through the
  storefront's API.
- Bare-metal pool-override writes refresh the held projection of their site and wake
  the loop, and override status reads the held projection.
- Every bare-metal end-to-end scenario that steps publication holds the storefront's
  loops first, as VM's deal scenarios do.

## Capabilities

### Modified Capabilities

- `storefront-publication`: publication runs as a controllable lifecycle loop in both
  compute storefronts; an accepted pool-override write wakes it in both; a bare-metal
  site whose projection is not held holds its listings during a cycle; the bare-metal
  opening recheck reads its site's held projection.

### New Capabilities

None.

## Non-Goals

- Unbacked bare-metal supply, which `unbacked-bare-metal-listings` adds on top of this.
- The listing lifecycle and fulfillment convergence, which stay with
  `kit-owned-listing-and-fulfillment-lifecycles`.
- API credits, whose storefront reads the credits service's projection for its own
  listings and holds no per-site projection state; whether it should is not decided
  here.
- A pool-override write's live check against the site, which stays live: its
  requirement is that a write is judged against the site's current projection, not a
  held one.

## Impact

- `kit/capacity-publication`: the per-site projection state and its poller.
- `domains/vms/storefront`: `site_projection_cache.py` reduced to VM's own
  explanations, and its consumers moved onto the kit's state.
- `domains/bare_metal/storefront`: publication, opening recheck, pool overrides, the
  lifecycle steps and server startup, and the durable accepted-generation table that
  override status reads today.
- `e2e-tests/`: bare-metal scenarios that step publication hold the loops first.
- No wire break. A bare-metal storefront's database keeps its accepted-generation
  table, whatever this change decides it is for.

## Permanent documentation impact

- [x] `docs/development/ARCHITECTURE.md` — "Storefront capacity boundary", whose
      statement that bare-metal publication remains operator-invoked no longer holds,
      and the kit's ownership of per-site projection state.
- [x] Existing subsystem specification — `storefront-publication` and its companion's
      "Autonomous publication" and "Reconciliation"; `market-composition`'s companion
      for the kit's projection state.
- [ ] New subsystem specification
- [ ] No permanent documentation change

Also: `docs/development/DEPLOYMENT_AND_CONFIG.md` for the bare-metal publication and
projection-poll intervals, and `docs/development/TESTING.md` if the lanes' hold
convention changes.

## Dependencies

- **Carved out of `kit-owned-listing-and-fulfillment-lifecycles`**, whose item
  "Replace the VM storefront's `site_projection_cache` with the capacity/publication
  kit's per-site projection state" moves here. That change no longer carries it.
- **Blocks `unbacked-bare-metal-listings`**, whose recheck and source reconciliation
  rely on bare metal holding projections and publishing on a loop.
- Depends on nothing open: `encapsulate-capacity-backing` (archived 2026-10-14) and
  `kit-owned-storefront-loop-lifecycle` (archived) supply the binding and the loop
  controller it builds on.
