# Design — share site projection state

## Context

Opened 2026-10-14, after `encapsulate-capacity-backing` was archived, from a review of
`unbacked-bare-metal-listings` against the implemented tree. The review found that
unbacked bare-metal listings would depend on source reconciliation alone, which bare
metal runs only when an operator invokes publication, and that the unbacked design had
to scope the inventory guard around bare metal's live recheck. Both follow from bare
metal holding no projections. The maintainer chose to have bare metal share VM's
projection logic and publication loop, as a focused prerequisite carved out of
`kit-owned-listing-and-fulfillment-lifecycles`.

What exists:

- `core_storefront.site_projections.ProjectionCache` is the shared primitive: a cached
  value with its identity, polled by version, refreshed on demand, reporting a load
  state that never reads a not-yet-loaded projection as empty.
- VM's `market_storefront.services.site_projection_cache` composes it: one
  resource-pool and one capacity-bucket cache per configured site, built from the
  aggregate's remote site clients; a poller loop gated by the lifecycle controller,
  which wakes the publication loop when any site's resource-pool identity changes;
  per-site refresh for override writes and inline reconciliation; a refresh on a
  capacity topology error; a status summary; and VM's own `listing_cardinality_mode`
  explanations.
- Bare metal's storefront builds its own aggregate over a durable reservation-to-site
  map and registers its loops on the same `StorefrontLoopController` VM uses. Its
  publication step is registered without a timer. Each publication run fetches every
  site's resource-pool projection, accepts it through
  `trusted_bare_metal_projection`, and records the accepted generation and pool IDs in
  `bare_metal_accepted_site_generations`, which override status reads. Its opening
  recheck fetches the listing's site live.

## Decisions

### A prerequisite, carved out of the kit lifecycle change

Decided with the maintainer. Replacing VM's projection cache with kit-owned per-site
state is an item of `kit-owned-listing-and-fulfillment-lifecycles`, which waits on
`kit-owned-storefront-shell`. The item needs neither the shell nor the listing and
fulfillment lifecycles, and Goal 7 needs it now, so it moves here and that change no
longer carries it.

Rejected: a version watch inside bare metal's publication loop, waking it on a
resource-pool generation change while it still fetches live. It would satisfy the
loop requirement but leave two projection routes, keep the live recheck the unbacked
design had to scope a requirement around, and be thrown away when bare metal moved
onto held projections.

### The state lives in `kit/capacity-publication`

The kit already owns exact site projection for the publication runtime and composes
over any aggregate capacity client; `CapacityEffects` established that a storefront
building its own aggregate composes the kit's state over it. Per-site projection state
is storefront-side and compute-family-neutral — the resource-pool and capacity-bucket
families are the site's, not a domain's — so it belongs beside the runtime rather than
in either domain. What reads a projection for one domain's meaning, such as VM's
`listing_cardinality_mode` explanations, stays that domain's.

### Bare metal publishes on the same loop controller as VM

Decided with the maintainer. Bare-metal publication becomes a timer-driven lifecycle
loop on the storefront's existing controller: held by the lifecycle pause, its existing
step and preview being the cycle the timer runs, woken by a resource-pool generation
change through the shared state and by an accepted pool-override write. The publication
command keeps running one cycle through the storefront's API, so an operator's control
is unchanged. The requirement "Publication runs as a controllable storefront lifecycle
loop" then holds for both compute storefronts, and its bare-metal exception goes.

### Bare metal reads held projections

Bare-metal publication derives from the held projection of each site and holds the
listings of a site whose projection is not held, as it does today for a site it cannot
fetch. The opening recheck reads the held projection of the listing's site.

A held projection can lag the site by up to one poll. That is the posture VM already
takes and the one "Advisory publication, authoritative admission" states: publication
and the recheck are advisory, and admission happens at the site when capacity is
reserved. The pool-override write check is the exception and stays live, because its
requirement is that a write is judged against the site's current projection.

## Open questions

To be decided before planning:

1. **One loop or two in the combined storefront.** The combined compute-family
   storefront runs VM and bare metal in one process. The loop requirement says a loop
   builds only the publication sources of the domains it publishes. Decide whether the
   combined storefront runs one publication loop over both domains or one loop per
   domain on the same controller, and whether both read one shared projection state per
   site, which the kit's state would make natural.
2. **The accepted-generation table.** `bare_metal_accepted_site_generations` exists so
   override status has a projection to read. Once override status reads the held
   projection, the table is unread, and `site-capacity`'s "Per-site projection
   load-state visibility" says a storefront must not persist projection generations
   across restart. Decide whether the table is frozen under the repository's rule for
   retired storefront tables, or keeps a purpose this change must state.
3. **Which families bare metal holds.** Bare-metal publication reads only the
   resource-pool family; availability arrives through each resource's view. Decide
   whether bare metal holds both families, as the kit's state does for VM, or only the
   resource-pool family, and whether the capacity-bucket family's topology-error
   refresh applies to it.
4. **Where generation trust is checked.** `trusted_bare_metal_projection` accepts a
   site's projection before bare metal reads it. Decide whether it runs once when the
   shared state accepts a generation, as a hook the domain supplies, or each time bare
   metal reads the held value.
5. **Intervals and configuration.** VM reads its poll and publication intervals from
   its `capacity` settings. Decide bare metal's settings, and whether the kit's state
   takes its interval from the composing storefront.
